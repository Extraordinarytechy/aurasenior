import json

import pytest
from botocore.exceptions import ClientError

from aurasenior import aws, channels, clock, sim, store
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


def test_a_notice_still_in_flight_promises_nothing(sample):
    open_window(sample, "kamala")
    store.put({"PK": store.hh(sample), "SK": "USAGE#2026-10-12", "converse_calls": 150})
    store.put({"PK": store.hh(sample), "SK": "SEND#unavailable#2026-10-12", "status": "sending",
               "at": clock.iso()})
    _scripted([])
    AgentRunner().run_turn(sample, "kamala", {"event_id": "ev3", "text": "hello"})
    assert [x["phrase_key"] for x in sim.read("whatsapp")] == ["not_heard"]
    assert "agent_unavailable_ok" not in store.get(store.hh(sample), "USAGE#2026-10-12")


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


def _blocked_with(where):
    """A guardrail block with the trace shape Converse returns when trace is enabled."""
    topic = {"topicPolicy": {"topics": [{"name": "Medication dose advice", "type": "DENY", "action": "BLOCKED",
                                         "detected": True}]}}
    trace = {"inputAssessment": {"g1": topic if where == "input" else {"invocationMetrics": {}}}}
    if where == "output":
        trace["outputAssessments"] = {"g1": [topic]}
    return {**_blocked(), "trace": {"guardrail": trace}}


def test_guardrail_findings_name_the_policy_and_the_side():
    from aurasenior.agent.runner import guardrail_findings

    assert guardrail_findings(_blocked_with("output")) == {"input": [], "output": ["Medication dose advice"]}
    assert guardrail_findings(_blocked_with("input")) == {"input": ["Medication dose advice"], "output": []}
    assert guardrail_findings(_blocked()) is None


def test_guardrail_config_asks_for_the_trace(sample, monkeypatch):
    monkeypatch.setenv("GUARDRAIL_ID", "g1")
    open_window(sample, "kamala")
    s = _scripted([end_turn("नमस्ते")])
    AgentRunner().run_turn(sample, "kamala", {"event_id": "ev10", "text": "नमस्ते"})
    assert s.calls[0]["guardrailConfig"]["trace"] == "enabled"


def test_reply_blocked_after_a_refill_ask_tells_her_only_what_happened(sample):
    open_window(sample, "kamala")
    _scripted([
        tool_use("log_medicine", {"medicine_id": "bp", "taken": False, "out_of_stock": True}, "a"),
        tool_use("request_refill_approval", {"medicine_id": "bp", "ask_person_id": "rohan"}, "b"),
        _blocked_with("output"),
    ])
    r = AgentRunner().run_turn(sample, "kamala", {"event_id": "ev11", "text": "BP वाली गोली खत्म हो गई। घुटने में थोड़ा दर्द है।"})
    assert r.outcome == "guardrail_blocked"
    reply = sim.read("whatsapp")[-1]
    assert reply["phrase_key"] == "refill_asked_elder"
    assert reply["text"] == "मैंने Rohan से आपकी BP tablets फिर से मँगवाने के बारे में पूछ लिया है।"
    g = [t for t in store.traces(sample) if t["step"] == "guardrail"][-1]
    assert g["output_topics"] == ["Medication dose advice"] and g["reply"] == "refill_asked_elder"


def test_reply_blocked_when_the_refill_card_did_not_go_out_claims_no_ask(sample):
    open_window(sample, "kamala")
    for ch in ("rcs", "sms", "email"):
        store.set_consent(sample, "rohan", ch, "opted_out", "test")
    _scripted([
        tool_use("log_medicine", {"medicine_id": "bp", "taken": False, "out_of_stock": True}, "a"),
        tool_use("request_refill_approval", {"medicine_id": "bp", "ask_person_id": "rohan"}, "b"),
        _blocked_with("output"),
    ])
    AgentRunner().run_turn(sample, "kamala", {"event_id": "ev12", "text": "BP वाली गोली खत्म हो गई।"})
    assert sim.read("whatsapp")[-1]["phrase_key"] == "noted_elder"


def test_blocked_input_gets_the_fixed_reply_even_after_tools(sample):
    open_window(sample, "kamala")
    _scripted([tool_use("log_medicine", {"medicine_id": "bp", "taken": True, "out_of_stock": False}, "a"),
               _blocked_with("input")])
    AgentRunner().run_turn(sample, "kamala", {"event_id": "ev13", "text": "क्या मैं दो गोली ले लूँ?"})
    assert sim.read("whatsapp")[-1]["phrase_key"] == "guardrail_blocked"


def test_family_reply_blocked_after_tools_gets_the_fixed_reply(sample):
    _scripted([tool_use("get_week", {}, "a"), _blocked_with("output")])
    AgentRunner().run_turn(sample, "rohan", {"event_id": "ev14", "text": "How was Mom this week?"})
    assert sim.read("rcs")[-1]["phrase_key"] == "guardrail_blocked"


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


def _memory_calls(monkeypatch):
    calls = []

    class Mem:
        def recall(self, *a, **k):
            return []

        def record_turn(self, hid, pid, user_text, reply_text):
            calls.append((user_text, reply_text))

    monkeypatch.setattr("aurasenior.agent.runner.build_store", lambda p: Mem())
    monkeypatch.setattr("aurasenior.agent.prompt.build_store", lambda p: Mem())
    return calls


