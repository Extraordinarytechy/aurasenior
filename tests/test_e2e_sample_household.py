"""End-to-end replay of the sample household on local simulators with a scripted model."""
from aurasenior import demo, sim


def test_sample_household_story(capsys):
    result = demo.replay(print_trace=True)
    out = capsys.readouterr().out
    with capsys.disabled():
        print("\n" + out)
    items = result["items"]
    emails = sim.read("email")
    wa = sim.read("whatsapp")
    rcs = sim.read("rcs")

    # pharmacy order email exactly once, and the confirmation voice note to the elder
    assert len([e for e in emails if e.get("template") == "aurasenior-refill-order"]) == 1
    assert any(m.get("phrase_key") == "refill_ordered_elder" and m["kind"] == "voice" for m in wa)
    # missed check-in alert, urgent fall alert and acknowledgement
    assert any(m.get("phrase_key") == "missed_checkin" for m in rcs)
    assert any(m.get("phrase_key") == "urgent_alert" and m.get("urgency") == "urgent" for m in rcs)
    assert any(m.get("phrase_key") == "esc_ack_elder" for m in wa)
    assert any(t["step"] == "ack" for t in items)
    # weekly summary to every recipient with email consent
    weekly = sorted(e["to"] for e in emails if e.get("template") == "aurasenior-weekly-summary")
    assert weekly == ["doctor@example.com", "rohan@example.com"]
    # the model calls suggest_call after each voice note; one fixed worth-a-call note goes to the son
    assert len([t for t in items if t["step"] == "tool" and t["tool"] == "suggest_call"]) == 3
    calls = [m for m in rcs if m["text"].startswith("Worth a call today")]
    assert [m["text"] for m in calls] == ["Worth a call today: Mom mentioned pain a few times this week."]
    assert "[SIMULATED BASELINE]" in result["trace"]
    assert not any(m["text"].startswith("Worth a call") for m in wa if m["person_id"] == "kamala")
    # STOP opts out
    assert [t for t in items if t["step"] == "consent"][-1]["outcome"] == "opted_out"
    # the model ran only on the four conversational turns; deterministic paths made no call
    assert result["unused_scripted"] == 0 and result["model_calls"] == 9
    # every send is labelled simulated and the trace shows the labels
    assert all(x["simulated"] for x in wa + rcs + emails)
    assert "[SIMULATED]" in result["trace"] and "[SCRIPTED MODEL]" in result["trace"]
