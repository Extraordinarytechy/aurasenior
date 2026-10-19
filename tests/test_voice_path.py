import json
import re
from pathlib import Path

import pytest

from aurasenior import aws, clock, router, sim, store, transcribe
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


def test_spoken_bare_yes_after_the_check_in_logs_the_tablet_and_answers_by_voice(bucket, sample):
    from aurasenior.handlers import scheduled

    store.set_wa_inbound(sample, "kamala")
    scheduled.run_checkin(sample, {}, "2026-10-12", "checkin#v")
    inbound.handler(wa_audio(ELDER, "wamid.V8"))
    job = transcribe.job_name(sample, "wamid.V8")
    _put_transcript(bucket, job, text="हां।")
    aws.override("bedrock-runtime", ScriptedConverse([]))
    inbound.handler(transcribe_done("evb-8", job))
    reply = sim.read("whatsapp")[-1]
    assert reply["phrase_key"] == "checkin_yes_logged" and reply["kind"] == "voice"
    assert store.get_medicine(sample, "bp").display_label in reply["text"]
    assert store.get(store.hh(sample), "LOG#2026-10-12#bp")["taken"] is True
    assert not any(t["step"] == "converse" for t in store.traces(sample))


def test_spoken_bare_yes_without_a_check_in_is_acknowledged_by_voice_only(bucket, sample):
    inbound.handler(wa_audio(ELDER, "wamid.V9"))
    job = transcribe.job_name(sample, "wamid.V9")
    _put_transcript(bucket, job, text="हाँ")
    aws.override("bedrock-runtime", ScriptedConverse([]))
    inbound.handler(transcribe_done("evb-9", job))
    reply = sim.read("whatsapp")[-1]
    assert reply["phrase_key"] == "consent_ack" and reply["kind"] == "voice" and reply["text"] == "ठीक है, धन्यवाद।"
    assert not store.query_prefix(sample, "LOG#")
    assert not any(t["step"] in ("converse", "tool") for t in store.traces(sample))


def test_failed_job_sends_not_heard(bucket, sample, capsys):
    inbound.handler(wa_audio(ELDER, "wamid.V3"))
    job = transcribe.job_name(sample, "wamid.V3")
    inbound.handler(transcribe_done("evb-3", job, status="FAILED"))
    assert sim.read("whatsapp")[-1]["phrase_key"] == "not_heard"
    assert '"ERROR"' in capsys.readouterr().out


def test_silent_note_gets_not_heard_without_a_model_turn(bucket, sample, capsys):
    inbound.handler(wa_audio(ELDER, "wamid.V6"))
    job = transcribe.job_name(sample, "wamid.V6")
    _put_transcript(bucket, job, text="")
    aws.override("bedrock-runtime", ScriptedConverse([]))
    inbound.handler(transcribe_done("evb-6", job))
    assert sim.read("whatsapp")[-1]["phrase_key"] == "not_heard"
    assert not store.query_prefix(sample, "SIGNAL#")
    assert '"ERROR"' not in capsys.readouterr().out


def test_signal_uses_arrival_time_and_is_labelled_simulated(bucket, sample):
    store.set_wa_inbound(sample, "kamala")
    router.send(store.elder(sample), router.Content(phrase="send_voice_note"), correlation_id="out#1")
    clock.advance(10)
    inbound.handler(wa_audio(ELDER, "wamid.V7"))
    job = transcribe.job_name(sample, "wamid.V7")
    clock.advance(30)  # transcription time must not count as reply delay
    _put_transcript(bucket, job)
    aws.override("bedrock-runtime", ScriptedConverse([end_turn("ठीक है।")]))
    inbound.handler(transcribe_done("evb-7", job))
    sig = store.query_prefix(sample, "SIGNAL#")[0]
    assert float(sig["features"]["reply_delay"]) == 600.0
    assert sig["simulated"] is True


def test_unknown_job_is_ignored(bucket, sample):
    inbound.handler(transcribe_done("evb-4", "aurasenior-other-123"))
    assert sim.read("whatsapp") == []


def test_large_media_asks_for_voice_note(bucket, sample):
    store.set_wa_inbound(sample, "kamala")
    inbound.handler(wa_audio(ELDER, "wamid.V5", size=20 * 1024 * 1024))
    assert sim.read("whatsapp")[-1]["phrase_key"] == "send_voice_note"
