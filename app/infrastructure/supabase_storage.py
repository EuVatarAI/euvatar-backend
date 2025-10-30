import requests
from ..core.settings import Settings
from ..domain.ports import IStorage

class SupabaseStorage(IStorage):
    def __init__(self, settings: Settings):
        self._s = settings

    def upsert(self, bucket: str, path: str, content_type: str, data: bytes) -> None:
        up_url = f"{self._s.supabase_url}/storage/v1/object/{bucket}/{path}"
        r = requests.post(up_url, headers={
            "Authorization": f"Bearer {self._s.supabase_service_role}",
            "apikey": self._s.supabase_service_role,
            "x-upsert": "true",
            "Content-Type": content_type or "application/octet-stream"
        }, data=data, timeout=120)
        if not r.ok:
            hint = r.text[:300]
            if r.status_code == 403:
                hint += " | DICA: 403 em Storage geralmente é RLS/policy ou uso de ANON KEY. No servidor, use SUPABASE_SERVICE_ROLE."
            raise RuntimeError(f"storage_{r.status_code}: {hint}")

    def public_url(self, bucket: str, path: str) -> str:
        return f"{self._s.supabase_url}/storage/v1/object/public/{bucket}/{path}"
