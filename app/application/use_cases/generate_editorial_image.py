"""Use-case for editorial image generation from a reference photo."""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass

from app.application.services.image_prompt_builder import build_editorial_prompt
from app.domain.ports import IImageGenerationClient


@dataclass
class GenerateEditorialImageInput:
    gender: str
    hair_color: str
    reference_image_bytes: bytes
    reference_mime_type: str


def execute(image_client: IImageGenerationClient, args: GenerateEditorialImageInput) -> tuple[dict, int]:
    if not args.reference_image_bytes:
        return {"ok": False, "error": "missing_reference_image"}, 400

    try:
        prompt = build_editorial_prompt(args.gender, args.hair_color)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}, 400

    try:
        t0 = time.time()
        out = image_client.generate_from_reference(
            prompt=prompt,
            image_bytes=args.reference_image_bytes,
            mime_type=args.reference_mime_type,
        )
        latency_ms = int((time.time() - t0) * 1000)
        return (
            {
                "ok": True,
                "model": out.get("model"),
                "latency_ms": latency_ms,
                "mime_type": out.get("mime_type"),
                "image_base64": base64.b64encode(out.get("image_bytes") or b"").decode("ascii"),
                "usage_metadata": out.get("usage_metadata"),
                "prompt_applied": prompt,
            },
            200,
        )
    except Exception as exc:
        return {"ok": False, "error": f"image_generation_failed:{exc}"}, 502

