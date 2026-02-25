import os
import unittest
from unittest.mock import patch, Mock
import os

from app.presentation.http.server import create_app


class QuizPhase1EndpointTests(unittest.TestCase):
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
    def test_public_experience_success(self, get_json):
        get_json.return_value = [
            {
                "id": "exp-1",
                "type": "quiz",
                "status": "active",
                "config_json": {"title": "Quiz Evento"},
            }
        ]
        resp = self.client.get("/public/experience/quiz-evento")
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["experience_id"], "exp-1")
        self.assertEqual(payload["type"], "quiz")

    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    def test_public_experience_not_found(self, get_json):
        get_json.return_value = []
        resp = self.client.get("/public/experience/inexistente")
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "experience_not_found_or_inactive")

    @patch("app.presentation.http.blueprints.quiz_bp.requests.post")
    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    def test_create_credential_success(self, get_json, post):
        get_json.return_value = [{"id": "exp-1", "status": "active"}]
        post_resp = Mock()
        post_resp.ok = True
        post_resp.json.return_value = [{"id": "cred-1"}]
        post.return_value = post_resp

        resp = self.client.post(
            "/credentials",
            json={
                "experience_id": "exp-1",
                "data": {"name": "Thaleson", "city": "SP"},
                "mode_used": "mobile",
            },
        )
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["credential_id"], "cred-1")

    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    def test_create_credential_invalid_mode(self, get_json):
        get_json.return_value = [{"id": "exp-1", "status": "active"}]
        resp = self.client.post(
            "/credentials",
            json={
                "experience_id": "exp-1",
                "data": {"name": "Teste"},
                "mode_used": "desktop",
            },
        )
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "invalid_mode_used")

    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    def test_create_credential_missing_experience_id(self, get_json):
        get_json.return_value = [{"id": "exp-1", "status": "active"}]
        resp = self.client.post(
            "/credentials",
            json={"data": {"name": "Teste"}, "mode_used": "mobile"},
        )
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "missing_experience_id")

    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    def test_create_credential_experience_not_found_or_inactive(self, get_json):
        get_json.return_value = []
        resp = self.client.post(
            "/credentials",
            json={
                "experience_id": "exp-x",
                "data": {"name": "Teste"},
                "mode_used": "mobile",
            },
        )
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "experience_not_found_or_inactive")

    @patch("app.presentation.http.blueprints.quiz_bp.requests.post")
    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    def test_signed_url_success(self, get_json, post):
        get_json.return_value = [{"id": "exp-1", "status": "active"}]
        sign_resp = Mock()
        sign_resp.ok = True
        sign_resp.json.return_value = {
            "signedURL": "/object/upload/sign/avatar-media/quiz/exp-1/user_photo/a.jpg?token=t"
        }
        post.return_value = sign_resp

        resp = self.client.post(
            "/uploads/signed-url",
            json={
                "experience_id": "exp-1",
                "type": "user_photo",
                "file_size_bytes": 1024,
            },
        )
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertIn("upload_url", payload)
        self.assertTrue(payload["storage_path"].startswith("quiz/exp-1/user_photo/"))

    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    def test_signed_url_invalid_type(self, get_json):
        get_json.return_value = [{"id": "exp-1", "status": "active"}]
        resp = self.client.post(
            "/uploads/signed-url",
            json={"experience_id": "exp-1", "type": "exe"},
        )
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "invalid_upload_type")

    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    def test_signed_url_file_too_large(self, get_json):
        get_json.return_value = [{"id": "exp-1", "status": "active"}]
        resp = self.client.post(
            "/uploads/signed-url",
            json={
                "experience_id": "exp-1",
                "type": "user_photo",
                "file_size_bytes": 99_999_999,
            },
        )
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 413)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "file_too_large")

    @patch("app.presentation.http.blueprints.quiz_bp.requests.patch")
    @patch("app.presentation.http.blueprints.quiz_bp.requests.post")
    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    def test_confirm_upload_success(self, get_json, post, patch_req):
        # first call checks experience active, second checks credential isolation
        get_json.side_effect = [
            [{"id": "exp-1", "status": "active"}],
            [{"id": "cred-1", "experience_id": "exp-1"}],
        ]
        up_resp = Mock()
        up_resp.ok = True
        post.return_value = up_resp
        patch_resp = Mock()
        patch_resp.ok = True
        patch_req.return_value = patch_resp

        resp = self.client.post(
            "/uploads/confirm",
            json={
                "experience_id": "exp-1",
                "credential_id": "cred-1",
                "storage_path": "quiz/exp-1/user_photo/file.jpg",
                "type": "user_photo",
            },
        )
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])

    @patch("app.presentation.http.blueprints.quiz_bp.requests.patch")
    @patch("app.presentation.http.blueprints.quiz_bp.requests.post")
    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    def test_confirm_upload_eager_generation_returns_generation_id(
        self, get_json, post, patch_req
    ):
        prev = os.environ.get("QUIZ_EAGER_GENERATION_ON_UPLOAD")
        os.environ["QUIZ_EAGER_GENERATION_ON_UPLOAD"] = "true"
        try:
            get_json.side_effect = [
                [{"id": "exp-1", "status": "active"}],  # active experience check
                [
                    {"id": "cred-1", "experience_id": "exp-1"}
                ],  # credential ownership check
                [
                    {
                        "id": "exp-1",
                        "type": "quiz",
                        "status": "active",
                        "max_generations": 100,
                    }
                ],  # eager exp load
                [],  # done generation count
                [],  # reusable generation lookup
            ]
            up_resp = Mock()
            up_resp.ok = True
            gen_insert_resp = Mock()
            gen_insert_resp.ok = True
            gen_insert_resp.json.return_value = [{"id": "gen-eager-1"}]
            post.side_effect = [up_resp, gen_insert_resp]
            patch_resp = Mock()
            patch_resp.ok = True
            patch_req.return_value = patch_resp

            resp = self.client.post(
                "/uploads/confirm",
                json={
                    "experience_id": "exp-1",
                    "credential_id": "cred-1",
                    "storage_path": "quiz/exp-1/user_photo/file.jpg",
                    "type": "user_photo",
                },
            )
            payload = resp.get_json()
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["generation_id"], "gen-eager-1")
        finally:
            if prev is None:
                os.environ.pop("QUIZ_EAGER_GENERATION_ON_UPLOAD", None)
            else:
                os.environ["QUIZ_EAGER_GENERATION_ON_UPLOAD"] = prev

    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    def test_confirm_upload_invalid_scope(self, get_json):
        get_json.side_effect = [
            [{"id": "exp-1", "status": "active"}],
            [{"id": "cred-1", "experience_id": "exp-1"}],
        ]
        resp = self.client.post(
            "/uploads/confirm",
            json={
                "experience_id": "exp-1",
                "credential_id": "cred-1",
                "storage_path": "quiz/exp-2/user_photo/file.jpg",
                "type": "user_photo",
            },
        )
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "invalid_storage_path_scope")

    @patch("app.presentation.http.blueprints.quiz_bp.requests.post")
    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    def test_create_generation_success(self, get_json, post):
        # experience lookup, credential lookup, done-count lookup
        get_json.side_effect = [
            [
                {
                    "id": "exp-1",
                    "type": "quiz",
                    "status": "active",
                    "max_generations": 100,
                }
            ],
            [{"id": "cred-1", "experience_id": "exp-1"}],
            [],
            [],
        ]
        post_resp = Mock()
        post_resp.ok = True
        post_resp.json.return_value = [{"id": "gen-1"}]
        post.return_value = post_resp

        resp = self.client.post(
            "/generations",
            json={"experience_id": "exp-1", "credential_id": "cred-1"},
        )
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["generation_id"], "gen-1")
        self.assertFalse(payload["reused"])

    @patch("app.presentation.http.blueprints.quiz_bp.requests.post")
    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    def test_create_generation_reuses_existing(self, get_json, post):
        # experience lookup, credential lookup, done-count lookup, reusable lookup
        get_json.side_effect = [
            [
                {
                    "id": "exp-1",
                    "type": "quiz",
                    "status": "active",
                    "max_generations": 100,
                }
            ],
            [{"id": "cred-1", "experience_id": "exp-1"}],
            [],
            [
                {
                    "id": "gen-existing",
                    "status": "processing",
                    "kind": "quiz_result",
                    "credential_id": "cred-1",
                    "experience_id": "exp-1",
                }
            ],
        ]

        resp = self.client.post(
            "/generations",
            json={"experience_id": "exp-1", "credential_id": "cred-1"},
        )
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["generation_id"], "gen-existing")
        self.assertTrue(payload["reused"])
        post.assert_not_called()

    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    def test_create_generation_limit_exceeded(self, get_json):
        # experience lookup, credential lookup, done-count lookup (>= max)
        get_json.side_effect = [
            [{"id": "exp-1", "type": "quiz", "status": "active", "max_generations": 1}],
            [{"id": "cred-1", "experience_id": "exp-1"}],
            [{"id": "done-1"}],
        ]
        resp = self.client.post(
            "/generations",
            json={"experience_id": "exp-1", "credential_id": "cred-1"},
        )
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 429)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "generation_limit_exceeded")

    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    def test_get_generation_status_success(self, get_json):
        get_json.return_value = [
            {
                "id": "gen-1",
                "status": "done",
                "output_path": "quiz/exp-1/generations/gen-1.svg",
                "output_url": "https://example.com/out.png",
                "error_message": None,
            }
        ]
        resp = self.client.get("/generations/gen-1")
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["output_url"], "https://example.com/out.png")

    @patch("app.presentation.http.blueprints.quiz_bp.requests.post")
    @patch("app.presentation.http.blueprints.quiz_bp.get_json")
    def test_get_generation_status_builds_signed_output_url(self, get_json, post_req):
        get_json.return_value = [
            {
                "id": "gen-1",
                "status": "done",
                "output_path": "quiz/exp-1/generations/gen-1.svg",
                "output_url": None,
                "error_message": None,
            }
        ]
        post_resp = Mock()
        post_resp.ok = True
        post_resp.json.return_value = {
            "signedURL": "/object/sign/avatar-media/quiz/exp-1/generations/gen-1.svg?token=abc"
        }
        post_req.return_value = post_resp

        resp = self.client.get("/generations/gen-1")
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "done")
        self.assertIn(
            "/storage/v1/object/sign/avatar-media/quiz/exp-1/generations/gen-1.svg?token=abc",
            payload["output_url"],
        )


if __name__ == "__main__":
    unittest.main()
