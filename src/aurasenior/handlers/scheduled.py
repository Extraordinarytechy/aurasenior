"""aurasenior-scheduled: check-in chain, escalation rechecks, delivery checks, approval expiry, weekly summary."""
from __future__ import annotations

from .. import clock, dedupe, escalation, log, refill, router, schedules, store, summary
from ..memory import agentcore, build_store
from ..router import Content

KINDS = {"checkin", "followup", "missed_checkin", "escalation_recheck", "delivery_check", "approval_expiry",
         "weekly_summary"}


def handler(event: dict, context=None) -> dict:
    agentcore.reset_invocation()
    kind = event.get("kind")
    if kind not in KINDS:
        # selftest_error checks the ERROR metric filter end to end; unknown kinds would not be fixed by a retry.
        log.get().error("selftest_error" if kind == "selftest_error" else "unknown scheduled kind",
                        extra={"kind": str(kind)[:40]})
        return {"ok": True}
    hid = event["household_id"]
    h = store.get_household(hid)
    if not h:
        log.get().warning("scheduled run for unknown household")
        return {"ok": True}
    local_date = event.get("local_date") or clock.local_date(h.timezone)
    eid = event.get("event_id") or dedupe.scheduled_event_id(
        kind, hid, local_date=local_date, escalation_id=event.get("escalation_id"), run=event.get("run"),
        correlation_id=event.get("correlation_id"), approval_id=event.get("approval_id"))
    log.set_context(household_id=hid, correlation_id=eid)
    if not dedupe.claim(eid):
        return {"ok": True, "duplicate": True}
    try:
        RUNS[kind](hid, event, local_date, eid)
        dedupe.done(eid)
    except Exception:
        log.get().warning("scheduled run failed, released for retry", extra={"kind": kind})
        dedupe.release(eid)
        raise
    return {"ok": True}


def _morning_label(hid: str) -> str:
    meds = [m for m in store.medicines(hid) if m.time_of_day == "morning"]
    return meds[0].display_label if meds else ""


def run_checkin(hid: str, event: dict, local_date: str, eid: str, *, followup: bool = False) -> None:
    elder = store.elder(hid)
    h = store.get_household(hid)
    if elder.consent_status("whatsapp") != "opted_in":
        store.trace(hid, "followup" if followup else "checkin", outcome="skipped_no_consent")
        return
    which = "followup" if followup else "checkin"
    c = Content(phrase=f"{which}_voice", vars={"display_label": _morning_label(hid)}, voice=True,
                wa_template=f"aurasenior_{which}", wa_params=[elder.display_name], ref={"kind": "listen", "id": which})
    r = router.send(elder, c, correlation_id=f"{eid}#1")
    store.trace(hid, which, outcome=r.outcome, channel=r.channel, simulated=r.simulated)
    if followup:
        schedules.create_missed_checkin(hid, local_date, h.timezone)
    else:
        schedules.create_followup(hid, local_date, h.timezone)


def run_followup(hid, event, local_date, eid):
    run_checkin(hid, event, local_date, eid, followup=True)


def run_missed(hid, event, local_date, eid):
    escalation.escalate(hid, "missed_checkin")
    elder = store.elder(hid)
    build_store(elder).record_checkin(hid, elder.person_id, local_date, f"Check-in {local_date}: no reply")


def run_recheck(hid, event, local_date, eid):
    escalation.recheck_run(hid, event["escalation_id"], int(event["run"]))


def run_delivery_check(hid, event, local_date, eid):
    router.delivery_check_run(hid, event["correlation_id"])


def run_expiry(hid, event, local_date, eid):
    refill.expiry_run(hid, event["approval_id"])


def run_weekly(hid, event, local_date, eid):
    facts = summary.build_week(hid, local_date)
    elder = store.elder(hid)
    data = summary.to_template_data(facts, elder.display_name)
    for p in store.people(hid):
        if p.role in ("elder", "pharmacy") or not p.addresses.get("email"):
            continue
        if p.consent_status("email") != "opted_in":
            store.trace(hid, "weekly_summary", person_id=p.person_id, outcome="blocked_consent", channel="email")
            continue
        r = router.send(p, Content(text=f"Week of {facts.week_start}", email_template="aurasenior-weekly-summary",
                                   email_data=data), correlation_id=f"{eid}#{p.person_id}", only_channel="email")
        store.trace(hid, "weekly_summary", person_id=p.person_id, outcome=r.outcome, channel="email",
                    simulated=r.simulated)


RUNS = {"checkin": run_checkin, "followup": run_followup, "missed_checkin": run_missed,
        "escalation_recheck": run_recheck, "delivery_check": run_delivery_check, "approval_expiry": run_expiry,
        "weekly_summary": run_weekly}
