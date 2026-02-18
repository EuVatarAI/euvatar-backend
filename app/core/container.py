"""Dependency container wiring repositories and service clients."""

from dataclasses import dataclass, field
from app.core.settings import Settings
from app.domain.models import LiveSession, BudgetLedger
from app.infrastructure.heygen_client import HeygenClient
from app.infrastructure.openai_stt import OpenAIWhisperClient
from app.infrastructure.supabase_storage import SupabaseStorage
from app.infrastructure.context_repository import ContextRepository
from app.infrastructure.heygen_livekit_client import HeygenLivekitClient
from app.infrastructure.liveavatar_client import LiveAvatarClient
from app.infrastructure.gemini_image_client import GeminiImageClient

@dataclass
class Container:
    settings: Settings = field(default_factory=Settings.load)
    session: LiveSession = field(default_factory=LiveSession)
    budget: BudgetLedger = field(default_factory=BudgetLedger)

    # suporte multi-cliente básico (isolamento simples por client_id)
    sessions: dict[str, LiveSession] = field(default_factory=dict)
    budgets: dict[str, BudgetLedger] = field(default_factory=dict)

    heygen: HeygenClient = None
    stt: OpenAIWhisperClient | None = None
    image_gen: GeminiImageClient | None = None
    storage: SupabaseStorage = None
    ctx_repo: ContextRepository = None

    def __post_init__(self):
        self.heygen = HeygenClient(self.settings)
        
        # stt é opcional; só cria quando chave existir
        if self.settings.openai_api_key:
            self.stt = OpenAIWhisperClient(self.settings)
        # image generation is optional; only when Gemini key exists
        if self.settings.gemini_api_key:
            self.image_gen = GeminiImageClient(self.settings)
        self.storage = SupabaseStorage(self.settings)
        self.ctx_repo = ContextRepository(self.settings)

        if self.settings.avatar_provider == "liveavatar":
            self.heygen = LiveAvatarClient(self.settings)
        elif self.settings.use_livekit:
            self.heygen = HeygenLivekitClient(self.settings)
        else:
            self.heygen = HeygenClient(self.settings)

      

    def get_session(self, client_id: str) -> LiveSession:
        if client_id not in self.sessions:
            self.sessions[client_id] = LiveSession()
        return self.sessions[client_id]

    def get_budget(self, client_id: str) -> BudgetLedger:
        if client_id not in self.budgets:
            self.budgets[client_id] = BudgetLedger()
        return self.budgets[client_id]
