import json
import base64
import time
import os
import requests
import io
from dataclasses import replace
from datetime import datetime, timezone
from math import floor
from urllib.parse import urlparse
from flask import Blueprint, request, jsonify, current_app, send_from_directory
from app.core.settings import Settings

from app.application.use_cases.create_session import (
    CreateSessionInput,
    execute as create_session_uc,
    system_prompt,
)
from app.domain.models import LiveSession, BudgetLedger
from app.application.use_cases.say_to_avatar import (
    SayInput,
    SayOutput,
    execute as say_uc,
)
from app.application.use_cases.interrupt_session import (
    InterruptInput,
    execute as interrupt_uc,
)
from app.application.use_cases.metrics import build_metrics
from app.infrastructure.heygen_client import HeygenClient
from app.infrastructure.liveavatar_client import LiveAvatarClient

bp = Blueprint("session", __name__)

URL_KEEPALIVE = "https://api.heygen.com/v1/streaming.keep_alive"

# ============== helpers de log ==============
def _log(kind: str, msg: str, data=None):
    try:
        if data is None:
            current_app.logger.info("[%s] %s", kind, msg)
        else:
            as_txt = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)[:2000]
            current_app.logger.info("[%s] %s | %s", kind, msg, as_txt)
    except Exception:
        pass


def _http_from_error_code(code: str | None) -> int:
    """
    Códigos para o front:
    - session_inactive -> 410
    - task_in_progress / upstream_bad_request (quando usado como busy) -> 200 (soft busy)
    - demais -> 502
    """
    if code == "session_inactive":
        return 410
    if code in ("task_in_progress", "upstream_bad_request"):
        return 200  # soft busy: não quebra a sessão
    return 502
# ===========================================

def _client_id():
    # client_id vem de cabeçalho ou query para isolar sessões por cliente
    return (request.headers.get("X-Client-Id")
            or request.args.get("client_id")
            or (request.get_json(silent=True) or {}).get("client_id")
            or "default")


# compat: alguns deploys podem não ter métodos get_session/get_budget no container (instâncias antigas)
def _get_session(container, client_id: str) -> LiveSession:
    if hasattr(container, "get_session"):
        try:
            return container.get_session(client_id)
        except Exception:
            pass
    sessions = getattr(container, "sessions", None)
    if isinstance(sessions, dict):
        if client_id not in sessions:
            sessions[client_id] = LiveSession()
        return sessions[client_id]
    sess = getattr(container, "session", None)
    if sess is None:
        sess = LiveSession()
        try:
            setattr(container, "session", sess)
        except Exception:
            pass
    return sess


def _set_session(container, client_id: str, session_obj: LiveSession):
    try:
        if hasattr(container, "sessions"):
            sessions = getattr(container, "sessions")
            if isinstance(sessions, dict):
                sessions[client_id] = session_obj
                return
    except Exception:
        pass
    try:
        setattr(container, "session", session_obj)
    except Exception:
        pass


def _get_budget(container, client_id: str) -> BudgetLedger:
    if hasattr(container, "get_budget"):
        try:
            return container.get_budget(client_id)
        except Exception:
            pass
    budgets = getattr(container, "budgets", None)
    if isinstance(budgets, dict):
        if client_id not in budgets:
            budgets[client_id] = BudgetLedger()
        return budgets[client_id]
    b = getattr(container, "budget", None)
    if b is None:
        b = BudgetLedger()
        try:
            setattr(container, "budget", b)
        except Exception:
            pass
    return b


def _set_budget(container, client_id: str, budget_obj: BudgetLedger):
    try:
        if hasattr(container, "budgets"):
            budgets = getattr(container, "budgets")
            if isinstance(budgets, dict):
                budgets[client_id] = budget_obj
                return
    except Exception:
        pass
    try:
        setattr(container, "budget", budget_obj)
    except Exception:
        pass

def _is_allowed_fetch(url: str, settings: Settings) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    if not settings.doc_fetch_allow_hosts:
        return False
    host = (parsed.hostname or "").lower()
    return host in [h.lower() for h in settings.doc_fetch_allow_hosts]

def _build_training_summary(contexts, docs) -> str:
    parts = []
    if contexts:
        ctx_txt = "; ".join([f"{c.name} (kw: {c.keywords_text or ''})" for c in contexts][:6])
        parts.append(f"Contextos: {ctx_txt}")
    if docs:
        doc_txt = "; ".join([getattr(d, "name", "") for d in docs][:6])
        parts.append(f"Docs: {doc_txt}")
    return " | ".join(parts)

def _extract_pdf_text(data: bytes, max_pages: int = 3) -> str:
    try:
        import PyPDF2  # opcional; definido em requirements
    except Exception:
        return ""
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(data))
        texts = []
        for page in reader.pages[:max_pages]:
            try:
                t = page.extract_text() or ""
                if t: texts.append(t)
            except Exception:
                continue
        return "\n".join(texts)
    except Exception:
        return ""

def _extract_doc_snippet(url: str, timeout: int = 8, max_chars: int = 1500) -> str:
    settings: Settings = current_app.container.settings
    if not _is_allowed_fetch(url, settings):
        return ""
    try:
        r = requests.get(url, timeout=timeout, stream=True)
        if not r.ok:
            return ""
        ct = (r.headers.get("content-type") or "").lower()
        max_bytes = max(1024, settings.doc_fetch_max_bytes)
        data = b""
        for chunk in r.iter_content(2048):
            data += chunk
            if len(data) > max_bytes:
                return ""
        txt = ""
        if "text/plain" in ct:
            txt = data.decode("utf-8", errors="ignore")
        elif "pdf" in ct or (url or "").lower().endswith(".pdf"):
            txt = _extract_pdf_text(data)
        elif "json" in ct:
            txt = json.dumps(r.json(), ensure_ascii=False)
        txt = (txt or "").strip()
        if not txt:
            return ""
        if len(txt) > max_chars:
            return txt[:max_chars] + "..."
        return txt
    except Exception:
        return ""

