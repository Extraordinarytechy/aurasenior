"""Refill approval: the model can only ask; ordering is plain code after a person taps Order refill."""
from __future__ import annotations

from datetime import timedelta

from . import clock, log, router, schedules, store
from .models import Approval
from .router import Content


RECENT_HOURS = 24


def open_request(hid: str, medicine_id: str) -> Approval | None:
    """A pending request, or one family approved, ordered or took on themselves in the last day (the order or
    their own errand may still be on the way)."""
    since = clock.iso(clock.now() - timedelta(hours=RECENT_HOURS))
    for a in sorted(store.approvals(hid), key=lambda x: x.created_at, reverse=True):
        if a.medicine_id != medicine_id:
            continue
        if a.status == "pending" or (a.status in ("approved", "ordered", "self") and (a.handled_at or "") >= since):
            return a
    return None


def state(hid: str, medicine_id: str) -> dict:
    """The refill of this medicine as tools report it, so the model never has to guess whether family was asked."""
    a = open_request(hid, medicine_id)
    if not a:
        return {"approval_status": "none"}
    return {"approval_status": a.status, "ask_person_id": a.ask_person_id,
            "asked": a.status != "pending" or _card_went_out(hid, a.approval_id)}


def elder_line(hid: str, a: Approval, voice: bool) -> Content | None:
    """The fixed line that tells the elder where this refill really stands, or None when family was not asked."""
    med = store.get_medicine(hid, a.medicine_id)
    family = store.get_person(hid, a.ask_person_id)
    if not med or not family:
        return None
    phrase = {"ordered": "refill_ordered_elder", "self": "refill_self_elder",
              "approved": "refill_asked_elder"}.get(a.status)
    if a.status == "pending" and _card_went_out(hid, a.approval_id):
        phrase = "refill_asked_elder"
    if not phrase:
        return None
    return Content(phrase=phrase, voice=voice,
                   vars={"family_name": family.display_name, "display_label": med.display_label})


def request_refill_approval(hid: str, medicine_id: str, ask_person_id: str, *, correlation_id: str) -> dict:
    med = store.get_medicine(hid, medicine_id)
    asked = store.get_person(hid, ask_person_id)
    if not med or not asked or asked.role != "family":
        return {"status": "error", "reason": "unknown medicine or person is not family"}
    existing = open_request(hid, medicine_id)
    if existing:
        # Same medicine already asked about: no second card and no second expiry schedule.
        return {"status": "ok", "approval_id": existing.approval_id, "note": "already asked",
                "approval_status": existing.status, "ask_person_id": existing.ask_person_id,
                "asked": existing.status != "pending" or _card_went_out(hid, existing.approval_id)}
    aid = store.new_id()
    now = clock.iso()
    store.put_approval(Approval(hid, aid, "refill", medicine_id, "pending", ask_person_id, now, ran_out_at=now))
    rl = asked.relation_label or ""
    c = Content(phrase="refill_approval_title", vars={"relation_label": rl, "display_label": med.display_label},
                rcs_card={"title": "refill_approval_title", "description": "refill_approval_desc",
                          "suggestions": [["label_order_refill", f"refill:approve:{aid}"],
                                          ["label_self", f"refill:self:{aid}"],
                                          ["label_call", f"refill:call:{aid}"]]},
                sms_phrase="refill_sms", wa_template="aurasenior_family_refill", wa_params=[rl, med.display_label],
                email_template="aurasenior-refill-request", email_data={"display_label": med.display_label},
                ref={"kind": "approval", "id": aid})
    r = router.send(asked, c, correlation_id=correlation_id)
    schedules.create_approval_expiry(hid, aid, store.get_household(hid).timezone)
    store.trace(hid, "refill", outcome="approval_requested", approval_id=aid, person_id=ask_person_id)
    # "asked" is what the elder may be told: the card really went out to the family member.
    return {"status": "ok", "approval_id": aid, "send": r.outcome, "ask_person_id": ask_person_id,
            "asked": r.went_out}


def _card_went_out(hid: str, aid: str) -> bool:
    return any((m.get("ref") or {}).get("id") == aid for m in store.query_prefix(hid, "MSG#"))


def _elder_number(hid: str, to_pid: str, cid: str) -> None:
    p = store.get_person(hid, to_pid)
    elder = store.elder(hid)
    router.send(p, Content(phrase="elder_number", vars={"relation_label": p.relation_label or "",
                                                       "number": elder.addresses.get("whatsapp", "")}),
                correlation_id=cid)


def _help(hid: str, pid: str, cid: str) -> None:
    p = store.get_person(hid, pid)
    router.send(p, Content(phrase="sms_help"), correlation_id=cid)


