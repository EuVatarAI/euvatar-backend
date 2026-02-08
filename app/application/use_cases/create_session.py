"""Use-case to create streaming sessions with configured providers."""

# app/application/use_cases/create_session.py
from dataclasses import dataclass
from typing import Optional
from app.domain.models import LiveSession, BudgetLedger
from app.domain.ports import IHeygenClient
from app.application.services.session_budget import debit_session_and_track


# ==========================================================
# BACKSTORY / PERSONA
# ==========================================================
def build_backstory(persona: str, language: str, custom: Optional[str]) -> str:
    if custom:
        return custom

    persona = (persona or "default").lower()
    lang = (language or "pt-BR").lower()

    if persona == "barca":
        if lang.startswith("pt"):
            return (
                "Você é um jogador fictício do FC Barcelona. Tom: humilde, motivado e respeitoso. "
                "Fale sobre o clube, estilo de jogo, treinos e história. Evite dados confidenciais. "
                "Responda em até 3 frases em pt-BR."
            )
        return (
            "You are a fictional FC Barcelona player. Humble tone. "
            "Talk about the club, style, training and history. "
            "Avoid confidential info. Up to 3 sentences."
        )

    if lang.startswith("pt"):
        return "Você é a Assistente Euvatar: educada, direta e prática. Responda em até 2-3 frases."

    return "You are a pragmatic assistant. Be concise (2-3 sentences), clear and helpful."


def system_prompt(backstory: str, language: str, training: str = "") -> str:
    extra = f" Treinamento: {training}" if training else ""
    return (
        f"SISTEMA: Personagem -> {backstory}{extra} "
        f"Regras: responda no idioma da sessão ({language}); "
        f"no máximo 3 frases; seja claro e objetivo."
    )


# ==========================================================
# INPUT / OUTPUT
# ==========================================================
@dataclass
class CreateSessionInput:
    persona: str = "default"
    language: str = "pt-BR"
    quality: str = "low"
    backstory_param: Optional[str] = None
    voice_id: Optional[str] = None
    context_id: Optional[str] = None
    minutes: float = 2.5
    avatar_id: str = ""

    # fallback de recriação (quando sessão cai)
    resume_session_id: Optional[str] = None

    # idle timeout recomendado pela HeyGen (30..3600s)
    activity_idle_timeout: int = 120


@dataclass
class CreateSessionOutput:
    ok: bool
    session: Optional[LiveSession]
    error: Optional[str] = None


# ==========================================================
# USE CASE
# ==========================================================
def execute(
    heygen: IHeygenClient,
    ledger: BudgetLedger,
    args: CreateSessionInput
) -> CreateSessionOutput:
    """
    Use case responsável APENAS por:
    - Montar backstory
    - Criar sessão via IHeygenClient
    - Iniciar sessão
    - Criar LiveSession de domínio
    - Debitar orçamento

    NÃO conhece SDK, LiveKit, endpoints ou tokens.
    """
    try:
        backstory = build_backstory(
            args.persona,
            args.language,
            (args.backstory_param or "").strip() or None
        )

        minutes = max(0.5, float(args.minutes or 2.5))

        # Criação da sessão (delegado 100% ao client)
        session_id, livekit_url, access_token = heygen.new_session(
            avatar_id=args.avatar_id,
            language=args.language,
            backstory=backstory,
            quality=args.quality,
            voice_id=args.voice_id,
            context_id=args.context_id,
            activity_idle_timeout=int(args.activity_idle_timeout),
        )

        # Obrigatório segundo a HeyGen
        heygen.start_session(session_id)

        session = LiveSession(
            session_id=session_id,
            url=livekit_url,
            token=access_token,
            language=args.language,
            backstory=backstory,
            quality=args.quality,
        )

        # Controle de orçamento (regra de negócio)
        debit_session_and_track(ledger, session, minutes=minutes)

        return CreateSessionOutput(ok=True, session=session)

    except Exception as e:
        return CreateSessionOutput(
            ok=False,
            session=None,
            error=str(e),
        )
