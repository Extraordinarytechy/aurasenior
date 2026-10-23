"""WhatsApp through AWS End User Messaging Social (Meta Cloud API message bodies)."""
from __future__ import annotations

import json
import os
import secrets

from .. import aws, config
from . import parse, polly
from .base import InboundMessage, OutboundMessage, SendResult, StatusEvent
from .errors import to_result


class WhatsAppAws:
    channel = "whatsapp"
    simulated = False

    def __init__(self):
        self.phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
        self.bucket = os.environ.get("MEDIA_BUCKET", "")

    @property
    def _api(self) -> str:
        return config.get("whatsapp", "meta_api_version")

    def _post_media(self, audio: bytes, household_id: str) -> str:
        key = f"out/{household_id}/{secrets.token_hex(8)}.ogg"
        aws.client("s3").put_object(Bucket=self.bucket, Key=key, Body=audio, ContentType="audio/ogg")
        resp = aws.client("socialmessaging").post_whatsapp_message_media(
            originationPhoneNumberId=self.phone_number_id, sourceS3File={"bucketName": self.bucket, "key": key})
        return resp["mediaId"]

    def body(self, msg: OutboundMessage) -> dict:
        to = msg.to
        if msg.kind == "template":
            params = [{"type": "text", "text": p} for p in msg.template_params]
            lang = {"hi": "hi", "en": "en_US"}[msg.template.rsplit("_", 1)[1]]
            tpl = {"name": msg.template, "language": {"code": lang}}
            if params:
                tpl["components"] = [{"type": "body", "parameters": params}]
            return {"messaging_product": "whatsapp", "to": to, "type": "template", "template": tpl}
        return {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": msg.text}}

    def send(self, msg: OutboundMessage) -> SendResult:
        try:
            if msg.kind == "voice":
                media_id = self._post_media(polly.synthesize(msg.text, msg.language), msg.household_id)
                body = {"messaging_product": "whatsapp", "to": msg.to, "type": "audio",
                        "audio": {"id": media_id}}
            else:
                body = self.body(msg)
            resp = aws.client("socialmessaging").send_whatsapp_message(
                originationPhoneNumberId=self.phone_number_id, message=json.dumps(body).encode(),
                metaApiVersion=self._api)
            return SendResult.sent(resp["messageId"])
        except Exception as e:  # noqa: BLE001 - mapped to retryable or not
            return to_result(e)

    def fetch_media(self, media_id: str, household_id: str, msg_id: str) -> str:
        # AWS End User Messaging Social treats destinationS3File.key as a prefix and appends "<mediaId>.<ext>",
        # so the stored object is key + media_id + ".ogg". Point Transcribe at that real key, not the prefix.
        key = f"in/{household_id}/{msg_id}"
        aws.client("socialmessaging").get_whatsapp_message_media(
            mediaId=media_id, originationPhoneNumberId=self.phone_number_id,
            destinationS3File={"bucketName": self.bucket, "key": key})
        return f"{key}{media_id}.ogg"

    def mark_read(self, msg_id: str) -> None:
        body = {"messaging_product": "whatsapp", "status": "read", "message_id": msg_id}
        aws.client("socialmessaging").send_whatsapp_message(
            originationPhoneNumberId=self.phone_number_id, message=json.dumps(body).encode(), metaApiVersion=self._api)

    def parse_inbound(self, raw: dict) -> InboundMessage | None:
        return parse.whatsapp_inbound(raw)

    def parse_status(self, raw: dict) -> StatusEvent | None:
        return parse.whatsapp_status(raw)