def _build_training_details(contexts, docs) -> tuple[str, list]:
    summary = _build_training_summary(contexts, docs)
    doc_snippets = []
    for d in docs[:3]:
        snippet = _extract_doc_snippet(getattr(d, "url", ""))
        if snippet:
            doc_snippets.append(f"{getattr(d,'name','doc')}: {snippet}")
    # limita tamanho total do prompt extra
    if doc_snippets:
        joined = " | ".join(doc_snippets)
        summary = (summary + " | Conteúdo docs: " + joined) if summary else ("Conteúdo docs: " + joined)
    return summary, doc_snippets

def _load_training_cache(container, avatar_id: str):
    try:
        avatar_uuid = container.ctx_repo.resolve_avatar_uuid(avatar_id)
        if not avatar_uuid:
            return [], [], ""
        contexts = container.ctx_repo.list_contexts_by_avatar(avatar_uuid)
        docs = container.ctx_repo.list_training_docs_by_avatar(avatar_uuid)
        summary, _ = _build_training_details(contexts, docs)
        return contexts, docs, summary
    except Exception as e:
        _log("TRAIN", "cache_load_err", {"err": str(e)[:200]})
        return [], [], ""

@bp.get("/heygen-sdk.umd.js")
def serve_heygen_sdk():
    s = current_app.container.settings
    import os
    path = os.path.join(s.base_dir, "public", "heygen-sdk.umd.js")
    if not os.path.isfile(path):
        return "UMD não encontrado (ok ignorar se você não usa o arquivo). Coloque em public/heygen-sdk.umd.js", 404
    return send_from_directory(s.static_dir, "heygen-sdk.umd.js", mimetype="application/javascript")


def _supabase_headers(s: Settings) -> dict:
    key = s.supabase_service_role
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _fetch_avatar_credentials(s: Settings):
    """
    Busca API key/mapeamento em Supabase. Se falhar ou não houver, usa a key do .env como fallback.
    """
    base = s.supabase_url.rstrip("/") + "/rest/v1/avatar_credentials"
    headers = _supabase_headers(s)

    main = None
    mapping = []
    try:
        r = requests.get(
            base,
            params={"select": "api_key,avatar_id,avatar_external_id", "limit": 1},
            headers=headers,
            timeout=6,
        )
        if r.ok:
            main = (r.json() or [None])[0]
        else:
            _log("SUPA", "cred_fetch_err", {"status": r.status_code, "body": r.text[:120]})
    except Exception as e:
        _log("SUPA", "cred_fetch_exc", {"err": str(e)[:120]})

    try:
        rmap = requests.get(
            base,
            params={"select": "avatar_id,avatar_external_id"},
            headers=headers,
            timeout=6,
        )
        if rmap.ok:
            mapping = rmap.json() or []
        else:
            _log("SUPA", "map_fetch_err", {"status": rmap.status_code, "body": rmap.text[:120]})
    except Exception as e:
        _log("SUPA", "map_fetch_exc", {"err": str(e)[:120]})

    # fallback: usa HEYGEN_API_KEY do .env se não achar no Supabase
    if not main or not main.get("api_key"):
        main = {"api_key": s.heygen_api_key}

    return main, mapping


def _fetch_avatar_credentials_rows(s: Settings) -> list:
    """
    Busca todas as credenciais de avatar e já decodifica api_key e avatar_external_id.
    """
    base = s.supabase_url.rstrip("/") + "/rest/v1/avatar_credentials"
    headers = _supabase_headers(s)
    rows = []
    try:
        r = requests.get(
            base,
            params={"select": "api_key,avatar_id,avatar_external_id"},
            headers=headers,
            timeout=6,
        )
        if r.ok:
            rows = r.json() or []
        else:
            _log("SUPA", "cred_rows_fetch_err", {"status": r.status_code, "body": r.text[:120]})
    except Exception as e:
        _log("SUPA", "cred_rows_fetch_exc", {"err": str(e)[:120]})

    decoded = []
    for row in rows:
        api_key = _maybe_decode_api_key(row.get("api_key"))
        avatar_external_id = _maybe_decode_external_id(row.get("avatar_external_id"))
        if not api_key or not avatar_external_id:
            continue
        decoded.append({
            "api_key": api_key,
            "avatar_id": row.get("avatar_id"),
            "avatar_external_id": avatar_external_id,
        })
    return decoded


def _resolve_avatar_api_key(settings: Settings, avatar_id: str | None) -> str | None:
    if not avatar_id:
        return None
    rows = _fetch_avatar_credentials_rows(settings)
    for row in rows:
        if avatar_id == row.get("avatar_id") or avatar_id == row.get("avatar_external_id"):
            return row.get("api_key")
    return None


def _heygen_client_for_key(settings: Settings, api_key: str | None):
    if settings.avatar_provider == "liveavatar":
        if api_key:
            return LiveAvatarClient(replace(settings, liveavatar_api_key=api_key))
        return LiveAvatarClient(settings)
    if not api_key:
        return HeygenClient(settings)
    if api_key == settings.heygen_api_key:
        return HeygenClient(settings)
    return HeygenClient(replace(settings, heygen_api_key=api_key))


