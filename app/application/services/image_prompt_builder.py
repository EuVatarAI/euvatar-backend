"""Builds the fixed editorial prompt for Gemini image generation.

Rules come from the product document:
- Prompt is fixed and assembled only in backend.
- Frontend can only send controlled variables.
"""

from __future__ import annotations


ALLOWED_GENDERS = {"homem", "mulher"}
ALLOWED_HAIR_COLORS = {"loiro", "castanho", "preto", "ruivo", "grisalho"}

_GENDER_TOKENS = {
    "mulher": ("beautiful", "woman"),
    "homem": ("handsome", "man"),
}

_HAIR_TOKENS = {
    "loiro": "blond",
    "castanho": "brunette",
    "preto": "black-haired",
    "ruivo": "red-haired",
    "grisalho": "gray-haired",
}

_PROMPT_TEMPLATE = (
    "Portrait orientation 1:1, professional color studio portrait of a "
    "{person_quality} {hair_color} {person_noun}, medium shot.\n"
    "Maintain original facial features, proportions, skin tone, hair length, hair volume and hairstyle shape.\n"
    "Do not add wrinkles or signs of aging. Preserve youthful skin without altering facial structure.\n"
    "Color editorial studio portrait, three-quarter angle composition. Body slightly tilted, face facing left, "
    "eyes looking forward with a calm and confident side glance.\n"
    "Facial expression: subtle happy expression. Natural, relaxed smile. Soft smile with slightly lifted cheeks "
    "and gentle brightness in the eyes. No exaggerated grin, no forced smile.\n"
    "Professional studio lighting with natural daylight quality. Soft key light from one side, simulating large "
    "studio window light. Cinematic side lighting creating subtle chiaroscuro. Clean separation between subject "
    "and background using light, not artificial blur.\n"
    "Strong solid blue seamless background, infinite studio backdrop. Deep sky blue background, evenly lit from "
    "edge to edge. No texture, no gradients, no visible edges.\n"
    "Real human skin with visible pores and natural skin texture. No plastic look, no beauty retouching."
)


def build_editorial_prompt(gender: str, hair_color: str) -> str:
    """Returns the final fixed prompt with validated variable mapping."""
    g = (gender or "").strip().lower()
    h = (hair_color or "").strip().lower()

    if g not in ALLOWED_GENDERS:
        raise ValueError("invalid_gender")
    if h not in ALLOWED_HAIR_COLORS:
        raise ValueError("invalid_hair_color")

    person_quality, person_noun = _GENDER_TOKENS[g]
    hair_token = _HAIR_TOKENS[h]
    return _PROMPT_TEMPLATE.format(
        person_quality=person_quality,
        hair_color=hair_token,
        person_noun=person_noun,
    )