def test_turn_with_only_the_reply_blocked_is_kept_with_what_she_heard(sample, monkeypatch):
    calls = _memory_calls(monkeypatch)
    open_window(sample, "kamala")
    _scripted([tool_use("request_refill_approval", {"medicine_id": "bp", "ask_person_id": "rohan"}, "a"),
               _blocked_with("output")])
    text = "BP वाली गोली खत्म हो गई।"
    AgentRunner().run_turn(sample, "kamala", {"event_id": "ev15", "text": text})
    heard = "मैंने Rohan से आपकी BP tablets फिर से मँगवाने के बारे में पूछ लिया है।"
    assert calls == [(text, heard)]
    # Same frozen timestamp for both items, so their order in the table is not fixed.
    assert {(t["role"], t["text"]) for t in store.last_turns(sample, "kamala", 10)} == {("user", text),
                                                                                       ("assistant", heard)}


LIVE_CLAIM = ("माफ़ करें, आपकी BP वाली गोली खत्म हो गई है। मैं परिवार के लिए रिफ़िल की अनुमति माँग रही हूँ। "
              "घुटने में दर्द होने पर मैं खेद महसूस कर रही हूँ।")


def _ordered_today(hid):
    from aurasenior.models import Approval

    store.put_approval(Approval(hid, "a" * 12, "refill", "bp", "ordered", "rohan", clock.iso(),
                                handled_at=clock.iso(), ordered_at=clock.iso()))


def test_refill_claim_with_no_ask_this_turn_tells_her_the_order_instead(sample):
    open_window(sample, "kamala")
    _ordered_today(sample)
    s = _scripted([tool_use("log_medicine", {"medicine_id": "bp", "taken": False, "out_of_stock": True}, "a"),
                   end_turn(LIVE_CLAIM)])
    AgentRunner().run_turn(sample, "kamala", {"event_id": "ev20", "text": "BP वाली गोली खत्म हो गई। घुटने में थोड़ा दर्द है।"})
    result = s.calls[1]["messages"][-1]["content"][0]["toolResult"]["content"][0]["json"]
    assert result["refill"]["approval_status"] == "ordered"
    reply = sim.read("whatsapp")[-1]
    assert reply["phrase_key"] == "refill_ordered_elder" and reply["text"] == "Rohan ने आपकी BP tablets मँगवा दी है।"
    assert "अनुमति" not in " ".join(t["text"] for t in store.last_turns(sample, "kamala", 10))
    t = [x for x in store.traces(sample) if x["step"] == "reply"][-1]
    assert t["outcome"] == "refill_claim_replaced" and t["phrase"] == "refill_ordered_elder"


def test_refill_claim_after_only_a_log_says_noted(sample):
    open_window(sample, "kamala")
    _scripted([tool_use("log_medicine", {"medicine_id": "bp", "taken": False, "out_of_stock": True}, "a"),
               end_turn(LIVE_CLAIM)])
    AgentRunner().run_turn(sample, "kamala", {"event_id": "ev21", "text": "BP वाली गोली खत्म हो गई।", "voice": True})
    reply = sim.read("whatsapp")[-1]
    assert reply["phrase_key"] == "noted_elder" and reply["kind"] == "voice"


def test_refill_claim_with_no_tool_and_no_refill_says_nobody_was_asked(sample):
    open_window(sample, "kamala")
    _scripted([end_turn("मैंने रोहन से रिफ़िल मँगवाने को कह दिया है।")])
    AgentRunner().run_turn(sample, "kamala", {"event_id": "ev22", "text": "नमस्ते"})
    reply = sim.read("whatsapp")[-1]
    assert reply["phrase_key"] == "refill_none_elder"
    assert reply["text"] == "मैंने अभी किसी से दवा मँगवाने के बारे में नहीं पूछा है।"


def test_refill_reply_after_a_fresh_ask_that_went_out_is_kept(sample):
    open_window(sample, "kamala")
    text = "मैंने Rohan से आपकी BP tablets की रिफ़िल के बारे में पूछ लिया है। घुटने के दर्द के लिए मुझे खेद है।"
    _scripted([tool_use("log_medicine", {"medicine_id": "bp", "taken": False, "out_of_stock": True}, "a"),
               tool_use("request_refill_approval", {"medicine_id": "bp", "ask_person_id": "rohan"}, "b"),
               end_turn(text)])
    AgentRunner().run_turn(sample, "kamala", {"event_id": "ev23", "text": "BP वाली गोली खत्म हो गई।"})
    assert sim.read("whatsapp")[-1]["text"] == text


def test_family_reply_about_a_refill_is_not_rewritten(sample):
    _scripted([end_turn("Mom's BP tablets were ordered today.")])
    AgentRunner().run_turn(sample, "rohan", {"event_id": "ev24", "text": "Did the refill go through?"})
    assert sim.read("rcs")[-1]["text"] == "Mom's BP tablets were ordered today."


def test_reply_replaced_by_the_wording_rule_is_kept_as_the_replacement(sample, monkeypatch):
    calls = _memory_calls(monkeypatch)
    open_window(sample, "kamala")
    _scripted([end_turn("मैं आपको डायबिटीज़ के बारे में जानकारी नहीं दे सकती।")])
    AgentRunner().run_turn(sample, "kamala", {"event_id": "ev25", "text": "क्या मुझे डायबिटीज़ है?"})
    heard = "मैं इसका जवाब नहीं दे सकती। कृपया अपने डॉक्टर से पूछिए।"
    assert sim.read("whatsapp")[-1]["text"] == heard
    assert calls == [("क्या मुझे डायबिटीज़ है?", heard)]
    assert ("assistant", heard) in {(t["role"], t["text"]) for t in store.last_turns(sample, "kamala", 10)}


def test_turn_with_blocked_input_is_not_kept(sample, monkeypatch):
    calls = _memory_calls(monkeypatch)
    open_window(sample, "kamala")
    _scripted([_blocked_with("input")])
    AgentRunner().run_turn(sample, "kamala", {"event_id": "ev16", "text": "क्या मुझे डायबिटीज़ है?"})
    assert calls == [] and store.last_turns(sample, "kamala", 10) == []
