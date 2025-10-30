import json
import time
import os
import requests
from flask import Blueprint, request, jsonify, current_app, send_from_directory
from app.core.settings import Settings

from app.application.use_cases.create_session import (
    CreateSessionInput,
    execute as create_session_uc,
    system_prompt,
)
from app.application.use_cases.say_to_avatar import (
    SayInput,
    SayOutput,
    execute as say_uc,
)
from app.application.use_cases.interrupt_session import (
    InterruptInput,
    execute as interrupt_uc,
)
from app.application.use_cases.metrics import build_metrics

bp = Blueprint("session", __name__)

URL_KEEPALIVE = "https://api.heygen.com/v1/streaming.keep_alive"

# ============== helpers de log ==============
def _log(kind: str, msg: str, data=None):
    try:
        if data is None:
            current_app.logger.info("[%s] %s", kind, msg)
        else:
            as_txt = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)[:2000]
            current_app.logger.info("[%s] %s | %s", kind, msg, as_txt)
    except Exception:
        pass


def _http_from_error_code(code: str | None) -> int:
    """
    Códigos para o front:
    - session_inactive -> 410
    - task_in_progress / upstream_bad_request (quando usado como busy) -> 200 (soft busy)
    - demais -> 502
    """
    if code == "session_inactive":
        return 410
    if code in ("task_in_progress", "upstream_bad_request"):
        return 200  # soft busy: não quebra a sessão
    return 502
# ===========================================

@bp.get("/heygen-sdk.umd.js")
def serve_heygen_sdk():
    s = current_app.container.settings
    import os
    path = os.path.join(s.base_dir, "public", "heygen-sdk.umd.js")
    if not os.path.isfile(path):
        return "UMD não encontrado (ok ignorar se você não usa o arquivo). Coloque em public/heygen-sdk.umd.js", 404
    return send_from_directory(s.static_dir, "heygen-sdk.umd.js", mimetype="application/javascript")


@bp.get("/token")
def create_session_token():
    t0 = time.time()
    try:
        token = current_app.container.heygen.create_token()
        _log("TOKEN", "create ok", {"ms": int((time.time()-t0)*1000)})
        return jsonify({"ok": True, "token": token})
    except Exception as e:
        _log("ERR", "token_exception", {"ms": int((time.time()-t0)*1000), "e": str(e)})
        return jsonify({"ok": False, "error": f"token_exception: {e}"}), 500


@bp.get("/new")
def new_session():
    t0 = time.time()
    try:
        c = current_app.container
        language = request.args.get("language", "pt-BR")
        persona  = request.args.get("persona", "default")
        quality  = request.args.get("quality", "low")
        backstory_param = request.args.get("backstory") or ""
        voice_id = request.args.get("voice_id")
        minutes  = float(request.args.get("minutes", "2.5"))

        # >>> DICA (SDK novo): activityIdleTimeout deve ser tratado no client HeyGen (create_session_uc).
        # Garanta no seu IHeygenClient que está usando 'activityIdleTimeout' e NÃO 'disableIdleTimeout'.

        # === modo resume via GET /new?resume=1&session_id=... ===
        resume_flag = request.args.get("resume") == "1"
        resume_id   = request.args.get("session_id")

        if resume_flag:
            sid = resume_id or getattr(getattr(c, "session", None), "session_id", None)
            if not sid:
                return jsonify({"ok": False, "error": "missing_session_id"}), 400

            _log("RESUME", "in(/new)", {"session_id": sid})
            out = create_session_uc(
                c.heygen, c.budget,
                CreateSessionInput(
                    resume_session_id=sid,
                    persona=getattr(getattr(c, "session", None), "persona", persona),
                    language=getattr(getattr(c, "session", None), "language", language),
                    quality=getattr(getattr(c, "session", None), "quality", quality),
                    backstory_param=getattr(getattr(c, "session", None), "backstory", backstory_param),
                    voice_id=voice_id,
                    minutes=minutes,
                    avatar_id=c.settings.heygen_default_avatar,
                )
            )
            if not out.ok:
                _log("ERR", "resume_uc", {"error": out.error, "ms": int((time.time()-t0)*1000)})
                return jsonify({"ok": False, "error": out.error}), 502

            if not getattr(c, "session", None) or c.session.session_id != sid:
                c.session = out.session
            else:
                c.session.token = out.session.token
                c.session.url   = out.session.url

            if not getattr(c.session, "ends_at_epoch", None):
                c.session.ends_at_epoch = int(time.time() + minutes * 60)

            resp = {"ok": True, "session_id": c.session.session_id, "livekit_url": c.session.url, "access_token": c.session.token}
            _log("RESUME", "ok(/new)", {"ms": int((time.time()-t0)*1000), "session": c.session.session_id})
            return jsonify(resp)

        # === fluxo normal: criar sessão nova ===
        _log("NEW", "in", {"language": language, "persona": persona, "quality": quality, "minutes": minutes})

        out = create_session_uc(
            c.heygen, c.budget,
            CreateSessionInput(
                persona=persona, language=language, quality=quality,
                backstory_param=backstory_param, voice_id=voice_id,
                minutes=minutes, avatar_id=c.settings.heygen_default_avatar
            )
        )
        if not out.ok:
            _log("ERR", "create_session_uc", {"error": out.error, "ms": int((time.time()-t0)*1000)})
            return jsonify({"ok": False, "error": out.error}), 502

        c.session = out.session
        c.session.ends_at_epoch = int(time.time() + minutes * 60)

        resp = {"ok": True, "session_id": c.session.session_id, "livekit_url": c.session.url, "access_token": c.session.token}
        _log("NEW", "ok", {"ms": int((time.time()-t0)*1000), "session": c.session.session_id})
        return jsonify(resp)
    except Exception as e:
        _log("ERR", "new_exception", {"ms": int((time.time()-t0)*1000), "e": str(e)})
        return jsonify({"ok": False, "error": f"new_exception: {e}"}), 500



