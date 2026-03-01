"""Authentication helpers and request guards."""

from functools import wraps
from typing import Tuple
import requests
from flask import request, jsonify, current_app, abort, g

def _is_public_path_allowed(path: str) -> bool:
    static_allowed = {
        "/health",
        "/credentials",
        "/uploads/signed-url",
        "/uploads/confirm",
        "/generations",
    }
    if path in static_allowed:
        return True
    if path.startswith("/public/experience/"):
        return True
    if path.startswith("/generations/"):
        return True
    return False

def _extract_token() -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None

def _get_user_from_supabase(token: str) -> dict | None:
    settings = current_app.container.settings
    url = f"{settings.supabase_url}/auth/v1/user"
    headers = {
        "Authorization": f"Bearer {token}",
        "apikey": settings.supabase_service_role,
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    return resp.json()

def _get_client_id_for_user(user_id: str) -> str | None:
    settings = current_app.container.settings
    url = f"{settings.supabase_url}/rest/v1/admin_clients"
    headers = {
        "Authorization": f"Bearer {settings.supabase_service_role}",
        "apikey": settings.supabase_service_role,
    }
    params = {
        "select": "id,user_id",
        "user_id": f"eq.{user_id}",
        "limit": "1",
    }
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    rows = resp.json() or []
    if not rows:
        return None
    return rows[0].get("id")

def _get_client_id_for_avatar(avatar_id: str) -> str | None:
    settings = current_app.container.settings
    headers = {
        "Authorization": f"Bearer {settings.supabase_service_role}",
        "apikey": settings.supabase_service_role,
    }
    # 1) get avatar owner (user_id)
    try:
        avatar_resp = requests.get(
            f"{settings.supabase_url}/rest/v1/avatars",
            headers=headers,
            params={"select": "id,user_id", "id": f"eq.{avatar_id}", "limit": "1"},
            timeout=10,
        )
    except requests.RequestException:
        return None
    if avatar_resp.status_code != 200:
        return None
    avatar_rows = avatar_resp.json() or []
    if not avatar_rows:
        return None
    user_id = avatar_rows[0].get("user_id")
    if not user_id:
        return None
    return _get_client_id_for_user(user_id)

def _authenticate() -> Tuple[str, str]:
    token = _extract_token()
    if not token:
        if _is_public_path_allowed(request.path):
            return "public", "public"
        # Allow public avatar-scoped access for specific endpoints when avatar_id is provided
        public_avatar_id = request.headers.get("X-Public-Avatar-Id", "").strip()
        avatar_public_paths = {
            "/new",
            "/say",
            "/interrupt",
            "/end",
            "/context/resolve",
            "/liveavatar/voices",
        }
        if public_avatar_id:
            client_id = _get_client_id_for_avatar(public_avatar_id)
            if client_id and request.path in avatar_public_paths:
                return "public", client_id
        resp = jsonify({"ok": False, "error": "unauthorized"})
        resp.status_code = 401
        abort(resp)

    user = _get_user_from_supabase(token)
    if not user or not user.get("id"):
        resp = jsonify({"ok": False, "error": "unauthorized"})
        resp.status_code = 401
        abort(resp)

    user_id = user["id"]
    client_id = _get_client_id_for_user(user_id)
    if not client_id:
        resp = jsonify({"ok": False, "error": "missing_client_mapping"})
        resp.status_code = 403
        abort(resp)
    return user_id, client_id

def require_auth():
    user_id, client_id = _authenticate()
    g.user_id = user_id
    g.client_id = client_id

def protected(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        require_auth()
        return fn(*args, **kwargs)
    return wrapper
