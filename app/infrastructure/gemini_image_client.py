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
        self._model = (self._s.gemini_image_model or "gemini-2.5-flash-image").strip()
        self._api_key = (self._s.gemini_api_key or "").strip()
        self._url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:generateContent?key={self._api_key}"
        )
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    def _request_generation(self, payload: dict) -> dict:
        r = self._session.post(self._url, json=payload, timeout=90)
        if not r.ok:
            body = (r.text or "").replace("\n", " ").strip()
            body = body[:400] if body else ""
            raise RuntimeError(f"gemini_http_{r.status_code}:{body}")
        data = r.json() or {}

        image_part = None
        text_part = ""
        finish_reasons: list[str] = []
        for cand in data.get("candidates", []) or []:
            reason = str(cand.get("finishReason") or cand.get("finish_reason") or "").strip()
            if reason:
                finish_reasons.append(reason)
            content = cand.get("content") or {}
            for part in content.get("parts", []) or []:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    image_part = inline
                    break
                if (not text_part) and part.get("text"):
                    text_part = str(part.get("text") or "").strip()
            if image_part:
                break

        if not image_part:
            # Include provider diagnostics to make production failures actionable.
            prompt_feedback = data.get("promptFeedback") or data.get("prompt_feedback") or {}
            block_reason = str(prompt_feedback.get("blockReason") or prompt_feedback.get("block_reason") or "").strip()
            safety = prompt_feedback.get("safetyRatings") or prompt_feedback.get("safety_ratings") or []
            safety_compact = str(safety)[:240] if safety else ""
            reason_compact = ",".join(finish_reasons)[:120] if finish_reasons else ""
            text_compact = text_part.replace("\n", " ").strip()[:180] if text_part else ""
            details = []
            if reason_compact:
                details.append(f"finish={reason_compact}")
            if block_reason:
                details.append(f"block={block_reason}")
            if safety_compact:
                details.append(f"safety={safety_compact}")
            if text_compact:
                details.append(f"text={text_compact}")
            suffix = ";".join(details)
            if suffix:
                raise RuntimeError(f"gemini_no_image_in_response:{suffix}")
            raise RuntimeError("gemini_no_image_in_response")

        out_b64 = image_part.get("data") or ""
        out_mime = image_part.get("mimeType") or image_part.get("mime_type") or "image/png"

        return {
            "model": self._model,
            "mime_type": out_mime,
            "image_bytes": base64.b64decode(out_b64),
            "usage_metadata": data.get("usageMetadata") or data.get("usage_metadata"),
        }

    def generate_from_reference(self, prompt: str, image_bytes: bytes, mime_type: str) -> dict:
        if not image_bytes:
            raise ValueError("missing_reference_image")

        b64 = base64.b64encode(image_bytes).decode("ascii")
        return self.generate_from_reference_b64(
            prompt=prompt,
            image_b64=b64,
            mime_type=mime_type,
        )

    def generate_from_reference_b64(
        self, prompt: str, image_b64: str, mime_type: str
    ) -> dict:
        if not image_b64:
            raise ValueError("missing_reference_image")
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": mime_type or "image/jpeg",
                                "data": image_b64,
                            }
                        },
                    ]
                }
            ],
            "generation_config": {
                "response_modalities": ["IMAGE"],
            },
        }
        return self._request_generation(payload)

    def generate_from_prompt(self, prompt: str) -> dict:
        if not (prompt or "").strip():
            raise ValueError("missing_prompt")
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                    ]
                }
            ],
            "generation_config": {
                "response_modalities": ["IMAGE"],
            },
        }
        return self._request_generation(payload)
