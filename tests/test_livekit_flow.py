import os
import time
import requests
import pytest
from dotenv import load_dotenv

load_dotenv()


BASE_URL = os.getenv("EUVATAR_BASE_URL", "http://127.0.0.1:5001").rstrip("/")
API_TOKEN = os.getenv("APP_API_TOKEN", "")
AVATAR_ID = (os.getenv("TEST_AVATAR_ID") or os.getenv("HEYGEN_STREAMING_AVATAR") or "").strip()

HEADERS = {
    "Content-Type": "application/json",
    "X-Client-Id": "livekit-integration-001",
    "Authorization": f"Bearer {API_TOKEN}",
}


def test_livekit_avatar_flow():
    if not API_TOKEN or not AVATAR_ID:
        pytest.skip("Defina APP_API_TOKEN e HEYGEN_STREAMING_AVATAR para rodar este teste.")

    health = requests.get(f"{BASE_URL}/health", headers=HEADERS, timeout=20)
    print("HEALTH:", health.status_code, health.text[:300])
    assert health.ok, f"/health failed: {health.status_code} {health.text[:200]}"

    params = {
        "language": "pt-BR",
        "persona": "default",
        "quality": "low",
        "minutes": 2.5,
        "avatar_id": AVATAR_ID,
    }
    new_session = requests.get(f"{BASE_URL}/new", headers=HEADERS, params=params, timeout=60)
    print("NEW:", new_session.status_code, new_session.text[:600])
    assert new_session.ok, f"/new failed: {new_session.status_code} {new_session.text[:200]}"
    payload = new_session.json()
    assert payload.get("ok"), f"/new ok=false: {payload}"
    session_id = payload.get("session_id")
    livekit_url = payload.get("livekit_url")
    access_token = payload.get("access_token")
    assert session_id, "missing session_id"
    assert livekit_url and livekit_url.startswith(("ws://", "wss://")), "invalid livekit_url"
    assert access_token, "missing access_token"

    time.sleep(1.5)
    say_payload = {
        "session_id": session_id,
        "avatar_id": AVATAR_ID,
        "text": "Oi! Responda em uma frase curta.",
    }
    say = requests.post(f"{BASE_URL}/say", headers=HEADERS, json=say_payload, timeout=90)
    print("SAY:", say.status_code, say.text[:600])
    assert say.ok, f"/say failed: {say.status_code} {say.text[:200]}"
    say_json = say.json()
    assert say_json.get("ok"), f"/say ok=false: {say_json}"

    keepalive = requests.post(
        f"{BASE_URL}/keepalive",
        headers=HEADERS,
        json={"session_id": session_id},
        timeout=20,
    )
    print("KEEPALIVE:", keepalive.status_code, keepalive.text[:300])
    assert keepalive.ok, f"/keepalive failed: {keepalive.status_code} {keepalive.text[:200]}"

    end = requests.post(f"{BASE_URL}/end", headers=HEADERS, json={"session_id": session_id}, timeout=20)
    print("END:", end.status_code, end.text[:300])
    assert end.ok, f"/end failed: {end.status_code} {end.text[:200]}"
