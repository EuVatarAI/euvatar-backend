"""Infrastructure helper utilities."""

def headers_json(api_key: str) -> dict:
    return {"X-Api-Key": api_key, "Content-Type": "application/json"}
