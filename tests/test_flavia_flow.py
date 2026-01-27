import os
import unittest
from unittest.mock import patch

from app.presentation.http.server import create_app


class FlaviaFlowTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("HEYGEN_API_KEY", "env-key")
        os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
        os.environ.setdefault("SUPABASE_SERVICE_ROLE", "service-role")
        os.environ.setdefault("APP_API_TOKEN", "test-token")
        os.environ.setdefault("CORS_ORIGINS", "http://localhost:8080")
        os.environ.setdefault("APP_DEBUG", "false")
        self.app = create_app()
        self.client = self.app.test_client()

    def _auth_headers(self):
        return {"Authorization": "Bearer test-token"}

    @patch("app.presentation.http.blueprints.session_bp._load_training_cache", return_value=([], [], ""))
    @patch("app.presentation.http.blueprints.session_bp._log_avatar_session_start")
    @patch("app.presentation.http.blueprints.session_bp._resolve_avatar_external_id", side_effect=lambda s, a: a)
    @patch("app.presentation.http.blueprints.session_bp._resolve_avatar_api_key", return_value="user-key")
    @patch("app.presentation.http.blueprints.session_bp._heygen_client_for_key")
    def test_new_uses_avatar_api_key(
        self,
        heygen_for_key,
        resolve_key,
        resolve_external,
        log_start,
        load_cache,
    ):
        class DummyHeygen:
            def __init__(self, api_key):
                self.api_key = api_key

            def new_session(self, avatar_id, language, backstory, quality, voice_id, activity_idle_timeout=120):
                return ("sid-1", "https://livekit.test", "token-1")

            def start_session(self, session_id):
                return None

        calls = []

        def _factory(settings, api_key):
            calls.append(api_key)
            return DummyHeygen(api_key)

        heygen_for_key.side_effect = _factory

        resp = self.client.get("/new?avatar_id=avatar-123&client_id=test", headers=self._auth_headers())
        data = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["session_id"], "sid-1")
        self.assertEqual(calls, ["user-key"])

    @patch("app.infrastructure.context_repository.ContextRepository.resolve_avatar_uuid", return_value=None)
    @patch("app.presentation.http.blueprints.session_bp._load_training_cache", return_value=([], [], ""))
    @patch("app.presentation.http.blueprints.session_bp._log_avatar_session_start")
    @patch("app.presentation.http.blueprints.session_bp._resolve_avatar_external_id", side_effect=lambda s, a: a)
    @patch("app.presentation.http.blueprints.session_bp._resolve_avatar_api_key", return_value="user-key")
    @patch("app.presentation.http.blueprints.session_bp._heygen_client_for_key")
    def test_say_uses_session_api_key(
        self,
        heygen_for_key,
        resolve_key,
        resolve_external,
        log_start,
        load_cache,
        resolve_avatar_uuid,
    ):
        class DummyHeygen:
            def __init__(self, api_key):
                self.api_key = api_key

            def new_session(self, avatar_id, language, backstory, quality, voice_id, activity_idle_timeout=120):
                return ("sid-2", "https://livekit.test", "token-2")

            def start_session(self, session_id):
                return None

            def task_chat(self, session_id, text):
                return {"data": {"duration_ms": 12, "task_id": "task-1"}}

        calls = []

        def _factory(settings, api_key):
            calls.append(api_key)
            return DummyHeygen(api_key)

        heygen_for_key.side_effect = _factory

        resp = self.client.get("/new?avatar_id=avatar-456&client_id=test", headers=self._auth_headers())
        data = resp.get_json()
        self.assertTrue(data["ok"])

        say_resp = self.client.post(
            "/say",
            headers=self._auth_headers(),
            json={
                "session_id": data["session_id"],
                "text": "oi",
                "avatar_id": "avatar-456",
                "client_id": "test",
            },
        )
        say_data = say_resp.get_json()

        self.assertEqual(say_resp.status_code, 200)
        self.assertTrue(say_data["ok"])
        self.assertEqual(say_data["task_id"], "task-1")
        self.assertEqual(calls, ["user-key", "user-key"])


if __name__ == "__main__":
    unittest.main()
