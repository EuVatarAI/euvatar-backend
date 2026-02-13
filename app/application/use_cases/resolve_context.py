"""Use-case for matching context triggers and returning media."""

from dataclasses import dataclass
import time
from app.domain.ports import IContextRepository
from app.application.services.context_resolver import fast_match_context, resolve_with_gpt, resolve_media_for_match
from app.core.settings import Settings


@dataclass
class ResolveInput:
    avatar_identifier: str
    text: str
    client_id: str | None = None

def execute(settings: Settings, repo: IContextRepository, args: ResolveInput) -> dict:
    t0 = time.time()
    step_t0 = time.time()
    if args.client_id:
        avatar_uuid = repo.resolve_avatar_uuid_for_client(args.avatar_identifier, args.client_id)
    else:
        avatar_uuid = repo.resolve_avatar_uuid(args.avatar_identifier)
    resolve_avatar_ms = int((time.time() - step_t0) * 1000)
    # Diagnostic: confirm cache key stability
    print(f"RAG_ID [{time.strftime('%Y-%m-%dT%H:%M:%S')}]: avatar_identifier={args.avatar_identifier} avatar_uuid={avatar_uuid}", flush=True)
    if not avatar_uuid:
        return {
            "ok": True,
            "match": "none",
            "media": None,
            "method": "none",
            "latency_ms": int((time.time() - t0) * 1000),
            "resolve_avatar_ms": resolve_avatar_ms,
            "list_contexts_ms": 0,
            "fast_match_ms": 0,
        }
    step_t0 = time.time()
    contexts = repo.list_contexts_by_avatar(avatar_uuid)
    list_contexts_ms = int((time.time() - step_t0) * 1000)
    # Limit context list size to reduce GPT latency on large accounts.
    names = [c.name for c in contexts][:25]
    if not names:
        return {
            "ok": True,
            "match": "none",
            "media": None,
            "method": "none",
            "latency_ms": int((time.time() - t0) * 1000),
            "resolve_avatar_ms": resolve_avatar_ms,
            "list_contexts_ms": list_contexts_ms,
            "fast_match_ms": 0,
        }
    step_t0 = time.time()
    fm = fast_match_context(args.text, contexts)
    fast_match_ms = int((time.time() - step_t0) * 1000)
    if fm:
        media = resolve_media_for_match(contexts, fm)
        return {
            "ok": True,
            "match": fm,
            "media": media.__dict__ if media else None,
            "method": "fast",
            "latency_ms": int((time.time() - t0) * 1000),
            "resolve_avatar_ms": resolve_avatar_ms,
            "list_contexts_ms": list_contexts_ms,
            "fast_match_ms": fast_match_ms,
        }
    # Temporariamente desativado: GPT fallback para medir impacto de latency.
    return {
        "ok": True,
        "match": "none",
        "media": None,
        "method": "none",
        "latency_ms": int((time.time() - t0) * 1000),
        "resolve_avatar_ms": resolve_avatar_ms,
        "list_contexts_ms": list_contexts_ms,
        "fast_match_ms": fast_match_ms,
    }
