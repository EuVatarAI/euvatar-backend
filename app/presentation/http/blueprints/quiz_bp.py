"""Phase-1 production quiz endpoints (experience resolve + credential create)."""

from __future__ import annotations

import uuid
import os
from flask import Blueprint, current_app, jsonify, request

from app.infrastructure.supabase_rest import get_json, rest_headers
from app.shared.setup_logger import LOGGER
import requests

bp = Blueprint("quiz_phase1", __name__)
logger = LOGGER.get_logger(__name__)

_ALLOWED_MODES = {"mobile", "totem", "auto"}
_ALLOWED_UPLOAD_TYPES = {"user_photo", "video", "asset"}
_ALLOWED_GENERATION_KINDS = {"credential_card", "quiz_result", "photo_with"}
_MAX_UPLOAD_SIZE_BYTES_BY_TYPE = {
    "user_photo": int(os.getenv("QUIZ_MAX_USER_PHOTO_MB", "20"))
    * 1024
    * 1024,  # default 20 MB
    "video": 100 * 1024 * 1024,  # 100 MB
    "asset": 20 * 1024 * 1024,  # 20 MB
}


def _as_clean_str(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _is_eager_generation_enabled() -> bool:
    return os.getenv("QUIZ_EAGER_GENERATION_ON_UPLOAD", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _validate_gemini_key_against_model(
    api_key: str, model: str
) -> tuple[bool, str | None]:
    key = (api_key or "").strip()
    mdl = (model or "").strip()
    if not key:
        return False, "missing_api_key"
    if not mdl:
        return False, "missing_model"

    # Lightweight validation endpoint: checks both key validity and model access.
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}"
    try:
        r = requests.get(url, params={"key": key}, timeout=15)
    except requests.RequestException:
        return False, "gemini_unreachable"

    if r.status_code == 200:
        return True, None
    if r.status_code in (401, 403):
        return False, "gemini_key_invalid_or_forbidden"
    if r.status_code == 404:
        return False, "gemini_model_unavailable"
    if r.status_code == 429:
        return False, "gemini_quota_exceeded"
    return False, f"gemini_http_{r.status_code}"


def _load_active_experience_by_slug(slug: str) -> dict | None:
    c = current_app.container
    rows = get_json(
        c.settings,
        "experiences",
        "id,type,status,config_json",
        {"slug": f"eq.{slug}", "status": "in.(active,published)"},
        limit=1,
    )
    return rows[0] if rows else None


def _load_active_experience_by_id(experience_id: str) -> dict | None:
    c = current_app.container
    rows = get_json(
        c.settings,
        "experiences",
        "id,status",
        {"id": f"eq.{experience_id}", "status": "in.(active,published)"},
        limit=1,
    )
    return rows[0] if rows else None


def _load_experience_by_id(experience_id: str) -> dict | None:
    c = current_app.container
    rows = get_json(
        c.settings,
        "experiences",
        "id,type,status,max_generations",
        {"id": f"eq.{experience_id}"},
        limit=1,
    )
    return rows[0] if rows else None


def _load_credential_for_experience(
    credential_id: str, experience_id: str
) -> dict | None:
    c = current_app.container
    rows = get_json(
        c.settings,
        "credentials",
        "id,experience_id",
        {"id": f"eq.{credential_id}", "experience_id": f"eq.{experience_id}"},
        limit=1,
    )
    return rows[0] if rows else None


def _count_done_generations(experience_id: str) -> int:
    c = current_app.container
    rows = get_json(
        c.settings,
        "generations",
        "id",
        {"experience_id": f"eq.{experience_id}", "status": "eq.done"},
    )
    return len(rows)


def _kind_from_experience_type(experience_type: str) -> str:
    t = (experience_type or "").strip().lower()
    if t == "credentialing":
        return "credential_card"
    if t == "photo_with":
        return "photo_with"
    return "quiz_result"


def _find_reusable_generation(credential_id: str, kind: str) -> dict | None:
    c = current_app.container
    rows = get_json(
        c.settings,
        "generations",
        "id,status,kind,credential_id,experience_id",
        {
            "credential_id": f"eq.{credential_id}",
            "kind": f"eq.{kind}",
            "status": "in.(pending,processing,done)",
            "order": "created_at.desc",
        },
        limit=1,
    )
    return rows[0] if rows else None


def _insert_generation(experience_id: str, credential_id: str, kind: str) -> str:
    c = current_app.container
    url = f"{c.settings.supabase_url}/rest/v1/generations"
    r = requests.post(
        url,
        headers={
            **rest_headers(c.settings),
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        json=[
            {
                "experience_id": experience_id,
                "credential_id": credential_id,
                "kind": kind,
                "status": "pending",
            }
        ],
        timeout=20,
    )
    if not r.ok:
        raise RuntimeError(f"generation_insert_failed:{r.text[:180]}")
    rows = r.json() or []
    if not rows or not rows[0].get("id"):
        raise RuntimeError("generation_insert_empty")
    return str(rows[0]["id"])


def _create_or_reuse_generation(
    experience_id: str, credential_id: str, kind: str
) -> tuple[str, bool]:
    reusable = _find_reusable_generation(credential_id, kind)
    if reusable and reusable.get("id"):
        gid = str(reusable["id"])
        logger.info(
            "[quiz] reuse_generation generation_id=%s credential_id=%s kind=%s status=%s",
            gid,
            credential_id,
            kind,
            str(reusable.get("status") or ""),
        )
        return gid, True

    generation_id = _insert_generation(experience_id, credential_id, kind)
    logger.info(
        "[quiz] create_generation generation_id=%s credential_id=%s kind=%s",
        generation_id,
        credential_id,
        kind,
    )
    return generation_id, False


def _build_signed_download_url(storage_path: str, expires_in: int = 600) -> str | None:
    c = current_app.container
    bucket = c.settings.supabase_bucket
    sign_url = (
        f"{c.settings.supabase_url}/storage/v1/object/sign/{bucket}/{storage_path}"
    )
    r = requests.post(
        sign_url,
        headers={**rest_headers(c.settings), "Content-Type": "application/json"},
        json={"expiresIn": max(60, int(expires_in))},
        timeout=20,
    )
    if not r.ok:
        return None
    data = r.json() or {}
    signed = data.get("signedURL") or data.get("signedUrl") or data.get("url")
    if not signed and data.get("path") and data.get("token"):
        path = str(data.get("path"))
        token = str(data.get("token"))
        signed = f"/object/sign/{bucket}/{path}?token={token}"
    if not signed:
        return None
    return (
        signed
        if str(signed).startswith("http")
        else f"{c.settings.supabase_url}/storage/v1{signed}"
    )


@bp.get("/public/experience/<slug>")
def public_experience(slug: str):
    try:
        s = (slug or "").strip()
        if not s:
            return jsonify({"ok": False, "error": "missing_slug"}), 400

        exp = _load_active_experience_by_slug(s)
        if not exp:
            return (
                jsonify({"ok": False, "error": "experience_not_found_or_inactive"}),
                404,
            )

        return (
            jsonify(
                {
                    "ok": True,
                    "experience_id": exp.get("id"),
                    "type": exp.get("type"),
                    "config_json": exp.get("config_json") or {},
                }
            ),
            200,
        )
    except Exception as exc:
        return (
            jsonify({"ok": False, "error": f"public_experience_exception:{exc}"}),
            500,
        )


@bp.post("/gemini/validate-key")
def validate_gemini_key():
    try:
        payload = request.get_json(force=True) or {}
        api_key = (payload.get("api_key") or "").strip()
        model = (payload.get("model") or "gemini-2.5-flash-image").strip()

        valid, err = _validate_gemini_key_against_model(api_key, model)
        if not valid:
            return (
                jsonify(
                    {
                        "ok": False,
                        "valid": False,
                        "error": err or "gemini_validation_failed",
                    }
                ),
                400,
            )

        return jsonify({"ok": True, "valid": True, "model": model}), 200
    except Exception as exc:
        return (
            jsonify(
                {
                    "ok": False,
                    "valid": False,
                    "error": f"gemini_validate_exception:{exc}",
                }
            ),
            500,
        )


@bp.post("/credentials")
def create_credential():
    c = current_app.container
    try:
        payload = request.get_json(force=True) or {}
        experience_id = (payload.get("experience_id") or "").strip()
        data = payload.get("data") or {}
        mode_used = (payload.get("mode_used") or "").strip().lower()

        if not experience_id:
            return jsonify({"ok": False, "error": "missing_experience_id"}), 400
        if not isinstance(data, dict):
            return jsonify({"ok": False, "error": "invalid_data_payload"}), 400
        if mode_used not in _ALLOWED_MODES:
            return jsonify({"ok": False, "error": "invalid_mode_used"}), 400

        if not _load_active_experience_by_id(experience_id):
            return (
                jsonify({"ok": False, "error": "experience_not_found_or_inactive"}),
                404,
            )

        url = f"{c.settings.supabase_url}/rest/v1/credentials"
        req_rows = [
            {
                "experience_id": experience_id,
                "data_json": data,
                "mode_used": mode_used,
            }
        ]
        r = requests.post(
            url,
            headers={
                **rest_headers(c.settings),
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            json=req_rows,
            timeout=20,
        )
        if not r.ok:
            return (
                jsonify(
                    {"ok": False, "error": f"credential_insert_failed:{r.text[:180]}"}
                ),
                502,
            )

        rows = r.json() or []
        if not rows or not rows[0].get("id"):
            return jsonify({"ok": False, "error": "credential_insert_empty"}), 502

        return jsonify({"ok": True, "credential_id": rows[0]["id"]}), 201
    except Exception as exc:
        return (
            jsonify({"ok": False, "error": f"create_credential_exception:{exc}"}),
            500,
        )


@bp.post("/uploads/signed-url")
def create_signed_upload_url():
    c = current_app.container
    try:
        payload = request.get_json(force=True) or {}
        experience_id = (payload.get("experience_id") or "").strip()
        upload_type = (payload.get("type") or "").strip().lower()
        file_size_bytes = payload.get("file_size_bytes")

        if not experience_id:
            return jsonify({"ok": False, "error": "missing_experience_id"}), 400
        if upload_type not in _ALLOWED_UPLOAD_TYPES:
            return jsonify({"ok": False, "error": "invalid_upload_type"}), 400

        if file_size_bytes is not None:
            try:
                file_size_bytes = int(file_size_bytes)
            except Exception:
                return jsonify({"ok": False, "error": "invalid_file_size"}), 400
            if file_size_bytes <= 0:
                return jsonify({"ok": False, "error": "invalid_file_size"}), 400
            if file_size_bytes > _MAX_UPLOAD_SIZE_BYTES_BY_TYPE[upload_type]:
                return jsonify({"ok": False, "error": "file_too_large"}), 413

        if not _load_active_experience_by_id(experience_id):
            return (
                jsonify({"ok": False, "error": "experience_not_found_or_inactive"}),
                404,
            )

        ext_by_type = {"user_photo": "jpg", "video": "mp4", "asset": "bin"}
        storage_path = f"quiz/{experience_id}/{upload_type}/{uuid.uuid4().hex}.{ext_by_type[upload_type]}"
        bucket = c.settings.supabase_bucket

        sign_url = f"{c.settings.supabase_url}/storage/v1/object/upload/sign/{bucket}/{storage_path}"
        r = requests.post(
            sign_url,
            headers={**rest_headers(c.settings), "Content-Type": "application/json"},
            json={"expiresIn": 600},
            timeout=20,
        )
        if not r.ok:
            return (
                jsonify({"ok": False, "error": f"signed_url_failed:{r.text[:180]}"}),
                502,
            )

        data = r.json() or {}
        signed_url = (
            data.get("signedURL")
            or data.get("signedUrl")
            or data.get("uploadURL")
            or data.get("upload_url")
        )
        if not signed_url and data.get("url") and data.get("token"):
            base_url = str(data.get("url"))
            token = str(data.get("token"))
            if "token=" in base_url:
                signed_url = base_url
            else:
                sep = "&" if "?" in base_url else "?"
                signed_url = f"{base_url}{sep}token={token}"
        if not signed_url:
            return (
                jsonify({"ok": False, "error": "signed_url_missing_in_response"}),
                502,
            )
        upload_url = (
            signed_url
            if str(signed_url).startswith("http")
            else f"{c.settings.supabase_url}/storage/v1{signed_url}"
        )

        return (
            jsonify(
                {"ok": True, "upload_url": upload_url, "storage_path": storage_path}
            ),
            200,
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": f"signed_url_exception:{exc}"}), 500


@bp.post("/uploads/confirm")
def confirm_upload():
    c = current_app.container
    try:
        payload = request.get_json(force=True) or {}
        experience_id = (payload.get("experience_id") or "").strip()
        credential_id = (payload.get("credential_id") or "").strip()
        storage_path = (payload.get("storage_path") or "").strip()
        upload_type = (payload.get("type") or "user_photo").strip().lower()

        if not experience_id:
            return jsonify({"ok": False, "error": "missing_experience_id"}), 400
        if not credential_id:
            return jsonify({"ok": False, "error": "missing_credential_id"}), 400
        if not storage_path:
            return jsonify({"ok": False, "error": "missing_storage_path"}), 400
        if upload_type not in _ALLOWED_UPLOAD_TYPES:
            return jsonify({"ok": False, "error": "invalid_upload_type"}), 400

        if not _load_active_experience_by_id(experience_id):
            return (
                jsonify({"ok": False, "error": "experience_not_found_or_inactive"}),
                404,
            )
        if not _load_credential_for_experience(credential_id, experience_id):
            return (
                jsonify({"ok": False, "error": "credential_not_found_for_experience"}),
                404,
            )
        if not storage_path.startswith(f"quiz/{experience_id}/"):
            return jsonify({"ok": False, "error": "invalid_storage_path_scope"}), 400

        uploads_url = f"{c.settings.supabase_url}/rest/v1/uploads"
        up_resp = requests.post(
            uploads_url,
            headers={**rest_headers(c.settings), "Content-Type": "application/json"},
            json=[
                {
                    "experience_id": experience_id,
                    "credential_id": credential_id,
                    "type": upload_type,
                    "storage_path": storage_path,
                }
            ],
            timeout=20,
        )
        if not up_resp.ok:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": f"upload_audit_insert_failed:{up_resp.text[:180]}",
                    }
                ),
                502,
            )

        generation_id: str | None = None
        if upload_type == "user_photo":
            cred_patch_url = (
                f"{c.settings.supabase_url}/rest/v1/credentials?id=eq.{credential_id}"
            )
            patch_resp = requests.patch(
                cred_patch_url,
                headers={
                    **rest_headers(c.settings),
                    "Content-Type": "application/json",
                },
                json={"photo_path": storage_path},
                timeout=20,
            )
            if not patch_resp.ok:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": f"credential_photo_update_failed:{patch_resp.text[:180]}",
                        }
                    ),
                    502,
                )

            if _is_eager_generation_enabled():
                try:
                    exp = _load_experience_by_id(experience_id)
                    if exp and str(exp.get("status") or "").strip().lower() in {
                        "active",
                        "published",
                    }:
                        max_generations = int(exp.get("max_generations") or 0)
                        if (
                            max_generations > 0
                            and _count_done_generations(experience_id)
                            >= max_generations
                        ):
                            logger.warning(
                                "[quiz] eager_generation_skipped_limit experience_id=%s credential_id=%s",
                                experience_id,
                                credential_id,
                            )
                        else:
                            kind = _kind_from_experience_type(
                                str(exp.get("type") or "")
                            )
                            generation_id, reused = _create_or_reuse_generation(
                                experience_id, credential_id, kind
                            )
                            logger.info(
                                "[quiz] eager_generation_started generation_id=%s credential_id=%s reused=%s",
                                generation_id,
                                credential_id,
                                reused,
                            )
                except Exception as eager_exc:
                    logger.error(
                        "[quiz] eager_generation_failed experience_id=%s credential_id=%s error=%s",
                        experience_id,
                        credential_id,
                        str(eager_exc),
                    )

        return jsonify({"ok": True, "generation_id": generation_id}), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": f"confirm_upload_exception:{exc}"}), 500


