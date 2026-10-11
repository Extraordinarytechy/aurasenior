"""Channel adapter interface. Real AWS adapters and local simulators implement the same Protocol."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class OutboundMessage:
    person_id: str
    to: str  # E.164 number or email address
    kind: str  # text, voice, template, card, email_template
    text: str = ""  # what the person sees or hears (also used by the guard)
    language: str = "en-IN"
    urgency: str = "normal"
    correlation_id: str = ""
    household_id: str = ""
    template: str | None = None  # WhatsApp template name or SES template name
    template_params: list[str] = field(default_factory=list)
    template_data: dict[str, Any] = field(default_factory=dict)
    card: dict[str, Any] | None = None  # RCS card: title, description, suggestions [(label, postback)]
    suggestions: list[tuple[str, str]] = field(default_factory=list)  # RCS reply suggestions on text
    sms_fallback: str = ""  # SMS body used by RCS FallbackConfiguration
    phrase_key: str | None = None  # fixed phrase this message renders, used for guard exemptions
    list_management: bool = False  # SES unsubscribe handling for summaries and updates


@dataclass
class SendResult:
    ok: bool
    provider_id: str | None = None
    code: str | None = None
    retryable: bool = False
    simulated: bool = False

    @classmethod
    def sent(cls, provider_id: str, simulated: bool = False) -> "SendResult":
        return cls(True, provider_id, simulated=simulated)

    @classmethod
    def failed(cls, code: str, retryable: bool, simulated: bool = False) -> "SendResult":
        return cls(False, None, code, retryable, simulated)


@dataclass
class InboundMessage:
    channel: str
    event_id: str
    sender: str  # E.164 number
    text: str = ""
    kind: str = "text"  # text, audio, button, postback
    button_payload: str | None = None
    context_id: str | None = None
    postback: str | None = None
    audio_media_id: str | None = None
    audio_mime: str | None = None
    audio_size: int | None = None
    keyword: str | None = None
    simulated: bool = False
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class StatusEvent:
    channel: str
    event_id: str
    provider_id: str
    status: str  # sent, delivered, read, failed
    correlation_id: str | None = None


class ChannelAdapter(Protocol):
    channel: str
    simulated: bool

    def send(self, msg: OutboundMessage) -> SendResult: ...
    def parse_inbound(self, raw: dict) -> InboundMessage | None: ...
    def parse_status(self, raw: dict) -> StatusEvent | None: ...
