"""Transcribe stand-in: records the job request and does nothing else (simulated)."""
from __future__ import annotations

from . import append

simulated = True


class TranscribeSim:
    def __init__(self):
        self.jobs: list[dict] = []

    def start_transcription_job(self, **kw) -> dict:
        self.jobs.append(kw)
        append("transcribe", {"job": kw["TranscriptionJobName"], "language": kw.get("LanguageCode")})
        return {"TranscriptionJob": {"TranscriptionJobName": kw["TranscriptionJobName"],
                                     "TranscriptionJobStatus": "IN_PROGRESS"}}