def _maybe_decode_api_key(val: str | None) -> str | None:
    if not val:
        return val
    v = val.strip()
    # se parecer base64, tenta decodificar
    try:
        if any(ch in v for ch in ("=", "/")) or v.isascii():
            decoded = base64.b64decode(v).decode()
            # se decodificou para algo plausível (tem hífen típico da HeyGen), usa
            if decoded and any(c in decoded for c in "-_"):
                return decoded
    except Exception:
        pass
    return v


def _maybe_decode_external_id(val: str | None) -> str | None:
    if not val:
        return val
    v = val.strip()
    try:
        decoded = base64.b64decode(v).decode()
        if decoded:
            return decoded
    except Exception:
        pass
    return v


def _log_avatar_session_start(s: Settings, avatar_id: str, session_id: str, started_at_epoch: int):
    if not avatar_id or not session_id:
        return
    try:
        url = s.supabase_url.rstrip("/") + "/rest/v1/avatar_sessions"
        headers = _supabase_headers(s)
        headers["Prefer"] = "resolution=merge-duplicates"
        payload = {
            "avatar_id": avatar_id,
            "session_id": session_id,
            "started_at": datetime.fromtimestamp(started_at_epoch, tz=timezone.utc).isoformat(),
            "platform": "web",
            "metadata": {"source": "backend"},
        }
        requests.post(
            url,
            params={"on_conflict": "session_id"},
            headers=headers,
            json=payload,
            timeout=6,
        )
    except Exception as e:
        _log("SUPA", "session_start_log_err", {"err": str(e)[:120]})


def _log_avatar_session_end(s: Settings, session_id: str, duration_seconds: float):
    if not session_id:
        return
    try:
        url = s.supabase_url.rstrip("/") + "/rest/v1/avatar_sessions"
        headers = _supabase_headers(s)
        payload = {
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": max(0, int(duration_seconds or 0)),
        }
        requests.patch(
            url,
            params={"session_id": f"eq.{session_id}"},
            headers=headers,
            json=payload,
            timeout=6,
        )
    except Exception as e:
        _log("SUPA", "session_end_log_err", {"err": str(e)[:120]})


OPEN_SESSION_MAX_SECONDS = 15 * 60


def _build_avatar_usage_from_supa(rows: list) -> list:
    usage_by_avatar = {}
    for row in rows or []:
        avatar_id = row.get("avatar_id")
        duration = row.get("duration_seconds") or 0
        try:
            duration = float(duration or 0)
        except Exception:
            duration = 0
        if duration <= 0:
            started_at = row.get("started_at")
            ended_at = row.get("ended_at")
            if started_at and not ended_at:
                try:
                    dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                    duration = max(0.0, time.time() - dt.timestamp())
                    if duration > OPEN_SESSION_MAX_SECONDS:
                        duration = OPEN_SESSION_MAX_SECONDS
                except Exception:
                    duration = 0
        if not avatar_id or duration <= 0:
            continue
        agg = usage_by_avatar.get(avatar_id, {"seconds": 0, "count": 0})
        agg["seconds"] += duration
        agg["count"] += 1
        usage_by_avatar[avatar_id] = agg

    avatar_usage = []
    for avatar_id, val in usage_by_avatar.items():
        total_minutes = floor(val["seconds"] / 60)
        avatar_usage.append({
            "avatarId": avatar_id,
            "heygenAvatarId": None,
            "totalSeconds": val["seconds"],
            "totalMinutes": total_minutes,
            "heygenCredits": total_minutes,
            "euvatarCredits": total_minutes * 4,
            "sessionCount": val["count"],
        })
    return avatar_usage


def _fetch_avatar_sessions_usage(s: Settings) -> list:
    try:
        url = s.supabase_url.rstrip("/") + "/rest/v1/avatar_sessions"
        headers = _supabase_headers(s)
        # limita últimas sessões para não estourar payload
        r = requests.get(
            url,
            params={"select": "avatar_id,duration_seconds,session_id,started_at,ended_at", "order": "started_at.desc", "limit": 1000},
            headers=headers,
            timeout=6,
        )
        if not r.ok:
            _log("SUPA", "session_list_err", {"status": r.status_code, "body": r.text[:120]})
            return []
        return _build_avatar_usage_from_supa(r.json() or [])
    except Exception as e:
        _log("SUPA", "session_list_exc", {"err": str(e)[:120]})
        return []


def _resolve_avatar_external_id(settings: Settings, avatar_id: str) -> str:
    """
    Se avatar_id for UUID do Supabase, tenta buscar avatar_external_id na tabela avatar_credentials.
    Caso contrário, assume que já é o id da HeyGen.
    """
    # heurística simples: UUID contém '-'
    looks_uuid = "-" in avatar_id
    if not looks_uuid:
        return avatar_id
    try:
        url = settings.supabase_url.rstrip("/") + "/rest/v1/avatar_credentials"
        headers = {
            "apikey": settings.supabase_service_role,
            "Authorization": f"Bearer {settings.supabase_service_role}",
        }
        r = requests.get(
            url,
            params={"select": "avatar_external_id", "avatar_id": f"eq.{avatar_id}", "limit": 1},
            headers=headers,
            timeout=10,
        )
        if r.ok:
            data = (r.json() or [])
            if data:
                ext = data[0].get("avatar_external_id")
                return _maybe_decode_external_id(ext) or avatar_id
    except Exception:
        pass
    return avatar_id


