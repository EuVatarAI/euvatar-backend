from dataclasses import dataclass, field
from app.core.settings import Settings
from app.domain.models import LiveSession, BudgetLedger
from app.infrastructure.heygen_client import HeygenClient
from app.infrastructure.openai_stt import OpenAIWhisperClient
from app.infrastructure.supabase_storage import SupabaseStorage
from app.infrastructure.context_repository import ContextRepository


@dataclass
class Container:
    settings: Settings = field(default_factory=Settings.load)
    session: LiveSession = field(default_factory=LiveSession)
    budget: BudgetLedger = field(default_factory=BudgetLedger)

    heygen: HeygenClient = None
    stt: OpenAIWhisperClient | None = None
    storage: SupabaseStorage = None
    ctx_repo: ContextRepository = None

    def __post_init__(self):
        self.heygen = HeygenClient(self.settings)
        # stt é opcional; só cria quando chave existir
        if self.settings.openai_api_key:
            self.stt = OpenAIWhisperClient(self.settings)
        self.storage = SupabaseStorage(self.settings)
        self.ctx_repo = ContextRepository(self.settings)
