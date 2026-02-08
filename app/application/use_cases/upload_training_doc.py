"""Use-case for uploading training documents."""

from dataclasses import dataclass
from datetime import datetime, timezone
from app.core.settings import Settings
from app.domain.ports import IStorage, IContextRepository
from app.infrastructure.supabase_rest import insert_json, get_json, patch_json
from app.shared.text_utils import safe_filename

import io
import base64
import requests
from PyPDF2 import PdfReader


@dataclass
class UploadTrainingDocInput:
    avatar_identifier: str
    filename: str
    content_type: str
    data: bytes
    title: str | None = None


def execute(settings: Settings, storage: IStorage, repo: IContextRepository, args: UploadTrainingDocInput) -> tuple[dict, int]:
    avatar_uuid = repo.resolve_avatar_uuid(args.avatar_identifier)
    if not avatar_uuid:
        return {"ok": False, "error": "avatar_not_found"}, 404

    fname = safe_filename(args.filename or "document.bin")
    path = f"{avatar_uuid}/training-docs/{fname}"

    storage.upsert(settings.supabase_bucket, path, args.content_type, args.data)
    public_url = storage.public_url(settings.supabase_bucket, path)

    created_at = datetime.now(timezone.utc).isoformat()
    url_cols = ["document_url", "url", "file_url", "path"]
    name_cols = ["document_name", "name", "title", "document", "filename"]
    last_err = None
    for ucol in url_cols:
        for ncol in name_cols:
            for include_created in (True, False):
                row = {"avatar_id": avatar_uuid, ucol: public_url, ncol: (args.title or fname)}
                if include_created:
                    row["created_at"] = created_at
                try:
                    insert_json(settings, "training_docs", [row])
                    doc_name = row[ncol]
                    _attach_training_to_backstory(settings, avatar_uuid, args, doc_name)
                    _invalidate_avatar_context(settings, avatar_uuid)
                    return {
                        "ok": True,
                        "avatar_id": avatar_uuid,
                        "document_url": public_url,
                        "document_name": row[ncol],
                        "used_cols": {"url": ucol, "name": ncol, "created_at": include_created},
                    }, 200
                except Exception as e:
                    last_err = str(e)
                    continue

    return {"ok": False, "error": "insert_failed", "details": last_err}, 500


def _attach_training_to_backstory(settings: Settings, avatar_uuid: str, args: UploadTrainingDocInput, doc_name: str):
    try:
        text = _extract_text(args)
        if not text:
            return
        summary = _summarize_text(settings, text)
        if not summary:
            return
        # carrega backstory atual
        rows = get_json(settings, "avatars", "backstory", {"id": f"eq.{avatar_uuid}"}, limit=1)
        current = (rows[0].get("backstory") if rows else "") or ""
        block = f"\n\n[Treinado com o documento: {doc_name}]\n{summary}".strip()
        if block in current:
            return
        new_backstory = (current.strip() + "\n\n" + block).strip() if current.strip() else block
        url = f"{settings.supabase_url}/rest/v1/avatars?id=eq.{avatar_uuid}"
        patch_json(settings, url, {"backstory": new_backstory})
    except Exception:
        # falha silenciosa para não bloquear upload
        return


def _invalidate_avatar_context(settings: Settings, avatar_uuid: str):
    try:
        url = f"{settings.supabase_url}/rest/v1/avatar_credentials?avatar_id=eq.{avatar_uuid}"
        patch_json(settings, url, {"context_id": None})
    except Exception:
        return


def _extract_text(args: UploadTrainingDocInput) -> str:
    ct = (args.content_type or "").lower()
    name = (args.filename or "").lower()
    data = args.data or b""

    if ct.startswith("text/") or name.endswith(".txt"):
        try:
            return data.decode("utf-8", errors="ignore")
        except Exception:
            return ""

    if "pdf" in ct or name.endswith(".pdf"):
        try:
            reader = PdfReader(io.BytesIO(data))
            parts = []
            for page in reader.pages:
                parts.append(page.extract_text() or "")
            return "\n".join(parts)
        except Exception:
            return ""

    return ""


def _summarize_text(settings: Settings, text: str) -> str:
    clean = (text or "").strip()
    if not clean:
        return ""

    # limita tamanho para evitar payload enorme
    snippet = clean[:6000]

    if not settings.openai_api_key:
        return snippet[:1500]

    try:
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "system",
                    "content": "Resuma o texto em até 12 bullet points objetivos, em português do Brasil.",
                },
                {"role": "user", "content": snippet},
            ],
            "temperature": 0.2,
        }
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json=payload,
            timeout=60,
        )
        if not r.ok:
            return snippet[:1500]
        data = r.json() or {}
        return (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip() or snippet[:1500]
    except Exception:
        return snippet[:1500]
