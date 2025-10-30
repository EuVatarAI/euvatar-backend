import os

def ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)
