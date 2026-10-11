import json
import re
from pathlib import Path

import pytest

from aurasenior import aws, sim, store, transcribe
from aurasenior.handlers import inbound
from aurasenior.sim.converse import ScriptedConverse, end_turn, tool_use
from events import transcribe_done, wa_audio

ELDER = "+910000000001"
FIX = Path(__file__).parent / "fixtures" / "transcribe"


@pytest.fixture
def bucket(sample):
    transcribe.reset_sim()
    s3 = aws.client("s3")
    s3.create_bucket(Bucket="aurasenior-media-test")
    yield s3
    transcribe.reset_sim()


def _put_transcript(s3, job, text=None, fixture="hindi_reply.json"):
    data = json.loads((FIX / fixture).read_text(encoding="utf-8"))
    if text is not None:
        data["results"]["transcripts"] = [{"transcript": text}]
    s3.put_object(Bucket="aurasenior-media-test", Key=f"transcripts/{job}.json", Body=json.dumps(data).encode())


def test_job_name_is_valid_for_long_ids_with_equals():
    name = transcribe.job_name("sample01", "wamid." + "A=" * 120)
    assert len(name) <= 200 and re.fullmatch(r"[0-9a-zA-Z._-]+", name)


def test_completion_runs_the_turn_and_replies_by_voice(bucket, sample):
    inbound.handler(wa_audio(ELDER, "wamid.V1=="))
    job = transcribe.job_name(sample, "wamid.V1==")
    assert transcribe.client().jobs[0]["MediaFormat"] == "ogg"
    assert transcribe.client().jobs[0]["LanguageCode"] == "hi-IN"
    _put_transcript(bucket, job)
    aws.override("bedrock-runtime", ScriptedConverse([
        tool_use("log_medicine", {"medicine_id": "sugar", "taken": True, "out_of_stock": False}),
        end_turn("ठीक है।")]))
    inbound.handler(transcribe_done("evb-1", job))
    reply = sim.read("whatsapp")[-1]
    assert reply["kind"] == "voice" and reply["text"] == "ठीक है।"
    assert store.query_prefix(sample, "SIGNAL#")
    assert store.query_prefix(sample, "LOG#")


def test_whole_transcript_stop_opts_out(bucket, sample):
    inbound.handler(wa_audio(ELDER, "wamid.V2"))
    job = transcribe.job_name(sample, "wamid.V2")
    _put_transcript(bucket, job, text="बंद।")
    aws.override("bedrock-runtime", ScriptedConverse([]))
    inbound.handler(transcribe_done("evb-2", job))
    assert store.get_person(sample, "kamala").consent_status("whatsapp") == "opted_out"
    assert sim.read("whatsapp")[-1]["phrase_key"] == "stop_confirm"


def test_failed_job_sends_not_heard(bucket, sample, capsys):
    inbound.handler(wa_audio(ELDER, "wamid.V3"))
    job = transcribe.job_name(sample, "wamid.V3")
    inbound.handler(transcribe_done("evb-3", job, status="FAILED"))
    assert sim.read("whatsapp")[-1]["phrase_key"] == "not_heard"
    assert '"ERROR"' in capsys.readouterr().out


def test_unknown_job_is_ignored(bucket, sample):
    inbound.handler(transcribe_done("evb-4", "aurasenior-other-123"))
    assert sim.read("whatsapp") == []


def test_large_media_asks_for_voice_note(bucket, sample):
    store.set_wa_inbound(sample, "kamala")
    inbound.handler(wa_audio(ELDER, "wamid.V5", size=20 * 1024 * 1024))
    assert sim.read("whatsapp")[-1]["phrase_key"] == "send_voice_note"
