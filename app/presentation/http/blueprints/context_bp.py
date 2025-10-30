from flask import Blueprint, request, jsonify, current_app
from app.application.use_cases.resolve_context import execute as resolve_uc, ResolveInput

bp = Blueprint("context", __name__)

@bp.post("/context/resolve")
def context_resolve():
    c = current_app.container
    try:
        j = request.get_json(force=True) or {}
        avatar_id = (j.get("avatar_id") or "").strip()
        text = (j.get("text") or "").strip()
        if not avatar_id or not text:
            return jsonify({"ok": False, "error":"missing_params"}), 400
        out = resolve_uc(c.settings, c.ctx_repo, ResolveInput(avatar_identifier=avatar_id, text=text))
        return jsonify(out)
    except Exception as e:
        return jsonify({"ok": False, "error": f"resolve_exception: {e}"}), 500
