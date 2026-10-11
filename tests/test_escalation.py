import json

from aurasenior import clock, escalation, schedules, sim, store
from conftest import open_window


def _family_sends():
    return [x for x in sim.read("rcs") + sim.read("whatsapp") + sim.read("email") if x["person_id"] != "kamala"]


def _elder_sends():
    return [x for x in sim.read("whatsapp") if x["person_id"] == "kamala"]


def test_keyword_path_then_model_gives_one_escalation(sample):
    open_window(sample, "kamala")
    eid = escalation.escalate(sample, "fall_or_help", "I slipped near the chair")
    sends = len(_family_sends())
    assert escalation.escalate(sample, "fall_or_help", "I slipped") == eid
    assert len(_family_sends()) == sends
    assert len(escalation.open_escalations(sample)) == 1
    assert any("I slipped near the chair" in x.get("text", "") for x in sim.read("rcs"))
    assert any("esc_told_elder" == x.get("phrase_key") for x in _elder_sends())


def test_fall_upgrades_open_missed_checkin(sample):
    open_window(sample, "kamala")
    eid = escalation.escalate(sample, "missed_checkin")
    assert escalation.escalate(sample, "fall_or_help", "I fell") == eid
    e = store.get_escalation(sample, eid)
    assert e.reason == "fall_or_help" and e.quote == "I fell"
    assert escalation.escalate(sample, "fall_or_help", "help") == eid


def test_twelve_rechecks_then_unacknowledged(sample, capsys):
    open_window(sample, "kamala")
    eid = escalation.escalate(sample, "fall_or_help", "help")
    base_family = len(_family_sends())
    base_elder = len(_elder_sends())
    for run in range(1, 13):
        clock.advance(5)
        escalation.recheck_run(sample, eid, run)
    assert len(_elder_sends()) - base_elder == 12
    assert len(_family_sends()) > base_family
    assert store.get_escalation(sample, eid).status == "unacknowledged"
    errors = [json.loads(x) for x in capsys.readouterr().out.splitlines() if '"ERROR"' in x]
    assert any(e["msg"] == "escalation unacknowledged" for e in errors)
    after = len(sim.read("whatsapp"))
    escalation.recheck_run(sample, eid, 12)
    assert len(sim.read("whatsapp")) == after


def test_family_resend_on_even_runs_only(sample):
    eid = escalation.escalate(sample, "missed_checkin")
    n0 = len(sim.read("rcs"))
    escalation.recheck_run(sample, eid, 1)
    assert len(sim.read("rcs")) == n0
    escalation.recheck_run(sample, eid, 2)
    assert len(sim.read("rcs")) == n0 + 1


def test_missed_checkin_rechecks_send_nothing_to_elder(sample):
    open_window(sample, "kamala")
    eid = escalation.escalate(sample, "missed_checkin")
    for run in range(1, 4):
        escalation.recheck_run(sample, eid, run)
    assert _elder_sends() == []


def test_ack_stops_rechecks_and_tells_elder_for_falls(sample):
    open_window(sample, "kamala")
    eid = escalation.escalate(sample, "fall_or_help", "help")
    assert schedules.name_recheck(eid, 1) in schedules.client().names()
    assert escalation.ack_escalation(sample, eid, "rohan")
    assert schedules.name_recheck(eid, 1) not in schedules.client().names()
    assert _elder_sends()[-1]["text"] == "Rohan आपकी मदद के लिए आ रहे हैं।"
    assert not escalation.ack_escalation(sample, eid, "nbr")
    n = len(sim.read("whatsapp"))
    escalation.recheck_run(sample, eid, 1)
    assert len(sim.read("whatsapp")) == n


def test_elder_message_closes_missed_checkin_but_not_fall(sample):
    eid = escalation.escalate(sample, "missed_checkin")
    assert escalation.resolve_by_elder(sample)
    assert store.get_escalation(sample, eid).status == "resolved_by_elder"
    assert any("has replied now" in x.get("text", "") for x in sim.read("rcs"))
    fid = escalation.escalate(sample, "fall_or_help", "help")
    assert not escalation.resolve_by_elder(sample)
    assert store.get_escalation(sample, fid).status == "open"


def test_an_hour_of_urgent_sends_is_not_capped(sample):
    open_window(sample, "kamala")
    eid = escalation.escalate(sample, "fall_or_help", "help")
    for run in range(1, 12):
        escalation.recheck_run(sample, eid, run)
    assert not any(t.get("outcome") == "blocked_rate" for t in store.traces(sample))
