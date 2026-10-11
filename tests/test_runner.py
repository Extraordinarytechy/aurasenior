import json

import pytest
from botocore.exceptions import ClientError

from aurasenior import aws, channels, sim, store
from aurasenior.agent.runner import AgentRunner
from aurasenior.channels.base import SendResult
from aurasenior.sim.converse import ScriptedConverse, end_turn, tool_use
from conftest import open_window


def _scripted(responses):
    s = ScriptedConverse(responses)
    aws.override("bedrock-runtime", s)
    return s


def test_tool_use_then_end_turn_runs_tools_in_order(sample):
    open_window(sample, "kamala")
    s = _scripted([
        {"output": {"message": {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": "a", "name": "log_medicine", "input": {"medicine_id": "sugar", "taken": True, "out_of_stock": False}}},
            {"toolUse": {"toolUseId": "b", "name": "log_medicine", "input": {"medicine_id": "bp", "taken": False, "out_of_stock": True}}}]}},
         "stopReason": "tool_use"},
        tool_use("request_refill_approval", {"medicine_id": "bp", "ask_person_id": "rohan"}, "c"),
        end_turn("ठीक है, मैंने रोहन से पूछ लिया है।"),
    ])
    r = AgentRunner().run_turn(sample, "kamala", {"event_id": "ev1", "text": "शुगर की गोली ले ली। BP वाली खत्म हो गई।"})
    assert r.tools == ["log_medicine", "log_medicine", "request_refill_approval"] and r.outcome == "ok"
    assert len(s.calls) == 3
    second = s.calls[1]["messages"][-1]["content"]
    assert [b["toolResult"]["toolUseId"] for b in second] == ["a", "b"]
    assert store.get_medicine(sample, "bp").stock == "out"
    assert sim.read("whatsapp")[-1]["text"] == "ठीक है, मैंने रोहन से पूछ लिया है।"
    traces = [t for t in store.traces(sample) if t["step"] == "converse"]
    assert traces and all(t["model"] == "scripted" for t in traces)


def test_six_iterations_stop_with_warn(sample, capsys):
    _scripted([tool_use("get_household", {}, f"t{i}") for i in range(6)])
    r = AgentRunner().run_turn(sample, "kamala", {"event_id": "ev2", "text": "hello"})
    assert r.outcome == "max_iterations" and r.iterations == 6
    assert any(json.loads(x)["level"] == "WARN" for x in capsys.readouterr().out.splitlines())


def test_capped_day_sends_family_notice_once(sample, monkeypatch):
    open_window(sample, "kamala")
    store.put({"PK": store.hh(sample), "SK": "USAGE#2026-10-12", "converse_calls": 150})
    _scripted([])
    AgentRunner().run_turn(sample, "kamala", {"event_id": "ev3", "text": "hello"})
    AgentRunner().run_turn(sample, "kamala", {"event_id": "ev4", "text": "hello again"})
    notices = [x for x in sim.read("rcs") if x.get("phrase_key") == "agent_unavailable_family"]
    assert len(notices) == 1
    assert [x["phrase_key"] for x in sim.read("whatsapp")] == ["cost_cap", "cost_cap"]


def test_capped_turns_after_a_blocked_notice_promise_nothing(sample):
    open_window(sample, "kamala")
    store.set_consent(sample, "rohan", "rcs", "opted_out", "test")
    store.set_consent(sample, "rohan", "sms", "opted_out", "test")
    store.put({"PK": store.hh(sample), "SK": "USAGE#2026-10-12", "converse_calls": 150})
    _scripted([])
    AgentRunner().run_turn(sample, "kamala", {"event_id": "ev3", "text": "hello"})
    AgentRunner().run_turn(sample, "kamala", {"event_id": "ev4", "text": "hello again"})
    assert [x["phrase_key"] for x in sim.read("whatsapp")] == ["not_heard", "not_heard"]


