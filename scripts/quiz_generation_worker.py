#!/usr/bin/env python3
"""Simple queue worker for quiz generations (phase 3).

Consumes pending rows from public.generations, marks processing with atomic claim,
builds a basic SVG output card, uploads to Supabase Storage, then marks done/error.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import os
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

import requests
from dotenv import load_dotenv

# Allow running as "python3 scripts/quiz_generation_worker.py"
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.settings import Settings
from app.application.use_cases.generate_editorial_image import (
    GenerateEditorialImageInput,
    execute as generate_editorial_image_uc,
)
from app.application.services.image_prompt_builder import build_editorial_prompt
from app.infrastructure.gemini_image_client import GeminiImageClient
from app.infrastructure.supabase_rest import get_json, rest_headers


@dataclass
class Job:
    id: str
    experience_id: str
    credential_id: str
    kind: str


_ALLOWED_GENDERS = {"mulher", "homem"}
_ALLOWED_HAIR_COLORS = {"loiro", "castanho", "preto", "ruivo", "grisalho"}


def _estimated_cost_usd(job: Job) -> float:
    # Allows tuning by kind via env while keeping a safe default.
    default = float(os.getenv("QUIZ_GENERATION_ESTIMATED_COST_USD", "0.04"))
    by_kind = {
        "credential_card": float(os.getenv("QUIZ_COST_CREDENTIAL_CARD_USD", str(default))),
        "quiz_result": float(os.getenv("QUIZ_COST_QUIZ_RESULT_USD", str(default))),
        "photo_with": float(os.getenv("QUIZ_COST_PHOTO_WITH_USD", str(default))),
    }
    return float(by_kind.get(job.kind, default))


def _write_generation_log(
    settings: Settings,
    generation_id: str,
    *,
    level: str,
    event: str,
    message: str,
    payload: dict | None = None,
):
    """
    Best effort structured log sink for each generation job.
    If table is missing, worker continues without failing the generation.
    """
    url = f"{settings.supabase_url}/rest/v1/generation_logs"
    body = [
        {
            "generation_id": generation_id,
            "level": level,
            "event": event,
            "message": message,
            "payload_json": payload or {},
        }
    ]
    try:
        requests.post(
            url,
            headers={**rest_headers(settings), "Content-Type": "application/json"},
            json=body,
            timeout=10,
        )
    except Exception:
        pass


def _now_iso() -> str:
    return dt.datetime.utcnow().isoformat() + "Z"


def _claim_job(settings: Settings, job_id: str) -> Job | None:
    url = f"{settings.supabase_url}/rest/v1/generations?id=eq.{job_id}&status=eq.pending"
    body = {"status": "processing", "updated_at": _now_iso(), "error_message": None}
    r = requests.patch(
        url,
        headers={**rest_headers(settings), "Content-Type": "application/json", "Prefer": "return=representation"},
        json=body,
        timeout=20,
    )
    if not r.ok:
        return None
    rows = r.json() or []
    if not rows:
        return None
    row = rows[0]
    return Job(
        id=str(row.get("id") or ""),
        experience_id=str(row.get("experience_id") or ""),
        credential_id=str(row.get("credential_id") or ""),
        kind=str(row.get("kind") or "quiz_result"),
    )


def _load_credential_data(settings: Settings, credential_id: str) -> dict:
    rows = get_json(settings, "credentials", "id,data_json,photo_path", {"id": f"eq.{credential_id}"}, limit=1)
    if not rows:
        raise RuntimeError("credential_not_found")
    return rows[0]


def _ext_from_mime(mime: str) -> str:
    m = (mime or "").lower()
    if "jpeg" in m or "jpg" in m:
        return "jpg"
    if "webp" in m:
        return "webp"
    if "svg" in m:
        return "svg"
    return "png"


def _guess_mime_from_storage_path(storage_path: str) -> str:
    p = (storage_path or "").lower()
    if p.endswith(".jpg") or p.endswith(".jpeg"):
        return "image/jpeg"
    if p.endswith(".webp"):
        return "image/webp"
    if p.endswith(".png"):
        return "image/png"
    return "image/jpeg"


def _download_reference_image(settings: Settings, storage_path: str) -> tuple[bytes, str]:
    bucket = settings.supabase_bucket
    url = f"{settings.supabase_url}/storage/v1/object/{bucket}/{storage_path}"
    r = requests.get(url, headers=rest_headers(settings), timeout=40)
    if not r.ok:
        raise RuntimeError(f"reference_download_failed:{r.status_code}:{r.text[:160]}")
    mime = (r.headers.get("Content-Type") or "").strip() or _guess_mime_from_storage_path(storage_path)
    return r.content, mime


def _extract_generation_inputs(cred_row: dict) -> tuple[str, str]:
    data = cred_row.get("data_json") if isinstance(cred_row.get("data_json"), dict) else {}
    gender = str((data or {}).get("gender") or "mulher").strip().lower()
    hair_color = str((data or {}).get("hair_color") or "castanho").strip().lower()
    if gender not in _ALLOWED_GENDERS:
        gender = "mulher"
    if hair_color not in _ALLOWED_HAIR_COLORS:
        hair_color = "castanho"
    return gender, hair_color


def _load_archetype(settings: Settings, experience_id: str, archetype_id: str) -> dict | None:
    if not archetype_id:
        return None
    rows = get_json(
        settings,
        "archetypes",
        "id,name,image_prompt,text_prompt,use_photo_prompt",
        {"id": f"eq.{archetype_id}", "experience_id": f"eq.{experience_id}"},
        limit=1,
    )
    return rows[0] if rows else None


def _load_first_archetype(settings: Settings, experience_id: str) -> dict | None:
    rows = get_json(
        settings,
        "archetypes",
        "id,name,image_prompt,text_prompt,use_photo_prompt",
        {"experience_id": f"eq.{experience_id}", "order": "sort_order.asc"},
        limit=1,
    )
    return rows[0] if rows else None


def _resolve_experience_gemini_key(settings: Settings, experience_id: str) -> str | None:
    """
    Priority:
    1) experiences.gemini_api_key (per experience, set in panel)
    2) GEMINI_API_KEY from global settings (.env)
    """
    try:
        rows = get_json(
            settings,
            "experiences",
            "id,gemini_api_key",
            {"id": f"eq.{experience_id}"},
            limit=1,
        )
        exp_key = str((rows[0] or {}).get("gemini_api_key") or "").strip() if rows else ""
        if exp_key:
            return exp_key
    except Exception:
        # Keep backward compatibility on environments without gemini_api_key column.
        pass
    return settings.gemini_api_key


_VAR_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")
_WORD_RE = re.compile(r"\b[\wÀ-ÿ]+\b", re.UNICODE)

_PROMPT_EXACT_TRANSLATIONS = {
    "sim": "yes",
    "nao": "no",
    "não": "no",
    "masculino": "male",
    "feminino": "female",
    "homem": "man",
    "mulher": "woman",
    "loiro": "blond",
    "castanho": "brown",
    "preto": "black",
    "ruivo": "red",
    "grisalho": "gray",
    "solteiro": "single",
    "casado": "married",
    "divorciado": "divorced",
    "viuvo": "widowed",
    "viúvo": "widowed",
}

_PROMPT_WORD_TRANSLATIONS = {
    "anos": "years",
    "ano": "year",
    "empreendimento": "business",
    "empreendimentos": "businesses",
    "vendas": "sales",
    "venda": "sale",
    "corretor": "broker",
    "consultor": "consultant",
    "cliente": "client",
    "clientes": "clients",
    "premium": "premium",
    "iniciante": "beginner",
    "avancado": "advanced",
    "avançado": "advanced",
    "experiente": "experienced",
    "alto": "high",
    "media": "medium",
    "média": "medium",
    "baixo": "low",
}


def _strip_accents(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", text or "") if unicodedata.category(ch) != "Mn")


def _translate_prompt_value_to_english(value) -> str:
    """
    Converts dynamic prompt variable values to English before interpolation.
    Keeps unknown words as-is to avoid data loss.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(_translate_prompt_value_to_english(v) for v in value if v is not None)

    raw = str(value).strip()
    if not raw:
        return ""

    normalized = _strip_accents(raw).lower()
    if normalized in _PROMPT_EXACT_TRANSLATIONS:
        return _PROMPT_EXACT_TRANSLATIONS[normalized]

    def _replace_word(match: re.Match[str]) -> str:
        word = match.group(0)
        key = _strip_accents(word).lower()
        translated = _PROMPT_WORD_TRANSLATIONS.get(key)
        return translated if translated else word

    return _WORD_RE.sub(_replace_word, raw)


