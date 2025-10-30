import requests
from ..core.settings import Settings

def rest_headers(settings: Settings) -> dict:
    return {
        "apikey": settings.supabase_service_role,
        "Authorization": f"Bearer {settings.supabase_service_role}",
    }

def get_json(settings: Settings, table: str, select: str, params: dict, limit: int | None = None):
    url = f"{settings.supabase_url}/rest/v1/{table}"
    q = {"select": select, **params}
    if limit: q["limit"] = str(limit)
    r = requests.get(url, headers=rest_headers(settings), params=q, timeout=20)
    if not r.ok:
        msg = r.text[:200]
        if r.status_code == 403 and "row-level security" in msg.lower():
            msg += " (RLS: verifique policies ou use service role no backend)"
        raise RuntimeError(f"supabase_{table}_{r.status_code}: {msg}")
    return r.json() or []

def patch_json(settings: Settings, table_url: str, body: dict) -> None:
    r = requests.patch(table_url, headers={**rest_headers(settings), "Content-Type":"application/json"}, json=body, timeout=30)
    if not r.ok:
        msg = r.text[:300]
        if r.status_code == 403: msg += " | DICA: 403 no REST indica RLS; com Service Role isso não deve ocorrer."
        raise RuntimeError(f"update_{r.status_code}: {msg}")

def insert_json(settings: Settings, table: str, rows: list[dict]) -> None:
    url = f"{settings.supabase_url}/rest/v1/{table}"
    r = requests.post(url, headers={**rest_headers(settings), "Content-Type":"application/json", "Prefer":"return=representation"}, json=rows, timeout=30)
    if not r.ok:
        msg = r.text[:300]
        if r.status_code == 403: msg += " | DICA: 403 no REST indica RLS; com Service Role isso não deve ocorrer."
        raise RuntimeError(f"insert_{r.status_code}: {msg}")
