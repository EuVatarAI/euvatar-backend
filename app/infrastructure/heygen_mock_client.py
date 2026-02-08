"""Mock client for HeyGen streaming calls."""

from app.domain.ports import IHeygenClient

class HeygenMockClient(IHeygenClient):
    def __init__(self, settings=None):
        self.settings = settings

    def create_token(self) -> str:
        return "mock-livekit-token"

    def new_session(
        self,
        avatar_id: str,
        language: str,
        backstory: str,
        quality: str,
        voice_id=None,
        context_id: str | None = None,
        activity_idle_timeout: int = 120
    ):
        return (
            "mock-session-123",
            "wss://mock.livekit.local",
            "mock-livekit-token"
        )

    def start_session(self, session_id: str) -> None:
        return None

    def task_chat(self, session_id: str, text: str) -> dict:
        return {
            "ok": True,
            "data": {
                "text": f"[MOCK AVATAR]: {text}"
            }
        }

    def interrupt(self, session_id: str) -> None:
        return None

    def keep_alive(self, session_id: str, activity_idle_timeout=None):
        return {"ok": True}
