"""Domain models for sessions, budgets, and usage."""

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
    avatar_id: Optional[str] = None
    api_key: Optional[str] = None
    ends_at_epoch: Optional[int] = None  # epoch seconds
    started_at_epoch: Optional[int] = None  # epoch seconds
    training_contexts: List["ContextItem"] = field(default_factory=list)
    training_docs: List["TrainingDoc"] = field(default_factory=list)
    training_summary: str = ""

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

@dataclass
class TrainingDoc:
    id: str
    name: str
    url: str
    created_at: Optional[datetime] = None
