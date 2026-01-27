# app/infrastructure/heygen_livekit_client.py

import requests
from typing import Tuple
from app.core.settings import Settings
from app.domain.ports import IHeygenClient
from app.infrastructure.utils import headers_json


# === Endpoints NOVOS (Interactive Avatar + LiveKit) ===
URL_NEW_SESSION   = "https://api.heygen.com/v1/streaming.new"
URL_START_SESSION = "https://api.heygen.com/v1/streaming.start"
URL_TASK          = "https://api.heygen.com/v1/streaming.task"
URL_INTERRUPT     = "https://api.heygen.com/v1/streaming.interrupt"
URL_KEEPALIVE     = "https://api.heygen.com/v1/streaming.keep_alive"
URL_CREATE_TOKEN  = "https://api.heygen.com/v1/streaming.create_token"


class HeygenLivekitClient(IHeygenClient):
    """
    Implementação NOVA usando:
    - Interactive Avatar
    - LiveKit
    - Compatível com a interface IHeygenClient atual
    """

    def __init__(self, settings: Settings):
        self._s = settings

    
    def create_token(self) -> str:
        r = requests.post(
            URL_CREATE_TOKEN,
            headers={"X-Api-Key": self._s.heygen_api_key},
            json={},
            timeout=30
        )
        r.raise_for_status()

        data = r.json().get("data", {})
        token = data.get("token")

        if not token:
            raise RuntimeError("heygen_livekit: token não retornado")

        return token

    # ==========================================================
    # CRIA SESSÃO (Interactive Avatar)
    # ==========================================================
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
        """
        Retorna:
        - session_id
        - livekit_url
        - access_token
        """

        payload = {
            "version": "v2",
            "avatar_id": avatar_id,
            "language": language,
            "quality": quality,
            "backstory": backstory,
            "activity_idle_timeout": int(max(30, min(activity_idle_timeout, 3600))),
        }

        if voice_id:
            payload["voice"] = {"voice_id": voice_id}

        r = requests.post(
            URL_NEW_SESSION,
            json=payload,
            headers=headers_json(self._s.heygen_api_key),
            timeout=60
        )
        r.raise_for_status()

        data = r.json().get("data", {})

        session_id = data.get("session_id")
        livekit_url = data.get("url")
        access_token = data.get("access_token")

        if not session_id or not livekit_url or not access_token:
            raise RuntimeError("heygen_livekit: resposta inválida ao criar sessão")

        return session_id, livekit_url, access_token

    # ==========================================================
    # START SESSION (obrigatório após new_session)
    # ==========================================================
    def start_session(self, session_id: str) -> None:
        r = requests.post(
            URL_START_SESSION,
            json={"session_id": session_id},
            headers=headers_json(self._s.heygen_api_key),
            timeout=30
        )
        r.raise_for_status()

    # ==========================================================
    # CHAT / FALA DO AVATAR
    # ==========================================================
    def task_chat(self, session_id: str, text: str) -> dict:
        r = requests.post(
            URL_TASK,
            json={
                "session_id": session_id,
                "task_type": "chat",
                "task_mode": "sync",
                "text": text
            },
            headers=headers_json(self._s.heygen_api_key),
            timeout=90
        )
        r.raise_for_status()
        return r.json()

    # ==========================================================
    # INTERRUPT (corta fala atual)
    # ==========================================================
    def interrupt(self, session_id: str) -> None:
        r = requests.post(
            URL_INTERRUPT,
            json={"session_id": session_id},
            headers=headers_json(self._s.heygen_api_key),
            timeout=30
        )
        r.raise_for_status()

    # ==========================================================
    # KEEP ALIVE (mantém sessão ativa)
    # ==========================================================
    def keep_alive(
        self,
        session_id: str,
        activity_idle_timeout: int | None = None
    ) -> requests.Response:
        payload = {"session_id": session_id}

        if activity_idle_timeout:
            payload["activity_idle_timeout"] = int(
                max(30, min(activity_idle_timeout, 3600))
            )

        r = requests.post(
            URL_KEEPALIVE,
            json=payload,
            headers=headers_json(self._s.heygen_api_key),
            timeout=20
        )
        return r