def _calc_credits_payload(remaining_quota: float):
    """
    Replica a lógica da edge function:
    - remaining_quota vem em segundos (HeyGen)
    - heygenCredits = remaining_quota / 60
    - 1 HeyGen credit = 5 minutos = 20 créditos Euvatar
    """
    heygenCredits = remaining_quota / 60.0
    raw_euvatar = floor(heygenCredits * 20)
    raw_minutes = floor(heygenCredits * 5)

    totalEuvatarCredits = 960
    totalMinutes = 240
    totalHours = 4

    euvatarCredits = min(max(raw_euvatar, 0), totalEuvatarCredits)
    minutesRemaining = min(max(raw_minutes, 0), totalMinutes)
    hoursRemaining = minutesRemaining / 60.0

    usedCredits = max(0, totalEuvatarCredits - euvatarCredits)
    usedMinutes = max(0, totalMinutes - minutesRemaining)
    percentage = 0 if totalEuvatarCredits == 0 else round((euvatarCredits / totalEuvatarCredits) * 100)

    return {
        "euvatarCredits": euvatarCredits,
        "heygenCredits": floor(heygenCredits),
        "totalEuvatarCredits": totalEuvatarCredits,
        "minutesRemaining": minutesRemaining,
        "totalMinutes": totalMinutes,
        "hoursRemaining": round(hoursRemaining, 2),
        "totalHours": totalHours,
        "usedEuvatarCredits": usedCredits,
        "usedMinutes": usedMinutes,
        "percentageRemaining": percentage,
    }


def _build_avatar_usage(sessions: list, mapping_rows: list) -> list:
    usage_by_avatar = {}
    for session in sessions or []:
        avatar_id = session.get("avatar_id") or session.get("streaming_avatar_id") or session.get("avatarId")
        duration = session.get("duration") or session.get("duration_seconds") or session.get("durationSeconds") or 0
        try:
            duration = float(duration or 0)
        except Exception:
            duration = 0
        if duration > 10000:
            duration = duration / 1000.0
        if duration <= 0:
            started_at = (session.get("started_at") or session.get("start_time") or session.get("startTime")
                          or session.get("created_at"))
            if started_at:
                try:
                    if isinstance(started_at, (int, float)):
                        ts = float(started_at)
                        if ts > 1e12:
                            ts = ts / 1000.0
                        duration = max(0.0, time.time() - ts)
                    elif isinstance(started_at, str):
                        dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                        duration = max(0.0, time.time() - dt.timestamp())
                except Exception:
                    duration = 0
        if not avatar_id or duration <= 0:
            continue
        agg = usage_by_avatar.get(avatar_id, {"seconds": 0, "count": 0})
        agg["seconds"] += duration
        agg["count"] += 1
        usage_by_avatar[avatar_id] = agg

    mapping = {row.get("avatar_external_id"): row.get("avatar_id") for row in (mapping_rows or [])}
    avatar_usage = []
    for heygen_id, val in usage_by_avatar.items():
        total_minutes = floor(val["seconds"] / 60)
        avatar_usage.append({
            "avatarId": mapping.get(heygen_id) or heygen_id,
            "heygenAvatarId": heygen_id,
            "totalSeconds": val["seconds"],
            "totalMinutes": total_minutes,
            "heygenCredits": total_minutes,
            "euvatarCredits": total_minutes * 4,  # 1 minuto = 4 créditos Euvatar
            "sessionCount": val["count"],
        })
    return avatar_usage


