"""Local channel simulators. Each send is one JSON line in .sim/<channel>.jsonl, labelled simulated."""
from __future__ import annotations

import uuid
from dataclasses import asdict

from .. import sim
from . import parse
from .base import InboundMessage, OutboundMessage, SendResult, StatusEvent


class _Sim:
    channel = ""
    simulated = True

    def send(self, msg: OutboundMessage) -> SendResult:
        pid = f"sim-{uuid.uuid4().hex[:16]}"
        rec = {k: v for k, v in asdict(msg).items() if v not in (None, "", [], {}, False)}
        sim.append(self.channel, {"provider_id": pid, **rec})
        return SendResult.sent(pid, simulated=True)

    def sent(self) -> list[dict]:
        return sim.read(self.channel)


class WhatsAppSim(_Sim):
    channel = "whatsapp"

    def parse_inbound(self, raw: dict) -> InboundMessage | None:
        m = parse.whatsapp_inbound(raw)
        if m:
            m.simulated = True
        return m

    def parse_status(self, raw: dict) -> StatusEvent | None:
        return parse.whatsapp_status(raw)


class RcsSim(_Sim):
    channel = "rcs"

    def parse_inbound(self, raw: dict) -> InboundMessage | None:
        return parse.sms_rcs_inbound(raw)

    def parse_status(self, raw: dict) -> StatusEvent | None:
        return parse.sms_rcs_status(raw)


class SmsSim(RcsSim):
    channel = "sms"


class EmailSim(_Sim):
    channel = "email"

    def parse_inbound(self, raw: dict) -> InboundMessage | None:
        return None

    def parse_status(self, raw: dict) -> StatusEvent | None:
        return parse.ses_status(raw)
