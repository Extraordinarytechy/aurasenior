"""Outbound guard: the one choke point every send crosses (consent, WhatsApp window, wording, rate)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from . import clock, config, keywords, log, phrases, store, wording
from .channels.base import OutboundMessage
from .models import Person

WINDOW = timedelta(hours=23, minutes=30)
OPTIN_KEYS = {"optin_ask", "optin_ask_admin"}
URGENT_KEYS = {"urgent_alert", "urgent_sms", "aurasenior_urgent_alert", "aurasenior-urgent"}


@dataclass
class Allowed:
    message: OutboundMessage
    exemption: str | None = None
    replaced: str | None = None  # wording rule that caused a replacement
    ok: bool = True


@dataclass
class Blocked:
    reason: str  # blocked_consent, blocked_window, blocked_rate
    ok: bool = False


def window_open(person: Person) -> bool:
    if not person.wa_last_inbound_at:
        return False
    return clock.now() - clock.parse(person.wa_last_inbound_at) < WINDOW


def _household_date(person: Person) -> str:
    """Once-a-day limits use the household's local day, like the USAGE# counters."""
    h = store.get_household(person.household_id)
    return clock.local_date(h.timezone if h else "UTC")


def _exemption(person: Person, channel: str, msg: OutboundMessage, inbound_text: str | None,
               rcs_verified: bool) -> str | None:
    """Consent exemptions are decided here from the phrase key, never from a caller flag."""
    status = person.consent_status(channel)
    key = msg.phrase_key
    if key in OPTIN_KEYS and status in ("pending", "opted_out"):
        replying = inbound_text is not None and (status == "pending" or keywords.is_start(inbound_text, person.language))
        if replying or (channel == "rcs" and rcs_verified):
            local = _household_date(person)
            if store.set_usage_flag(person.household_id, local, f"optin_{person.person_id}_{channel}"):
                return "optin_ask"
        return None
    if key == "stop_confirm" and status == "opted_out" and inbound_text is not None:
        if keywords.is_stop(inbound_text, person.language):
            src = person.consent.get(channel, {}).get("at", "")
            if store.set_usage_flag(person.household_id, _household_date(person), f"stopc_{person.person_id}_{channel}_{src}"):
                return "stop_confirm"
    return None


def _is_urgent_template(msg: OutboundMessage) -> bool:
    name = (msg.template or "").rsplit("_", 1)[0] if msg.template and msg.template.startswith("aurasenior_") else msg.template
    return msg.phrase_key in URGENT_KEYS or name in URGENT_KEYS


def _replace_wording(person: Person, msg: OutboundMessage, rule: str, names: dict) -> OutboundMessage:
    log.get().warning("wording rule replaced a message", extra={"rule": rule, "person_id": person.person_id})
    text = phrases.render("guard_replacement", person.language, person.audience,
                          family_name=names.get("family_name", ""), elder_name=names.get("elder_name", ""))
    return OutboundMessage(**{**msg.__dict__, "kind": "voice" if msg.kind == "voice" else "text", "text": text,
                              "template": None, "template_params": [], "card": None, "suggestions": [],
                              "sms_fallback": text, "phrase_key": "guard_replacement"})


def guard(person: Person, channel: str, msg: OutboundMessage, *, inbound_text: str | None = None,
          rcs_verified: bool = False, names: dict | None = None):
    names = names or {}
    # 1. Consent
    exemption = None
    if person.consent_status(channel) != "opted_in":
        exemption = _exemption(person, channel, msg, inbound_text, rcs_verified)
        if not exemption:
            return Blocked("blocked_consent")
    # 2. WhatsApp window: free-form only inside it
    if channel == "whatsapp" and msg.kind != "template" and not window_open(person):
        return Blocked("blocked_window")
    # 3. Wording
    replaced = None
    if _is_urgent_template(msg):
        quote = msg.template_data.get("quote", "")
        if quote and wording.check(quote, person.language):
            withheld = phrases.render("quote_withheld", person.language)
            msg = _swap_quote(msg, quote, withheld)
            replaced = "quote"
    else:
        visible = " ".join([msg.text, msg.sms_fallback, " ".join(msg.template_params)]
                           + ([msg.card.get("title", ""), msg.card.get("description", "")] if msg.card else []))
        rule = wording.check(visible, person.language)
        if rule:
            if exemption:
                return Blocked("blocked_wording")
            msg = _replace_wording(person, msg, rule, names)
            replaced = rule
    # 4. Rate (normal urgency only; urgent sends are never counted or capped)
    if msg.urgency == "normal":
        h = store.get_household(person.household_id)
        tz = h.timezone if h else "UTC"
        now = clock.local_now(tz)
        n = store.incr_normal(person.household_id, now.strftime("%Y-%m-%d"), now.strftime("%H"))
        if n > config.limits()["normal_per_hour"]:
            log.get().warning("hourly send cap reached", extra={"household_id": person.household_id})
            return Blocked("blocked_rate")
    return Allowed(msg, exemption, replaced)


def _swap_quote(msg: OutboundMessage, quote: str, withheld: str) -> OutboundMessage:
    data = {**msg.template_data, "quote": withheld}
    return OutboundMessage(**{**msg.__dict__, "text": msg.text.replace(quote, withheld),
                              "sms_fallback": msg.sms_fallback.replace(quote, withheld),
                              "template_params": [withheld if p == quote else p for p in msg.template_params],
                              "template_data": data})
