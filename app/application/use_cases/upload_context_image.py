"""Use-case for uploading context images and metadata."""

from dataclasses import dataclass
from datetime import datetime, timezone
from app.core.settings import Settings
from app.domain.ports import IStorage, IContextRepository
from app.infrastructure.supabase_rest import get_json, patch_json, insert_json



@dataclass
class UploadInput:
    avatar_identifier: str
    context_name: str
    keywords: str
    media_type: str  # image|video
    filename: str
    content_type: str
    data: bytes

def execute(settings: Settings, storage: IStorage, repo: IContextRepository, args: UploadInput) -> dict:
    avatar_uuid = repo.resolve_avatar_uuid(args.avatar_identifier)
    if not avatar_uuid:
        return {"ok": False, "error": "avatar_not_found"}, 404

    media_type = args.media_type if args.media_type in ("image","video") else "image"
    fname = args.filename
    path = f"{avatar_uuid}/training/{fname}"
    storage.upsert(settings.supabase_bucket, path, args.content_type, args.data)

    public_url = storage.public_url(settings.supabase_bucket, path)
    rows = get_json(settings, "contexts", "id", {"avatar_id": f"eq.{avatar_uuid}", "name": f"eq.{args.context_name}"}, limit=1)
    if rows:
        cid = rows[0]["id"]
        url = f"{settings.supabase_url}/rest/v1/contexts?id=eq.{cid}"
        patch_json(settings, url, {
            "media_url": public_url,
            "media_type": media_type,
            "keywords_text": args.keywords,
            "enabled": True,
            "updated_at": datetime.now(timezone.utc).isoformat()
        })
    else:
        insert_json(settings, "contexts", [{
            "avatar_id": avatar_uuid,
            "name": args.context_name,
            "description": "",
            "media_url": public_url,
            "media_type": media_type,
            "keywords_text": args.keywords,
            "placement": "bottom_right",
            "size": "medium",
            "enabled": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        }])
    return {"ok": True, "contexto": args.context_name, "url_imagem": public_url, "avatar_id": avatar_uuid}, 200
