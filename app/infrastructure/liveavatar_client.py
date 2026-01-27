import requests
from typing import Tuple

from app.core.settings import Settings
from app.domain.ports import IHeygenClient


URL_SESSION_TOKEN = "https://api.liveavatar.com/v1/sessions/token"
URL_SESSION_START = "https://api.liveavatar.com/v1/sessions/start"
URL_SESSION_STOP = "https://api.liveavatar.com/v1/sessions/stop"
URL_SESSION_KEEPALIVE = "https://api.liveavatar.com/v1/sessions/keep_alive"


class LiveAvatarClient(IHeygenClient):
    """
    Cliente LiveAvatar (HeyGen LiveAvatar).
    - Cria session token e inicia a sessao (retorna livekit url + token)
    - Keep alive e stop via API
    """

    def __init__(self, settings: Settings):
        self._s = settings

    def create_token(self) -> str:
        raise RuntimeError("liveavatar: create_token não é suportado neste fluxo")

    def new_session(
        self,
        avatar_id: str,
        language: str,
        backstory: str,
        quality: str,
        voice_id: str | None,
        context_id: str | None = None,
        activity_idle_timeout: int = 120
    ) -> Tuple[str, str, str]:
        # LiveAvatar rejects unsupported locales (ex: pt-BR). Fallback to English.
        lang = (language or "").strip()
        if lang.lower().startswith("pt"):
            lang = "pt"

        payload: dict = {
            "mode": "FULL",
            "avatar_id": avatar_id,
            "avatar_persona": {
                "language": lang or "en",
            },
        }

        if voice_id:
            payload["avatar_persona"]["voice_id"] = voice_id
        if context_id:
            payload["avatar_persona"]["context_id"] = context_id
        elif backstory:
            # fallback: tenta usar backstory como prompt quando não há context_id
            payload["avatar_persona"]["prompt"] = backstory

        # LiveAvatar usa session token antes de iniciar
        token_resp = requests.post(
            URL_SESSION_TOKEN,
            headers={
                "X-API-KEY": self._s.liveavatar_api_key,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )

        if not token_resp.ok and backstory and not context_id:
            # Se a API não aceitar prompt, tenta novamente sem ele
            payload["avatar_persona"].pop("prompt", None)
            token_resp = requests.post(
                URL_SESSION_TOKEN,
                headers={
                    "X-API-KEY": self._s.liveavatar_api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30,
            )

        token_resp.raise_for_status()

        token_data = token_resp.json() or {}
        token_payload = token_data.get("data") or token_data
        session_id = token_payload.get("session_id") or token_payload.get("id")
        session_token = (
            token_payload.get("session_token")
            or token_payload.get("sessionToken")
            or token_payload.get("token")
        )

        if not session_token:
            raise RuntimeError(
                "liveavatar: session_token não retornado. payload="
                f"{token_data}"
            )

        start_payload = {}
        if session_id:
            start_payload["session_id"] = session_id

        start_resp = requests.post(
            URL_SESSION_START,
            headers={
                "Authorization": f"Bearer {session_token}",
                "Content-Type": "application/json",
            },
            json=start_payload or None,
            timeout=30,
        )
        if not start_resp.ok:
            raise RuntimeError(
                "liveavatar: start failed "
                f"status={start_resp.status_code} body={start_resp.text[:500]}"
            )
        start_data = start_resp.json() or {}
        print(f"[LIVEAVATAR] start response: {start_data}")
        start_payload = start_data.get("data") or start_data

        livekit_url = (
            start_payload.get("livekit_url")
            or start_payload.get("livekitUrl")
            or start_payload.get("url")
            or start_payload.get("room_url")
        )
        access_token = (
            start_payload.get("livekit_client_token")
            or start_payload.get("access_token")
            or start_payload.get("token")
            or start_payload.get("livekit_token")
        )

        if not session_id:
            session_id = start_payload.get("session_id") or start_payload.get("id")

        if not session_id or not livekit_url or not access_token:
            raise RuntimeError("liveavatar: resposta inválida ao iniciar sessão")

        return session_id, livekit_url, access_token

    def start_session(self, session_id: str) -> None:
        # Sessao ja iniciada no fluxo do LiveAvatar
        return None

    def task_chat(self, session_id: str, text: str) -> dict:
        raise RuntimeError("liveavatar: task_chat não suportado via API")

    def interrupt(self, session_id: str) -> None:
        # LiveAvatar usa stop para encerrar a sessao
        requests.post(
            URL_SESSION_STOP,
            headers={"Content-Type": "application/json"},
            json={"session_id": session_id},
            timeout=20,
        ).raise_for_status()

    def keep_alive(self, session_id: str, activity_idle_timeout: int | None = None):
        payload = {"session_id": session_id}
        if activity_idle_timeout:
            payload["activity_idle_timeout"] = int(activity_idle_timeout)
        return requests.post(
            URL_SESSION_KEEPALIVE,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=20,
        )