@bp.get("/credits")
def credits():
    """
    Retorna créditos e uso por avatar, consumindo Supabase (service role) e quota HeyGen.
    Payload compatível com a edge function get-heygen-credits.
    """
    s: Settings = current_app.container.settings
    if s.avatar_provider == "liveavatar":
        avatar_usage = _fetch_avatar_sessions_usage(s)
        return jsonify({
            "error": "Créditos LiveAvatar estimados via uso (sem API oficial)",
            "needsCredentialUpdate": False,
            "avatarUsage": avatar_usage,
            "euvatarCredits": 0,
            "heygenCredits": 0,
            "totalEuvatarCredits": 960,
            "minutesRemaining": 0,
            "totalMinutes": 240,
            "hoursRemaining": 0,
            "totalHours": 4,
            "usedEuvatarCredits": 0,
            "usedMinutes": 0,
            "percentageRemaining": 0,
        }), 200

    # Busca todas as credenciais por avatar (cada avatar pode ter sua própria api_key)
    cred_rows = _fetch_avatar_credentials_rows(s)
    keys = sorted({row.get("api_key") for row in cred_rows if row.get("api_key")})

    # fallback: usa HEYGEN_API_KEY do .env se não achar no Supabase
    if not keys and s.heygen_api_key:
        keys = [s.heygen_api_key]
        _log("CRED", "using_env_key_fallback", {"len": len(s.heygen_api_key or ""), "starts": (s.heygen_api_key or "")[:6]})
    else:
        _log("CRED", "using_keys_from_supa", {"count": len(keys)})

    mapping = [{"avatar_id": row.get("avatar_id"), "avatar_external_id": row.get("avatar_external_id")} for row in cred_rows]

    # Primeiro tenta o endpoint novo; se 404 ou 401, tenta o antigo.
    def _fetch_quota(url: str, key: str):
        return requests.get(
            url,
            headers={"X-Api-Key": key, "Content-Type": "application/json"},
            timeout=15,
        )

    if not keys:
        return jsonify({"error": "Credenciais não configuradas", "avatarUsage": []}), 400

    remaining_quota_total = 0.0
    quota_ok = False
    quota_any_401 = False

    for key in keys:
        try:
            quota_resp = _fetch_quota("https://api.heygen.com/v2/get_remaining_quota", key)
            if quota_resp.status_code in (401, 404):
                _log("HEYGEN", "quota_fallback", {"status": quota_resp.status_code, "body": quota_resp.text[:200]})
                quota_resp = _fetch_quota("https://api.heygen.com/v2/user/remaining_quota", key)
        except Exception as e:
            _log("HEYGEN", "quota_exc", {"err": str(e)[:200]})
            continue

        if quota_resp is None:
            continue

        if quota_resp.status_code == 401:
            quota_any_401 = True
            try:
                _log("HEYGEN", "quota_401_body", {"body": quota_resp.text[:200]})
            except Exception:
                pass
            continue

        if not quota_resp.ok:
            _log("HEYGEN", "quota_err", {"status": quota_resp.status_code, "body": quota_resp.text[:200]})
            continue

        data = quota_resp.json() if quota_resp.text else {}
        remaining_quota = (data.get("data") or {}).get("remaining_quota") or data.get("remaining_quota") or 0
        remaining_quota_total += float(remaining_quota or 0)
        quota_ok = True

    payload = _calc_credits_payload(remaining_quota_total) if quota_ok else {
        "euvatarCredits": 0,
        "heygenCredits": 0,
        "totalEuvatarCredits": 960,
        "minutesRemaining": 0,
        "totalMinutes": 240,
        "hoursRemaining": 0,
        "totalHours": 4,
        "usedEuvatarCredits": 0,
        "usedMinutes": 0,
        "percentageRemaining": 0,
    }

    avatar_usage = _fetch_avatar_sessions_usage(s)
    if not avatar_usage:
        try:
            sessions = []
            for key in keys:
                sessions_resp = requests.get(
                    "https://api.heygen.com/v2/streaming.list",
                    params={"page_size": 100},
                    headers={"X-Api-Key": key, "Content-Type": "application/json"},
                    timeout=20,
                )
                if sessions_resp.ok:
                    sessions_data = sessions_resp.json().get("data", {})
                    sessions.extend(sessions_data.get("data", []) or [])
                else:
                    _log("HEYGEN", "sessions_err", {"status": sessions_resp.status_code, "body": sessions_resp.text[:200]})
            avatar_usage = _build_avatar_usage(sessions, mapping)
        except Exception as e:
            _log("HEYGEN", "sessions_exc", {"err": str(e)[:200]})

    payload["avatarUsage"] = avatar_usage
    if not quota_ok and quota_any_401:
        payload["error"] = "A API key do Euvatar está inválida ou expirada"
        payload["needsCredentialUpdate"] = True
        return jsonify(payload), 200
    if not quota_ok:
        payload["error"] = "Erro ao buscar créditos do Euvatar"
        return jsonify(payload), 502
    return jsonify(payload), 200


@bp.get("/heygen/avatars")
def list_heygen_avatars():
    """
    Lista avatares da HeyGen usando a API key configurada em avatar_credentials (Supabase).
    Endpoint HeyGen: GET /v2/avatars
    """
    s: Settings = current_app.container.settings
    if s.avatar_provider == "liveavatar":
        return list_liveavatar_avatars()
    creds, _ = _fetch_avatar_credentials(s)
    api_key = None
    if creds and creds.get("api_key"):
        api_key = _maybe_decode_api_key(creds.get("api_key"))
    elif s.heygen_api_key:
        api_key = _maybe_decode_api_key(s.heygen_api_key)
    if not api_key:
        return jsonify({"error": "Credenciais não configuradas"}), 400
    if s.avatar_provider == "liveavatar":
        return list_liveavatar_avatars()
    try:
        resp = requests.get(
            "https://api.heygen.com/v2/avatars",
            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
            timeout=15,
        )
    except Exception as e:
        _log("HEYGEN", "avatars_exc", {"err": str(e)[:200]})
        return jsonify({"error": "Erro ao consultar avatares HeyGen"}), 502

    if resp.status_code == 401:
        return jsonify({"error": "API key inválida ou expirada", "needsCredentialUpdate": True}), 200
    if not resp.ok:
        _log("HEYGEN", "avatars_err", {"status": resp.status_code, "body": resp.text[:200]})
        return jsonify({"error": "Erro ao consultar avatares HeyGen", "details": resp.text[:200]}), 502

    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text[:500]}

    return jsonify({"ok": True, "data": data.get("data") if isinstance(data, dict) else data}), 200


@bp.get("/liveavatar/avatars")
def list_liveavatar_avatars():
    """
    Lista avatares do LiveAvatar (publicos + da conta).
    """
    s: Settings = current_app.container.settings
    creds, _ = _fetch_avatar_credentials(s)
    api_key = None
    if creds and creds.get("api_key"):
        api_key = _maybe_decode_api_key(creds.get("api_key"))
    elif s.liveavatar_api_key:
        api_key = s.liveavatar_api_key
    if not api_key:
        return jsonify({"error": "Credenciais não configuradas"}), 400

    def _fetch(url: str):
        return requests.get(
            url,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            timeout=15,
        )

    public_resp = _fetch("https://api.liveavatar.com/v1/avatars/public")
    account_resp = _fetch("https://api.liveavatar.com/v1/avatars")

    if public_resp.status_code == 401 or account_resp.status_code == 401:
        return jsonify({"error": "API key inválida ou expirada", "needsCredentialUpdate": True}), 200

    if not public_resp.ok and not account_resp.ok:
        _log("LIVEAVATAR", "avatars_err", {
            "public_status": public_resp.status_code,
            "account_status": account_resp.status_code
        })
        return jsonify({"error": "Erro ao consultar avatares LiveAvatar"}), 502

    public_data = public_resp.json() if public_resp.ok and public_resp.text else {}
    account_data = account_resp.json() if account_resp.ok and account_resp.text else {}

    return jsonify({
        "ok": True,
        "data": {
            "public": public_data.get("data") if isinstance(public_data, dict) else public_data,
            "account": account_data.get("data") if isinstance(account_data, dict) else account_data,
        }
    }), 200

