from typing import Optional, List
from app.core.settings import Settings
from app.domain.models import ContextItem, TrainingDoc
from app.domain.ports import IContextRepository
from app.infrastructure.supabase_rest import get_json, insert_json

class ContextRepository(IContextRepository):
    def __init__(self, settings: Settings):
        self._s = settings

    def _ensure_avatar_exists(self, uuid_str: str, name: str) -> bool:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        # tenta inserir com user_id nulo (requer que FK permita NULL)
        payloads = [
            {"id": uuid_str, "name": name, "user_id": None},
            {"id": uuid_str, "name": name, "user_id": None, "created_at": now},
            {"id": uuid_str, "name": name, "user_id": None, "created_at": now, "updated_at": now},
        ]
        for body in payloads:
            try:
                insert_json(self._s, "avatars", [body])
                return True
            except Exception as e:
                msg = str(e).lower()
                if "duplicate key" in msg or "already exists" in msg:
                    return True
                continue
        return False

    def resolve_avatar_uuid(self, avatar_identifier: str) -> Optional[str]:
        import uuid
        if not avatar_identifier: return None
        c = avatar_identifier.strip()
        try:
            _ = uuid.UUID(c); return c
        except Exception:
            rows = get_json(self._s, "avatars", "id,name", {"name": f"eq.{c}"}, limit=1)
            if rows:
                return rows[0]["id"]
            # fallback: gera UUID determinístico a partir do nome e garante a linha em avatars
            gen = str(uuid.uuid5(uuid.NAMESPACE_DNS, c.lower()))
            if self._ensure_avatar_exists(gen, c):
                return gen
            return None

    def list_contexts_by_avatar(self, avatar_uuid: str) -> List[ContextItem]:
        rows = get_json(self._s, "contexts", "name,media_url,media_type,keywords_text,description,enabled", {"avatar_id": f"eq.{avatar_uuid}"})
        items: List[ContextItem] = []
        for r in rows:
            if "enabled" in r and r["enabled"] is not None and (not r["enabled"]):
                continue
            kws = (r.get("keywords_text") or "").strip()
            desc = (r.get("description") or "").strip()
            if desc and desc not in kws:
                kws = f"{kws}; {desc}".strip("; ").strip()
            items.append(ContextItem(
                name=(r.get("name") or "").strip(),
                media_url=(r.get("media_url") or "").strip(),
                media_type=(r.get("media_type") or "image").strip() or "image",
                keywords_text=kws
            ))
        return [c for c in items if c.name]

    def list_training_docs_by_avatar(self, avatar_uuid: str) -> List[TrainingDoc]:
        # select * evita erro quando coluna document_name não existe em alguns ambientes
        rows = get_json(self._s, "training_docs", "*", {"avatar_id": f"eq.{avatar_uuid}"})
        items: List[TrainingDoc] = []
        for r in rows:
            name = (r.get("document_name")
                    or r.get("name")
                    or r.get("title")
                    or r.get("document")
                    or r.get("filename")
                    or "").strip()
            url = (r.get("document_url")
                   or r.get("url")
                   or r.get("file_url")
                   or r.get("path")
                   or "").strip()
            items.append(TrainingDoc(
                id=str(r.get("id") or ""),
                name=name,
                url=url,
                created_at=r.get("created_at")
            ))
        return [d for d in items if d.id and d.url]
