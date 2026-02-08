"""Health and readiness endpoints."""

from flask import Blueprint, jsonify, current_app, request, g

bp = Blueprint("health", __name__)

@bp.get("/health")
def health():
    c = current_app.container
    client_id = getattr(g, "client_id", None) or "default"
    session = c.get_session(client_id)
    budget = c.get_budget(client_id)
    return jsonify({
        "ok": True,
        "has_api_key": True,
        "using_service_role": True,
        "avatar": c.settings.heygen_default_avatar,
        "session_active": bool(session.session_id),
        "quality": session.quality,
        "ends_at": session.ends_at_epoch,
        "bucket": c.settings.supabase_bucket,
        "budget": {
            "credits_per_session": budget.credits_per_session,
            "total_credits_spent": budget.total_credits_spent,
            "sessions": len(budget.sessions)
        }
    })
