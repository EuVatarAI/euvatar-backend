import base64, json
from flask import Blueprint, jsonify, current_app
from app.infrastructure.supabase_storage import SupabaseStorage

bp = Blueprint("debug", __name__)

def _jwt_role(token: str):
    try:
        payload = token.split('.')[1] + '=='
        return json.loads(base64.urlsafe_b64decode(payload.encode()).decode()).get('role')
    except Exception:
        return None

@bp.get("/debug/env")
def debug_env():
    c = current_app.container
    tail = (c.settings.supabase_service_role[-10:] if c.settings.supabase_service_role else None)
    return jsonify({
        "app": "server_voice_solid",
        "sb_role": _jwt_role(c.settings.supabase_service_role),
        "bucket": c.settings.supabase_bucket,
        "url": c.settings.supabase_url,
        "key_tail": tail,
    })

@bp.post("/debug/storage-selftest")
def debug_storage_selftest():
    c = current_app.container
    try:
        path = f"debug/ping_from_flask.txt"
        c.storage.upsert(c.settings.supabase_bucket, path, "text/plain", b"hello-from-flask")
        return jsonify({"ok": True, "status": 200, "text": "stored"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
