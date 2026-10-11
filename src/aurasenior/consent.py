"""Opt-in and STOP. WhatsApp opt-in is always started by the person; consent changes are traced with source."""
from __future__ import annotations

from . import keywords, router, store
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


def handle(person: Person, channel: str, text: str, *, correlation_id: str, simulated: bool = False) -> bool:
    """True when the message was a consent message (or the person is not opted in) and nothing else should run."""
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
            source = "sms_sim_inbound_yes" if simulated else "rcs_inbound_yes"
        store.set_consent(person.household_id, person.person_id, channel, "opted_in", source, simulated)
        p = store.get_person(person.household_id, person.person_id)
        router.send(p, Content(phrase="optin_done", vars={"relation_label": p.relation_label or ""}),
                    correlation_id=correlation_id, only_channel=channel)
        return True
    if status != "opted_in":
        if channel == "whatsapp":
            _ask(person, channel, text, correlation_id)  # the guard allows this at most once a day
        return True
    return False
