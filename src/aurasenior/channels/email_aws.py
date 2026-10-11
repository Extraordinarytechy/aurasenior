"""Templated email through SES v2 with the aurasenior-email configuration set."""
from __future__ import annotations

import json
import os

from .. import aws, config
from . import parse
from .base import InboundMessage, OutboundMessage, SendResult, StatusEvent
from .errors import to_result


class EmailAws:
    channel = "email"
    simulated = False

    def __init__(self):
        self.sender = os.environ.get("SENDER_EMAIL", "")

    def request(self, msg: OutboundMessage) -> dict:
        data = {"brand": config.brand(), **msg.template_data}
        req = {"FromEmailAddress": self.sender, "Destination": {"ToAddresses": [msg.to]},
               "Content": {"Template": {"TemplateName": msg.template, "TemplateData": json.dumps(data)}},
               "ConfigurationSetName": "aurasenior-email"}
        if msg.list_management:
            req["ListManagementOptions"] = {"ContactListName": "aurasenior-contacts", "TopicName": "updates"}
        return req

    def send(self, msg: OutboundMessage) -> SendResult:
        try:
            resp = aws.client("sesv2").send_email(**self.request(msg))
            return SendResult.sent(resp["MessageId"])
        except Exception as e:  # noqa: BLE001
            return to_result(e)

    def parse_inbound(self, raw: dict) -> InboundMessage | None:
        return None

    def parse_status(self, raw: dict) -> StatusEvent | None:
        return parse.ses_status(raw)
