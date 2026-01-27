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


@bp.get("/context/list")
def context_list():
    """Lista os contextos (mídias + keywords) de um avatar."""
    c = current_app.container
    try:
        avatar_id = (request.args.get("avatar_id") or "").strip()
        if not avatar_id:
            return jsonify({"ok": False, "error": "missing_avatar_id"}), 400

        avatar_uuid = c.ctx_repo.resolve_avatar_uuid(avatar_id)
        if not avatar_uuid:
            return jsonify({"ok": False, "error": "avatar_not_found"}), 404
        items = c.ctx_repo.list_contexts_by_avatar(avatar_uuid)
        data = [
            {
                "name": it.name,
                "media_url": it.media_url,
                "media_type": it.media_type,
                "keywords": it.keywords_text,
            }
            for it in items
        ]
        return jsonify({"ok": True, "avatar_id": avatar_uuid, "items": data})
    except Exception as e:
        return jsonify({"ok": False, "error": f"list_exception: {e}"}), 500
