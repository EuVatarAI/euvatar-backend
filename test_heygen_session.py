import os
import requests

API_KEY = os.getenv("HEYGEN_API_KEY") or "ZmMwYjE0ZjJjZDE4NGMyM2JiNGJlY2U4N2JjYzM1MzctMTc1OTc3MzI3NA=="
AVATAR_ID = "Santa_Fireplace_Front_public"

URL = "https://api.heygen.com/v1/streaming.new"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

payload = {
    "avatar_id": AVATAR_ID,
    "language": "pt-BR"
}

print("🎅 Testando Papai Noel (novo modelo API)...")
print("➡ Avatar:", AVATAR_ID)

response = requests.post(URL, headers=headers, json=payload)

print("\nStatus:", response.status_code)
print("Resposta:", response.text)

if response.status_code != 200:
    print("\n❌ Falhou. O avatar pode estar incorreto ou API Key inválida.")
    exit()

j = response.json()
sid = j["data"]["session_id"]
token = j["data"]["access_token"]
ws_url = j["data"]["url"]

print("\n🎄 Sessão criada com sucesso!")
print("Session ID:", sid)
print("Access Token:", token)
print("LiveKit WS URL:", ws_url)
print("\nPronto! Agora você pode conectar via WebRTC usando esse WS.")
