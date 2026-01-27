import base64
import os
import unittest

import requests


def _b64(val: str) -> str:
    return base64.b64encode(val.encode("utf-8")).decode("ascii")


@unittest.skipUnless(os.getenv("RUN_REAL_TESTS") == "1", "Set RUN_REAL_TESTS=1 to run integration tests")
class FlaviaFlowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        self.supabase_service_role = os.getenv("SUPABASE_SERVICE_ROLE", "")
        self.backend_url = os.getenv("BACKEND_URL", "http://localhost:5001").rstrip("/")
        self.api_token = os.getenv("APP_API_TOKEN", "")
        self.avatar_id = os.getenv("TEST_SUPABASE_AVATAR_ID", "")
        self.heygen_api_key = os.getenv("TEST_HEYGEN_API_KEY", "")
        self.heygen_external_id = os.getenv("TEST_HEYGEN_AVATAR_EXTERNAL_ID", "")
        self.account_id = os.getenv("TEST_HEYGEN_ACCOUNT_ID", "test-account")

        missing = [
            name for name, value in [
                ("SUPABASE_URL", self.supabase_url),
                ("SUPABASE_SERVICE_ROLE", self.supabase_service_role),
                ("BACKEND_URL", self.backend_url),
                ("APP_API_TOKEN", self.api_token),
                ("TEST_SUPABASE_AVATAR_ID", self.avatar_id),
                ("TEST_HEYGEN_API_KEY", self.heygen_api_key),
                ("TEST_HEYGEN_AVATAR_EXTERNAL_ID", self.heygen_external_id),
            ] if not value
        ]
        if missing:
            self.skipTest("Missing env vars: " + ", ".join(missing))

    def _supabase_headers(self):
        return {
            "apikey": self.supabase_service_role,
            "Authorization": f"Bearer {self.supabase_service_role}",
            "Content-Type": "application/json",
        }

    def _backend_headers(self):
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    def test_real_flow_uses_avatar_credentials(self):
        payload = {
            "avatar_id": self.avatar_id,
            "account_id": _b64(self.account_id),
            "api_key": _b64(self.heygen_api_key),
            "avatar_external_id": _b64(self.heygen_external_id),
        }
        upsert_url = f"{self.supabase_url}/rest/v1/avatar_credentials?on_conflict=avatar_id"
        headers = self._supabase_headers()
        headers["Prefer"] = "resolution=merge-duplicates"
        resp = requests.post(upsert_url, headers=headers, json=payload, timeout=20)
        if not resp.ok:
            self.fail(f"Supabase upsert failed: {resp.status_code} {resp.text}")

        try:
            new_url = f"{self.backend_url}/new?avatar_id={self.avatar_id}&client_id=integration"
            new_resp = requests.get(new_url, headers=self._backend_headers(), timeout=30)
            data = new_resp.json() if new_resp.text else {}
            self.assertEqual(new_resp.status_code, 200)
            self.assertTrue(data.get("ok"), f"/new failed: {data}")
            session_id = data.get("session_id")
            self.assertTrue(session_id)

            if os.getenv("RUN_REAL_SAY") == "1":
                say_payload = {
                    "session_id": session_id,
                    "text": "teste",
                    "avatar_id": self.avatar_id,
                    "client_id": "integration",
                }
                say_url = f"{self.backend_url}/say"
                say_resp = requests.post(say_url, headers=self._backend_headers(), json=say_payload, timeout=30)
                say_data = say_resp.json() if say_resp.text else {}
                self.assertEqual(say_resp.status_code, 200)
                self.assertTrue(say_data.get("ok"), f"/say failed: {say_data}")
        finally:
            delete_url = f"{self.supabase_url}/rest/v1/avatar_credentials?avatar_id=eq.{self.avatar_id}"
            requests.delete(delete_url, headers=self._supabase_headers(), timeout=20)


if __name__ == "__main__":
    unittest.main()
