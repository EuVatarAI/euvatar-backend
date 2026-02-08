"""Use-case for computing usage and credit metrics."""

from ...domain.models import LiveSession, BudgetLedger

def build_metrics(session: LiveSession, ledger: BudgetLedger) -> dict:
    import time
    elapsed = max(0, (session.ends_at_epoch - int(time.time()))) if session.ends_at_epoch else 0
    return {"ok": True, "session_active": bool(session.session_id),
            "ends_at": session.ends_at_epoch, "seconds_left": elapsed,
            "budget": {"credits_per_session": ledger.credits_per_session,
                       "total_credits_spent": ledger.total_credits_spent,
                       "sessions": ledger.sessions}}
