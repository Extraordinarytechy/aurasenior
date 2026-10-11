"""Fall, help and missed check-in escalation. One open escalation per household and reason."""
from __future__ import annotations

from botocore.exceptions import ClientError

from . import clock, log, phrases, router, schedules, store
from .models import Escalation, Person
from .router import Content

MAX_RUNS = 12


def _marker(reason: str) -> str:
    return f"ESCOPEN#{reason}"


def _open(hid: str, reason: str) -> Escalation | None:
    item = store.get(store.hh(hid), _marker(reason))
    if not item:
        return None
    e = store.get_escalation(hid, item["escalation_id"])
    return e if e and e.status == "open" else None


def _claim(hid: str, reason: str, eid: str) -> bool:
    try:
        store.put({"PK": store.hh(hid), "SK": _marker(reason), "escalation_id": eid},
                  ConditionExpression="attribute_not_exists(PK)")
        return True
    except ClientError as e:
        if store.is_conditional_failure(e):
            return False
        raise


def _release(hid: str, reason: str, eid: str) -> None:
    # Conditional, so a retried step never frees a newer escalation's marker.
    try:
        store.table().delete_item(Key={"PK": store.hh(hid), "SK": _marker(reason)},
                                  ConditionExpression="escalation_id = :e", ExpressionAttributeValues={":e": eid})
    except ClientError as e:
        if not store.is_conditional_failure(e):
            raise


def family_content(e: Escalation, person: Person) -> Content:
    rl = person.relation_label or ""
    ref = {"kind": "escalation", "id": e.escalation_id}
    if e.reason == "fall_or_help":
        quote = (e.quote or "")[:100]
        return Content(phrase="urgent_alert", quote=quote, vars={"relation_label": rl},
                       rcs_suggestions=[["label_on_it", f"esc:ack:{e.escalation_id}"]], sms_phrase="urgent_sms",
                       wa_template="aurasenior_urgent_alert", wa_params=[rl, quote], email_template="aurasenior-urgent",
                       ref=ref)
    return Content(phrase="missed_checkin", vars={"relation_label": rl},
                   rcs_suggestions=[["label_on_it", f"esc:ack:{e.escalation_id}"], ["label_send_number", "info:number"]],
                   sms_phrase="missed_checkin_sms", wa_template="aurasenior_family_missed", wa_params=[rl],
                   email_template="aurasenior-missed-checkin", ref=ref)


def _alert_family(hid: str, e: Escalation, run: int, *, email_too: bool = False) -> None:
    h = store.get_household(hid)
    for pid in h.escalation_order:
        p = store.get_person(hid, pid)
        if not p:
            continue
        c = family_content(e, p)
        cid = f"esc#{e.escalation_id}#{e.reason}#{run}#{pid}"
        r = router.send(p, c, urgency="urgent", correlation_id=cid)
        if email_too and r.channel != "email" and p.addresses.get("email") and p.consent_status("email") == "opted_in":
            router.send(p, c, urgency="urgent", correlation_id=f"{cid}#email", only_channel="email")


def _tell_elder(hid: str, phrase: str, eid: str, run: int, **vars) -> None:
    elder = store.elder(hid)
    router.send(elder, Content(phrase=phrase, vars=vars, voice=True), urgency="urgent",
                correlation_id=f"elder#{phrase}#{eid}#{run}")


def _first_alerts(hid: str, e: Escalation) -> None:
    """Run-0 sends and the first recheck. Safe to repeat: SEND# skips anyone already reached."""
    _alert_family(hid, e, 0)
    if e.reason == "fall_or_help":
        _tell_elder(hid, "esc_told_elder", e.escalation_id, 0,
                    family_name=router.names_for(hid).get("family_name", ""))
    if e.recheck_run == 0:
        schedules.create_recheck(hid, e.escalation_id, 1, store.get_household(hid).timezone)


def escalate(hid: str, reason: str, quote: str = "") -> str:
    """Idempotent: an open escalation for the same reason is returned. Its first alerts are re-run, which sends
    nothing new to people already reached, so a retry after a failed send completes the fan-out."""
    existing = _open(hid, reason)
    if existing:
        _first_alerts(hid, existing)
        return existing.escalation_id
    if reason == "fall_or_help":
        missed = _open(hid, "missed_checkin")
        if missed and store.transition(store.hh(hid), f"ESC#{missed.escalation_id}", "reason", "missed_checkin",
                                       "fall_or_help", quote=quote[:200]):
            store.table().delete_item(Key={"PK": store.hh(hid), "SK": _marker("missed_checkin")})
            if _claim(hid, "fall_or_help", missed.escalation_id):
                e = store.get_escalation(hid, missed.escalation_id)
                store.trace(hid, "escalate", reason="fall_or_help", outcome="upgraded", escalation_id=e.escalation_id)
                _first_alerts(hid, e)
                return e.escalation_id
    eid = store.new_id()
    if not _claim(hid, reason, eid):
        e = _open(hid, reason)
        return e.escalation_id if e else eid
    e = Escalation(hid, eid, reason, quote[:200], "open", clock.iso())
    store.put_escalation(e)
    store.trace(hid, "escalate", reason=reason, outcome="created", escalation_id=eid)
    _first_alerts(hid, e)
    return eid


