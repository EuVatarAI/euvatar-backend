import os, time, requests, json
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("HEYGEN_API_KEY")
if not API_KEY:
    raise SystemExit("❌ Coloque HEYGEN_API_KEY no .env ou exporte no terminal")

H = {"X-Api-Key": API_KEY, "Content-Type": "application/json"}
AVATAR_ID = os.getenv("HEYGEN_STREAMING_AVATAR", "Thaddeus_ProfessionalLook2_public")

URL_NEW   = "https://api.heygen.com/v1/streaming.new"
URL_START = "https://api.heygen.com/v1/streaming.start"
URL_TASK  = "https://api.heygen.com/v1/streaming.task"
URL_KA    = "https://api.heygen.com/v1/streaming.keep_alive"
URL_INT   = "https://api.heygen.com/v1/streaming.interrupt"

def log(msg, data=None):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", (json.dumps(data, ensure_ascii=False) if data else ""))

try:
    # 1. Criar sessão
    body = {
        "version": "v2",
        "avatar_id": AVATAR_ID,
        "language": "pt-BR",
        "backstory": "Você é um pizzaiolo amigável.",
        "quality": "low",
        "activity_idle_timeout": 120  # 2 minutos
    }
    log("POST /streaming.new")
    r = requests.post(URL_NEW, headers=H, json=body, timeout=30)
    if not r.ok:
        raise SystemExit(f"❌ Erro new: {r.status_code} {r.text[:300]}")
    data = r.json()["data"]
    sid = data["session_id"]
    log("✅ Sessão criada", {"session_id": sid})

    # 2. Iniciar
    r = requests.post(URL_START, headers=H, json={"session_id": sid}, timeout=20)
    if not r.ok:
        raise SystemExit(f"❌ Erro start: {r.status_code} {r.text[:300]}")
    log("🚀 Sessão iniciada")

    # 3. Task de fala
    task_payload = {
        "session_id": sid,
        "task_type": "chat",
        "task_mode": "sync",
        "text": "Olá! Pode se apresentar como pizzaiolo, por favor?"
    }
    log("🗣 Enviando /streaming.task")
    r = requests.post(URL_TASK, headers=H, json=task_payload, timeout=90)
    log("🎧 Resposta", {"status": r.status_code, "body": r.text[:300]})

    if not r.ok:
        raise SystemExit("❌ Falha no /task")

    # 4. Loop de keep-alive
    log("🔄 Iniciando keep-alive 10s")
    for i in range(6):  # 1 minuto
        time.sleep(10)
        ka = requests.post(URL_KA, headers=H, json={"session_id": sid}, timeout=10)
        log("KEEPALIVE", {"ok": ka.ok, "status": ka.status_code})
        if not ka.ok:
            raise SystemExit(f"❌ Keepalive falhou no ciclo {i+1}: {ka.text[:200]}")

    # 5. Encerrar sessão
    log("🛑 Enviando /streaming.interrupt")
    r = requests.post(URL_INT, headers=H, json={"session_id": sid}, timeout=10)
    log("Fim", {"status": r.status_code, "text": r.text[:200]})

except Exception as e:
    log("⚠️ Exceção", {"error": str(e)})
