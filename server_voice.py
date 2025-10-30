# server_voice.py
# -*- coding: utf-8 -*-
import os, re, time, unicodedata
import uuid as _uuid
from datetime import datetime, timezone
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import requests

# ================== Setup & ENV ==================
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "public")
UPLOAD_DIR = os.path.abspath(os.path.join(BASE_DIR, "uploads"))
os.makedirs(UPLOAD_DIR, exist_ok=True)

load_dotenv()

# HeyGen
HEYGEN_API_KEY = os.getenv("HEYGEN_API_KEY")
assert HEYGEN_API_KEY, "Coloque HEYGEN_API_KEY no .env"

H_HEYGEN = {"X-Api-Key": HEYGEN_API_KEY, "Content-Type": "application/json"}
URL_NEW       = "https://api.heygen.com/v1/streaming.new"
URL_START     = "https://api.heygen.com/v1/streaming.start"
URL_TASK      = "https://api.heygen.com/v1/streaming.task"
URL_INTERRUPT = "https://api.heygen.com/v1/streaming.interrupt"

# Avatar interativo (válido público)
INTERACTIVE_AVATAR = os.getenv("HEYGEN_STREAMING_AVATAR", "Thaddeus_ProfessionalLook2_public")

# OpenAI (STT e GPT p/ contexto)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# ===== Supabase (AGORA: Service Role OBRIGATÓRIA no servidor) =====
SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE")  # sem fallback para ANON
assert SUPABASE_URL and SUPABASE_SERVICE_KEY, "Defina SUPABASE_URL e SUPABASE_SERVICE_ROLE no .env"

H_SUPABASE = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
}

# Supabase Storage
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "avatar-media")  # bucket público já usado no projeto

# ================ Flask app ======================
app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")
CORS(app)

# ================ Sessão & Métricas ==============
def now_ts() -> int: return int(time.time())

SESSION = {
    "id": None, "url": None, "token": None,
    "language": None, "backstory": None, "quality": "low",
    "ends_at": None,  # epoch seg
}
BUDGET = {
    "credits_per_session": 10,
    "total_credits_spent": 0,
    "sessions": []
}

# ============== Mini-RAG local (fallback simples) ============
DOC_INDEX = {}  # {"termo":[{"name","url"}]}

MEDIA_TRIGGERS = [
    {
        "pattern": r"\b(onde fica|localiza(?:ç|c)ão|mapa|endereço|como chego)\b",
        "type": "image",
        "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/7/79/Barcelona_City_Center_Map.svg/1280px-Barcelona_City_Center_Map.svg.png",
        "caption": "Mapa – Centro de Barcelona"
    },
    {
        "pattern": r"\b(video|vídeo|tour|passeio)\b",
        "type": "video",
        "url": "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4",
        "caption": "Vídeo demonstrativo"
    }
]

# ============== Helpers de NEGÓCIO ================
def build_backstory(persona: str, language: str, custom: str = None) -> str:
    if custom: return custom
    persona = (persona or "default").lower()
    lang = (language or "pt-BR").lower()
    if persona == "barca":
        if lang.startswith("pt"):
            return ("Você é um jogador fictício do FC Barcelona. Tom: humilde, motivado e respeitoso. "
                    "Fale sobre o clube, estilo de jogo, treinos e história. Evite dados confidenciais. "
                    "Responda em até 3 frases em pt-BR.")
        return ("You are a fictional FC Barcelona player. Humble tone. Talk about the club, style, training, history. "
                "Avoid confidential info. Up to 3 sentences.")
    if lang.startswith("pt"):
        return ("Você é a Assistente Euvatar: educada, direta, prática. "
                "Responda em até 2-3 frases, exemplos simples quando fizer sentido.")
    return ("You are a pragmatic assistant. Be concise (2-3 sentences), clear and helpful.")

def system_prompt(bs: str, lang: str) -> str:
    return (f"SISTEMA: Personagem -> {bs} "
            f"Regras: responda no idioma da sessão ({lang}); no máx. 3 frases; claro e objetivo.")

