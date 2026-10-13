"""Opt-in and STOP. WhatsApp opt-in is always started by the person; consent changes are traced with source."""
from __future__ import annotations

from zoneinfo import ZoneInfo

from . import clock, keywords, router, store
from .models import Person
from .router import Content


def _names(person: Person) -> dict:
    n = router.names_for(person.household_id)
    h = store.get_household(person.household_id)
    admin = store.get_person(person.household_id, h.admin_person_id)
    return {"family_name": n.get("family_name", ""), "admin_name": admin.display_name if admin else "",
            "relation_label": person.relation_label or ""}


def _ask(person: Person, channel: str, text: str | None, cid: str, rcs_verified: bool = False):
    h = store.get_household(person.household_id)
    key = "optin_ask_admin" if person.person_id == h.admin_person_id and not person.is_elder else "optin_ask"
    return router.send(person, Content(phrase=key, vars=_names(person), voice=person.is_elder),
                       correlation_id=cid, inbound_text=text, rcs_verified=rcs_verified, only_channel=channel)


def _checkin_yes(person: Person, correlation_id: str) -> bool:
    """A bare yes after today's check-in went out ("have you taken your tablet?") and before that medicine was
    logged: log it as taken. The check-in asks about the first morning medicine only."""
    hid = person.household_id
    tz = store.get_household(hid).timezone
    today = clock.local_date(tz)
    morning = [m for m in store.medicines(hid) if m.time_of_day == "morning"]
    if not morning or any(x["medicine_id"] == morning[0].medicine_id for x in store.logs_between(hid, today, today)):
        return False
    asked = any(m.get("person_id") == person.person_id and (m.get("ref") or {}) == {"kind": "listen", "id": "checkin"}
                and clock.parse(m["at"]).astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d") == today
                for m in store.query_prefix(hid, "MSG#"))
    if not asked:
        return False
    store.log_medicine(hid, morning[0].medicine_id, today, taken=True, source_msg=correlation_id)
    store.trace(hid, "medicine", person_id=person.person_id, medicine_id=morning[0].medicine_id,
                outcome="taken_from_checkin_yes")
    return True


def handle(person: Person, channel: str, text: str, *, correlation_id: str, simulated: bool = False,
           voice: bool = False) -> bool:
    """True when the message was a consent message (or the person is not opted in) and nothing else should run.
    voice: the message was a voice note, so the elder's acknowledgement is spoken too."""
    lang = person.language
    status = person.consent_status(channel)
    if keywords.is_stop(text, lang):
        store.set_consent(person.household_id, person.person_id, channel, "opted_out",
                          f"{'wa' if channel == 'whatsapp' else channel}_inbound_stop", simulated)
        if channel == "whatsapp":
            p = store.get_person(person.household_id, person.person_id)
            router.send(p, Content(phrase="stop_confirm"), correlation_id=correlation_id, inbound_text=text,
                        only_channel=channel)
        return True
    if keywords.is_start(text, lang) and status != "opted_in":
        _ask(person, channel, text, correlation_id)
        return True
    if keywords.is_yes(text, lang) and status != "opted_in":
        if channel == "whatsapp":
            source = "wa_inbound_yes"
        else:
            # Only the SMS simulator record gets the simulator source; "simulated" alone just labels the trace.
            source = "sms_sim_inbound_yes" if person.simulated else f"{channel}_inbound_yes"
        store.set_consent(person.household_id, person.person_id, channel, "opted_in", source, simulated)
        p = store.get_person(person.household_id, person.person_id)
        router.send(p, Content(phrase="optin_done", vars={"relation_label": p.relation_label or ""}),
                    correlation_id=correlation_id, only_channel=channel)
        return True
    if status == "opted_in" and (keywords.is_yes(text, lang) or keywords.is_start(text, lang)):
        # A bare YES or START carries no new information: a model turn would only act again on old context.
        # The one exception is the elder's bare yes to this morning's tablet question, logged here.
        outcome = "already_opted_in"
        if person.is_elder and keywords.is_yes(text, lang) and _checkin_yes(person, correlation_id):
            outcome = "checkin_yes"
        store.trace(person.household_id, "consent", person_id=person.person_id, channel=channel,
                    outcome=outcome, simulated=simulated)
        router.send(person, Content(phrase="consent_ack", vars={"relation_label": person.relation_label or ""},
                                    voice=voice and person.is_elder),
                    correlation_id=correlation_id, inbound_text=text, only_channel=channel)
        return True
    if status != "opted_in":
        if channel == "whatsapp":
            _ask(person, channel, text, correlation_id)  # the guard allows this at most once a day
        return True
    return False
