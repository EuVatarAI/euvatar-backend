"""OpenAI speech-to-text adapter."""

import requests
from app.core.settings import Settings
from app.domain.ports import ISTTClient

class OpenAIWhisperClient(ISTTClient):
    def __init__(self, settings: Settings):
        self._s = settings
        if not self._s.openai_api_key:
            raise RuntimeError("missing_OPENAI_API_KEY")

    def transcribe(self, filename: str, stream, mimetype: str) -> str:
        data = {"model":"whisper-1","response_format":"json","temperature":"0"}
        files = {"file": (filename or "audio.webm", stream, mimetype or "audio/webm")}
        r = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {self._s.openai_api_key}"},
            data=data, files=files, timeout=120
        )
        r.raise_for_status()
        return (r.json() or {}).get("text", "").strip()