def detect_media_keywords(text: str):
    txt = (text or "").lower()
    for rule in MEDIA_TRIGGERS:
        if re.search(rule["pattern"], txt):
            return {"type": rule["type"], "url": rule["url"], "caption": rule.get("caption")}
    return None

# ================== Supabase util =====================
def sb_get_json(table: str, select: str, params: dict, limit: int = None):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    q = {"select": select, **params}
    if limit:
        q["limit"] = str(limit)
    r = requests.get(url, headers=H_SUPABASE, params=q, timeout=20)
    if not r.ok:
        # dica de RLS/credencial
        msg = r.text[:200]
        if r.status_code == 403 and "row-level security" in msg.lower():
            msg += " (RLS: verifique policies ou use service role no backend)"
        raise RuntimeError(f"supabase_{table}_{r.status_code}: {msg}")
    return r.json() or []

def resolve_avatar_uuid(avatar_id_or_name: str):
    import uuid as _uuid
    if not avatar_id_or_name:
        return None
    candidate = avatar_id_or_name.strip()
    try:
        _ = _uuid.UUID(candidate)
        return candidate
    except Exception:
        pass
    rows = sb_get_json("avatars", "id,name", {"name": f"eq.{candidate}"}, limit=1)
    if rows:
        return rows[0]["id"]
    return None

def sb_get_contexts_by_avatar_any(avatar_id_or_slug: str):
    resolved = resolve_avatar_uuid(avatar_id_or_slug)
    if not resolved:
        return []
    rows = sb_get_json(
        "contexts",
        "name,media_url,media_type,keywords_text,enabled",
        {"avatar_id": f"eq.{resolved}"}
    )
    out = []
    for row in rows:
        if "enabled" in row and row["enabled"] is not None and (not row["enabled"]):
            continue
        out.append({
            "name": (row.get("name") or "").strip(),
            "media_url": (row.get("media_url") or "").strip(),
            "media_type": (row.get("media_type") or "image").strip() or "image",
            "keywords_text": (row.get("keywords_text") or "").strip()
        })
    return [c for c in out if c["name"]]

# ============== FAST MATCH ===================
def _norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return s

def fast_match_context(user_text: str, contexts: list) -> str:
    text = _norm(user_text)
    if not text:
        return None
    for c in contexts:
        name = _norm(c.get("name", ""))
        if name and name in text:
            return c["name"]
        
        if name:
            for tok in name.split("_"):
                if tok and tok in text:
                    return c["name"]
        
        kws = _norm(c.get("keywords_text", ""))
        if kws:
            parts = [k.strip() for k in re.split(r"[;,|]", kws) if k.strip()]
            for k in parts:
                if k and k in text:
                    return c["name"]
    return None

# ============== GPT Resolver (fallback) ==============
def resolve_context_with_gpt(user_text: str, context_names: list) -> str:
    if not OPENAI_API_KEY or not context_names:
        return "none"
    system = ("Você recebe uma fala do usuário e uma lista de contextos. "
              "Se corresponder claramente a um dos contextos, responda APENAS com esse contexto (texto exato). "
              "Caso contrário, responda 'none'. Sem explicações.")
    user = "Fala: {}\nContextos:\n- {}".format(user_text, "\n- ".join(context_names))
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        "temperature": 0
    }
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        json=payload, timeout=25
    )
    if not r.ok:
        return "none"
    try:
        content = r.json()["choices"][0]["message"]["content"].strip()
        return content if content in context_names else "none"
    except Exception:
        return "none"

def resolve_media_for_match(contexts: list, match: str):
    for c in contexts:
        if c["name"] == match and c["media_url"]:
            mtype = (c.get("media_type") or "image").lower()
            if mtype not in ("image", "video"): mtype = "image"
            return {"type": mtype, "url": c["media_url"], "caption": c["name"]}
    return None

# =================== Rotas ========================
@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "has_api_key": True,
        "using_service_role": True,  # agora é obrigatório
        "avatar": INTERACTIVE_AVATAR,
        "session_active": bool(SESSION["id"]),
        "quality": SESSION.get("quality"),
        "ends_at": SESSION.get("ends_at"),
        "bucket": SUPABASE_BUCKET,
        "budget": {
            "credits_per_session": BUDGET["credits_per_session"],
            "total_credits_spent": BUDGET["total_credits_spent"],
            "sessions": len(BUDGET["sessions"])
        }
    })

