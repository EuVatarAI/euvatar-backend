import os
import unittest
from unittest.mock import Mock, patch

from app.presentation.http.server import create_app


class QuizLeadsBlueprintTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("HEYGEN_API_KEY", "env-key")
        os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
        os.environ.setdefault("SUPABASE_SERVICE_ROLE", "service-role")
        os.environ.setdefault("APP_API_TOKEN", "test-token")
        os.environ.setdefault("CORS_ORIGINS", "http://localhost:8080")
        os.environ.setdefault("APP_DEBUG", "false")
        self.app = create_app()
        self.client = self.app.test_client()

    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    def test_public_lead_config_success(self, get_json):
        get_json.side_effect = [
            [
                {
                    "id": "exp-1",
                    "type": "quiz",
                    "status": "published",
                    "config_json": {},
                }
            ],
            [
                {
                    "variable_key": "nome_completo",
                    "label": "Nome",
                    "field_type": "text",
                    "required": True,
                    "sort_order": 0,
                    "options": None,
                }
            ],
        ]

        resp = self.client.get("/public/experience/minha-exp/lead-config")
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["experience_id"], "exp-1")
        self.assertTrue(payload["lead_capture"]["enabled"])
        self.assertEqual(len(payload["lead_capture"]["fields"]), 1)

    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    def test_public_lead_create_rejects_invalid_mode(self, get_json):
        get_json.return_value = [
            {"id": "exp-1", "type": "quiz", "status": "published", "config_json": {}}
        ]

        resp = self.client.post(
            "/public/experience/minha-exp/leads",
            json={"mode_used": "desktop", "data": {"nome": "A"}},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "invalid_mode_used")

    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    def test_public_lead_create_validates_required_fields(self, get_json):
        get_json.side_effect = [
            [
                {
                    "id": "exp-1",
                    "type": "quiz",
                    "status": "published",
                    "config_json": {},
                }
            ],
            [
                {
                    "variable_key": "email",
                    "label": "E-mail",
                    "field_type": "email",
                    "required": True,
                    "sort_order": 0,
                    "options": None,
                }
            ],
        ]

        resp = self.client.post(
            "/public/experience/minha-exp/leads",
            json={"mode_used": "mobile", "data": {"email": ""}},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "missing_required_field:email")

    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    @patch("app.presentation.http.blueprints.quiz_bp.requests.post")
    def test_public_lead_create_success_even_when_lead_insert_fails(
        self, post_req, get_json
    ):
        get_json.side_effect = [
            [
                {
                    "id": "exp-1",
                    "type": "quiz",
                    "status": "published",
                    "config_json": {},
                }
            ],
            [
                {
                    "variable_key": "nome",
                    "label": "Nome",
                    "field_type": "text",
                    "required": False,
                    "sort_order": 0,
                    "options": None,
                }
            ],
        ]

        credential_ok = Mock()
        credential_ok.ok = True
        credential_ok.json.return_value = [{"id": "cred-1"}]

        lead_fail = Mock()
        lead_fail.ok = False
        lead_fail.status_code = 500

        post_req.side_effect = [credential_ok, lead_fail]

        resp = self.client.post(
            "/public/experience/minha-exp/leads",
            json={"mode_used": "mobile", "data": {"nome": "Thales"}},
        )
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 201)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["credential_id"], "cred-1")
        self.assertIsNone(payload["lead_id"])
        self.assertFalse(payload["lead_inserted"])
        self.assertTrue(payload["unlock"])

    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    @patch("app.presentation.http.blueprints.quiz_bp.requests.post")
    def test_public_lead_create_without_credential(self, post_req, get_json):
        get_json.side_effect = [
            [
                {
                    "id": "exp-1",
                    "type": "quiz",
                    "status": "published",
                    "config_json": {},
                }
            ],
            [
                {
                    "variable_key": "nome",
                    "label": "Nome",
                    "field_type": "text",
                    "required": False,
                    "sort_order": 0,
                    "options": None,
                }
            ],
        ]
        lead_ok = Mock()
        lead_ok.ok = True
        lead_ok.json.return_value = [{"id": "lead-1"}]
        post_req.return_value = lead_ok

        resp = self.client.post(
            "/public/experience/minha-exp/leads",
            json={
                "mode_used": "mobile",
                "create_credential": False,
                "data": {"nome": "Thales"},
            },
        )
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 201)
        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["credential_id"])
        self.assertEqual(payload["lead_id"], "lead-1")
        self.assertTrue(payload["lead_inserted"])

    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    def test_public_experience_metrics_success(self, get_json):
        get_json.side_effect = [
            [
                {
                    "id": "exp-1",
                    "type": "quiz",
                    "status": "published",
                    "config_json": {},
                }
            ],
            [{"id": "l1"}, {"id": "l2"}],
            [{"id": "g1"}],
        ]
        resp = self.client.get("/public/experience/minha-exp/metrics")
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["started"], 2)
        self.assertEqual(payload["completed"], 1)
        self.assertEqual(payload["dropped"], 1)

    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    @patch("app.presentation.http.blueprints.quiz_bp.requests.patch")
    def test_complete_public_lead_success(self, patch_req, get_json):
        get_json.return_value = [
            {"id": "exp-1", "type": "quiz", "status": "published", "config_json": {}}
        ]
        patch_ok = Mock()
        patch_ok.ok = True
        patch_req.return_value = patch_ok

        resp = self.client.post(
            "/public/experience/minha-exp/leads/lead-1/complete",
            json={"archetype_result_id": "arch-1"},
        )
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["completed"])

    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    def test_complete_public_lead_requires_archetype(self, get_json):
        get_json.return_value = [
            {"id": "exp-1", "type": "quiz", "status": "published", "config_json": {}}
        ]
        resp = self.client.post(
            "/public/experience/minha-exp/leads/lead-1/complete",
            json={},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "missing_archetype_result_id")


if __name__ == "__main__":
    unittest.main()