@bp.post("/say")
def say():
    t0 = time.time()
    c = current_app.container
    try:
        data = request.get_json(force=True) or {}
        session_id = data.get("session_id") or getattr(getattr(c, "session", None), "session_id", None)
        text = (data.get("text") or "").strip()
        avatar_id = (data.get("avatar_id") or "").strip()

        _log("SAY", "in", {"session_id": session_id, "text_len": len(text)})

        if not session_id or not text:
            return jsonify({"ok": False, "error": "missing_params"}), 400

        # sessão expirada pelo nosso controle de tempo
        if getattr(c, "session", None) and getattr(c.session, "ends_at_epoch", None):
            if int(time.time()) >= int(c.session.ends_at_epoch):
                _log("SAY", "expired", {"now": int(time.time()), "ends": int(c.session.ends_at_epoch)})
                return jsonify({"ok": False, "error": "session_expired", "error_code": "session_inactive"}), 410

        sys = data.get("system") or system_prompt(getattr(c.session, "backstory", "") or "", getattr(c.session, "language", "pt-BR") or "pt-BR")

        out: SayOutput = say_uc(c.settings, c.heygen, c.ctx_repo, SayInput(c.session, text, sys, avatar_identifier=avatar_id))

        if not out.ok:
            status = _http_from_error_code(out.error_code)
            payload = {
                "ok": False,
                "error": out.error or "say_failed",
                "error_code": out.error_code or "upstream_error",
                "soft_busy": bool(getattr(out, "soft_busy", False))
            }
            _log("ERR", "say_uc", {"ms": int((time.time()-t0)*1000), **payload})
            return jsonify(payload), status

        resp = {
            "ok": True,
            "duration_ms": out.duration_ms,
            "task_id": out.task_id,
            "media": (out.media.__dict__ if out.media else None),
            "context_method": out.context_method
        }
        _log("SAY", "ok", {"ms": int((time.time()-t0)*1000), "task_id": out.task_id, "duration_ms": out.duration_ms})
        return jsonify(resp)
    except Exception as e:
        _log("ERR", "say_exception", {"ms": int((time.time()-t0)*1000), "e": str(e)})
        return jsonify({"ok": False, "error": f"say_exception: {e}"}), 500
    