def test_retry_after_a_throttled_notice_sends_it(sample, monkeypatch):
    open_window(sample, "kamala")
    store.put({"PK": store.hh(sample), "SK": "USAGE#2026-10-12", "converse_calls": 150})
    _scripted([])
    rcs = channels.get("rcs")
    real = rcs.send
    state = {"done": False}

    def throttle_once(msg):
        if not state["done"]:
            state["done"] = True
            return SendResult.failed("ThrottlingException", True, simulated=True)
        return real(msg)

    monkeypatch.setattr(rcs, "send", throttle_once)
    with pytest.raises(Exception):
        AgentRunner().run_turn(sample, "kamala", {"event_id": "ev3", "text": "hello"})
    AgentRunner().run_turn(sample, "kamala", {"event_id": "ev3", "text": "hello"})
    AgentRunner().run_turn(sample, "kamala", {"event_id": "ev4", "text": "hello again"})
    assert len([x for x in sim.read("rcs") if x.get("phrase_key") == "agent_unavailable_family"]) == 1
    assert [x["phrase_key"] for x in sim.read("whatsapp")] == ["cost_cap", "cost_cap"]


def _blocked():
    return {"output": {"message": {"role": "assistant", "content": [{"text": "I cannot help with that."}]}},
            "stopReason": "guardrail_intervened"}


def _sends_to(*pids):
    return [x for x in sim.read("whatsapp") + sim.read("rcs") + sim.read("sms") + sim.read("email")
            if x["person_id"] in pids]


def test_guardrail_block_answers_the_elder_in_hindi_and_tells_nobody(sample):
    open_window(sample, "kamala")
    _scripted([_blocked()])
    r = AgentRunner().run_turn(sample, "kamala", {"event_id": "ev8", "text": "क्या मुझे कोई बीमारी है?", "voice": True})
    assert r.outcome == "guardrail_blocked"
    reply = sim.read("whatsapp")[-1]
    assert reply["phrase_key"] == "guardrail_blocked" and reply["kind"] == "voice"
    assert reply["text"] == "मैं इसमें मदद नहीं कर सकती। कृपया अपने डॉक्टर से पूछिए।"
    assert _sends_to("rohan", "simfam", "nbr", "doctor", "pharmacy") == []
    assert store.last_turns(sample, "kamala", 10) == []


def test_guardrail_block_answers_family_in_english(sample):
    _scripted([_blocked()])
    AgentRunner().run_turn(sample, "rohan", {"event_id": "ev9", "text": "What illness does Mom have?"})
    reply = sim.read("rcs")[-1]
    assert reply["phrase_key"] == "guardrail_blocked" and reply["text"] == "I cannot help with that."
    assert _sends_to("kamala", "nbr", "simfam") == []


def test_guardrail_phrases_promise_nothing():
    from aurasenior import phrases

    assert phrases.render("guardrail_blocked", "en-IN", "elder") == "I cannot help with that. Please ask your doctor."
    assert phrases.render("guardrail_blocked", "hi-IN", "family") == "मैं इसमें मदद नहीं कर सकती।"


class Fatal:
    label = "bedrock"

    def converse(self, **kw):
        raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "Converse")


def test_fatal_error_sends_family_notice_once(sample, capsys):
    open_window(sample, "kamala")
    aws.override("bedrock-runtime", Fatal())
    AgentRunner().run_turn(sample, "kamala", {"event_id": "ev5", "text": "hello"})
    AgentRunner().run_turn(sample, "kamala", {"event_id": "ev6", "text": "hello"})
    assert len([x for x in sim.read("rcs") if x.get("phrase_key") == "agent_unavailable_family"]) == 1
    errors = [x for x in capsys.readouterr().out.splitlines() if json.loads(x)["level"] == "ERROR"]
    assert len(errors) == 1


def test_record_turn_gets_text_and_reply(sample, monkeypatch):
    calls = []

    class Mem:
        def recall(self, *a, **k):
            return []

        def record_turn(self, hid, pid, user_text, reply_text):
            calls.append((user_text, reply_text))

    monkeypatch.setattr("aurasenior.agent.runner.build_store", lambda p: Mem())
    monkeypatch.setattr("aurasenior.agent.prompt.build_store", lambda p: Mem())
    open_window(sample, "kamala")
    _scripted([end_turn("नमस्ते")])
    AgentRunner().run_turn(sample, "kamala", {"event_id": "ev7", "text": "नमस्ते"})
    assert calls == [("नमस्ते", "नमस्ते")]