@bp.get("/token")
def create_session_token():
    t0 = time.time()
    try:
        c = current_app.container
        avatar_id = request.args.get("avatar_id") or ""
        api_key = _resolve_avatar_api_key(c.settings, avatar_id) or c.settings.heygen_api_key
        token = _heygen_client_for_key(c.settings, api_key).create_token()
        _log("TOKEN", "create ok", {"ms": int((time.time()-t0)*1000)})
        return jsonify({"ok": True, "token": token})
    except Exception as e:
        _log("ERR", "token_exception", {"ms": int((time.time()-t0)*1000), "e": str(e)})
        return jsonify({"ok": False, "error": f"token_exception: {e}"}), 500


@bp.get("/new")
def new_session():
    t0 = time.time()
    try:
        c = current_app.container
        client_id = _client_id()
        session = _get_session(c, client_id)
        budget = _get_budget(c, client_id)
        language = request.args.get("language", "pt-BR")
        persona  = request.args.get("persona", "default")
        quality  = request.args.get("quality", "low")
        backstory_param = request.args.get("backstory") or ""
        voice_id = request.args.get("voice_id")
        context_id = request.args.get("context_id")
        context_id = request.args.get("context_id")
        minutes  = float(request.args.get("minutes", "2.5"))

        # >>> DICA (SDK novo): activityIdleTimeout deve ser tratado no client HeyGen (create_session_uc).
        # Garanta no seu IHeygenClient que está usando 'activityIdleTimeout' e NÃO 'disableIdleTimeout'.

        # === modo resume via GET /new?resume=1&session_id=... ===
        resume_flag = request.args.get("resume") == "1"
        resume_id   = request.args.get("session_id")

        if resume_flag:
            sid = resume_id or getattr(session, "session_id", None)
            if not sid:
                return jsonify({"ok": False, "error": "missing_session_id"}), 400

            _log("RESUME", "in(/new)", {"session_id": sid})
            # receber avatar_id vindo do front
            avatar_id = request.args.get("avatar_id") or c.settings.heygen_default_avatar
            api_key = _resolve_avatar_api_key(c.settings, avatar_id) or c.settings.heygen_api_key
            heygen_client = _heygen_client_for_key(c.settings, api_key)

            if c.settings.avatar_provider == "liveavatar":
                if not voice_id and c.settings.liveavatar_voice_id:
                    voice_id = c.settings.liveavatar_voice_id
                if not context_id and c.settings.liveavatar_context_id:
                    context_id = c.settings.liveavatar_context_id

            out = create_session_uc(
                heygen_client, budget,
                CreateSessionInput(
                    persona=persona,
                    language=language,
                    quality=quality,
                    backstory_param=backstory_param,
                    voice_id=voice_id,
                    context_id=context_id,
                    minutes=minutes,
                    avatar_id=avatar_id
                )
            )

            if not out.ok:
                _log("ERR", "resume_uc", {"error": out.error, "ms": int((time.time()-t0)*1000)})
                return jsonify({"ok": False, "error": out.error}), 502

            out.session.avatar_id = avatar_id
            out.session.api_key = api_key
            _set_session(c, client_id, out.session)
            now_epoch = int(time.time())
            out.session.started_at_epoch = now_epoch
            if not getattr(out.session, "ends_at_epoch", None):
                out.session.ends_at_epoch = int(now_epoch + minutes * 60)
            try:
                _log_avatar_session_start(c.settings, avatar_id, out.session.session_id, now_epoch)
            except Exception:
                pass

            # carrega cache de treinamento (contextos + docs) uma vez
            ctxs, docs, summary = _load_training_cache(c, avatar_id)
            out.session.training_contexts = ctxs
            out.session.training_docs = docs
            out.session.training_summary = summary

            resp = {"ok": True, "session_id": out.session.session_id, "livekit_url": out.session.url, "access_token": out.session.token}
            _log("RESUME", "ok(/new)", {"ms": int((time.time()-t0)*1000), "session": out.session.session_id})
            return jsonify(resp)

        # === fluxo normal: criar sessão nova ===
        _log("NEW", "in", {"language": language, "persona": persona, "quality": quality, "minutes": minutes})

        avatar_id_in = request.args.get("avatar_id") or c.settings.heygen_default_avatar
        api_key = _resolve_avatar_api_key(c.settings, avatar_id_in) or c.settings.heygen_api_key
        heygen_client = _heygen_client_for_key(c.settings, api_key)
        avatar_id = _resolve_avatar_external_id(c.settings, avatar_id_in)
        if c.settings.avatar_provider == "liveavatar":
            if not voice_id and c.settings.liveavatar_voice_id:
                voice_id = c.settings.liveavatar_voice_id
            if not context_id and c.settings.liveavatar_context_id:
                context_id = c.settings.liveavatar_context_id

        out = create_session_uc(
            heygen_client, budget,
            CreateSessionInput(
                persona=persona,
                language=language,
                quality=quality,
                backstory_param=backstory_param,
                voice_id=voice_id,
                context_id=context_id,
                minutes=minutes,
                avatar_id=avatar_id   # <-- AGORA SIM!!
            )
        )
        if not out.ok:
            _log("ERR", "create_session_uc", {"error": out.error, "ms": int((time.time()-t0)*1000)})
            return jsonify({"ok": False, "error": out.error}), 502

        out.session.avatar_id = avatar_id_in
        out.session.api_key = api_key
        _set_session(c, client_id, out.session)
        now_epoch = int(time.time())
        out.session.started_at_epoch = now_epoch
        out.session.ends_at_epoch = int(now_epoch + minutes * 60)
        try:
            _log_avatar_session_start(c.settings, avatar_id_in, out.session.session_id, now_epoch)
        except Exception:
            pass

        # carrega cache de treinamento (contextos + docs) uma vez
        ctxs, docs, summary = _load_training_cache(c, avatar_id_in)
        out.session.training_contexts = ctxs
        out.session.training_docs = docs
        out.session.training_summary = summary

        resp = {"ok": True, "session_id": out.session.session_id, "livekit_url": out.session.url, "access_token": out.session.token}
        _log("NEW", "ok", {"ms": int((time.time()-t0)*1000), "session": out.session.session_id})
        return jsonify(resp)
    except Exception as e:
        _log("ERR", "new_exception", {"ms": int((time.time()-t0)*1000), "e": str(e)})
        return jsonify({"ok": False, "error": f"new_exception: {e}"}), 500