def _render_prompt_template(template: str, data: dict | None) -> str:
    raw = str(template or "").strip()
    if not raw:
        return ""
    payload = data if isinstance(data, dict) else {}

    def _replace(match: re.Match[str]) -> str:
        key = str(match.group(1) or "").strip()
        val = payload.get(key)
        if val is None:
            return ""
        return _translate_prompt_value_to_english(val)

    rendered = _VAR_TOKEN_RE.sub(_replace, raw)
    # normalize whitespace while keeping line breaks readable
    rendered = "\n".join(line.strip() for line in rendered.splitlines() if line.strip())
    return rendered


def _build_svg_card(job: Job, cred_row: dict) -> bytes:
    data = cred_row.get("data_json") or {}
    name = html.escape(str(data.get("name") or "Participante"))
    city = html.escape(str(data.get("city") or ""))
    profession = html.escape(str(data.get("profession") or ""))
    subtitle = f"{city} {profession}".strip()
    subtitle = html.escape(subtitle) if subtitle else "EUVATAR Experience"
    ts = html.escape(dt.datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S UTC"))
    kind = html.escape(job.kind)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1080">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#0b1f3a"/>
    <stop offset="100%" stop-color="#1f4f8a"/>
  </linearGradient>
</defs>
<rect width="1080" height="1080" fill="url(#bg)"/>
<rect x="80" y="80" width="920" height="920" rx="36" fill="#ffffff" opacity="0.93"/>
<text x="130" y="220" font-size="52" font-family="Arial, sans-serif" fill="#0b1f3a">EUVATAR CARD</text>
<text x="130" y="320" font-size="68" font-weight="700" font-family="Arial, sans-serif" fill="#10294a">{name}</text>
<text x="130" y="390" font-size="36" font-family="Arial, sans-serif" fill="#274c77">{subtitle}</text>
<text x="130" y="480" font-size="28" font-family="Arial, sans-serif" fill="#274c77">Generation kind: {kind}</text>
<text x="130" y="900" font-size="22" font-family="Arial, sans-serif" fill="#4c627d">Generated at {ts}</text>
</svg>"""
    return svg.encode("utf-8")


def _upload_output(
    settings: Settings,
    experience_id: str,
    generation_id: str,
    data: bytes,
    *,
    mime_type: str,
) -> str:
    bucket = settings.supabase_bucket
    ext = _ext_from_mime(mime_type)
    path = f"quiz/{experience_id}/generations/{generation_id}.{ext}"
    url = f"{settings.supabase_url}/storage/v1/object/{bucket}/{path}"
    r = requests.post(
        url,
        headers={
            **rest_headers(settings),
            "x-upsert": "true",
            "Content-Type": mime_type or "image/png",
        },
        data=data,
        timeout=30,
    )
    if not r.ok:
        raise RuntimeError(f"storage_upload_failed:{r.status_code}:{r.text[:160]}")
    return path


def _finish_job_done(settings: Settings, job: Job, duration_ms: int, output_path: str):
    url = f"{settings.supabase_url}/rest/v1/generations?id=eq.{job.id}"
    body_with_cost = {
        "status": "done",
        "duration_ms": duration_ms,
        "output_path": output_path,
        "output_url": None,
        "cost_estimated_usd": _estimated_cost_usd(job),
        "cost_currency": "USD",
        "error_message": None,
        "updated_at": _now_iso(),
    }
    r = requests.patch(
        url,
        headers={**rest_headers(settings), "Content-Type": "application/json"},
        json=body_with_cost,
        timeout=20,
    )
    if r.ok:
        return
    # backward compatibility: environments without cost columns yet
    body_legacy = {
        "status": "done",
        "duration_ms": duration_ms,
        "output_path": output_path,
        "output_url": None,
        "error_message": None,
        "updated_at": _now_iso(),
    }
    requests.patch(
        url,
        headers={**rest_headers(settings), "Content-Type": "application/json"},
        json=body_legacy,
        timeout=20,
    )


def _finish_job_error(settings: Settings, job: Job, duration_ms: int, err: str):
    url = f"{settings.supabase_url}/rest/v1/generations?id=eq.{job.id}"
    body_with_cost = {
        "status": "error",
        "duration_ms": duration_ms,
        "cost_estimated_usd": _estimated_cost_usd(job),
        "cost_currency": "USD",
        "error_message": err[:1000],
        "updated_at": _now_iso(),
    }
    r = requests.patch(
        url,
        headers={**rest_headers(settings), "Content-Type": "application/json"},
        json=body_with_cost,
        timeout=20,
    )
    if r.ok:
        return
    body_legacy = {
        "status": "error",
        "duration_ms": duration_ms,
        "error_message": err[:1000],
        "updated_at": _now_iso(),
    }
    requests.patch(
        url,
        headers={**rest_headers(settings), "Content-Type": "application/json"},
        json=body_legacy,
        timeout=20,
    )


def _process_job(settings: Settings, job: Job):
    t0 = time.time()
    _write_generation_log(
        settings,
        job.id,
        level="info",
        event="job_started",
        message="Generation worker started processing job",
        payload={"kind": job.kind, "experience_id": job.experience_id, "credential_id": job.credential_id},
    )
    try:
        cred = _load_credential_data(settings, job.credential_id)
        gender, hair_color = _extract_generation_inputs(cred)
        cred_data_for_log = cred.get("data_json") if isinstance(cred.get("data_json"), dict) else {}
        _write_generation_log(
            settings,
            job.id,
            level="info",
            event="credential_loaded",
            message="Credential row loaded",
            payload={
                "has_photo_path": bool(cred.get("photo_path")),
                "has_data_json": bool(cred.get("data_json")),
                "gender": gender,
                "hair_color": hair_color,
                "winner_archetype_id": str((cred_data_for_log or {}).get("winner_archetype_id") or ""),
            },
        )
        out_path = ""
        photo_path = str(cred.get("photo_path") or "").strip()
        cred_data = cred.get("data_json") if isinstance(cred.get("data_json"), dict) else {}
        winner_archetype_id = str((cred_data or {}).get("winner_archetype_id") or "").strip()
        archetype = _load_archetype(settings, job.experience_id, winner_archetype_id) if winner_archetype_id else None
        if not archetype:
            archetype = _load_first_archetype(settings, job.experience_id)
        archetype_prompt = _render_prompt_template(str((archetype or {}).get("image_prompt") or ""), cred_data)
        prompt_source = "archetype" if archetype_prompt else "fixed_default"

        # Preferred mode: Gemini generation. With photo when available; prompt-only when archetype allows it.
        effective_gemini_key = _resolve_experience_gemini_key(settings, job.experience_id)
        use_photo_prompt = bool((archetype or {}).get("use_photo_prompt"))
        can_prompt_only = bool(effective_gemini_key and (not photo_path) and archetype_prompt and (not use_photo_prompt))
        if effective_gemini_key and (photo_path or can_prompt_only):
            gemini_settings = replace(settings, gemini_api_key=effective_gemini_key)
            gemini = GeminiImageClient(gemini_settings)
            if photo_path:
                ref_bytes, ref_mime = _download_reference_image(settings, photo_path)
                out, status = generate_editorial_image_uc(
                    gemini,
                    GenerateEditorialImageInput(
                        gender=gender,
                        hair_color=hair_color,
                        reference_image_bytes=ref_bytes,
                        reference_mime_type=ref_mime,
                        prompt_override=archetype_prompt or None,
                    ),
                )
                if status != 200 or not out.get("ok"):
                    raise RuntimeError(str(out.get("error") or f"gemini_failed_status_{status}"))
                generated_b64 = str(out.get("image_base64") or "")
                generated_mime = str(out.get("mime_type") or "image/png")
                prompt_applied = str(out.get("prompt_applied") or "")
                model_name = out.get("model")
                latency_ms = out.get("latency_ms")
                generation_mode = "reference_photo"
            else:
                prompt_applied = archetype_prompt or build_editorial_prompt(gender, hair_color)
                t_gem = time.time()
                raw = gemini.generate_from_prompt(prompt_applied)
                latency_ms = int((time.time() - t_gem) * 1000)
                generated_bytes_raw = raw.get("image_bytes") or b""
                generated_b64 = base64.b64encode(generated_bytes_raw).decode("ascii") if generated_bytes_raw else ""
                generated_mime = str(raw.get("mime_type") or "image/png")
                model_name = raw.get("model")
                generation_mode = "prompt_only"

            generated_bytes = base64.b64decode(generated_b64) if generated_b64 else b""
            if not generated_bytes:
                raise RuntimeError("gemini_empty_image")
            out_path = _upload_output(
                settings,
                job.experience_id,
                job.id,
                generated_bytes,
                mime_type=generated_mime,
            )
            _write_generation_log(
                settings,
                job.id,
                level="info",
                event="gemini_generated",
                message="Gemini generated and uploaded output image",
                payload={
                    "model": model_name,
                    "latency_ms": latency_ms,
                    "mime_type": generated_mime,
                    "output_path": out_path,
                    "prompt_source": prompt_source,
                    "prompt_chars": len(prompt_applied or ""),
                    "archetype_id": (archetype or {}).get("id"),
                    "archetype_name": (archetype or {}).get("name"),
                    "generation_mode": generation_mode,
                    "use_photo_prompt": use_photo_prompt,
                    "has_photo_path": bool(photo_path),
                    "gemini_key_source": "experience" if str(effective_gemini_key or "") != str(settings.gemini_api_key or "") else "global",
                },
            )
        else:
            # Fallback path keeps previous behavior for environments without Gemini or without reference image.
            svg = _build_svg_card(job, cred)
            out_path = _upload_output(
                settings,
                job.experience_id,
                job.id,
                svg,
                mime_type="image/svg+xml",
            )
            _write_generation_log(
                settings,
                job.id,
                level="warning",
                event="fallback_svg_output",
                message="Fallback SVG output used (gemini path not eligible)",
                payload={
                    "has_gemini_key": bool(effective_gemini_key),
                    "has_photo_path": bool(photo_path),
                    "use_photo_prompt": bool((archetype or {}).get("use_photo_prompt")),
                    "has_archetype_prompt": bool(archetype_prompt),
                    "output_path": out_path,
                },
            )
        _write_generation_log(
            settings,
            job.id,
            level="info",
            event="output_uploaded",
            message="Output uploaded to storage",
            payload={"output_path": out_path},
        )
        dur = int((time.time() - t0) * 1000)
        _finish_job_done(settings, job, dur, out_path)
        _write_generation_log(
            settings,
            job.id,
            level="info",
            event="job_done",
            message="Generation job completed",
            payload={
                "duration_ms": dur,
                "cost_estimated_usd": _estimated_cost_usd(job),
                "cost_currency": "USD",
            },
        )
        print(f"[WORKER] done generation={job.id} duration_ms={dur}")
    except Exception as exc:
        dur = int((time.time() - t0) * 1000)
        _finish_job_error(settings, job, dur, str(exc))
        _write_generation_log(
            settings,
            job.id,
            level="error",
            event="job_error",
            message="Generation job failed",
            payload={
                "duration_ms": dur,
                "cost_estimated_usd": _estimated_cost_usd(job),
                "cost_currency": "USD",
                "error": str(exc)[:1000],
            },
        )
        print(f"[WORKER] error generation={job.id} duration_ms={dur} err={exc}")


def _fetch_pending(settings: Settings, limit: int) -> list[str]:
    rows = get_json(
        settings,
        "generations",
        "id",
        {"status": "eq.pending", "order": "created_at.asc"},
        limit=limit,
    )
    return [str(r.get("id")) for r in rows if r.get("id")]


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run quiz generation worker")
    parser.add_argument("--max-workers", type=int, default=5, help="Concurrent jobs")
    parser.add_argument("--batch-size", type=int, default=20, help="Pending fetch size")
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    parser.add_argument("--poll-seconds", type=float, default=2.0, help="Sleep interval when no pending jobs")
    args = parser.parse_args()

    settings = Settings.load()
    max_workers = max(1, int(args.max_workers))
    batch_size = max(1, int(args.batch_size))

    while True:
        pending_ids = _fetch_pending(settings, batch_size)
        if not pending_ids:
            if args.once:
                break
            time.sleep(max(0.1, args.poll_seconds))
            continue

        claimed: list[Job] = []
        for pid in pending_ids:
            job = _claim_job(settings, pid)
            if job:
                _write_generation_log(
                    settings,
                    job.id,
                    level="info",
                    event="job_claimed",
                    message="Job claimed from pending queue",
                    payload={"kind": job.kind},
                )
                claimed.append(job)

        if claimed:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                for job in claimed:
                    pool.submit(_process_job, settings, job)

        if args.once:
            break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
