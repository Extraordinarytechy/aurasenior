from aurasenior import clock, store, summary
from aurasenior.models import Approval, Escalation


def test_week_facts_from_fixed_items(sample):
    hid = sample
    for d in range(12, 19):
        store.log_medicine(hid, "sugar", f"2026-10-{d}", taken=d != 15)
    store.put_approval(Approval(hid, "a" * 12, "refill", "bp", "ordered", "rohan", "2026-10-12T04:00:00+00:00",
                                ran_out_at="2026-10-12T04:00:00+00:00", ordered_at="2026-10-12T04:12:00+00:00"))
    store.put_escalation(Escalation(hid, "e" * 12, "fall_or_help", "I fell", "acknowledged",
                                    "2026-10-14T05:00:00+00:00", acknowledged_at="2026-10-14T05:07:00+00:00"))
    store.put_escalation(Escalation(hid, "f" * 12, "missed_checkin", "", "unacknowledged",
                                    "2026-10-16T05:00:00+00:00"))
    store.put({"PK": store.hh(hid), "SK": "SIGNAL#2026-10-13#m1", "date": "2026-10-13", "mentions": {"pain": 2, "low_mood": 0},
               "simulated": False})
    f = summary.build_week(hid, "2026-10-18")
    sugar = next(m for m in f.medicines if m["display_label"] == "sugar tablet")
    assert sugar["days_taken"] == 6 and sugar["days_not_taken"] == 1
    assert f.refills == {"requested": 1, "ordered": 1, "minutes_to_order": [12]}
    assert {"reason": "fall_or_help", "status": "acknowledged", "minutes_to_ack": 7} in f.escalations
    assert {"reason": "missed_checkin", "status": "unacknowledged", "minutes_to_ack": "unacknowledged"} in f.escalations
    assert f.missed_checkins == 1 and f.mentions["pain"] == 2
    assert f.quotes == []
    data = summary.to_template_data(f, "Kamala")
    assert data["brand"] and "sugar tablet: taken 6 days, not taken 1 day, no answer 0 days" in data["medicines"]


def test_week_with_nothing_logged_reads_as_no_answer(sample):
    store.log_medicine(sample, "bp", "2026-10-18", taken=False, out_of_stock=True)
    data = summary.to_template_data(summary.build_week(sample, "2026-10-18"), "Kamala")
    assert "BP tablets: taken 0 days, not taken 1 day, no answer 6 days" in data["medicines"]
    assert "sugar tablet: taken 0 days, not taken 0 days, no answer 7 days" in data["medicines"]
    assert "of 7 days" not in data["medicines"]


def test_quotes_only_when_shared(sample):
    store.put_turn(sample, "kamala", "user", "BP tablets are finished")
    assert summary.build_week(sample, "2026-10-18").quotes == []
    store.update(store.hh(sample), "PROFILE", share_transcripts=True)
    assert summary.build_week(sample, "2026-10-18").quotes == ["BP tablets are finished"]
    clock.advance(0)
