"""Repository for context triggers and training documents."""

from typing import Optional, List, Dict, Tuple
import time
from app.core.settings import Settings
from app.domain.models import ContextItem, TrainingDoc
from app.domain.ports import IContextRepository
from app.infrastructure.supabase_rest import get_json, insert_json

class ContextRepository(IContextRepository):
    def __init__(self, settings: Settings):
        self._s = settings
        # Simple in-memory TTL caches to reduce RAG latency.
        self._avatar_cache: Dict[str, Tuple[float, Optional[str]]] = {}
        self._contexts_cache: Dict[str, Tuple[float, List[ContextItem]]] = {}
        self._client_owner_cache: Dict[str, Tuple[float, Optional[str]]] = {}
        self._avatar_owner_cache: Dict[str, Tuple[float, Optional[str]]] = {}
        self._avatar_client_cache: Dict[str, Tuple[float, Optional[str]]] = {}
        self._cache_ttl_seconds = 600

    def _cache_get(self, cache: Dict, key: str):
        item = cache.get(key)
        if not item:
            return None
        ts, value = item
        if (time.time() - ts) > self._cache_ttl_seconds:
            cache.pop(key, None)
            return None
        return value

    def _cache_set(self, cache: Dict, key: str, value):
        cache[key] = (time.time(), value)

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
        cached = self._cache_get(self._avatar_cache, c)
        if cached is not None:
            return cached
        try:
            _ = uuid.UUID(c)
            self._cache_set(self._avatar_cache, c, c)
            return c
        except Exception:
            rows = get_json(self._s, "avatars", "id,name", {"name": f"eq.{c}"}, limit=1)
            if rows:
                resolved = rows[0]["id"]
                self._cache_set(self._avatar_cache, c, resolved)
                return resolved
            # fallback: gera UUID determinístico a partir do nome e garante a linha em avatars
            gen = str(uuid.uuid5(uuid.NAMESPACE_DNS, c.lower()))
            if self._ensure_avatar_exists(gen, c):
                self._cache_set(self._avatar_cache, c, gen)
                return gen
            return None

    def resolve_avatar_uuid_for_client(self, avatar_identifier: str, client_id: str) -> Optional[str]:
        """Resolve avatar only when it belongs to the provided client_id."""
        cache_key = f"{avatar_identifier}:{client_id}"
        cached = self._cache_get(self._avatar_client_cache, cache_key)
        if cached is not None:
            return cached

        avatar_uuid = self.resolve_avatar_uuid(avatar_identifier)
        if not avatar_uuid or not client_id:
            return None

        # Map client_id -> owner user_id
        owner_user_id = self._cache_get(self._client_owner_cache, client_id)
        if owner_user_id is None:
            rows = get_json(
                self._s,
                "admin_clients",
                "user_id",
                {"id": f"eq.{client_id}"},
                limit=1,
            )
            if not rows:
                return None
            owner_user_id = (rows[0].get("user_id") or "").strip()
            self._cache_set(self._client_owner_cache, client_id, owner_user_id)
        if not owner_user_id:
            return None

        # Ensure avatar belongs to that user
        owner_key = f"{avatar_uuid}:{owner_user_id}"
        owner_cached = self._cache_get(self._avatar_owner_cache, owner_key)
        if owner_cached is None:
            avatar_rows = get_json(
                self._s,
                "avatars",
                "id",
                {"id": f"eq.{avatar_uuid}", "user_id": f"eq.{owner_user_id}"},
                limit=1,
            )
            owner_cached = "ok" if avatar_rows else ""
            self._cache_set(self._avatar_owner_cache, owner_key, owner_cached)
        if not owner_cached:
            self._cache_set(self._avatar_client_cache, cache_key, None)
            return None
        self._cache_set(self._avatar_client_cache, cache_key, avatar_uuid)
        return avatar_uuid

    def list_contexts_by_avatar(self, avatar_uuid: str) -> List[ContextItem]:
        cached = self._cache_get(self._contexts_cache, avatar_uuid)
        if cached is not None:
            return cached
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
        filtered = [c for c in items if c.name]
        self._cache_set(self._contexts_cache, avatar_uuid, filtered)
        return filtered

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
