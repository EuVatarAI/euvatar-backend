"""Use-case to send text to the avatar during a session."""

# app/application/use_cases/say_to_avatar.py
from dataclasses import dataclass
from typing import Optional, Any, Dict
import time
import threading

from app.domain.ports import IHeygenClient, IContextRepository
from app.domain.models import MediaMatch, LiveSession
from app.application.services.context_resolver import (
    fast_match_context,
    resolve_media_for_match,
    resolve_with_gpt,
)
from app.application.services.media_detector import detect_from_text
from app.core.settings import Settings

try:
    from flask import current_app as _flask_app
except Exception:
    _flask_app = None


@dataclass
class SayInput:
    session: LiveSession
    user_text: str
    system_prompt: str
    avatar_identifier: str | None = None


@dataclass
class SayOutput:
    ok: bool
    duration_ms: int | None
    task_id: str | None
    response_text: str | None
    media: MediaMatch | None
    context_method: str
    # sinalização de “busy suave”: front deve aguardar e tentar de novo
    soft_busy: bool = False
    error: str | None = None
    error_code: str | None = None


def _log(kind: str, msg: str, data: Optional[Any] = None) -> None:
    try:
        if _flask_app:
            if data is not None:
                _flask_app.logger.info("[%s] %s | %s", kind, msg, str(data)[:1500])
            else:
                _flask_app.logger.info("[%s] %s", kind, msg)
    except Exception:
        pass


def _normalize_heygen_error(err_text: str) -> tuple[str, int]:
    e = (err_text or "").lower()

    if "room not found" in e or "session not found" in e or "inactive" in e or "expired" in e:
        return ("session_inactive", 410)

    # muitos 400 da HeyGen vêm como "BAD REQUEST" mesmo quando é "task in progress"
    if "already running" in e or "task in progress" in e or "busy" in e:
        return ("task_in_progress", 429)

    if "locked" in e:
        return ("task_locked", 423)

    if "rate limit" in e or "too many requests" in e:
        return ("rate_limited", 429)

    if "unavailable" in e or "upstream connect error" in e:
        return ("upstream_unavailable", 503)

    if "bad request" in e:
        return ("upstream_bad_request", 400)

    return ("unknown", 500)


def _extract_response_text(result: Dict[str, Any], data: Dict[str, Any]) -> str:
    """
    Try to extract the final assistant text from Heygen task_chat payload.
    Falls back to empty string when no text-like field is present.
    """
    candidates = [
        data.get("text"),
        data.get("response"),
        data.get("answer"),
        data.get("message"),
        (data.get("output") or {}).get("text") if isinstance(data.get("output"), dict) else None,
        (data.get("content") or {}).get("text") if isinstance(data.get("content"), dict) else None,
        result.get("text"),
        result.get("response"),
        result.get("answer"),
        result.get("message"),
    ]
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


# -------- gate anti-concorrência por sessão (mem local) --------
_BUSY: dict[str, float] = {}
_LOCK = threading.Lock()
BUSY_TTL = 8.0  # s

def _set_busy(session_id: str, busy: bool):
    with _LOCK:
        now = time.time()
        for k, ts in list(_BUSY.items()):
            if now - ts > BUSY_TTL:
                _BUSY.pop(k, None)
        if busy:
            _BUSY[session_id] = now
        else:
            _BUSY.pop(session_id, None)

def _is_busy(session_id: str) -> bool:
    with _LOCK:
        ts = _BUSY.get(session_id)
        return bool(ts and (time.time() - ts) < BUSY_TTL)


