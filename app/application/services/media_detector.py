import re
from typing import Optional
from ...domain.models import MediaMatch

MEDIA_TRIGGERS = [
    {
        "pattern": r"\b(onde fica|localiza(?:ç|c)ão|mapa|endereço|como chego)\b",
        "type": "image",
        "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/7/79/Barcelona_City_Center_Map.svg/1280px-Barcelona_City_Center_Map.svg.png",
        "caption": "Mapa – Centro de Barcelona",
    },
    {
        "pattern": r"\b(video|vídeo|tour|passeio)\b",
        "type": "video",
        "url": "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4",
        "caption": "Vídeo demonstrativo",
    },
]

def detect_from_text(text: str) -> Optional[MediaMatch]:
    txt = (text or "").lower()
    for rule in MEDIA_TRIGGERS:
        if re.search(rule["pattern"], txt):
            return MediaMatch(type=rule["type"], url=rule["url"], caption=rule.get("caption"))
    return None