def handle_action(hid: str, sender_pid: str, action: str, target: str | None, *, correlation_id: str) -> str:
    from . import escalation

    if action == "info:number":
        _elder_number(hid, sender_pid, correlation_id)
        return "number_sent"
    if action == "esc:ack":
        return "acknowledged" if target and escalation.ack_escalation(hid, target, sender_pid) else "ignored"
    a = store.get_approval(hid, target) if target else None
    if not a or a.ask_person_id != sender_pid:
        log.get().info("refill tap ignored", extra={"household_id": hid})
        return "ignored"
    if action == "refill:call":
        _elder_number(hid, sender_pid, correlation_id)
        return "number_sent"
    new = {"refill:approve": "approved", "refill:self": "self"}.get(action)
    if not new:
        _help(hid, sender_pid, correlation_id)
        return "already_handled"
    if store.transition(store.hh(hid), f"APPROVAL#{a.approval_id}", "status", "pending", new,
                        handled_at=clock.iso(), handled_cid=correlation_id):
        store.trace(hid, "refill", outcome=new, approval_id=a.approval_id, person_id=sender_pid)
    elif not (a.handled_cid == correlation_id and _done_states(new, a.status)):
        _help(hid, sender_pid, correlation_id)
        return "already_handled"
    # Also reached on a retry of the same tap: the sends below are SEND# deduped.
    schedules.delete_approval_expiry(a.approval_id)
    if new == "approved":
        return send_pharmacy_order(hid, a.approval_id, correlation_id=correlation_id)
    med = store.get_medicine(hid, a.medicine_id)
    sender = store.get_person(hid, sender_pid)
    router.send(store.elder(hid), Content(phrase="refill_self_elder", voice=True,
                                          vars={"family_name": sender.display_name, "display_label": med.display_label}),
                correlation_id=f"{correlation_id}#elder")
    return "self"


def _done_states(new: str, status: str) -> bool:
    return status in (("approved", "ordered") if new == "approved" else ("self",))


def send_pharmacy_order(hid: str, aid: str, *, correlation_id: str) -> str:
    """Plain code, never a model tool. Only runs after a person approved; "ordered" means a retry finishing."""
    a = store.get_approval(hid, aid)
    if not a or a.status not in ("approved", "ordered"):
        log.get().warning("pharmacy order skipped", extra={"household_id": hid})
        return "not_approved"
    med = store.get_medicine(hid, a.medicine_id)
    pharmacy = store.get_person(hid, med.pharmacy_person_id)
    approver = store.get_person(hid, a.ask_person_id)
    elder = store.elder(hid)
    data = {"pharmacy_name": pharmacy.display_name, "medicine_name": med.name, "elder_name": elder.display_name,
            "approver_name": approver.display_name, "approved_at": a.handled_at or clock.iso()}
    r = router.send(pharmacy, Content(text=f"Refill request for {elder.display_name}", email_template="aurasenior-refill-order",
                                      email_data=data), correlation_id=f"{correlation_id}#order", only_channel="email")
    if not r.went_out:
        log.get().error("pharmacy order email not sent", extra={"household_id": hid, "outcome": r.outcome})
        router.send(approver, Content(phrase="refill_order_failed"), correlation_id=f"{correlation_id}#failed")
        return "order_failed"
    if store.transition(store.hh(hid), f"APPROVAL#{aid}", "status", "approved", "ordered", ordered_at=clock.iso()):
        store.set_stock(hid, med.medicine_id, "ordered")
        store.trace(hid, "refill", outcome="ordered", approval_id=aid, channel="email", simulated=r.simulated)
    router.send(elder, Content(phrase="refill_ordered_elder", voice=True,
                               vars={"family_name": approver.display_name, "display_label": med.display_label},
                               wa_template="aurasenior_refill_update",
                               wa_params=[elder.display_name, med.display_label, approver.display_name]),
                correlation_id=f"{correlation_id}#elder")
    router.send(approver, Content(phrase="refill_ordered_family",
                                  vars={"pharmacy_name": pharmacy.display_name, "relation_label": approver.relation_label or "",
                                        "display_label": med.display_label}),
                correlation_id=f"{correlation_id}#family")
    return "ordered"


def expiry_run(hid: str, aid: str) -> None:
    a = store.get_approval(hid, aid)
    if not a or not store.transition(store.hh(hid), f"APPROVAL#{aid}", "status", "pending", "expired"):
        return
    med = store.get_medicine(hid, a.medicine_id)
    p = store.get_person(hid, a.ask_person_id)
    store.trace(hid, "refill", outcome="expired", approval_id=aid)
    router.send(p, Content(phrase="refill_expired", vars={"relation_label": p.relation_label or "",
                                                         "display_label": med.display_label}),
                correlation_id=f"expiry#{aid}")
