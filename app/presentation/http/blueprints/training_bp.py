from flask import Blueprint, request, jsonify, current_app
import requests
from app.application.use_cases.upload_training_doc import (
    execute as upload_training_uc,
    UploadTrainingDocInput,
)

bp = Blueprint("training", __name__)


@bp.post("/training/upload")
def training_upload():
    c = current_app.container
    try:
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "no_file"}), 400

        avatar_in = (request.form.get("avatar_id") or "").strip()
        title = (request.form.get("title") or "").strip() or None
        if not avatar_in:
            return jsonify({"ok": False, "error": "missing_avatar_id"}), 400

        f = request.files["file"]
        max_bytes = c.settings.upload_max_mb * 1024 * 1024
        data = f.stream.read()
        if len(data) > max_bytes:
            return jsonify({"ok": False, "error": "file_too_large"}), 413
        out, status = upload_training_uc(
            c.settings,
            c.storage,
            c.ctx_repo,
            UploadTrainingDocInput(
                avatar_identifier=avatar_in,
                filename=f.filename or "document.bin",
                content_type=(f.mimetype or "application/octet-stream"),
                data=data,
                title=title,
            ),
        )
        return jsonify(out), status
    except Exception as e:
        return jsonify({"ok": False, "error": f"training_upload_exception:{e}"}), 500


@bp.get("/training/list")
def training_list():
    c = current_app.container
    try:
        avatar_id = (request.args.get("avatar_id") or "").strip()
        if not avatar_id:
            return jsonify({"ok": False, "error": "missing_avatar_id"}), 400

        avatar_uuid = c.ctx_repo.resolve_avatar_uuid(avatar_id)
        if not avatar_uuid:
            return jsonify({"ok": False, "error": "avatar_not_found"}), 404
        docs = c.ctx_repo.list_training_docs_by_avatar(avatar_uuid)
        data = [
            {
                "id": d.id,
                "name": d.name,
                "url": d.url,
                "created_at": d.created_at,
            }
            for d in docs
        ]
        return jsonify({"ok": True, "avatar_id": avatar_uuid, "items": data})
    except Exception as e:
        return jsonify({"ok": False, "error": f"training_list_exception:{e}"}), 500


@bp.post("/training/delete")
def training_delete():
    c = current_app.container
    try:
        data = request.get_json(force=True) or {}
        doc_id = (data.get("doc_id") or data.get("id") or "").strip()
        doc_url = (data.get("doc_url") or data.get("url") or "").strip()

        if not doc_id:
            return jsonify({"ok": False, "error": "missing_doc_id"}), 400

        # remove file from storage if we can parse it
        if doc_url and "/storage/v1/object/public/" in doc_url:
            try:
                marker = "/storage/v1/object/public/"
                after = doc_url.split(marker, 1)[1]
                bucket, path = after.split("/", 1)
                del_url = f"{c.settings.supabase_url}/storage/v1/object/{bucket}/{path}"
                requests.delete(
                    del_url,
                    headers={
                        "Authorization": f"Bearer {c.settings.supabase_service_role}",
                        "apikey": c.settings.supabase_service_role,
                    },
                    timeout=30,
                )
            except Exception:
                pass

        # delete row from training_docs
        del_row_url = f"{c.settings.supabase_url}/rest/v1/training_docs"
        resp = requests.delete(
            del_row_url,
            headers={
                "Authorization": f"Bearer {c.settings.supabase_service_role}",
                "apikey": c.settings.supabase_service_role,
            },
            params={"id": f"eq.{doc_id}"},
            timeout=30,
        )
        if not resp.ok:
            return jsonify({"ok": False, "error": "delete_failed", "details": resp.text[:200]}), 502

        return jsonify({"ok": True}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": f"training_delete_exception:{e}"}), 500
