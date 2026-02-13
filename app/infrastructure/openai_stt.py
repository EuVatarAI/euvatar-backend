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
        files = {"file": (filename or "audio.webm", stream, mimetype or "audio/webm")}
        models = self._s.stt_models or ["gpt-4o-mini-transcribe", "whisper-1"]
        last_error = None
        for model in models:
            data = {
                "model": model,
                "response_format": "text",
                "temperature": "0",
                "language": "pt",
            }
            try:
                r = requests.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self._s.openai_api_key}"},
                    data=data,
                    files=files,
                    timeout=30,
                )
                r.raise_for_status()
                return (r.text or "").strip()
            except Exception as exc:
                last_error = exc
                # rewind stream before trying next model
                try:
                    stream.seek(0)
                except Exception:
                    pass
                continue
        raise last_error if last_error else RuntimeError("stt_transcription_failed")
