"""HTTP client for HeyGen REST endpoints."""

# app/infrastructure/heygen_client.py
from __future__ import annotations
import requests
from app.infrastructure.utils import headers_json
from app.core.settings import Settings
from app.domain.ports import IHeygenClient

URL_NEW        = "https://api.heygen.com/v1/streaming.new"
URL_START      = "https://api.heygen.com/v1/streaming.start"
URL_TASK       = "https://api.heygen.com/v1/streaming.task"
URL_INTERRUPT  = "https://api.heygen.com/v1/streaming.interrupt"
URL_TOKEN      = "https://api.heygen.com/v1/streaming.create_token"
URL_KEEPALIVE  = "https://api.heygen.com/v1/streaming.keep_alive"

class HeygenClient(IHeygenClient):
    def __init__(self, settings: Settings):
        self._s = settings

    def create_token(self) -> str:
        r = requests.post(URL_TOKEN, headers={"X-Api-Key": self._s.heygen_api_key}, json={}, timeout=30)
        r.raise_for_status()
        data = r.json().get("data", {})
        token = data.get("token")
        if not token:
            raise RuntimeError("no_token")
        return token

    def new_session(
        self,
        avatar_id: str,
        language: str,
        backstory: str,
        quality: str,
        voice_id: str | None,
        context_id: str | None = None,
        activity_idle_timeout: int = 120,
    ):
        body = {
            "version": "v2",
            "avatar_id": avatar_id,
            "language": language,
            "backstory": backstory,
            # OBS: disable_idle_timeout é obsoleto segundo o suporte.
            # Use activity_idle_timeout (30..3600s)
            "activity_idle_timeout": int(max(30, min(activity_idle_timeout, 3600))),
            "quality": quality
        }
        if voice_id:
            body["voice"] = {"voice_id": voice_id}
        r = requests.post(URL_NEW, json=body, headers=headers_json(self._s.heygen_api_key), timeout=60)
        r.raise_for_status()
        data = r.json().get("data", {})
        return data.get("session_id"), data.get("url"), data.get("access_token")

    def start_session(self, session_id: str) -> None:
        r = requests.post(URL_START, json={"session_id": session_id},
                          headers=headers_json(self._s.heygen_api_key), timeout=60)
        r.raise_for_status()

    def task_chat(self, session_id: str, text: str) -> dict:
        r = requests.post(
            URL_TASK,
            json={"session_id": session_id, "task_type": "chat", "task_mode": "sync", "text": text},
            headers=headers_json(self._s.heygen_api_key),
            timeout=90
        )
        r.raise_for_status()
        return r.json()

    def interrupt(self, session_id: str) -> None:
        r = requests.post(URL_INTERRUPT, json={"session_id": session_id},
                          headers=headers_json(self._s.heygen_api_key), timeout=30)
        r.raise_for_status()

    # NOVO: keep-alive real no provedor
    def keep_alive(self, session_id: str, activity_idle_timeout: int | None = None) -> requests.Response:
        payload = {"session_id": session_id}
        # algumas versões aceitam prolongar o idle timeout dinamicamente
        if activity_idle_timeout:
            payload["activity_idle_timeout"] = int(max(30, min(activity_idle_timeout, 3600)))
        r = requests.post(URL_KEEPALIVE, json=payload, headers=headers_json(self._s.heygen_api_key), timeout=20)
        return r

# util local
class _U: 
    pass
