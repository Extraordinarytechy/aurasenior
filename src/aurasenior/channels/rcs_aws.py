"""RCS through AWS End User Messaging SMS, with per-message SMS fallback handled by AWS."""
from __future__ import annotations

import os

from .. import aws
from . import parse
from .base import InboundMessage, OutboundMessage, SendResult, StatusEvent
from .errors import to_result

CONFIG_SET = "aurasenior-sms"


def _reply(label: str, postback: str) -> dict:
    return {"Reply": {"Text": label[:25], "PostbackData": postback}}


class RcsAws:
    channel = "rcs"
    simulated = False

    def __init__(self):
        self.agent_id = os.environ.get("RCS_AGENT_ID", "")
        self.sms_origin = os.environ.get("SMS_ORIGINATION_NUMBER_ARN", "")

    def request(self, msg: OutboundMessage) -> dict:
        if msg.kind == "card" and msg.card:
            content = {"RichCard": {"CardOrientation": "VERTICAL", "CardContent": {
                "Title": msg.card["title"][:200], "Description": msg.card["description"],
                "Suggestions": [_reply(lbl, pb) for lbl, pb in msg.card["suggestions"][:4]]}}}
            rcs = {"Content": content}
        else:
            rcs = {"Content": {"TextMessage": {"Body": msg.text}}}
            if msg.suggestions:
                rcs["Suggestions"] = [_reply(lbl, pb) for lbl, pb in msg.suggestions[:4]]
        req = {"DestinationPhoneNumber": msg.to, "OriginationIdentity": self.agent_id, "RcsMessageContent": rcs,
               "ConfigurationSetName": CONFIG_SET, "Context": {"correlation_id": msg.correlation_id[:100]}}
        if msg.sms_fallback and self.sms_origin:
            req["FallbackConfiguration"] = {"Channel": "SMS", "MessageBody": msg.sms_fallback,
                                            "OriginationIdentity": self.sms_origin}
        return req

    def send(self, msg: OutboundMessage) -> SendResult:
        try:
            resp = aws.client("pinpoint-sms-voice-v2").send_rcs_message(**self.request(msg))
            return SendResult.sent(resp["MessageId"])
        except Exception as e:  # noqa: BLE001
            return to_result(e)

    def parse_inbound(self, raw: dict) -> InboundMessage | None:
        return parse.sms_rcs_inbound(raw)

    def parse_status(self, raw: dict) -> StatusEvent | None:
        return parse.sms_rcs_status(raw)
