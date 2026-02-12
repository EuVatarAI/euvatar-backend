"""Speech-to-text endpoints for audio transcription.

IMPORTANT:
This endpoint only transcribes and prepares assistant text. It does not resolve
or return media triggers. Trigger resolution is executed in `/say`, after the
final assistant response is produced.
"""

from __future__ import annotations

import requests
from flask import Blueprint, request, jsonify, current_app, g

from app.application.use_cases.speech_to_text import execute, STTInput
from app.application.use_cases.resolve_context import execute as resolve_context_uc, ResolveInput

bp = Blueprint("stt", __name__)


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
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.2,
            "max_tokens": 140,
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
        if "audio" not in request.files:
            return jsonify({"ok": False, "error": "no_audio"}), 400
        if not c.stt:
            return jsonify({"ok": False, "error": "missing_OPENAI_API_KEY"}), 500
        f = request.files["audio"]
        stt_out = execute(c.stt, STTInput(filename=f.filename, stream=f.stream, mimetype=f.mimetype))
        if not stt_out.get("ok"):
            return jsonify(stt_out), 500

        user_text = (stt_out.get("text") or "").strip()
        avatar_id = (request.form.get("avatar_id") or "").strip()
        backstory = (request.form.get("backstory") or "").strip()
        system_prompt = backstory or (
            "Você é a Assistente Euvatar: educada, direta e prática. "
            "Responda em até 2-3 frases."
        )

        response_text = _generate_response_text(system_prompt, user_text) if user_text else ""

        media = None
        context_method = "none"
        if avatar_id and response_text:
            try:
                resolved = resolve_context_uc(
                    c.settings,
                    c.ctx_repo,
                    ResolveInput(
                        avatar_identifier=avatar_id,
                        text=response_text,
                        client_id=getattr(g, "client_id", None),
                    ),
                )
                media = resolved.get("media")
                context_method = resolved.get("method") or "none"
            except Exception:
                media = None
                context_method = "none"

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
