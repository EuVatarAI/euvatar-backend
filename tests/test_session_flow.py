import os
import requests
import time

BASE_URL = os.getenv("EUVATAR_BASE_URL", "http://127.0.0.1:5001").rstrip("/")
API_TOKEN = os.getenv("APP_API_TOKEN", "")
AVATAR_ID = os.getenv("HEYGEN_STREAMING_AVATAR", "")
LANG = "pt-BR"

HEADERS = {
    "Content-Type": "application/json",
    "X-Client-Id": "test-client-001",
    "Authorization": f"Bearer {API_TOKEN}",
}

def test_health():
    r = requests.get(f"{BASE_URL}/health", headers=HEADERS)
    print("HEALTH:", r.status_code, r.json())

def test_new_session():
    params = {
        "language": LANG,
        "persona": "default",
        "quality": "low",
        "minutes": 2.5,
        "avatar_id": AVATAR_ID
    }
    r = requests.get(f"{BASE_URL}/new", headers=HEADERS, params=params)
    print("NEW:", r.status_code, r.json())
    return r.json()

def test_say(session_id):
    payload = {
        "session_id": session_id,
        "avatar_id": AVATAR_ID,
        "text": "Olá! Pode se apresentar rapidamente?"
    }
    r = requests.post(f"{BASE_URL}/say", headers=HEADERS, json=payload)
    print("SAY:", r.status_code, r.json())

def test_keepalive(session_id):
    payload = {
        "session_id": session_id
    }
    r = requests.post(f"{BASE_URL}/keepalive", headers=HEADERS, json=payload)
    print("KEEPALIVE:", r.status_code, r.json())

def test_metrics():
    r = requests.get(f"{BASE_URL}/metrics", headers=HEADERS)
    print("METRICS:", r.status_code, r.json())

def test_credits():
    r = requests.get(f"{BASE_URL}/credits", headers=HEADERS)
    print("CREDITS:", r.status_code, r.json())

def test_end(session_id):
    payload = {
        "session_id": session_id
    }
    r = requests.post(f"{BASE_URL}/end", headers=HEADERS, json=payload)
    print("END:", r.status_code, r.json())

if __name__ == "__main__":
    print("\n=== TESTE BACKEND EUVATAR ===\n")

    if not API_TOKEN or not AVATAR_ID:
        raise SystemExit("Defina APP_API_TOKEN e HEYGEN_STREAMING_AVATAR no ambiente antes de testar.")

    test_health()

    session = test_new_session()
    assert session.get("ok"), "Falha ao criar sessão"

    session_id = session["session_id"]

    time.sleep(2)
    test_say(session_id)

    time.sleep(2)
    test_say(session_id)

    time.sleep(2)
    test_keepalive(session_id)

    time.sleep(2)
    test_metrics()

    time.sleep(2)
    test_end(session_id)

    time.sleep(1)
    test_credits()

    print("\n=== TESTE FINALIZADO COM SUCESSO ===")