@bp.route("/keepalive", methods=["POST", "OPTIONS"])
def keepalive():
    """KeepAlive real: chamamos a HeyGen. Se ela disser 'closed/inactive', devolvemos error_code=session_inactive."""
    if request.method == "OPTIONS":
        return jsonify({"ok": True}), 200
    try:
        c = current_app.container
        if not getattr(c, "session", None) or not getattr(c.session, "session_id", None):
            return jsonify({"ok": False, "error": "no_session"}), 200

        sid = c.session.session_id
        # você pode guardar isso no Settings se quiser expor na UI
        idle = getattr(c.settings, "heygen_activity_idle_timeout", 120)
        r = c.heygen.keep_alive(sid, activity_idle_timeout=idle)

        try:
            body = r.json()
        except Exception:
            body = {"message": r.text[:300]}

        error_code = None
        msg = (str(body) or "").lower()
        if r.status_code == 400:
            if "invalid session state" in msg or "closed" in msg or "inactive" in msg or "not found" in msg:
                error_code = "session_inactive"

        current_app.logger.info("[PING] keepalive %s | heygen=%s", sid, r.status_code)
        return jsonify({
            "ok": bool(r.ok),
            "heygen_status": r.status_code,
            "heygen_body": body,
            "error_code": error_code
        }), 200

    except Exception as e:
        return jsonify({"ok": False, "error": f"keepalive_exception: {e}"}), 200

@bp.after_app_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return resp


@bp.post("/resume")
def resume_livekit():
    """Renova token/URL do LiveKit para a MESMA sessão (sem gastar crédito)."""
    t0 = time.time()
    try:
        c = current_app.container
        data = request.get_json(force=True) or {}
        sid = data.get("session_id") or getattr(getattr(c, "session", None), "session_id", None)
        if not sid:
            return jsonify({"ok": False, "error": "missing_session_id"}), 400

        _log("RESUME", "in", {"session_id": sid})

        mins_left = 2.5
        if getattr(c, "session", None) and getattr(c.session, "ends_at_epoch", None):
            left = max(1, int(c.session.ends_at_epoch - time.time()))
            mins_left = max(0.5, left / 60.0)

        out = create_session_uc(
            c.heygen, c.budget,
            CreateSessionInput(
                resume_session_id=sid,
                persona=getattr(getattr(c, "session", None), "persona", "default"),
                language=getattr(getattr(c, "session", None), "language", "pt-BR"),
                quality=getattr(getattr(c, "session", None), "quality", "low"),
                backstory_param=getattr(getattr(c, "session", None), "backstory", ""),
                voice_id=None,
                minutes=mins_left,
                avatar_id=c.settings.heygen_default_avatar
            )
        )
        if not out.ok:
            _log("ERR", "resume_uc", {"error": out.error, "ms": int((time.time()-t0)*1000)})
            return jsonify({"ok": False, "error": out.error}), 502

        if not getattr(c, "session", None) or c.session.session_id != sid:
            c.session = out.session
        else:
            c.session.token = out.session.token
            c.session.url   = out.session.url

        resp = {
            "ok": True,
            "session_id": c.session.session_id,
            "livekit_url": c.session.url,
            "access_token": c.session.token
        }
        _log("RESUME", "ok", {"ms": int((time.time()-t0)*1000), "session": c.session.session_id})
        return jsonify(resp)
    except Exception as e:
        _log("ERR", "resume_exception", {"ms": int((time.time()-t0)*1000), "e": str(e)})
        return jsonify({"ok": False, "error": f"resume_exception: {e}"}), 500


@bp.post("/interrupt")
def interrupt():
    t0 = time.time()
    c = current_app.container
    try:
        session_id = (request.get_json(force=True) or {}).get("session_id") or getattr(getattr(c, "session", None), "session_id", None)
        if not session_id:
            return jsonify({"ok": False, "error": "missing_session_id"}), 400
        interrupt_uc(c.heygen, InterruptInput(session_id))
        _log("INT", "ok", {"ms": int((time.time()-t0)*1000)})
        return jsonify({"ok": True})
    except Exception as e:
        _log("ERR", "interrupt_exception", {"ms": int((time.time()-t0)*1000), "e": str(e)})
        return jsonify({"ok": False, "error": f"interrupt_exception: {e}"}), 500


@bp.post("/end")
def end():
    c = current_app.container
    try:
        c.session = type(c.session)()  # reset
    except Exception:
        pass
    _log("END", "ok")
    return jsonify({"ok": True})


@bp.get("/metrics")
def metrics():
    c = current_app.container
    return jsonify(build_metrics(c.session, c.budget))