def recheck_run(hid: str, eid: str, run: int) -> None:
    e = store.get_escalation(hid, eid)
    if not e or e.status != "open":
        return
    store.update(store.hh(hid), f"ESC#{eid}", recheck_run=run)
    names = router.names_for(hid)
    if e.reason == "fall_or_help":
        _tell_elder(hid, "esc_reassure_elder", eid, run, family_name=names.get("family_name", ""))
    if run % 2 == 0:
        _alert_family(hid, e, run, email_too=True)
    if run >= MAX_RUNS:
        store.transition(store.hh(hid), f"ESC#{eid}", "status", "open", "unacknowledged")
        _release(hid, e.reason, eid)
        store.trace(hid, "escalation", outcome="unacknowledged", escalation_id=eid)
        log.get().error("escalation unacknowledged", extra={"household_id": hid, "escalation_id": eid})
        return
    schedules.create_recheck(hid, eid, run + 1, store.get_household(hid).timezone)


def ack_escalation(hid: str, eid: str, by_pid: str) -> bool:
    e = store.get_escalation(hid, eid)
    by = store.get_person(hid, by_pid)
    if not e or not by or by.role not in ("family", "neighbour"):
        log.get().info("ack ignored", extra={"household_id": hid})
        return False
    if store.transition(store.hh(hid), f"ESC#{eid}", "status", "open", "acknowledged",
                        acknowledged_by=by_pid, acknowledged_at=clock.iso()):
        store.trace(hid, "ack", outcome="acknowledged", escalation_id=eid, person_id=by_pid)
    elif not (e.status == "acknowledged" and e.acknowledged_by == by_pid):
        return False
    # Also reached on a retry of the same ack: the notices below are SEND# deduped.
    _release(hid, e.reason, eid)
    schedules.delete_recheck(eid, e.recheck_run + 1)
    h = store.get_household(hid)
    for pid in h.escalation_order:
        if pid == by_pid:
            continue
        p = store.get_person(hid, pid)
        if p:
            note = phrases.render("esc_ack_family", p.language, ack_name=by.display_name)
            router.send(p, Content(phrase="esc_ack_family", vars={"ack_name": by.display_name},
                                   wa_template="aurasenior_family_update", wa_params=[p.relation_label or "", note],
                                   email_template="aurasenior-update", email_data={"update_text": note}),
                        urgency="urgent", correlation_id=f"ack#{eid}#{pid}")
    if e.reason == "fall_or_help":
        _tell_elder(hid, "esc_ack_elder", eid, 0, name=by.display_name)
    return True


def _resolved_by(hid: str, correlation_id: str) -> Escalation | None:
    for e in store.escalations(hid):
        if e.reason == "missed_checkin" and e.status == "resolved_by_elder" and e.resolved_cid == correlation_id:
            return e
    return None


def resolve_by_elder(hid: str, correlation_id: str = "") -> bool:
    """A late reply closes a missed check-in only. A fall always needs a person to check.
    A retry of the same inbound event finds the escalation it closed and re-runs the deduped notices."""
    e = _open(hid, "missed_checkin")
    if e and store.transition(store.hh(hid), f"ESC#{e.escalation_id}", "status", "open", "resolved_by_elder",
                              resolved_cid=correlation_id):
        store.trace(hid, "escalation", outcome="resolved_by_elder", escalation_id=e.escalation_id)
    else:
        e = _resolved_by(hid, correlation_id) if correlation_id else None
        if not e:
            return False
    _release(hid, "missed_checkin", e.escalation_id)
    schedules.delete_recheck(e.escalation_id, e.recheck_run + 1)
    h = store.get_household(hid)
    for pid in h.escalation_order:
        p = store.get_person(hid, pid)
        if p:
            rl = p.relation_label or ""
            late = phrases.render("checkin_late_family", p.language, relation_label=rl)
            router.send(p, Content(phrase="checkin_late_family", vars={"relation_label": rl},
                                   wa_template="aurasenior_family_update", wa_params=[rl, late],
                                   email_template="aurasenior-update", email_data={"update_text": late}),
                        correlation_id=f"late#{e.escalation_id}#{pid}")
    return True


def open_escalations(hid: str) -> list[Escalation]:
    return [e for e in store.escalations(hid) if e.status == "open"]
