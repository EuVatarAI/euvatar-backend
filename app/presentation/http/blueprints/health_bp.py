from flask import Blueprint, jsonify, current_app

bp = Blueprint("health", __name__)

@bp.get("/health")
def health():
    c = current_app.container
    return jsonify({
        "ok": True,
        "has_api_key": True,
        "using_service_role": True,
        "avatar": c.settings.heygen_default_avatar,
        "session_active": bool(c.session.session_id),
        "quality": c.session.quality,
        "ends_at": c.session.ends_at_epoch,
        "bucket": c.settings.supabase_bucket,
        "budget": {
            "credits_per_session": c.budget.credits_per_session,
            "total_credits_spent": c.budget.total_credits_spent,
            "sessions": len(c.budget.sessions)
        }
    })
