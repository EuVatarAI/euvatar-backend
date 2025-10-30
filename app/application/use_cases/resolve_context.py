from dataclasses import dataclass
import time
from app.domain.ports import IContextRepository
from app.application.services.context_resolver import fast_match_context, resolve_with_gpt, resolve_media_for_match
from app.core.settings import Settings


@dataclass
class ResolveInput:
    avatar_identifier: str
    text: str

def execute(settings: Settings, repo: IContextRepository, args: ResolveInput) -> dict:
    t0 = time.time()
    avatar_uuid = repo.resolve_avatar_uuid(args.avatar_identifier)
    if not avatar_uuid:
        return {"ok": True, "match": "none", "media": None, "method": "none", "latency_ms": int((time.time()-t0)*1000)}
    contexts = repo.list_contexts_by_avatar(avatar_uuid)
    names = [c.name for c in contexts]
    if not names:
        return {"ok": True, "match": "none", "media": None, "method": "none", "latency_ms": int((time.time()-t0)*1000)}
    fm = fast_match_context(args.text, contexts)
    if fm:
        media = resolve_media_for_match(contexts, fm)
        return {"ok": True, "match": fm, "media": media.__dict__ if media else None, "method": "fast", "latency_ms": int((time.time()-t0)*1000)}
    match = resolve_with_gpt(settings, args.text, names)
    media = resolve_media_for_match(contexts, match) if match != "none" else None
    return {"ok": True, "match": match, "media": media.__dict__ if media else None, "method": "gpt" if match!="none" else "none", "latency_ms": int((time.time()-t0)*1000)}
