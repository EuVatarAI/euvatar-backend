from dataclasses import dataclass
from datetime import datetime, timezone
from app.core.settings import Settings
from app.domain.ports import IStorage, IContextRepository
from app.infrastructure.supabase_rest import insert_json
from app.shared.text_utils import safe_filename


@dataclass
class UploadTrainingDocInput:
    avatar_identifier: str
    filename: str
    content_type: str
    data: bytes
    title: str | None = None


def execute(settings: Settings, storage: IStorage, repo: IContextRepository, args: UploadTrainingDocInput) -> tuple[dict, int]:
    avatar_uuid = repo.resolve_avatar_uuid(args.avatar_identifier)
    if not avatar_uuid:
        return {"ok": False, "error": "avatar_not_found"}, 404

    fname = safe_filename(args.filename or "document.bin")
    path = f"{avatar_uuid}/training-docs/{fname}"

    storage.upsert(settings.supabase_bucket, path, args.content_type, args.data)
    public_url = storage.public_url(settings.supabase_bucket, path)

    created_at = datetime.now(timezone.utc).isoformat()
    url_cols = ["document_url", "url", "file_url", "path"]
    name_cols = ["document_name", "name", "title", "document", "filename"]
    last_err = None
    for ucol in url_cols:
        for ncol in name_cols:
            for include_created in (True, False):
                row = {"avatar_id": avatar_uuid, ucol: public_url, ncol: (args.title or fname)}
                if include_created:
                    row["created_at"] = created_at
                try:
                    insert_json(settings, "training_docs", [row])
                    return {
                        "ok": True,
                        "avatar_id": avatar_uuid,
                        "document_url": public_url,
                        "document_name": row[ncol],
                        "used_cols": {"url": ucol, "name": ncol, "created_at": include_created},
                    }, 200
                except Exception as e:
                    last_err = str(e)
                    continue

    return {"ok": False, "error": "insert_failed", "details": last_err}, 500
