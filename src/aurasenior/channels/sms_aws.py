"""SMS through AWS End User Messaging SMS from the simulator origination number."""
from __future__ import annotations

import os

from .. import aws
from . import parse
from .base import InboundMessage, OutboundMessage, SendResult, StatusEvent
from .errors import to_result


class SmsAws:
    channel = "sms"
    simulated = False

    def __init__(self):
        self.origin = os.environ.get("SMS_ORIGINATION_NUMBER_ARN", "")

    def request(self, msg: OutboundMessage) -> dict:
        return {"DestinationPhoneNumber": msg.to, "OriginationIdentity": self.origin, "MessageBody": msg.text,
                "MessageType": "TRANSACTIONAL", "ConfigurationSetName": "aurasenior-sms",
                "Context": {"correlation_id": msg.correlation_id[:100]}}

    def send(self, msg: OutboundMessage) -> SendResult:
        try:
            resp = aws.client("pinpoint-sms-voice-v2").send_text_message(**self.request(msg))
            return SendResult.sent(resp["MessageId"])
        except Exception as e:  # noqa: BLE001
            return to_result(e)

    def parse_inbound(self, raw: dict) -> InboundMessage | None:
        return parse.sms_rcs_inbound(raw)

    def parse_status(self, raw: dict) -> StatusEvent | None:
        return parse.sms_rcs_status(raw)