@app.get("/heygen-sdk.umd.js")
def serve_heygen_sdk():
    path = os.path.join(STATIC_DIR, "heygen-sdk.umd.js")
    if not os.path.isfile(path):
        return "UMD não encontrado (ok ignorar se você não usa o arquivo). Coloque em public/heygen-sdk.umd.js", 404
    return send_from_directory(STATIC_DIR, "heygen-sdk.umd.js", mimetype="application/javascript")

@app.get("/token")
def create_session_token():
    try:
        r = requests.post("https://api.heygen.com/v1/streaming.create_token",
                          headers={"X-Api-Key": HEYGEN_API_KEY}, json={}, timeout=30)
        if not r.ok: return jsonify({"ok": False, "error": r.text}), r.status_code
        j = r.json() or {}; token = (j.get("data") or {}).get("token")
        if not token: return jsonify({"ok": False, "error": "no_token"}), 502
        return jsonify({"ok": True, "token": token})
    except Exception as e:
        return jsonify({"ok": False, "error": f"token_exception: {e}"}), 500

@app.get("/new")
def new_session():
    try:
        language = request.args.get("language", "pt-BR")
        persona  = request.args.get("persona", "default")
        quality  = request.args.get("quality", "low")
        backstory_param = request.args.get("backstory") or ""
        voice_id = request.args.get("voice_id")
        minutes  = float(request.args.get("minutes", "2.5"))

        bs = build_backstory(persona, language, backstory_param.strip() or None)
        body = {
            "version": "v2",
            "avatar_id": INTERACTIVE_AVATAR,
            "language": language,
            "backstory": bs,
            "disable_idle_timeout": True,
            "quality": quality
        }
        if voice_id:
            body["voice"] = {"voice_id": voice_id}

        r = requests.post(URL_NEW, json=body, headers=H_HEYGEN, timeout=60)
        if not r.ok:
            return jsonify({"ok": False, "error": r.text}), r.status_code
        data = r.json().get("data", {})
        session_id, livekit_url, token = data.get("session_id"), data.get("url"), data.get("access_token")

        s = requests.post(URL_START, json={"session_id": session_id}, headers=H_HEYGEN, timeout=60)
        if not s.ok:
            return jsonify({"ok": False, "error": s.text}), s.status_code

        SESSION.update({
            "id": session_id, "url": livekit_url, "token": token,
            "language": language, "backstory": bs, "quality": quality,
            "ends_at": now_ts() + int(minutes * 60),
        })

        BUDGET["total_credits_spent"] += BUDGET["credits_per_session"]
        BUDGET["sessions"].append({
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "minutes_planned": minutes,
            "credits_debited": BUDGET["credits_per_session"],
            "quality": quality,
            "language": language
        })

        return jsonify({"ok": True, "session_id": session_id, "livekit_url": livekit_url, "access_token": token})
    except Exception as e:
        return jsonify({"ok": False, "error": f"new_exception: {e}"}), 500

@app.post("/stt")
def stt_route():
    try:
        if "audio" not in request.files:
            return jsonify({"ok": False, "error": "no_audio"}), 400
        if not OPENAI_API_KEY:
            return jsonify({"ok": False, "error": "missing_OPENAI_API_KEY"}), 500

        f = request.files["audio"]
        data = {
            "model": "whisper-1",
            "response_format": "json",
            "temperature": "0"
        }
        files = {"file": (f.filename or "audio.webm", f.stream, f.mimetype or "audio/webm")}
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
        r = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers=headers, data=data, files=files, timeout=120
        )
        if not r.ok:
            return jsonify({"ok": False, "error": f"openai_{r.status_code}: {r.text[:300]}"}), 502

        j = r.json()
        text = j.get("text", "").strip()
        return jsonify({"ok": True, "text": text})
    except Exception as e:
        return jsonify({"ok": False, "error": f"stt_exception: {e}"}), 500

