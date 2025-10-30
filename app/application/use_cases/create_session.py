# app/application/use_cases/create_session.py
from dataclasses import dataclass
from typing import Optional
from app.domain.models import LiveSession, BudgetLedger
from app.domain.ports import IHeygenClient
from app.application.services.session_budget import debit_session_and_track

def build_backstory(persona: str, language: str, custom: Optional[str]) -> str:
    if custom: 
        return custom
    persona = (persona or "default").lower()
    lang = (language or "pt-BR").lower()
    if persona == "barca":
        if lang.startswith("pt"):
            return ("Você é um jogador fictício do FC Barcelona. Tom: humilde, motivado e respeitoso. "
                    "Fale sobre o clube, estilo de jogo, treinos e história. Evite dados confidenciais. "
                    "Responda em até 3 frases em pt-BR.")
        return ("You are a fictional FC Barcelona player. Humble tone. Talk about the club, style, training, history. "
                "Avoid confidential info. Up to 3 sentences.")
    if lang.startswith("pt"):
        return ("Você é a Assistente Euvatar: educada, direta, prática. Responda em até 2-3 frases.")
    return ("You are a pragmatic assistant. Be concise (2-3 sentences), clear and helpful.")

def system_prompt(bs: str, lang: str) -> str:
    return (f"SISTEMA: Personagem -> {bs} "
            f"Regras: responda no idioma da sessão ({lang}); no máx. 3 frases; claro e objetivo.")

@dataclass
class CreateSessionInput:
    # criação normal
    persona: str = "default"
    language: str = "pt-BR"
    quality: str = "low"
    backstory_param: Optional[str] = None
    voice_id: Optional[str] = None
    minutes: float = 2.5
    avatar_id: str = ""  # settings.heygen_default_avatar

    # resume: quando a sessão remota caiu/fechou, recriamos rapidamente
    resume_session_id: Optional[str] = None

    # novo (HeyGen): tempo de inatividade antes de encerrar
    activity_idle_timeout: int = 120  # segundos (30..3600)

@dataclass
class CreateSessionOutput:
    ok: bool
    session: Optional[LiveSession]
    error: Optional[str] = None

def execute(heygen: IHeygenClient, ledger: BudgetLedger, args: CreateSessionInput) -> CreateSessionOutput:
    """
    - Se resume_session_id vier preenchido → criamos uma nova sessão mantendo contexto (fallback confiável).
      (SDK HTTP atual não fornece refresh de token/URL da mesma sessão.)
    - Sempre passamos activity_idle_timeout conforme recomendado pelo suporte HeyGen.
    """
    try:
        bs = build_backstory(args.persona, args.language, (args.backstory_param or "").strip() or None)

        # Fallback de "resume": recria a sessão com mesmos parâmetros (rápido e estável)
        _minutes = max(0.5, float(args.minutes or 2.5))

        session_id, livekit_url, token = heygen.new_session(
            avatar_id=args.avatar_id,
            language=args.language,
            backstory=bs,
            quality=args.quality,
            voice_id=args.voice_id,
            activity_idle_timeout=int(args.activity_idle_timeout)
        )
        heygen.start_session(session_id)

        s = LiveSession(
            session_id=session_id,
            url=livekit_url,
            token=token,
            language=args.language,
            backstory=bs,
            quality=args.quality
        )

        # ends_at é calculado na camada HTTP; aqui debitamos orçamento/ledger
        debit_session_and_track(ledger, s, minutes=_minutes)

        return CreateSessionOutput(ok=True, session=s)

    except Exception as e:
        return CreateSessionOutput(ok=False, session=None, error=str(e))
