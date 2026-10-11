import pytest

from aurasenior import aws, channels, schedules, sim, store
from aurasenior.channels.base import SendResult
from aurasenior.handlers import inbound
from aurasenior.memory import agentcore
from aurasenior.sim.converse import ScriptedConverse, end_turn
from events import wa_button, wa_text

ELDER = "+910000000001"


class NoModel:
    label = "scripted"

    def converse(self, **kw):
        raise AssertionError("this path must not call the model")


def test_throttled_first_attempt_then_retry_sends_once(sample, monkeypatch):
    store.set_wa_inbound(sample, "kamala")
    aws.override("bedrock-runtime", ScriptedConverse([end_turn("ठीक है"), end_turn("ठीक है")]))
    wa = channels.get("whatsapp")
    real = wa.send
    calls = {"n": 0}

    def flaky(msg):
        calls["n"] += 1
        if calls["n"] == 1:
            return SendResult.failed("ThrottlingException", True, simulated=True)
        return real(msg)

    monkeypatch.setattr(wa, "send", flaky)
    ev = wa_text(ELDER, "wamid.T1", "नमस्ते")
    with pytest.raises(Exception):
        inbound.handler(ev)
    inbound.handler(ev)
    inbound.handler(ev)
    assert len(sim.read("whatsapp")) == 1


def test_same_event_twice_gives_one_send(sample):
    aws.override("bedrock-runtime", ScriptedConverse([end_turn("ठीक है")]))
    ev = wa_text(ELDER, "wamid.T2", "नमस्ते")
    inbound.handler(ev)
    inbound.handler(ev)
    assert len(sim.read("whatsapp")) == 1


def test_fall_words_give_one_told_message_not_two(sample):
    s = ScriptedConverse([end_turn("मैंने रोहन को बता दिया है। मैं आपके साथ हूँ।")])
    aws.override("bedrock-runtime", s)
    inbound.handler(wa_text(ELDER, "wamid.F1", "I fell near the chair"))
    to_elder = [x for x in sim.read("whatsapp") if x["person_id"] == "kamala"]
    assert [x.get("phrase_key") for x in to_elder] == ["esc_told_elder"]
    assert "just been told" in s.calls[0]["system"][0]["text"]
    assert any(t["step"] == "reply" and t["outcome"] == "skipped_already_messaged" for t in store.traces(sample))


def test_model_escalate_tool_does_not_repeat_the_told_message(sample):
    from aurasenior.sim.converse import tool_use

    store.set_wa_inbound(sample, "kamala")
    aws.override("bedrock-runtime", ScriptedConverse([
        tool_use("escalate", {"reason": "fall_or_help", "quote": "not feeling safe"}),
        end_turn("I have told Rohan.")]))
    from aurasenior.agent.runner import AgentRunner

    AgentRunner().run_turn(sample, "kamala", {"event_id": "ev-t", "text": "not feeling safe"})
    to_elder = [x for x in sim.read("whatsapp") if x["person_id"] == "kamala"]
    assert [x.get("phrase_key") for x in to_elder] == ["esc_told_elder"]


def test_elder_reply_records_checkin_once(sample, monkeypatch):
    monkeypatch.setenv("AGENTCORE_MEMORY_ID", "aurasenior_memory-abc")
    calls = []

    class Stub:
        def create_event(self, **kw):
            calls.append(kw)
            return {}

        def retrieve_memory_records(self, **kw):
            return {"memoryRecordSummaries": []}

    aws.override("bedrock-agentcore", Stub())
    agentcore.reset_invocation()
    aws.override("bedrock-runtime", ScriptedConverse([end_turn("अच्छा"), end_turn("अच्छा")]))
    schedules.create_followup(sample, "2026-10-12", "Asia/Kolkata")
    inbound.handler(wa_text(ELDER, "wamid.T3", "नमस्ते"))
    inbound.handler(wa_text(ELDER, "wamid.T4", "और कुछ नहीं"))
    lines = [c for c in calls if c.get("clientToken")]
    assert len(lines) == 1
    assert lines[0]["payload"][0]["conversational"]["content"]["text"] == "Check-in 2026-10-12: replied 09:00"
    assert lines[0]["clientToken"] == agentcore.checkin_token(sample, "kamala", "2026-10-12")


def test_fall_phrase_escalates_before_the_model(sample):
    aws.override("bedrock-runtime", ScriptedConverse([end_turn("मैं यहाँ हूँ")]))
    inbound.handler(wa_text(ELDER, "wamid.T5", "मैं कुर्सी के पास गिर गई"))
    assert store.escalations(sample)[0].reason == "fall_or_help"
    rcs = sim.read("rcs")
    assert rcs and rcs[0]["text"].startswith("URGENT")
    traces = [t["step"] for t in store.traces(sample)]
    assert traces.index("escalate") < traces.index("converse")


def test_listen_tap_sends_voice_note_without_model(sample):
    aws.override("bedrock-runtime", NoModel())
    from aurasenior.handlers import scheduled

    scheduled.handler({"kind": "checkin", "household_id": sample})
    tmpl = sim.read("whatsapp")[-1]
    assert tmpl["kind"] == "template"
    inbound.handler(wa_button(ELDER, "wamid.T6", "सुनें", tmpl["provider_id"]))
    voice = sim.read("whatsapp")[-1]
    assert voice["kind"] == "voice" and voice["phrase_key"] == "checkin_voice"
    assert schedules.name_followup(sample, "2026-10-12") not in schedules.client().names()


def test_unknown_sender_gets_nothing(sample):
    inbound.handler(wa_text("+910000000099", "wamid.T7", "hello"))
    assert sim.read("whatsapp") == []


def test_simulated_inbound_refused_for_real_number(sample):
    from events import two_way

    store.set_consent(sample, "rohan", "rcs", "pending", "test")
    inbound.handler(two_way("+12025550101", "in-1", "YES", simulated=True))
    assert store.get_person(sample, "rohan").consent_status("rcs") == "pending"
