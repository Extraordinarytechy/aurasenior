"""Turns RCS postbacks, SMS digits and WhatsApp button taps into one "<action>:<id>" form."""
from __future__ import annotations

import re

from . import phrases, store
from .channels.base import InboundMessage
from .models import Person

PATTERN = re.compile(r"^(refill:(approve|self|call)|esc:ack):[a-z0-9]{12}$")
DIGITS = {"1": "refill:approve", "2": "refill:self", "3": "info:number", "4": "esc:ack"}


def _newest_pending_approval(hid: str, pid: str) -> str | None:
    items = sorted((a for a in store.approvals(hid) if a.status == "pending" and a.ask_person_id == pid),
                   key=lambda a: a.created_at)
    return items[-1].approval_id if items else None


def _newest_open_escalation(hid: str) -> str | None:
    items = sorted((e for e in store.escalations(hid) if e.status == "open"), key=lambda e: e.created_at)
    return items[-1].escalation_id if items else None


def parse_postback(data: str) -> tuple[str, str | None] | None:
    if data == "info:number":
        return "info:number", None
    if PATTERN.match(data or ""):
        action, _, ident = data.rpartition(":")
        return action, ident
    return None


def digit(sender: Person, text: str) -> tuple[str, str | None] | None | str:
    """Returns (action, id), "help" for a digit with no target, or None when the text is not a digit."""
    t = text.strip()
    if t not in DIGITS:
        return None
    action = DIGITS[t]
    if action == "info:number":
        return action, None
    if action == "esc:ack":
        eid = _newest_open_escalation(sender.household_id)
        return (action, eid) if eid else "help"
    aid = _newest_pending_approval(sender.household_id, sender.person_id)
    return (action, aid) if aid else "help"


def whatsapp_button(sender: Person, m: InboundMessage) -> tuple[str, str | None] | str | None:
    action = phrases.action_for_label(m.button_payload or "", sender.language)
    if not action:
        return None
    ref = None
    if m.context_id:
        msg = store.get_msg(sender.household_id, m.context_id)
        ref = (msg or {}).get("ref")
    if action == "listen":
        which = (ref or {}).get("id", "checkin")
        return f"listen:{which}", None
    if action == "info:number":
        return action, None
    if ref and ref.get("id"):
        full = f"{action}:{ref['id']}"
        parsed = parse_postback(full)
        return parsed if parsed else None
    reverse = {v: k for k, v in DIGITS.items()}
    return digit(sender, reverse.get(action, ""))
