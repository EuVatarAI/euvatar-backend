import base64
import unittest

from app.application.use_cases.generate_editorial_image import (
    GenerateEditorialImageInput,
    execute,
)


class _FakeImageClient:
    def generate_from_reference(self, prompt: str, image_bytes: bytes, mime_type: str) -> dict:
        assert "professional color studio portrait" in prompt
        return {
            "model": "gemini-2.5-flash-image",
            "mime_type": "image/png",
            "image_bytes": b"\x89PNGfake",
            "usage_metadata": {"promptTokenCount": 123},
        }


class _FailingImageClient:
    def generate_from_reference(self, prompt: str, image_bytes: bytes, mime_type: str) -> dict:
        raise RuntimeError("provider_down")


class GenerateEditorialImageTests(unittest.TestCase):
    def test_success_with_fixed_prompt_mapping(self):
        out, status = execute(
            _FakeImageClient(),
            GenerateEditorialImageInput(
                gender="mulher",
                hair_color="castanho",
                reference_image_bytes=b"img-bytes",
                reference_mime_type="image/jpeg",
            ),
        )
        self.assertEqual(status, 200)
        self.assertTrue(out["ok"])
        self.assertEqual(out["model"], "gemini-2.5-flash-image")
        self.assertEqual(out["mime_type"], "image/png")
        self.assertIn("beautiful brunette woman", out["prompt_applied"])
        self.assertEqual(base64.b64decode(out["image_base64"]), b"\x89PNGfake")

    def test_invalid_variable_returns_400(self):
        out, status = execute(
            _FakeImageClient(),
            GenerateEditorialImageInput(
                gender="x",
                hair_color="castanho",
                reference_image_bytes=b"img-bytes",
                reference_mime_type="image/jpeg",
            ),
        )
        self.assertEqual(status, 400)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "invalid_gender")

    def test_missing_reference_image_returns_400(self):
        out, status = execute(
            _FakeImageClient(),
            GenerateEditorialImageInput(
                gender="mulher",
                hair_color="castanho",
                reference_image_bytes=b"",
                reference_mime_type="image/jpeg",
            ),
        )
        self.assertEqual(status, 400)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "missing_reference_image")

    def test_provider_failure_returns_502(self):
        out, status = execute(
            _FailingImageClient(),
            GenerateEditorialImageInput(
                gender="mulher",
                hair_color="castanho",
                reference_image_bytes=b"img-bytes",
                reference_mime_type="image/jpeg",
            ),
        )
        self.assertEqual(status, 502)
        self.assertFalse(out["ok"])
        self.assertIn("image_generation_failed", out["error"])


if __name__ == "__main__":
    unittest.main()

