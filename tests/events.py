"""Builders for raw inbound events in the shapes the services publish (fictional ids and numbers)."""
import json

WA_TOPIC = "arn:aws:sns:us-east-1:000000000000:aurasenior-whatsapp-events"
SMS_TOPIC = "arn:aws:sns:us-east-1:000000000000:aurasenior-sms-rcs-events"


def sns(topic: str, message: dict) -> dict:
    return {"Records": [{"EventSource": "aws:sns", "Sns": {"TopicArn": topic, "Message": json.dumps(message)}}]}


def _wa(message: dict) -> dict:
    entry = {"id": "100000000000001", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"phone_number_id": "200000000000001"}, "messages": [message]}}]}
    return sns(WA_TOPIC, {"whatsAppWebhookEntry": json.dumps(entry, ensure_ascii=False)})


def wa_text(sender: str, wamid: str, text: str) -> dict:
    return _wa({"from": sender.lstrip("+"), "id": wamid, "type": "text", "text": {"body": text}})


def wa_audio(sender: str, wamid: str, media_id: str = "300000000000001", size: int = 20000) -> dict:
    return _wa({"from": sender.lstrip("+"), "id": wamid, "type": "audio",
                "audio": {"id": media_id, "mime_type": "audio/ogg; codecs=opus", "file_size": size}})


def wa_button(sender: str, wamid: str, label: str, context_id: str | None) -> dict:
    m = {"from": sender.lstrip("+"), "id": wamid, "type": "button", "button": {"payload": label, "text": label}}
    if context_id:
        m["context"] = {"id": context_id}
    return _wa(m)


def two_way(sender: str, msg_id: str, body: str, postback: str | None = None, simulated: bool = False) -> dict:
    m = {"originationNumber": sender, "destinationNumber": "+12025550199", "messageBody": body,
         "inboundMessageId": msg_id}
    if postback:
        m["postbackData"] = postback
        m["channel"] = "RCS"
    if simulated:
        m["simulated"] = True
    return sns(SMS_TOPIC, m)


def transcribe_done(event_id: str, job: str, status: str = "COMPLETED") -> dict:
    return {"id": event_id, "source": "aws.transcribe", "detail-type": "Transcribe Job State Change",
            "detail": {"TranscriptionJobName": job, "TranscriptionJobStatus": status}}