# ============== Resolver contexto (BACKEND) ==============
@app.post("/context/resolve")
def context_resolve():
    import time as _t
    t0 = _t.time()
    try:
        j = request.get_json(force=True) or {}
        avatar_id = (j.get("avatar_id") or "").strip()
        text = (j.get("text") or "").strip()
        if not avatar_id or not text:
            return jsonify({"ok": False, "error":"missing_params"}), 400

        contexts = sb_get_contexts_by_avatar_any(avatar_id)
        names = [c["name"] for c in contexts]

        if not names:
            dt = int((_t.time()-t0)*1000)
            return jsonify({"ok": True, "match": "none", "media": None, "method": "none", "latency_ms": dt})

        fm = fast_match_context(text, contexts)
        if fm:
            media = resolve_media_for_match(contexts, fm)
            dt = int((_t.time()-t0)*1000)
            return jsonify({"ok": True, "match": fm, "media": media, "method": "fast", "latency_ms": dt})

        match = resolve_context_with_gpt(text, names)
        media = resolve_media_for_match(contexts, match) if match != "none" else None
        dt = int((_t.time()-t0)*1000)
        return jsonify({"ok": True, "match": match, "media": media, "method": "gpt" if match!="none" else "none", "latency_ms": dt})
    except Exception as e:
        return jsonify({"ok": False, "error": f"resolve_exception: {e}"}), 500

@app.post("/say")
def say():
    import time as _t
    t0 = _t.time()
    try:
        data = request.get_json(force=True) or {}
        session_id = data.get("session_id") or SESSION.get("id")
        text = (data.get("text") or "").strip()
        avatar_id = (data.get("avatar_id") or "").strip()
        if not session_id or not text:
            return jsonify({"ok": False, "error": "session_id e text são obrigatórios"}), 400

        if SESSION.get("ends_at") and now_ts() >= SESSION["ends_at"]:
            return jsonify({"ok": False, "error": "session_expired"}), 410

        bs   = SESSION.get("backstory", "")
        lang = SESSION.get("language", "pt-BR")
        system = data.get("system") or system_prompt(bs, lang)

        payload = {
            "session_id": session_id,
            "task_type": "chat",
            "task_mode": "sync",
            "text": f"{system}\nUSUÁRIO: {text}"
        }
        r = requests.post(URL_TASK, json=payload, headers=H_HEYGEN, timeout=90)
        if not r.ok:
            return jsonify({"ok": False, "error": r.text}), r.status_code
        j = r.json()
        dur_ms = int((j.get("data") or {}).get("duration_ms", 0))

        media = None
        method = "none"
        try:
            if avatar_id:
                contexts = sb_get_contexts_by_avatar_any(avatar_id)
                names = [c["name"] for c in contexts]
                if names:
                    fm = fast_match_context(text, contexts)
                    if fm:
                        media = resolve_media_for_match(contexts, fm)
                        method = "fast"
                    else:
                        match = resolve_context_with_gpt(text, names)
                        if match != "none":
                            media = resolve_media_for_match(contexts, match)
                            method = "gpt"
            if not media:
                media = detect_media_keywords(text)
                if media:
                    method = "keywords"
        except Exception:
            pass

        latency_ms = int((_t.time()-t0)*1000)
        return jsonify({
            "ok": True,
            "duration_ms": dur_ms,
            "task_id": (j.get("data") or {}).get("task_id"),
            "media": media,
            "context_method": method,
            "resolver_latency_ms": latency_ms
        })
    except Exception as e:
        return jsonify({"ok": False, "error": f"say_exception: {e}"}), 500

@app.post("/interrupt")
def interrupt():
    try:
        session_id = (request.get_json(force=True) or {}).get("session_id") or SESSION.get("id")
        if not session_id:
            return jsonify({"ok": False, "error": "session_id ausente"}), 400
        r = requests.post(URL_INTERRUPT, json={"session_id": session_id}, headers=H_HEYGEN, timeout=30)
        if not r.ok:
            return jsonify({"ok": False, "error": r.text}), r.status_code
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": f"interrupt_exception: {e}"}), 500

@app.post("/end")
def end():
    SESSION.update({"id": None, "url": None, "token": None, "language": None, "backstory": None, "ends_at": None})
    return jsonify({"ok": True})

