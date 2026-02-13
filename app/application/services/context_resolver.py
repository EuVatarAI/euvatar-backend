from typing import List, Optional
import requests
from ...domain.models import ContextItem, MediaMatch
from ...shared.text_utils import normalize
from ...core.settings import Settings

def fast_match_context(user_text: str, contexts: List[ContextItem]) -> Optional[str]:
    text = normalize(user_text)
    if not text: return None
    for c in contexts:
        name = normalize(c.name)
        if name and name in text:
            return c.name
        if name:
            for tok in name.split("_"):
                if tok and tok in text:
                    return c.name
        kws = normalize(c.keywords_text or "")
        if kws:
            parts = [p.strip() for p in re_split(kws)]
            # also split by whitespace to catch phrases like "quando usuario fala sobre chocolate"
            for p in list(parts):
                parts.extend(p.split())
            for k in parts:
                if len(k) < 3:
                    continue
                if k and k in text:
                    return c.name
    return None

def re_split(kws: str) -> list[str]:
    import re
    return [x for x in re.split(r"[;,|]", kws) if x]

def resolve_media_for_match(contexts: List[ContextItem], match: str) -> Optional[MediaMatch]:
    for c in contexts:
        if c.name == match and c.media_url:
            m = (c.media_type or "image").lower()
            if m not in ("image", "video"): m = "image"
            return MediaMatch(type=m, url=c.media_url, caption=c.name)
    return None

def resolve_with_gpt(settings: Settings, user_text: str, context_names: List[str]) -> str:
    if not settings.openai_api_key or not context_names:
        return "none"
    system = ("Você recebe uma fala do usuário e uma lista de contextos. "
              "Se corresponder claramente a um dos contextos, responda APENAS com esse contexto (texto exato). "
              "Caso contrário, responda 'none'. Sem explicações.")
    user = "Fala: {}\nContextos:\n- {}".format(user_text, "\n- ".join(context_names))
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "max_tokens": 24,
        },
        timeout=12
    )
    if not r.ok: return "none"
    try:
        content = r.json()["choices"][0]["message"]["content"].strip()
        return content if content in context_names else "none"
    except Exception:
        return "none"