@bp.post("/say")
def say():
    t0 = time.time()
    c = current_app.container
    client_id = _client_id()
    session = _get_session(c, client_id)
    try:
        data = request.get_json(force=True) or {}
        session_id = data.get("session_id") or getattr(session, "session_id", None)
        text = (data.get("text") or "").strip()
        avatar_id = (data.get("avatar_id") or "").strip()

        _log("SAY", "in", {"session_id": session_id, "text_len": len(text)})

        if not session_id or not text:
            return jsonify({"ok": False, "error": "missing_params"}), 400

        # sessão expirada pelo nosso controle de tempo
        if getattr(session, "ends_at_epoch", None):
            if int(time.time()) >= int(session.ends_at_epoch):
                _log("SAY", "expired", {"now": int(time.time()), "ends": int(session.ends_at_epoch)})
                return jsonify({"ok": False, "error": "session_expired", "error_code": "session_inactive"}), 410

        training = getattr(session, "training_summary", "")
        if not training and avatar_id:
            try:
                ctxs, docs, summary = _load_training_cache(c, avatar_id)
                if summary:
                    session.training_contexts = ctxs
                    session.training_docs = docs
                    session.training_summary = summary
                    training = summary
            except Exception:
                pass
        sys = data.get("system") or system_prompt(
            getattr(session, "backstory", "") or "",
            getattr(session, "language", "pt-BR") or "pt-BR",
            training
        )

        api_key = getattr(session, "api_key", None)
        if not api_key:
            api_key = _resolve_avatar_api_key(c.settings, avatar_id or getattr(session, "avatar_id", None)) or c.settings.heygen_api_key
        heygen_client = _heygen_client_for_key(c.settings, api_key)
        out: SayOutput = say_uc(c.settings, heygen_client, c.ctx_repo, SayInput(session, text, sys, avatar_identifier=avatar_id))

        if not out.ok:
            status = _http_from_error_code(out.error_code)
            payload = {
                "ok": False,
                "error": out.error or "say_failed",
                "error_code": out.error_code or "upstream_error",
                "soft_busy": bool(getattr(out, "soft_busy", False))
            }
            _log("ERR", "say_uc", {"ms": int((time.time()-t0)*1000), **payload})
            return jsonify(payload), status

        resp = {
            "ok": True,
            "duration_ms": out.duration_ms,
            "task_id": out.task_id,
            "media": (out.media.__dict__ if out.media else None),
            "context_method": out.context_method
        }
        _log("SAY", "ok", {"ms": int((time.time()-t0)*1000), "task_id": out.task_id, "duration_ms": out.duration_ms})
        return jsonify(resp)
    except Exception as e:
        _log("ERR", "say_exception", {"ms": int((time.time()-t0)*1000), "e": str(e)})
        return jsonify({"ok": False, "error": f"say_exception: {e}"}), 500
    

