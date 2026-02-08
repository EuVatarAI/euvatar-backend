"""Shared text parsing and normalization utilities."""

from __future__ import annotations
import re, unicodedata

def normalize(s: str) -> str:
    s = (s or "").lower().strip()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return s

def tokenize_filename_terms(name: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9À-ú]+", (name or "").lower())

def safe_filename(name: str, default: str = "file.bin") -> str:
    import os
    base, ext = os.path.splitext((name or default).lower())
    base = ''.join(c for c in unicodedata.normalize('NFD', base) if unicodedata.category(c) != 'Mn')
    base = re.sub(r'[^a-z0-9]+', '_', base).strip('_') or "file"
    ext = re.sub(r'[^.a-z0-9]', '', ext) or ".bin"
    return f"{base}{ext}"
