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
    "Preserve original facial features, proportions, skin tone, hair length, volume, and hairstyle.\n"
    "Do not add wrinkles or signs of aging. Keep youthful skin without altering facial structure.\n"
    "Three-quarter editorial composition: body slightly tilted, face turned left, eyes forward, calm confident side glance.\n"
    "Subtle happy expression with a natural relaxed soft smile. No exaggerated grin or forced smile.\n"
    "Natural daylight-quality studio lighting with soft side key light and subtle cinematic chiaroscuro.\n"
    "Strong solid blue seamless background, infinite studio backdrop. Deep sky blue, evenly lit, no texture, no gradients, no visible edges.\n"
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
