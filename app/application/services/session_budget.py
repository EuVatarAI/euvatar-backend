from datetime import datetime, timezone
from app.domain.models import LiveSession, BudgetLedger

def debit_session_and_track(ledger: BudgetLedger, s: LiveSession, minutes: float):
    ledger.total_credits_spent += ledger.credits_per_session
    ledger.sessions.append({
        "session_id": s.session_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "minutes_planned": minutes,
        "credits_debited": ledger.credits_per_session,
        "quality": s.quality,
        "language": s.language
    })
