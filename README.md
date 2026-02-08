# EuVatar Backend 🧠🎥

Backend HTTP (Flask) responsável por iniciar sessões do LiveAvatar/HeyGen, controlar streaming, STT, credenciais e métricas de uso.

---

## ✨ O que este backend faz

- ✅ **Cria sessões** de avatar (LiveAvatar/HeyGen)
- ✅ **Controla áudio (STT)** e comandos de sessão
- ✅ **Resolve gatilhos de mídia** (contextos)
- ✅ **Lê credenciais por cliente** no Supabase
- ✅ **Bloqueia execução sem API Key** (sem fallback global)
- ✅ **Calcula uso de créditos** baseado em sessões

---

## 🧱 Arquitetura (alto nível)

```
frontend (Vite/React)
        ↓
backend (Flask)
        ↓
LiveAvatar / HeyGen APIs
        ↓
LiveKit Streaming
```

- O frontend **nunca envia API Key**.
- O backend busca a chave do cliente no banco (Supabase).
- Cada cliente usa somente sua chave vinculada.

---

## 📂 Estrutura de pastas

```
app/
  core/            # Config + container
  domain/          # Modelos e interfaces
  application/     # Use cases
  infrastructure/  # Integrações externas
  presentation/    # Rotas HTTP
```

---

## ⚙️ Variáveis de ambiente (.env)

Crie um `.env` a partir do `.env.example`:

```bash
cp .env.example .env
```

Principais variáveis:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE`
- `LIVEAVATAR_API_KEY`
- `AVATAR_PROVIDER=liveavatar`
- `APP_HOST` / `APP_PORT`

---

## ▶️ Como rodar local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m app.main
```

A API sobe em:
```
http://127.0.0.1:5001
```

---

## 🔗 Integração com o Frontend

O frontend consome as rotas do backend:

- `GET /new` → cria sessão do avatar
- `POST /stt` → converte áudio em texto
- `POST /context/resolve` → gatilhos de mídia
- `GET /credits` → métricas e créditos

No front, o `VITE_BACKEND_URL` deve apontar para este backend.

---

## ✅ Regras importantes (segurança)

- **Sem fallback global** de API Key
- **JWT do cliente** é obrigatório
- **RLS ativado** no Supabase

---

## 🧪 Testes

```bash
python3 -m unittest tests/test_voice_id_validation.py
```

---

## 🚀 Produção

```bash
sudo systemctl restart euvatar_backend.service
sudo systemctl status euvatar_backend.service --no-pager
```

Logs:
```bash
sudo journalctl -u euvatar_backend.service -f
```

---

## 📌 Observações

- O backend usa o `client_id` extraído do JWT.
- As credenciais são sempre carregadas do Supabase (`admin_clients`).

---

Qualquer dúvida, fale com o time de backend 🛠️
