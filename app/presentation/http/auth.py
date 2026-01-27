from functools import wraps
from flask import request, jsonify, current_app, abort

def _extract_token() -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    header = request.headers.get("X-Api-Token")
    if header:
        return header.strip()
    return None

def require_auth():
    expected = current_app.container.settings.api_token
    incoming = _extract_token()
    if not incoming or incoming != expected:
        resp = jsonify({"ok": False, "error": "unauthorized"})
        resp.status_code = 401
        abort(resp)

def protected(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        require_auth()
        return fn(*args, **kwargs)
    return wrapper