@app.get("/metrics")
def metrics():
    elapsed = max(0, (SESSION["ends_at"] - now_ts())) if SESSION.get("ends_at") else 0
    return jsonify({
        "ok": True,
        "session_active": bool(SESSION["id"]),
        "ends_at": SESSION.get("ends_at"),
        "seconds_left": elapsed,
        "budget": {
            "credits_per_session": BUDGET["credits_per_session"],
            "total_credits_spent": BUDGET["total_credits_spent"],
            "sessions": BUDGET["sessions"]
        }
    })

# ============== Upload & mini-RAG local =============
@app.post("/upload")
def upload():
    if request.method == "POST" and request.files:
        files = request.files.getlist("file")
        added = []
        for f in files:
            fname = f.filename
            dest = os.path.join(UPLOAD_DIR, f"{_uuid.uuid4().hex}_{fname}")
            f.save(dest)
            url = f"/uploads/{os.path.basename(dest)}"
            base_terms = re.findall(r"[a-zA-Z0-9À-ú]+", fname.lower())
            for t in base_terms:
                DOC_INDEX.setdefault(t, []).append({"name": fname, "url": url})
            added.append({"name": fname, "url": url})
        return jsonify({"ok": True, "added": added, "index_terms": list(DOC_INDEX.keys())})
    return jsonify({"ok": False, "error": "no files"}), 400

@app.get("/search")
def search():
    q = (request.args.get("q") or "").strip().lower()
    if not q: return jsonify({"ok": True, "results": []})
    terms = re.findall(r"[a-zA-Z0-9À-ú]+", q)
    hits = []
    for t in terms: hits.extend(DOC_INDEX.get(t, []))
    seen = set(); out=[]
    for h in hits:
        key = h["url"]
        if key in seen: continue
        out.append(h); seen.add(key)
    return jsonify({"ok": True, "results": out})

@app.get("/uploads/<path:fname>")
def serve_upload(fname):
    return send_from_directory(UPLOAD_DIR, fname)

# ============== Upload imagem de contexto → Supabase =============
def _slugify_filename(name: str) -> str:
    base, ext = os.path.splitext((name or "image").lower())
    base = ''.join(c for c in unicodedata.normalize('NFD', base) if unicodedata.category(c) != 'Mn')
    base = re.sub(r'[^a-z0-9]+', '_', base).strip('_')
    ext  = re.sub(r'[^.a-z0-9]', '', ext) or '.png'
    return f"{base}{ext}"

