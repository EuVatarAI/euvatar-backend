from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any

@dataclass
class LiveSession:
    session_id: Optional[str] = None
    url: Optional[str] = None
    token: Optional[str] = None
    language: str = "pt-BR"
    backstory: Optional[str] = None
    quality: str = "low"
    ends_at_epoch: Optional[int] = None  # epoch seconds

@dataclass
class BudgetLedger:
    credits_per_session: int = 10
    total_credits_spent: int = 0
    sessions: List[Dict[str, Any]] = field(default_factory=list)

@dataclass
class ContextItem:
    name: str
    media_url: Optional[str]
    media_type: str  # "image"|"video"
    keywords_text: str

@dataclass
class MediaMatch:
    type: str      # "image"|"video"
    url: str
    caption: Optional[str] = None