def execute(settings: Settings, heygen: IHeygenClient, ctx_repo: IContextRepository, args: SayInput) -> SayOutput:
    """
    Serializa /say por sessão. Em erros 400 recorrentes da HeyGen pós-1ª fala,
    sinaliza 'soft_busy' para o front aguardar e re-tentar — sem usar /interrupt.
    """
    session_id = args.session.session_id

    # evita concorrência local
    if _is_busy(session_id):
        _log("SAY", "busy gate", {"session": session_id})
        return SayOutput(
            ok=False, duration_ms=None, task_id=None, response_text=None, media=None,
            context_method="none", soft_busy=True, error="task in progress",
            error_code="task_in_progress"
        )

    try:
        _set_busy(session_id, True)

        if settings.avatar_provider == "liveavatar":
            return SayOutput(
                ok=False,
                duration_ms=None,
                task_id=None,
                response_text=None,
                media=None,
                context_method="none",
                error="liveavatar_task_chat_not_supported",
                error_code="not_supported"
            )

        prompt = f"{args.system_prompt}\nUSUÁRIO: {args.user_text}"
        _log("SAY", "task_chat init", {"session": session_id})

        attempts = 0
        result: Dict[str, Any] | None = None
        last_err_text: str | None = None

        # backoff suave (sem interrupt)
        while attempts < 6:
            attempts += 1
            try:
                result = heygen.task_chat(session_id, prompt)
                break  # sucesso
            except Exception as e:
                last_err_text = str(e)
                code, _ = _normalize_heygen_error(last_err_text)
                _log("ERR", "task_chat exception", {"mapped": code, "attempt": attempts, "err": last_err_text[:500]})

                if code in ("task_in_progress", "task_locked", "upstream_bad_request", "rate_limited", "upstream_unavailable"):
                    time.sleep(0.7 * attempts)
                    continue

                if code == "session_inactive":
                    return SayOutput(
                        ok=False, duration_ms=None, task_id=None, response_text=None, media=None,
                        context_method="none", error=last_err_text, error_code=code
                    )

                # demais: não insistir
                break

        if result is None:
            code, _ = _normalize_heygen_error(last_err_text or "unknown")
            # trata 400 recorrente como busy suave — deixa o front esperar e tentar dps
            if code in ("task_in_progress", "upstream_bad_request"):
                return SayOutput(
                    ok=False, duration_ms=None, task_id=None, response_text=None, media=None,
                    context_method="none", soft_busy=True,
                    error=last_err_text, error_code=code
                )
            return SayOutput(
                ok=False, duration_ms=None, task_id=None, response_text=None, media=None,
                context_method="none", error=last_err_text, error_code=code
            )

        data = (result.get("data") or {}) if isinstance(result, dict) else {}
        duration_ms = int(data.get("duration_ms", 0)) if isinstance(data.get("duration_ms", 0), (int, float)) else 0
        task_id = data.get("task_id")
        _log("SAY", "task_chat ok", {"duration_ms": duration_ms, "task_id": task_id})

        # Trigger resolution MUST use only the assistant final response text.
        response_text = _extract_response_text(result if isinstance(result, dict) else {}, data)
        trigger_text = response_text.strip()

        # ========= contexto/mídia =========
        media: Optional[MediaMatch] = None
        method = "none"

        if trigger_text and args.avatar_identifier:
            avatar_uuid = ctx_repo.resolve_avatar_uuid(args.avatar_identifier)
            if avatar_uuid:
                contexts = getattr(args.session, "training_contexts", None) or ctx_repo.list_contexts_by_avatar(avatar_uuid)
                names = [c.name for c in contexts]
                if names:
                    fm = fast_match_context(trigger_text, contexts)
                    if fm:
                        media = resolve_media_for_match(contexts, fm); method = "fast"
                    else:
                        match = resolve_with_gpt(settings, trigger_text, names)
                        if match != "none":
                            media = resolve_media_for_match(contexts, match); method = "gpt"

        if trigger_text and not media:
            m = detect_from_text(trigger_text)
            if m:
                media = m; method = "keywords"

        return SayOutput(
            ok=True, duration_ms=duration_ms, task_id=task_id, response_text=trigger_text, media=media, context_method=method
        )

    except Exception as e:
        err_text = str(e)
        code, _ = _normalize_heygen_error(err_text)
        _log("ERR", "execute fatal", {"mapped": code, "err": err_text[:500]})
        return SayOutput(
            ok=False, duration_ms=None, task_id=None, response_text=None, media=None,
            context_method="none", error=err_text, error_code=code
        )
    finally:
        _set_busy(session_id, False)