@app.post("/upload/context-image")
def upload_context_image():
    """
    Multipart form:
      - file: binário
      - avatar_id: UUID ou name (será resolvido para UUID)
      - contexto: nome do contexto (string)
      - keywords: texto livre (ex: "pizza, cardapio, menu")
      - media_type: 'image' ou 'video' (default 'image')
    """
    try:
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "no_file"}), 400

        avatar_in = (request.form.get("avatar_id") or "").strip()
        contexto   = (request.form.get("contexto") or "").strip()
        keywords   = (request.form.get("keywords") or "").strip()
        media_type = (request.form.get("media_type") or "image").strip().lower()
        if media_type not in ("image", "video"):
            media_type = "image"

        if not avatar_in or not contexto:
            return jsonify({"ok": False, "error": "missing_params"}), 400

        avatar_uuid = resolve_avatar_uuid(avatar_in)
        if not avatar_uuid:
            return jsonify({"ok": False, "error": "avatar_not_found"}), 404

        f = request.files["file"]
        orig = f.filename or "media.bin"

        def normalize_name(name: str) -> str:
            name = name.lower()
            name = "".join(c for c in unicodedata.normalize("NFD", name) if unicodedata.category(c) != "Mn")
            name = re.sub(r"[^a-z0-9._-]+", "_", name)
            name = re.sub(r"_+", "_", name).strip("_")
            return name or f"file_{_uuid.uuid4().hex}"
        fname = normalize_name(orig)

        # caminho no bucket (AGORA usa o SUPABASE_BUCKET do .env)
        bucket = SUPABASE_BUCKET
        path = f"{avatar_uuid}/training/{fname}"

        # ===== Upload para Storage com Service Role + upsert =====
        up_url = f"{SUPABASE_URL}/storage/v1/object/{bucket}/{path}"
        storage_headers = {
            **H_SUPABASE,
            "Content-Type": f.mimetype or "application/octet-stream",
            "x-upsert": "true"
        }
        bin_data = f.stream.read()
        r = requests.post(up_url, headers=storage_headers, data=bin_data, timeout=120)
        if not r.ok:
            # dica de erro clara (RLS/credencial/bucket)
            hint = r.text[:300]
            if r.status_code == 403:
                hint += " | DICA: 403 em Storage geralmente é RLS/policy ou uso de ANON KEY. No servidor, use SUPABASE_SERVICE_ROLE."
            return jsonify({"ok": False, "error": f"storage_{r.status_code}: {hint}"}), 502

        public_url = f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{path}"

        # verifica se já existe contexto com mesmo nome
        rows = sb_get_json("contexts", "id", {"avatar_id": f"eq.{avatar_uuid}", "name": f"eq.{contexto}"}, limit=1)
        if rows:
            # update
            cid = rows[0]["id"]
            url = f"{SUPABASE_URL}/rest/v1/contexts?id=eq.{cid}"
            body = {
                "media_url": public_url,
                "media_type": media_type,
                "keywords_text": keywords,
                "enabled": True,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            u = requests.patch(url, headers={**H_SUPABASE, "Content-Type": "application/json"}, json=body, timeout=30)
            if not u.ok:
                msg = u.text[:300]
                if u.status_code == 403:
                    msg += " | DICA: 403 no REST indica RLS sem permissão; com Service Role isso não deve ocorrer."
                return jsonify({"ok": False, "error": f"update_{u.status_code}: {msg}"}), 502
        else:
            # insert
            url = f"{SUPABASE_URL}/rest/v1/contexts"
            body = [{
                "avatar_id": avatar_uuid,
                "name": contexto,
                "description": "",  # <- adiciona isso (ou algo como "context image upload")
                "media_url": public_url,
                "media_type": media_type,
                "keywords_text": keywords,
                "placement": "bottom_right",
                "size": "medium",
                "enabled": True,
                "created_at": datetime.now(timezone.utc).isoformat()
            }]
            ins = requests.post(url, headers={**H_SUPABASE, "Content-Type": "application/json", "Prefer": "return=representation"}, json=body, timeout=30)
            if not ins.ok:
                msg = ins.text[:300]
                if ins.status_code == 403:
                    msg += " | DICA: 403 no REST indica RLS sem permissão; com Service Role isso não deve ocorrer."
                return jsonify({"ok": False, "error": f"insert_{ins.status_code}: {msg}"}), 502

        return jsonify({"ok": True, "contexto": contexto, "url_imagem": public_url, "avatar_id": avatar_uuid})
    except Exception as e:
        return jsonify({"ok": False, "error": f"upload_exception:{e}"}), 500
import base64, json

def _jwt_role(token: str):
    try:
        payload = token.split('.')[1] + '=='
        return json.loads(base64.urlsafe_b64decode(payload.encode()).decode()).get('role')
    except Exception:
        return None

@app.get("/debug/env")
def debug_env():
    # NÃO loga a chave inteira; só o papel e os últimos 10 chars
    tail = (SUPABASE_SERVICE_KEY[-10:] if SUPABASE_SERVICE_KEY else None)
    return jsonify({
        "app": "server_voice",
        "sb_role": _jwt_role(SUPABASE_SERVICE_KEY),  # deve ser "service_role"
        "bucket": SUPABASE_BUCKET,
        "url": SUPABASE_URL,
        "key_tail": tail,
    })

@app.post("/debug/storage-selftest")
def debug_storage_selftest():
    try:
        up_url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/debug/ping_from_flask.txt"
        r = requests.post(
            up_url,
            headers={
                "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                "apikey": SUPABASE_SERVICE_KEY,
                "x-upsert": "true",
                "Content-Type": "text/plain"
            },
            data=b"hello-from-flask",
            timeout=30
        )
        return jsonify({"ok": r.ok, "status": r.status_code, "text": r.text[:300]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
# ================== Run ============================
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
