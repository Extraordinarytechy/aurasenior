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


def _is_checkin(m: dict) -> bool:
    """The check-in template or voice note (scheduled, or the voice note sent when she taps Listen)."""
    return ((m.get("ref") or {}) == {"kind": "listen", "id": "checkin"}
            or (m.get("content") or {}).get("phrase") == "checkin_voice")


def _checkin_yes(person: Person, correlation_id: str) -> str | None:
    """A bare yes right after today's check-in ("have you taken your tablet?") and before that medicine was
    logged: log it as taken and return its display label. The check-in asks about the first morning medicine only.
    The latest message sent to her must be the check-in itself: a yes to the follow-up ("are you okay?") or to
    any later question is not a tablet answer."""
    hid = person.household_id
    tz = store.get_household(hid).timezone
    today = clock.local_date(tz)
    morning = [m for m in store.medicines(hid) if m.time_of_day == "morning"]
    if not morning or any(x["medicine_id"] == morning[0].medicine_id for x in store.logs_between(hid, today, today)):
        return None
    outs = [m for m in store.query_prefix(hid, "MSG#")
            if m.get("person_id") == person.person_id and m.get("direction") == "out"]
    if not outs:
        return None
    last_at = max(m["at"] for m in outs)
    latest = [m for m in outs if m["at"] == last_at]  # same-second sends: all of them must be the check-in
    if (clock.parse(last_at).astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d") != today
            or not all(_is_checkin(m) for m in latest)):
        return None
    store.log_medicine(hid, morning[0].medicine_id, today, taken=True, source_msg=correlation_id)
    store.trace(hid, "medicine", person_id=person.person_id, medicine_id=morning[0].medicine_id,
                outcome="taken_from_checkin_yes")
    return morning[0].display_label


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
        logged = person.is_elder and keywords.is_yes(text, lang) and _checkin_yes(person, correlation_id)
        if logged:
            outcome = "checkin_yes"
        store.trace(person.household_id, "consent", person_id=person.person_id, channel=channel,
                    outcome=outcome, simulated=simulated)
        # Say back what was logged, so she can correct it with her next message.
        c = (Content(phrase="checkin_yes_logged", vars={"display_label": logged}, voice=voice) if logged else
             Content(phrase="consent_ack", vars={"relation_label": person.relation_label or ""},
                     voice=voice and person.is_elder))
        router.send(person, c, correlation_id=correlation_id, inbound_text=text, only_channel=channel)
        return True
    if status != "opted_in":
        if channel == "whatsapp":
            _ask(person, channel, text, correlation_id)  # the guard allows this at most once a day
        return True
    return False
