"""Backend-only endpoint for editorial image generation with Gemini."""

from __future__ import annotations

import base64
import imghdr
import os
import uuid

from flask import Blueprint, current_app, jsonify, request

from app.application.use_cases.generate_editorial_image import (
    GenerateEditorialImageInput,
    execute as generate_editorial_image_uc,
)

bp = Blueprint("image_gen", __name__)


@bp.post("/image/generate")
def image_generate_route():
    c = current_app.container
    try:
        if not c.image_gen:
            return jsonify({"ok": False, "error": "missing_GEMINI_API_KEY"}), 500

        if "image" not in request.files:
            return jsonify({"ok": False, "error": "missing_image"}), 400

        gender = (request.form.get("gender") or "").strip().lower()
        hair_color = (request.form.get("hair_color") or "").strip().lower()
        if not gender or not hair_color:
            return jsonify({"ok": False, "error": "missing_params"}), 400

        f = request.files["image"]
        max_bytes = c.settings.upload_max_mb * 1024 * 1024
        data = f.stream.read()
        if not data:
            return jsonify({"ok": False, "error": "empty_image"}), 400
        if len(data) > max_bytes:
            return jsonify({"ok": False, "error": "file_too_large"}), 413
        if not imghdr.what(None, data):
            return jsonify({"ok": False, "error": "invalid_image_format"}), 400

        out, status = generate_editorial_image_uc(
            c.image_gen,
            GenerateEditorialImageInput(
                gender=gender,
                hair_color=hair_color,
                reference_image_bytes=data,
                reference_mime_type=(f.mimetype or "image/jpeg"),
            ),
        )
        if status != 200:
            return jsonify(out), status

        out_mime = out.get("mime_type") or "image/png"
        if out_mime == "image/jpeg":
            ext = "jpg"
        elif out_mime == "image/webp":
            ext = "webp"
        else:
            ext = "png"

        filename = f"generated_{uuid.uuid4().hex}.{ext}"
        dest = os.path.join(c.settings.upload_dir, filename)
        gen_bytes = base64.b64decode(out.get("image_base64") or "")
        with open(dest, "wb") as fp:
            fp.write(gen_bytes)

        return jsonify(
            {
                "ok": True,
                "model": out.get("model"),
                "latency_ms": out.get("latency_ms"),
                "mime_type": out_mime,
                "image_url": f"/uploads/{filename}",
                "usage_metadata": out.get("usage_metadata"),
                "prompt_applied": out.get("prompt_applied"),
            }
        ), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": f"image_generate_exception:{exc}"}), 500