@bp.post("/generations")
def create_generation():
    c = current_app.container
    try:
        payload = request.get_json(force=True) or {}
        experience_id = _as_clean_str(payload.get("experience_id"))
        credential_id = _as_clean_str(payload.get("credential_id"))
        kind_in = _as_clean_str(payload.get("kind")).lower()

        if not experience_id:
            return jsonify({"ok": False, "error": "missing_experience_id"}), 400
        if not credential_id:
            return jsonify({"ok": False, "error": "missing_credential_id"}), 400

        exp = _load_experience_by_id(experience_id)
        if not exp or str(exp.get("status") or "").strip().lower() not in {
            "active",
            "published",
        }:
            return (
                jsonify({"ok": False, "error": "experience_not_found_or_inactive"}),
                404,
            )
        if not _load_credential_for_experience(credential_id, experience_id):
            return (
                jsonify({"ok": False, "error": "credential_not_found_for_experience"}),
                404,
            )

        max_generations = int(exp.get("max_generations") or 0)
        if (
            max_generations > 0
            and _count_done_generations(experience_id) >= max_generations
        ):
            return jsonify({"ok": False, "error": "generation_limit_exceeded"}), 429

        kind = kind_in or _kind_from_experience_type(str(exp.get("type") or ""))
        if kind not in _ALLOWED_GENERATION_KINDS:
            return jsonify({"ok": False, "error": "invalid_generation_kind"}), 400

        generation_id, reused = _create_or_reuse_generation(
            experience_id, credential_id, kind
        )
        status = 200 if reused else 201
        return (
            jsonify({"ok": True, "generation_id": generation_id, "reused": reused}),
            status,
        )
    except Exception as exc:
        logger.error(
            "[quiz] create_generation_exception experience_id=%s credential_id=%s error=%s",
            (request.get_json(silent=True) or {}).get("experience_id"),
            (request.get_json(silent=True) or {}).get("credential_id"),
            str(exc),
        )
        return (
            jsonify({"ok": False, "error": f"create_generation_exception:{exc}"}),
            500,
        )


