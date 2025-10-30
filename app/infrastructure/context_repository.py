from typing import Optional, List
from app.core.settings import Settings
from app.domain.models import ContextItem
from app.domain.ports import IContextRepository
from app.infrastructure.supabase_rest import get_json

class ContextRepository(IContextRepository):
    def __init__(self, settings: Settings):
        self._s = settings

    def resolve_avatar_uuid(self, avatar_identifier: str) -> Optional[str]:
        import uuid
        if not avatar_identifier: return None
        c = avatar_identifier.strip()
        try:
            _ = uuid.UUID(c); return c
        except Exception:
            rows = get_json(self._s, "avatars", "id,name", {"name": f"eq.{c}"}, limit=1)
            if rows: return rows[0]["id"]
            return None

    def list_contexts_by_avatar(self, avatar_uuid: str) -> List[ContextItem]:
        rows = get_json(self._s, "contexts", "name,media_url,media_type,keywords_text,enabled", {"avatar_id": f"eq.{avatar_uuid}"})
        items: List[ContextItem] = []
        for r in rows:
            if "enabled" in r and r["enabled"] is not None and (not r["enabled"]):
                continue
            items.append(ContextItem(
                name=(r.get("name") or "").strip(),
                media_url=(r.get("media_url") or "").strip(),
                media_type=(r.get("media_type") or "image").strip() or "image",
                keywords_text=(r.get("keywords_text") or "").strip()
            ))
        return [c for c in items if c.name]
