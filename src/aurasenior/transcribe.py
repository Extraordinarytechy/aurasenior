"""Voice note transcription with Amazon Transcribe batch jobs (word timings feed the voice signals)."""
from __future__ import annotations

import hashlib
import json
import os

from . import aws, channels, config, languages, store
from .models import Person
from .sim.transcribe import TranscribeSim

MAX_MEDIA = 16 * 1024 * 1024
_sim: TranscribeSim | None = None


def client():
    global _sim
    if config.mode("transcribe") == "sim":
        if _sim is None:
            _sim = TranscribeSim()
        return _sim
    return aws.client("transcribe")


def reset_sim() -> None:
    global _sim
    _sim = None


def job_name(hid: str, wamid: str) -> str:
    # The raw WhatsApp id is long and may contain "=", which the job name pattern does not allow.
    return f"aurasenior-{hid}-{hashlib.sha256(wamid.encode()).hexdigest()[:32]}"


def bucket() -> str:
    return os.environ.get("MEDIA_BUCKET", "")


def start(person: Person, wamid: str, media_id: str) -> str:
    hid = person.household_id
    job = job_name(hid, wamid)
    adapter = channels.get("whatsapp")
    key = f"in/{hid}/{hashlib.sha256(wamid.encode()).hexdigest()[:16]}.ogg"
    if hasattr(adapter, "fetch_media"):
        key = adapter.fetch_media(media_id, hid, hashlib.sha256(wamid.encode()).hexdigest()[:16])
    client().start_transcription_job(
        TranscriptionJobName=job, LanguageCode=languages.row(person.language).transcribe_code, MediaFormat="ogg",
        Media={"MediaFileUri": f"s3://{bucket()}/{key}"}, OutputBucketName=bucket(), OutputKey=f"transcripts/{job}.json")
    store.put_tjob(job, hid, person.person_id, wamid)
    store.put_msg(hid, wamid, channel="whatsapp", person_id=person.person_id, correlation_id=wamid, direction="in",
                  transcribe_job=job)
    store.trace(hid, "transcribe", outcome="started", person_id=person.person_id,
                simulated=config.mode("transcribe") == "sim")
    return job


def read_transcript(job: str) -> dict:
    obj = aws.client("s3").get_object(Bucket=bucket(), Key=f"transcripts/{job}.json")
    return json.loads(obj["Body"].read())


def text_of(data: dict) -> str:
    return " ".join(t.get("transcript", "") for t in data.get("results", {}).get("transcripts", [])).strip()
