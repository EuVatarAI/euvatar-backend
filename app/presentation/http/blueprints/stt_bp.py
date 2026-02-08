"""Speech-to-text endpoints for audio transcription."""

from flask import Blueprint, request, jsonify, current_app
from app.application.use_cases.speech_to_text import execute, STTInput

bp = Blueprint("stt", __name__)

@bp.post("/stt")
def stt_route():
    c = current_app.container
    try:
        if "audio" not in request.files:
            return jsonify({"ok": False, "error": "no_audio"}), 400
        if not c.stt:
            return jsonify({"ok": False, "error": "missing_OPENAI_API_KEY"}), 500
        f = request.files["audio"]
        out = execute(c.stt, STTInput(filename=f.filename, stream=f.stream, mimetype=f.mimetype))
        return jsonify(out)
    except Exception as e:
        return jsonify({"ok": False, "error": f"stt_exception: {e}"}), 500
