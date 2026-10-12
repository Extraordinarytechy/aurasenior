"""Send on the preferred channel, fall back on failure, and record every decision in the trace."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from . import channels, clock, dedupe, log, phrases, schedules, store
from .channels.base import OutboundMessage
from .models import Person
from .outbound import Allowed, guard, window_open


class RetryableSendError(Exception):
    """A provider throttled or failed with 5xx: the event is retried by Lambda, SEND# stops repeats."""


@dataclass
class Content:
    """What to say, with the per-channel forms. Text comes from phrases.toml unless text is given."""

    phrase: str | None = None
    vars: dict = field(default_factory=dict)
    text: str | None = None
    voice: bool = False
    wa_template: str | None = None
    wa_params: list[str] = field(default_factory=list)
    rcs_card: dict | None = None  # {"title": phrase, "description": phrase, "suggestions": [[label_phrase, postback]]}
    rcs_suggestions: list[list[str]] = field(default_factory=list)
    sms_phrase: str | None = None
    email_template: str | None = None
    email_data: dict = field(default_factory=dict)
    ref: dict | None = None
    quote: str | None = None


@dataclass
class RouteResult:
    outcome: str  # sent, blocked_consent, blocked_window, blocked_rate, blocked_wording, failed, undeliverable, skipped
    channel: str | None = None
    provider_id: str | None = None
    simulated: bool = False
    replaced: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome in ("sent", "skipped")

    @property
    def went_out(self) -> bool:
        """Sent now or by an earlier attempt. A skipped send without a provider id failed before or is in flight."""
        return self.outcome == "sent" or (self.outcome == "skipped" and bool(self.provider_id))


def names_for(hid: str) -> dict:
    h = store.get_household(hid)
    if not h:
        return {}
    elder = store.get_person(hid, h.elder_person_id)
    first = store.get_person(hid, h.escalation_order[0]) if h.escalation_order else None
    return {"elder_name": elder.display_name if elder else "", "family_name": first.display_name if first else "",
            "relation_label": (first.relation_label if first else "") or ""}


def _render(person: Person, key: str, vars: dict) -> str:
    return phrases.render(key, person.language, person.audience, **vars)


def build(person: Person, channel: str, c: Content, correlation_id: str, urgency: str) -> OutboundMessage | None:
    addr = person.addresses.get(channel)
    if not addr:
        return None
    vars = {**c.vars}
    if c.quote is not None:
        vars["quote"] = c.quote
    base = dict(person_id=person.person_id, to=addr, language=person.language, urgency=urgency,
                correlation_id=correlation_id, household_id=person.household_id, phrase_key=c.phrase)
    body = c.text if c.text is not None else (_render(person, c.phrase, vars) if c.phrase else "")
    data = {"quote": c.quote} if c.quote is not None else {}
    if channel == "whatsapp":
        if window_open(person) and body:
            return OutboundMessage(kind="voice" if c.voice else "text", text=body, template_data=data, **base)
        if c.wa_template:
            t = phrases.template(c.wa_template, person.language)
            shown = phrases.template_body(c.wa_template, person.language, c.wa_params)
            return OutboundMessage(kind="template", text=shown, template=t["name"], template_params=list(c.wa_params),
                                   template_data=data, **base)
        # No template fits outside the window: the guard reports blocked_window.
        return OutboundMessage(kind="voice" if c.voice else "text", text=body, template_data=data, **base)
    if channel in ("rcs", "sms"):
        sms = _render(person, c.sms_phrase, vars) if c.sms_phrase else body
        if channel == "sms":
            return OutboundMessage(kind="text", text=sms, template_data=data, **base)
        if c.rcs_card:
            card = {"title": _render(person, c.rcs_card["title"], vars),
                    "description": _render(person, c.rcs_card["description"], vars),
                    "suggestions": [(_render(person, lbl, vars), pb) for lbl, pb in c.rcs_card["suggestions"]]}
            return OutboundMessage(kind="card", text=card["title"], card=card, sms_fallback=sms, template_data=data,
                                   **base)
        sugg = [(_render(person, lbl, vars), pb) for lbl, pb in c.rcs_suggestions]
        return OutboundMessage(kind="text", text=body, suggestions=sugg, sms_fallback=sms, template_data=data, **base)
    if channel == "email":
        if not c.email_template:
            return None
        h = store.get_household(person.household_id)
        tdata = {**{k: str(v) for k, v in vars.items()}, **c.email_data}
        tdata.setdefault("relation_label", person.relation_label or "")
        if h:
            tdata.setdefault("elder_name", names_for(person.household_id).get("elder_name", ""))
        return OutboundMessage(kind="email_template", text=body, template=c.email_template, template_data=tdata,
                               list_management=c.email_template in ("aurasenior-weekly-summary", "aurasenior-update"),
                               **base)
    return None


