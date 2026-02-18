import io
import os
import unittest
import base64
from unittest.mock import patch

from app.presentation.http.server import create_app


class ImageGenerateEndpointTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("HEYGEN_API_KEY", "env-key")
        os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
        os.environ.setdefault("SUPABASE_SERVICE_ROLE", "service-role")
        os.environ.setdefault("APP_API_TOKEN", "test-token")
        os.environ.setdefault("CORS_ORIGINS", "http://localhost:8080")
        os.environ.setdefault("APP_DEBUG", "false")
        os.environ["UPLOAD_MAX_MB"] = "1"
        self.auth_patcher = patch("app.presentation.http.server.require_auth", lambda: None)
        self.auth_patcher.start()
        self.app = create_app()
        self.client = self.app.test_client()

    def tearDown(self):
        self.auth_patcher.stop()

    def _auth_headers(self):
        return {"Authorization": "Bearer test-token"}

    @staticmethod
    def _valid_png_bytes() -> bytes:
        return base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/w8AAgMBgM8fVZkAAAAASUVORK5CYII="
        )

    @patch("app.presentation.http.blueprints.image_gen_bp.generate_editorial_image_uc")
    def test_generate_image_success(self, gen_uc):
        self.app.container.image_gen = object()
        gen_uc.return_value = (
            {
                "ok": True,
                "model": "gemini-2.5-flash-image",
                "latency_ms": 1234,
                "mime_type": "image/png",
                "image_base64": "iVBOR2Zha2U=",
                "usage_metadata": {"promptTokenCount": 10},
                "prompt_applied": "fixed prompt",
            },
            200,
        )

        data = {
            "gender": "mulher",
            "hair_color": "castanho",
            "image": (io.BytesIO(self._valid_png_bytes()), "ref.png"),
        }
        resp = self.client.post(
            "/image/generate",
            headers=self._auth_headers(),
            data=data,
            content_type="multipart/form-data",
        )
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["model"], "gemini-2.5-flash-image")
        self.assertIn("/uploads/generated_", payload["image_url"])

    def test_generate_image_missing_file(self):
        self.app.container.image_gen = object()
        resp = self.client.post(
            "/image/generate",
            headers=self._auth_headers(),
            data={"gender": "mulher", "hair_color": "castanho"},
            content_type="multipart/form-data",
        )
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "missing_image")

    def test_generate_image_missing_params(self):
        self.app.container.image_gen = object()
        data = {
            "image": (io.BytesIO(self._valid_png_bytes()), "ref.png"),
        }
        resp = self.client.post(
            "/image/generate",
            headers=self._auth_headers(),
            data=data,
            content_type="multipart/form-data",
        )
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "missing_params")

    def test_generate_image_empty_file(self):
        self.app.container.image_gen = object()
        data = {
            "gender": "mulher",
            "hair_color": "castanho",
            "image": (io.BytesIO(b""), "ref.png"),
        }
        resp = self.client.post(
            "/image/generate",
            headers=self._auth_headers(),
            data=data,
            content_type="multipart/form-data",
        )
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "empty_image")

    def test_generate_image_file_too_large(self):
        self.app.container.image_gen = object()
        too_big = b"a" * (1024 * 1024 + 1)
        data = {
            "gender": "mulher",
            "hair_color": "castanho",
            "image": (io.BytesIO(too_big), "ref.jpg"),
        }
        resp = self.client.post(
            "/image/generate",
            headers=self._auth_headers(),
            data=data,
            content_type="multipart/form-data",
        )
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 413)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "file_too_large")

    def test_generate_image_invalid_format(self):
        self.app.container.image_gen = object()
        data = {
            "gender": "mulher",
            "hair_color": "castanho",
            "image": (io.BytesIO(b"not-an-image"), "ref.jpg"),
        }
        resp = self.client.post(
            "/image/generate",
            headers=self._auth_headers(),
            data=data,
            content_type="multipart/form-data",
        )
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "invalid_image_format")

    def test_generate_image_invalid_gender(self):
        self.app.container.image_gen = object()
        data = {
            "gender": "nao-binario",
            "hair_color": "castanho",
            "image": (io.BytesIO(self._valid_png_bytes()), "ref.png"),
        }
        resp = self.client.post(
            "/image/generate",
            headers=self._auth_headers(),
            data=data,
            content_type="multipart/form-data",
        )
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "invalid_gender")

    def test_generate_image_invalid_hair_color(self):
        self.app.container.image_gen = object()
        data = {
            "gender": "mulher",
            "hair_color": "azul",
            "image": (io.BytesIO(self._valid_png_bytes()), "ref.png"),
        }
        resp = self.client.post(
            "/image/generate",
            headers=self._auth_headers(),
            data=data,
            content_type="multipart/form-data",
        )
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "invalid_hair_color")

    @patch("app.presentation.http.blueprints.image_gen_bp.generate_editorial_image_uc")
    def test_generate_image_provider_error_502(self, gen_uc):
        self.app.container.image_gen = object()
        gen_uc.return_value = ({"ok": False, "error": "image_generation_failed:timeout"}, 502)
        data = {
            "gender": "mulher",
            "hair_color": "castanho",
            "image": (io.BytesIO(self._valid_png_bytes()), "ref.png"),
        }
        resp = self.client.post(
            "/image/generate",
            headers=self._auth_headers(),
            data=data,
            content_type="multipart/form-data",
        )
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 502)
        self.assertFalse(payload["ok"])
        self.assertIn("image_generation_failed", payload["error"])

    def test_generate_image_missing_key_config(self):
        self.app.container.image_gen = None
        data = {
            "gender": "mulher",
            "hair_color": "castanho",
            "image": (io.BytesIO(self._valid_png_bytes()), "ref.png"),
        }
        resp = self.client.post(
            "/image/generate",
            headers=self._auth_headers(),
            data=data,
            content_type="multipart/form-data",
        )
        payload = resp.get_json()
        self.assertEqual(resp.status_code, 500)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "missing_GEMINI_API_KEY")


if __name__ == "__main__":
    unittest.main()
