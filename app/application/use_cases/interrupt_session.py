"""Use-case to interrupt or stop a session."""

from dataclasses import dataclass
from app.domain.ports import IHeygenClient

@dataclass
class InterruptInput:
    session_id: str

def execute(heygen: IHeygenClient, args: InterruptInput) -> dict:
    heygen.interrupt(args.session_id)
    return {"ok": True}