@bp.route("/keepalive", methods=["POST", "OPTIONS"])
def keepalive():
    """KeepAlive real: chamamos a HeyGen. Se ela disser 'closed/inactive', devolvemos error_code=session_inactive."""
    if request.method == "OPTIONS":
        return jsonify({"ok": True}), 200
    try:
        c = current_app.container
        client_id = _client_id()
        session = _get_session(c, client_id)
        if not getattr(session, "session_id", None):
            return jsonify({"ok": False, "error": "no_session"}), 200
        data = request.get_json(silent=True) or {}

        sid = session.session_id
        # você pode guardar isso no Settings se quiser expor na UI
        idle = getattr(c.settings, "heygen_activity_idle_timeout", 120)
        api_key = getattr(session, "api_key", None) or c.settings.heygen_api_key
        r = _heygen_client_for_key(c.settings, api_key).keep_alive(sid, activity_idle_timeout=idle)

        try:
            body = r.json()
        except Exception:
            body = {"message": r.text[:300]}

        error_code = None
        msg = (str(body) or "").lower()
        if r.status_code == 400:
            if "invalid session state" in msg or "closed" in msg or "inactive" in msg or "not found" in msg:
                error_code = "session_inactive"

        # estende o TTL local quando o usuário clica em "Continuar" (mantém alinhado ao timer do front)
        extend_minutes = 0.0
        try:
            extend_minutes = float(data.get("extend_minutes") or 0)
        except Exception:
            extend_minutes = 0.0
        if extend_minutes > 0:
            session.ends_at_epoch = int(time.time() + max(0.5, extend_minutes) * 60)

        current_app.logger.info("[PING] keepalive %s | heygen=%s | extend=%.2f", sid, r.status_code, extend_minutes)
        return jsonify({
            "ok": bool(r.ok),
            "heygen_status": r.status_code,
            "heygen_body": body,
            "error_code": error_code
        }), 200

    except Exception as e:
        return jsonify({"ok": False, "error": f"keepalive_exception: {e}"}), 200

@bp.after_app_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Client-Id"
    return resp


@bp.post("/resume")
def resume_livekit():
    """Renova token/URL do LiveKit para a MESMA sessão (sem gastar crédito)."""
    t0 = time.time()
    try:
        c = current_app.container
        client_id = _client_id()
        session = _get_session(c, client_id)
        budget = _get_budget(c, client_id)
        data = request.get_json(force=True) or {}
        sid = data.get("session_id") or getattr(session, "session_id", None)
        if not sid:
            return jsonify({"ok": False, "error": "missing_session_id"}), 400

        _log("RESUME", "in", {"session_id": sid})

        mins_left = 2.5
        if getattr(session, "ends_at_epoch", None):
            left = max(1, int(session.ends_at_epoch - time.time()))
            mins_left = max(0.5, left / 60.0)
        
        api_key = getattr(session, "api_key", None) or c.settings.heygen_api_key
        heygen_client = _heygen_client_for_key(c.settings, api_key)
        avatar_id = getattr(session, "avatar_id", None) or c.settings.heygen_default_avatar
        out = create_session_uc(
            heygen_client, budget,
            CreateSessionInput(
            
                resume_session_id=sid,
                persona=getattr(session, "persona", "default"),
                language=getattr(session, "language", "pt-BR"),
                quality=getattr(session, "quality", "low"),
                backstory_param=getattr(session, "backstory", ""),
                voice_id=None,
                minutes=mins_left,
                avatar_id=avatar_id
            )
        )
        if not out.ok:
            _log("ERR", "resume_uc", {"error": out.error, "ms": int((time.time()-t0)*1000)})
            return jsonify({"ok": False, "error": out.error}), 502

        out.session.avatar_id = avatar_id
        out.session.api_key = api_key
        _set_session(c, client_id, out.session)

        resp = {
            "ok": True,
            "session_id": out.session.session_id,
            "livekit_url": out.session.url,
            "access_token": out.session.token
        }
        _log("RESUME", "ok", {"ms": int((time.time()-t0)*1000), "session": out.session.session_id})
        return jsonify(resp)
    except Exception as e:
        _log("ERR", "resume_exception", {"ms": int((time.time()-t0)*1000), "e": str(e)})
        return jsonify({"ok": False, "error": f"resume_exception: {e}"}), 500


@bp.post("/interrupt")
def interrupt():
    t0 = time.time()
    c = current_app.container
    client_id = _client_id()
    session = _get_session(c, client_id)
    try:
        session_id = (request.get_json(force=True) or {}).get("session_id") or getattr(session, "session_id", None)
        if not session_id:
            return jsonify({"ok": False, "error": "missing_session_id"}), 400
        api_key = getattr(session, "api_key", None) or c.settings.heygen_api_key
        interrupt_uc(_heygen_client_for_key(c.settings, api_key), InterruptInput(session_id))
        _log("INT", "ok", {"ms": int((time.time()-t0)*1000), "session": session_id})
        return jsonify({"ok": True})
    except Exception as e:
        _log("ERR", "interrupt_exception", {"ms": int((time.time()-t0)*1000), "e": str(e)})
        return jsonify({"ok": False, "error": f"interrupt_exception: {e}"}), 500
    finally:
        try:
            if getattr(session, "session_id", None):
                started_at = getattr(session, "started_at_epoch", None)
                if started_at:
                    duration = max(0, int(time.time()) - int(started_at))
                    try:
                        _log_avatar_session_end(c.settings, session.session_id, duration)
                    except Exception:
                        pass
            _set_session(c, client_id, LiveSession())
        except Exception:
            pass


@bp.post("/end")
def end():
    c = current_app.container
    client_id = _client_id()
    try:
        session = _get_session(c, client_id)
        if getattr(session, "session_id", None):
            started_at = getattr(session, "started_at_epoch", None)
            if started_at:
                duration = max(0, int(time.time()) - int(started_at))
                try:
                    _log_avatar_session_end(c.settings, session.session_id, duration)
                except Exception:
                    pass
        _set_session(c, client_id, LiveSession())  # reset apenas desse cliente
    except Exception:
        pass
    _log("END", "ok")
    return jsonify({"ok": True})


@bp.get("/metrics")
def metrics():
    c = current_app.container
    client_id = _client_id()
    session = _get_session(c, client_id)
    budget = _get_budget(c, client_id)
    return jsonify(build_metrics(session, budget))
