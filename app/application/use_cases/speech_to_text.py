"""Use-case for speech-to-text transcription."""

from dataclasses import dataclass
from app.domain.ports import ISTTClient


@dataclass
class STTInput:
    filename: str
    stream: any
    mimetype: str

def execute(stt: ISTTClient, args: STTInput) -> dict:
    text = stt.transcribe(args.filename, args.stream, args.mimetype)
    return {"ok": True, "text": text}