@bp.get("/generations/<generation_id>")
def get_generation_status(generation_id: str):
    try:
        gid = (generation_id or "").strip()
        if not gid:
            return jsonify({"ok": False, "error": "missing_generation_id"}), 400

        c = current_app.container
        rows = get_json(
            c.settings,
            "generations",
            "id,status,output_path,output_url,error_message,duration_ms,cost_estimated_usd,cost_currency",
            {"id": f"eq.{gid}"},
            limit=1,
        )
        if not rows:
            return jsonify({"ok": False, "error": "generation_not_found"}), 404

        row = rows[0]
        output_url = row.get("output_url")
        if row.get("status") == "done" and not output_url and row.get("output_path"):
            output_url = _build_signed_download_url(
                str(row.get("output_path")), expires_in=900
            )
        return (
            jsonify(
                {
                    "ok": True,
                    "status": row.get("status"),
                    "duration_ms": row.get("duration_ms"),
                    "output_url": output_url,
                    "cost_estimated_usd": row.get("cost_estimated_usd"),
                    "cost_currency": row.get("cost_currency") or "USD",
                    "error_message": row.get("error_message"),
                }
            ),
            200,
        )
    except Exception as exc:
        return (
            jsonify({"ok": False, "error": f"generation_status_exception:{exc}"}),
            500,
        )


@bp.get("/generations/<generation_id>/logs")
def get_generation_logs(generation_id: str):
    """
    Returns structured worker logs for a generation (if generation_logs table exists).
    """
    try:
        gid = (generation_id or "").strip()
        if not gid:
            return jsonify({"ok": False, "error": "missing_generation_id"}), 400

        c = current_app.container
        rows = get_json(
            c.settings,
            "generation_logs",
            "id,generation_id,level,event,message,payload_json,created_at",
            {"generation_id": f"eq.{gid}", "order": "created_at.asc"},
        )
        return jsonify({"ok": True, "generation_id": gid, "logs": rows}), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": f"generation_logs_exception:{exc}"}), 500