def _deliver(person: Person, channel: str, msg: OutboundMessage, c: Content, urgency: str,
             correlation_id: str) -> RouteResult:
    adapter = channels.get(channel)
    holder: dict = {}

    def do_send():
        r = adapter.send(msg)
        holder["r"] = r
        if not r.ok and r.retryable:
            raise RetryableSendError(r.code)
        return r.provider_id if r.ok else None

    ran, provider_id = dedupe.send_once(person.household_id, correlation_id, do_send)
    if not ran:
        return RouteResult("skipped", channel, provider_id, adapter.simulated)
    r = holder["r"]
    if not r.ok:
        log.get().error("send failed", extra={"channel": channel, "code": r.code, "person_id": person.person_id})
        store.trace(person.household_id, "send", channel=channel, person_id=person.person_id, outcome="failed",
                    code=r.code, phrase=c.phrase, simulated=adapter.simulated)
        return RouteResult("failed", channel, simulated=adapter.simulated)
    store.put_msg(person.household_id, r.provider_id, channel=channel, person_id=person.person_id,
                  correlation_id=correlation_id, ref=c.ref, kind=msg.kind, urgency=urgency,
                  content=_content_record(c), simulated=adapter.simulated)
    store.trace(person.household_id, "send", channel=channel, person_id=person.person_id, outcome="sent",
                kind=msg.kind, phrase=c.phrase or (None if msg.template else "model_text"), template=msg.template,
                text=msg.text[:300], urgency=urgency, simulated=adapter.simulated)
    receipt = getattr(adapter, "receipt", None) if adapter.simulated else None
    status = receipt() if receipt else None
    if status:
        on_status(person.household_id, r.provider_id, status)  # simulator receipt; real ones arrive by SNS
    return RouteResult("sent", channel, r.provider_id, adapter.simulated)


def _content_record(c: Content) -> dict:
    return {k: v for k, v in asdict(c).items() if v not in (None, [], {}, False, "")}


def send(person: Person, c: Content, *, urgency: str = "normal", correlation_id: str,
         inbound_text: str | None = None, rcs_verified: bool = False, only_channel: str | None = None) -> RouteResult:
    names = names_for(person.household_id)
    order = [only_channel] if only_channel else [person.preferred_channel]
    if not only_channel and person.fallback_channel not in ("none", "", None):
        order.append(person.fallback_channel)
    result = RouteResult("undeliverable")
    for i, channel in enumerate(order):
        cid = correlation_id if i == 0 else f"{correlation_id}#fb"
        if i > 0 and person.consent_status(channel) != "opted_in":
            store.trace(person.household_id, "fallback", channel=channel, person_id=person.person_id,
                        outcome="blocked_consent")
            return RouteResult("blocked_consent", channel)
        msg = build(person, channel, c, cid, urgency)
        if msg is None:
            result = RouteResult("blocked_window" if channel == "whatsapp" else "undeliverable", channel)
            continue
        g = guard(person, channel, msg, inbound_text=inbound_text, rcs_verified=rcs_verified, names=names)
        if not isinstance(g, Allowed):
            store.trace(person.household_id, "guard", channel=channel, person_id=person.person_id, outcome=g.reason,
                        phrase=c.phrase)
            result = RouteResult(g.reason, channel)
            if g.reason in ("blocked_consent", "blocked_window"):
                continue
            return result
        result = _deliver(person, channel, g.message, c, urgency, cid)
        result.replaced = g.replaced
        if result.outcome == "skipped" and result.provider_id == "" and i + 1 < len(order):
            # The earlier attempt failed on this channel; its fallback has its own SEND# row.
            continue
        if result.outcome in ("sent", "skipped"):
            if result.outcome == "sent" and urgency == "urgent" and i == 0 and len(order) > 1:
                tz = (store.get_household(person.household_id).timezone)
                schedules.create_delivery_check(person.household_id, cid, tz)
            return result
    if result.outcome in ("undeliverable",) or (len(order) == 1 and not result.ok):
        log.get().warning("message undeliverable", extra={"person_id": person.person_id, "outcome": result.outcome})
        store.trace(person.household_id, "route", person_id=person.person_id, outcome=result.outcome or "undeliverable")
    return result


def _content_from(record: dict) -> Content:
    return Content(**{k: v for k, v in record.items() if k in Content.__dataclass_fields__})


def on_status(hid: str, provider_id: str, status: str) -> None:
    if not store.append_status(hid, provider_id, status):
        return
    msg = store.get_msg(hid, provider_id)
    store.trace(hid, "status", channel=msg["channel"], person_id=msg["person_id"], outcome=status,
                simulated=bool(msg.get("simulated")))
    if status == "failed":
        _fallback(hid, msg)


def _fallback(hid: str, msg: dict) -> RouteResult | None:
    person = store.get_person(hid, msg["person_id"])
    fb = person.fallback_channel if person else "none"
    if not person or fb in ("none", "", None) or fb == msg["channel"]:
        log.get().warning("no fallback channel", extra={"person_id": msg["person_id"]})
        store.trace(hid, "route", person_id=msg["person_id"], outcome="undeliverable")
        return None
    if person.consent_status(fb) != "opted_in":
        store.trace(hid, "fallback", channel=fb, person_id=person.person_id, outcome="blocked_consent")
        return None
    return send(person, _content_from(msg.get("content", {})), urgency=msg.get("urgency", "normal"),
                correlation_id=f"{msg['correlation_id']}#fb", only_channel=fb)


def delivery_check_run(hid: str, correlation_id: str) -> None:
    msgs = store.msgs_by_correlation(hid, correlation_id)
    if not msgs:
        return
    if any(m.get("last_status") in ("delivered", "read") for m in msgs):
        store.trace(hid, "delivery_check", outcome="delivered", simulated=bool(msgs[0].get("simulated")))
        return
    store.trace(hid, "delivery_check", outcome="no_delivery", simulated=bool(msgs[0].get("simulated")))
    _fallback(hid, msgs[0])


def now_iso() -> str:
    return clock.iso()
