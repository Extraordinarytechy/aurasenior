import json

from botocore.exceptions import ClientError

from aurasenior import aws, sim, store
from aurasenior.agent.runner import AgentRunner
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
