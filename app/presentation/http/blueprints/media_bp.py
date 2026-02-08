"""Media upload and retrieval endpoints."""

import os, uuid, re
from flask import Blueprint, request, jsonify, current_app, send_from_directory
from app.shared.text_utils import tokenize_filename_terms, safe_filename
from app.application.use_cases.upload_context_image import (
    execute as upload_uc,
    UploadInput,
)
bp = Blueprint("media", __name__)

# ------- mini-RAG local em memória -------
DOC_INDEX: dict[str, list[dict]] = {}

@bp.post("/upload")
def upload():
    c = current_app.container
    max_bytes = c.settings.upload_max_mb * 1024 * 1024
    if request.method == "POST" and request.files:
        files = request.files.getlist("file")
        added = []
        for f in files:
            if f.content_length and f.content_length > max_bytes:
                return jsonify({"ok": False, "error": "file_too_large"}), 413
            fname = f.filename
            dest = os.path.join(c.settings.upload_dir, f"{uuid.uuid4().hex}_{fname}")
            f.save(dest)
            url = f"/uploads/{os.path.basename(dest)}"
            for t in tokenize_filename_terms(fname):
                DOC_INDEX.setdefault(t, []).append({"name": fname, "url": url})
            added.append({"name": fname, "url": url})
        return jsonify({"ok": True, "added": added, "index_terms": list(DOC_INDEX.keys())})
    return jsonify({"ok": False, "error": "no files"}), 400

@bp.get("/search")
def search():
    q = (request.args.get("q") or "").strip().lower()
    if not q: return jsonify({"ok": True, "results": []})
    terms = re.findall(r"[a-zA-Z0-9À-ú]+", q)
    hits = []
    for t in terms: hits.extend(DOC_INDEX.get(t, []))
    seen, out = set(), []
    for h in hits:
        k = h["url"]
        if k in seen: continue
        out.append(h); seen.add(k)
    return jsonify({"ok": True, "results": out})

@bp.get("/uploads/<path:fname>")
def serve_upload(fname):
    c = current_app.container
    return send_from_directory(c.settings.upload_dir, fname)

@bp.post("/upload/context-image")
def upload_context_image():
    c = current_app.container
    try:
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "no_file"}), 400
        max_bytes = c.settings.upload_max_mb * 1024 * 1024

        avatar_in = (request.form.get("avatar_id") or "").strip()
        contexto   = (request.form.get("contexto") or "").strip()
        keywords   = (request.form.get("keywords") or "").strip()
        media_type = (request.form.get("media_type") or "image").strip().lower()
        if media_type not in ("image", "video"): media_type = "image"
        if not avatar_in or not contexto:
            return jsonify({"ok": False, "error": "missing_params"}), 400

        f = request.files["file"]
        fname = safe_filename(f.filename or "media.bin")
        data = f.stream.read()
        if len(data) > max_bytes:
            return jsonify({"ok": False, "error": "file_too_large"}), 413

        out, status = upload_uc(
            c.settings, c.storage, c.ctx_repo,
            UploadInput(
                avatar_identifier=avatar_in,
                context_name=contexto,
                keywords=keywords,
                media_type=media_type,
                filename=fname,
                content_type=(f.mimetype or "application/octet-stream"),
                data=data
            )
        )
        return jsonify(out), status
    except Exception as e:
        return jsonify({"ok": False, "error": f"upload_exception:{e}"}), 500
