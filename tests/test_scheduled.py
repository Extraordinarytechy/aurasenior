import json

import pytest

from aurasenior import aws, channels, clock, schedules, sim, store
from aurasenior.channels.base import SendResult
from aurasenior.handlers import scheduled
from aurasenior.memory import agentcore


def test_checkin_retried_after_send_sends_once(sample, monkeypatch):
    real = schedules.create_followup
    state = {"n": 0}

    def boom(*a, **k):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("scheduler throttled")
        return real(*a, **k)

    monkeypatch.setattr(schedules, "create_followup", boom)
    with pytest.raises(RuntimeError):
        scheduled.handler({"kind": "checkin", "household_id": sample})
    scheduled.handler({"kind": "checkin", "household_id": sample})
    assert len([x for x in sim.read("whatsapp") if x.get("template") == "aurasenior_checkin_hi"]) == 1


def test_chain_checkin_followup_missed(sample):
    sim_s = schedules.client()
    scheduled.handler({"kind": "checkin", "household_id": sample})
    due = sim_s.due(clock.advance(90))
    assert [d["payload"]["kind"] for d in due] == ["followup"]
    sim_s.pop(due[0]["name"])
    scheduled.handler(due[0]["payload"])
    assert sim.read("whatsapp")[-1]["template"] == "aurasenior_followup_hi"
    due = sim_s.due(clock.advance(60))
    assert [d["payload"]["kind"] for d in due] == ["missed_checkin"]
    sim_s.pop(due[0]["name"])
    scheduled.handler(due[0]["payload"])
    assert store.escalations(sample)[0].reason == "missed_checkin"
    assert any("No reply from Mom" in x.get("text", "") for x in sim.read("rcs"))


def test_missed_checkin_records_no_reply_line_with_stable_token(sample, monkeypatch):
    monkeypatch.setenv("AGENTCORE_MEMORY_ID", "aurasenior_memory-abc")
    calls = []

    class Stub:
        def create_event(self, **kw):
            calls.append(kw)
            return {}

    aws.override("bedrock-agentcore", Stub())
    ev = {"kind": "missed_checkin", "household_id": sample, "local_date": "2026-10-12",
          "event_id": "missed_checkin#sample01#2026-10-12"}
    scheduled.handler(ev)
    store.table().delete_item(Key={"PK": "DEDUP#missed_checkin#sample01#2026-10-12", "SK": "DEDUP"})
    agentcore.reset_invocation()
    scheduled.handler(ev)
    assert [c["payload"][0]["conversational"]["content"]["text"] for c in calls] == ["Check-in 2026-10-12: no reply"] * 2
    assert calls[0]["clientToken"] == calls[1]["clientToken"]


def test_weekly_summary_goes_to_every_consented_email(sample):
    store.set_consent(sample, "nbr", "email", "pending", "test")
    scheduled.handler({"kind": "weekly_summary", "household_id": sample})
    to = sorted(x["to"] for x in sim.read("email") if x.get("template") == "aurasenior-weekly-summary")
    assert to == ["doctor@example.com", "rohan@example.com"]
    blocked = [t for t in store.traces(sample) if t["step"] == "weekly_summary" and t["outcome"] == "blocked_consent"]
    assert [t["person_id"] for t in blocked] == ["nbr"]


def test_selftest_error_writes_one_error_line_and_nothing_else(sample, capsys):
    before = store.table().scan()["Count"]
    assert scheduled.handler({"kind": "selftest_error"}) == {"ok": True}
    out = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert [(o["level"], o["msg"]) for o in out] == [("ERROR", "selftest_error")]
    assert store.table().scan()["Count"] == before
    assert sim.read("whatsapp") == [] and sim.read("rcs") == []


def test_unknown_kind_is_rejected(sample, capsys):
    assert scheduled.handler({"kind": "dance"}) == {"ok": True}
    assert json.loads(capsys.readouterr().out.splitlines()[0])["level"] == "ERROR"


def test_checkin_skipped_without_whatsapp_consent(sample):
    store.set_consent(sample, "kamala", "whatsapp", "pending", "test")
    scheduled.handler({"kind": "checkin", "household_id": sample})
    assert sim.read("whatsapp") == []
    channels.reset()
    _ = SendResult
