"""Speech-to-text endpoints for audio transcription.

IMPORTANT:
This endpoint only transcribes and prepares assistant text. It does not resolve
or return media triggers. Trigger resolution is executed in `/say`, after the
final assistant response is produced.
"""

from __future__ import annotations

import requests
import time
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app, g

from app.application.use_cases.speech_to_text import execute, STTInput
from app.application.use_cases.resolve_context import execute as resolve_context_uc, ResolveInput

bp = Blueprint("stt", __name__)
MAX_AUDIO_BYTES = 3 * 1024 * 1024  # 3 MB to keep STT latency low


def _generate_response_text(system_prompt: str, user_text: str) -> str:
    """
    Generates assistant text in backend so `/say` can consume the same semantic intent.
    Media trigger resolution does not happen here.
    """
    c = current_app.container
    settings = c.settings
    if not settings.openai_api_key:
        return ""
    try:
        payload = {
            # Faster model to reduce LLM latency in STT pipeline.
            "model": "gpt-4.1-nano",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.1,
            # Keep response very short to hit ~2s end-to-end target.
            "max_tokens": 24,
        }
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        if not resp.ok:
            return ""
        data = resp.json()
        text = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "")
        return (text or "").strip()
    except Exception:
        return ""


@bp.post("/stt")
def stt_route():
    c = current_app.container
    try:
        if request.content_length and request.content_length > MAX_AUDIO_BYTES:
            return jsonify({"ok": False, "error": "audio_too_large"}), 413
        if "audio" not in request.files:
            return jsonify({"ok": False, "error": "no_audio"}), 400
        if not c.stt:
            return jsonify({"ok": False, "error": "missing_OPENAI_API_KEY"}), 500
        f = request.files["audio"]
        if f.content_length and f.content_length > MAX_AUDIO_BYTES:
            return jsonify({"ok": False, "error": "audio_too_large"}), 413
        stt_t0 = time.time()
        stt_out = execute(c.stt, STTInput(filename=f.filename, stream=f.stream, mimetype=f.mimetype))
        stt_ms = int((time.time() - stt_t0) * 1000)
        print(f"STT_MS [{datetime.utcnow().isoformat(timespec='milliseconds')}Z]: {stt_ms}", flush=True)
        if not stt_out.get("ok"):
            return jsonify(stt_out), 500

        user_text = (stt_out.get("text") or "").strip()
        avatar_id = (request.form.get("avatar_id") or "").strip()
        backstory = (request.form.get("backstory") or "").strip()
        # Keep prompt short to reduce LLM latency.
        trimmed_backstory = backstory[:150] if backstory else ""
        system_prompt = trimmed_backstory or (
            "Você é a Assistente Euvatar: educada, direta e prática. "
            "Responda em até 1-2 frases."
        )

        llm_ms = 0
        if user_text:
            llm_t0 = time.time()
            response_text = _generate_response_text(system_prompt, user_text)
            llm_ms = int((time.time() - llm_t0) * 1000)
            print(f"LLM_MS [{datetime.utcnow().isoformat(timespec='milliseconds')}Z]: {llm_ms}", flush=True)
        else:
            response_text = ""

        media = None
        context_method = "none"
        rag_ms = 0
        # Prefer auth client_id, fallback to form (public mode).
        form_client_id = (request.form.get("client_id") or "").strip() or None
        resolved_client_id = getattr(g, "client_id", None) or form_client_id
        if avatar_id and response_text:
            try:
                rag_t0 = time.time()
                resolved = resolve_context_uc(
                    c.settings,
                    c.ctx_repo,
                    ResolveInput(
                        avatar_identifier=avatar_id,
                        text=response_text,
                        client_id=resolved_client_id,
                    ),
                )
                rag_ms = int((time.time() - rag_t0) * 1000)
                ts = datetime.utcnow().isoformat(timespec='milliseconds') + "Z"
                print(f"RAG_CLIENT [{ts}]: client_id={resolved_client_id}", flush=True)
                print(f"RAG_MS [{ts}]: {rag_ms}", flush=True)
                # Detailed breakdown for diagnostics
                print(
                    f"RAG_DETAIL [{ts}]: "
                    f"resolve_avatar_ms={resolved.get('resolve_avatar_ms')} "
                    f"list_contexts_ms={resolved.get('list_contexts_ms')} "
                    f"fast_match_ms={resolved.get('fast_match_ms')}",
                    flush=True,
                )
                media = resolved.get("media")
                context_method = resolved.get("method") or "none"
            except Exception:
                media = None
                context_method = "none"

        # Diagnostic log required by delay/repeat investigation.
        resolved_ts = datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
        print(f"MEDIA RESOLVIDA [{resolved_ts}] :", media, flush=True)

        return jsonify(
            {
                "ok": True,
                "text": user_text,
                "response_text": response_text,
                "media": media,
                "context_method": context_method,
            }
        )
    except Exception as e:
        return jsonify({"ok": False, "error": f"stt_exception: {e}"}), 500
