"""Payload parsers shared by the AWS adapters and the simulators.

WhatsApp: End User Messaging Social publishes an SNS message whose whatsAppWebhookEntry field holds the Meta
webhook entry as a JSON string. SMS and RCS: the two-way SMS payload and the configuration set event records.
SES: configuration set event records. Unknown shapes return None.
"""
from __future__ import annotations

import json
from typing import Any

from .base import InboundMessage, StatusEvent

_WA_STATUS = {"sent": "sent", "delivered": "delivered", "read": "read", "failed": "failed"}
_SMS_STATUS = {"TEXT_DELIVERED": "delivered", "TEXT_SUCCESSFUL": "delivered", "RCS_DELIVERED": "delivered",
               "RCS_READ": "read", "TEXT_SENT": "sent", "RCS_SENT": "sent", "TEXT_FAILED": "failed",
               "RCS_FAILED": "failed", "TEXT_BLOCKED": "failed", "TEXT_INVALID": "failed",
               "TEXT_UNREACHABLE": "failed", "TEXT_CARRIER_UNREACHABLE": "failed", "TEXT_TTL_EXPIRED": "failed"}
_SES_STATUS = {"Delivery": "delivered", "Send": "sent", "Bounce": "failed", "Reject": "failed",
               "RenderingFailure": "failed", "Open": "read", "Complaint": "failed"}


def e164(number: str | None) -> str:
    if not number:
        return ""
    digits = "".join(c for c in number if c.isdigit())
    return "+" + digits if digits else ""


def _loads(s: Any) -> Any:
    if isinstance(s, (dict, list)):
        return s
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return None


def _wa_value(raw: dict) -> dict | None:
    entry = _loads(raw.get("whatsAppWebhookEntry"))
    if not isinstance(entry, dict):
        return None
    for change in entry.get("changes", []):
        if change.get("field") == "messages" and isinstance(change.get("value"), dict):
            return change["value"]
    return None


def whatsapp_inbound(raw: dict) -> InboundMessage | None:
    value = _wa_value(raw)
    if not value or not value.get("messages"):
        return None
    m = value["messages"][0]
    base = {"channel": "whatsapp", "event_id": m.get("id", ""), "sender": e164(m.get("from")), "raw": raw,
            "context_id": (m.get("context") or {}).get("id")}
    t = m.get("type")
    if t == "text":
        return InboundMessage(text=m.get("text", {}).get("body", ""), kind="text", **base)
    if t == "audio":
        a = m.get("audio", {})
        return InboundMessage(kind="audio", audio_media_id=a.get("id"), audio_mime=a.get("mime_type"),
                              audio_size=a.get("file_size"), **base)
    if t == "button":
        b = m.get("button", {})
        return InboundMessage(kind="button", button_payload=b.get("payload") or b.get("text"),
                              text=b.get("text", ""), **base)
    if t == "interactive":
        reply = (m.get("interactive") or {}).get("button_reply") or {}
        return InboundMessage(kind="button", button_payload=reply.get("title"), text=reply.get("title", ""), **base)
    if t:
        return InboundMessage(kind=t, **base)  # image, sticker and others: handled as unsupported media
    return None


def whatsapp_status(raw: dict) -> StatusEvent | None:
    value = _wa_value(raw)
    if not value or not value.get("statuses"):
        return None
    s = value["statuses"][0]
    status = _WA_STATUS.get(s.get("status", ""))
    if not status:
        return None
    return StatusEvent("whatsapp", f"{s.get('id')}#{status}", s.get("id", ""), status)


def sms_rcs_inbound(raw: dict) -> InboundMessage | None:
    if "inboundMessageId" not in raw or "originationNumber" not in raw:
        return None
    body = raw.get("messageBody", "") or ""
    postback = raw.get("postbackData") or raw.get("PostbackData")
    channel = "rcs" if raw.get("channel", "").lower() == "rcs" or postback else raw.get("channel", "sms").lower()
    return InboundMessage(channel=channel if channel in ("sms", "rcs") else "sms", event_id=raw["inboundMessageId"],
                          sender=e164(raw["originationNumber"]), text=body, kind="postback" if postback else "text",
                          postback=postback, keyword=raw.get("messageKeyword"),
                          simulated=bool(raw.get("simulated", False)), raw=raw)


def sms_rcs_status(raw: dict) -> StatusEvent | None:
    et = raw.get("eventType", "")
    if et not in _SMS_STATUS or "messageId" not in raw:
        return None
    channel = "rcs" if et.startswith("RCS_") else "sms"
    ctx = raw.get("context") or {}
    return StatusEvent(channel, f"{raw['messageId']}#{et}", raw["messageId"], _SMS_STATUS[et], ctx.get("correlation_id"))


def ses_status(raw: dict) -> StatusEvent | None:
    et = raw.get("eventType") or raw.get("notificationType")
    mail = raw.get("mail") or {}
    if et not in _SES_STATUS or not mail.get("messageId"):
        return None
    return StatusEvent("email", f"{mail['messageId']}#{et}", mail["messageId"], _SES_STATUS[et])


def sns_messages(event: dict) -> list[tuple[str, dict]]:
    """(topic ARN, decoded message) for each SNS record in a Lambda event."""
    out = []
    for r in event.get("Records", []):
        sns = r.get("Sns") or {}
        msg = _loads(sns.get("Message"))
        if isinstance(msg, dict):
            out.append((sns.get("TopicArn", ""), msg))
    return out
