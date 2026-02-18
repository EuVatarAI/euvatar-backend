"""Gemini image generation adapter."""

from __future__ import annotations

import base64
import requests

from app.core.settings import Settings
from app.domain.ports import IImageGenerationClient


class GeminiImageClient(IImageGenerationClient):
    def __init__(self, settings: Settings):
        self._s = settings
        if not self._s.gemini_api_key:
            raise RuntimeError("missing_GEMINI_API_KEY")

    def generate_from_reference(self, prompt: str, image_bytes: bytes, mime_type: str) -> dict:
        if not image_bytes:
            raise ValueError("missing_reference_image")

        model = self._s.gemini_image_model or "gemini-2.5-flash-image"
        b64 = base64.b64encode(image_bytes).decode("ascii")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={self._s.gemini_api_key}"
        )
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": mime_type or "image/jpeg",
                                "data": b64,
                            }
                        },
                    ]
                }
            ],
            "generation_config": {
                "response_modalities": ["IMAGE"],
            },
        }
        r = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=90)
        r.raise_for_status()
        data = r.json() or {}

        image_part = None
        for cand in data.get("candidates", []) or []:
            content = cand.get("content") or {}
            for part in content.get("parts", []) or []:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    image_part = inline
                    break
            if image_part:
                break

        if not image_part:
            raise RuntimeError("gemini_no_image_in_response")

        out_b64 = image_part.get("data") or ""
        out_mime = image_part.get("mimeType") or image_part.get("mime_type") or "image/png"

        return {
            "model": model,
            "mime_type": out_mime,
            "image_bytes": base64.b64decode(out_b64),
            "usage_metadata": data.get("usageMetadata") or data.get("usage_metadata"),
        }

