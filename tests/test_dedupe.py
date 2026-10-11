import pytest

from aurasenior import clock, dedupe


def test_duplicate_after_done_is_skipped(table, frozen):
    assert dedupe.claim("e1")
    dedupe.done("e1")
    clock.advance(30)
    assert not dedupe.claim("e1")


def test_fresh_processing_claim_blocks_and_stale_one_is_taken_over(table, frozen):
    assert dedupe.claim("e2")
    clock.advance(2)
    assert not dedupe.claim("e2")
    clock.advance(4)
    assert dedupe.claim("e2")


def test_release_lets_the_retry_through(table, frozen):
    assert dedupe.claim("e3")
    dedupe.release("e3")
    assert dedupe.claim("e3")


def test_send_once_runs_once_across_a_retry(table, frozen):
    calls = []

    def send():
        calls.append(1)
        return "prov-1"

    assert dedupe.send_once("hh1", "e#1", send) == (True, "prov-1")
    assert dedupe.send_once("hh1", "e#1", send) == (False, "prov-1")
    assert len(calls) == 1


def test_send_once_failure_allows_retry(table, frozen):
    def boom():
        raise RuntimeError("throttled")

    with pytest.raises(RuntimeError):
        dedupe.send_once("hh1", "e#2", boom)
    assert dedupe.send_once("hh1", "e#2", lambda: "p2") == (True, "p2")


def test_event_id_formats():
    assert dedupe.scheduled_event_id("checkin", "hh1", local_date="2026-10-12") == "checkin#hh1#2026-10-12"
    assert dedupe.scheduled_event_id("weekly_summary", "hh1", local_date="2026-10-18") == "weekly#hh1#2026-10-18"
    assert dedupe.scheduled_event_id("followup", "hh1", local_date="2026-10-12") == "followup#hh1#2026-10-12"
    assert dedupe.scheduled_event_id("escalation_recheck", escalation_id="abc", run=3) == "recheck#abc#3"
    assert dedupe.scheduled_event_id("delivery_check", correlation_id="x#1") == "dcheck#x#1"
    assert dedupe.scheduled_event_id("approval_expiry", approval_id="a1") == "expiry#a1"
