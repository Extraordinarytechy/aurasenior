import json
from pathlib import Path

import pytest

from aurasenior.channels import parse

FIX = Path(__file__).parent / "fixtures" / "events"


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_whatsapp_text():
    m = parse.whatsapp_inbound(_load("whatsapp_text.json"))
    assert (m.kind, m.text, m.sender, m.event_id) == ("text", "START", "+910000000001", "wamid.TEXT0001")


def test_whatsapp_audio():
    m = parse.whatsapp_inbound(_load("whatsapp_audio.json"))
    assert m.kind == "audio" and m.audio_media_id == "300000000000001" and m.audio_mime.startswith("audio/ogg")


def test_whatsapp_button_has_label_and_context():
    m = parse.whatsapp_inbound(_load("whatsapp_button.json"))
    assert m.kind == "button" and m.button_payload == "सुनें" and m.context_id == "wamid.TEMPLATE0001"


def test_whatsapp_status():
    s = parse.whatsapp_status(_load("whatsapp_status.json"))
    assert (s.provider_id, s.status) == ("wamid.OUT0001", "delivered")
    assert parse.whatsapp_inbound(_load("whatsapp_status.json")) is None


def test_sms_inbound_and_rcs_postback():
    m = parse.sms_rcs_inbound(_load("sms_inbound.json"))
    assert (m.channel, m.text, m.sender) == ("sms", "1", "+14254147755")
    r = parse.sms_rcs_inbound(_load("rcs_postback.json"))
    assert (r.channel, r.kind, r.postback) == ("rcs", "postback", "refill:approve:0123456789ab")


def test_rcs_suggestion_tap_from_real_device():
    # Captured from a real RCS device (AWS End User Messaging): the suggestion tap arrives as kind=text with the
    # PostbackData nested in a JSON messageBody. The parser must surface it as a postback, not route it to the AI.
    m = parse.sms_rcs_inbound(_load("rcs_suggestion_tap.json"))
    assert (m.channel, m.kind, m.postback) == ("rcs", "postback", "refill:approve:c2563e6bdeec")
    assert m.sender == "+14036181196"


def test_rcs_conversation_started_event_dropped():
    # System events (CONVERSATION_STARTED, IS_TYPING) carry no user content and must be ignored, not sent to the AI.
    assert parse.sms_rcs_inbound(_load("rcs_conversation_started.json")) is None


def test_sms_and_rcs_status_events():
    s = parse.sms_rcs_status(_load("sms_delivered.json"))
    assert (s.channel, s.status, s.correlation_id) == ("sms", "delivered", "checkin#sample01#2026-10-12#1")
    r = parse.sms_rcs_status(_load("rcs_read.json"))
    assert (r.channel, r.status) == ("rcs", "read")


def test_ses_status():
    s = parse.ses_status(_load("ses_delivery.json"))
    assert (s.channel, s.provider_id, s.status) == ("email", "010001-ses-0001", "delivered")


@pytest.mark.parametrize("raw", [{}, {"foo": 1}, {"whatsAppWebhookEntry": "not json"}, {"eventType": "Nope"}])
def test_unknown_shapes_return_none(raw):
    assert parse.whatsapp_inbound(raw) is None
    assert parse.whatsapp_status(raw) is None
    assert parse.sms_rcs_inbound(raw) is None
    assert parse.sms_rcs_status(raw) is None
    assert parse.ses_status(raw) is None


def test_sns_messages_decodes_records():
    ev = {"Records": [{"Sns": {"TopicArn": "arn:t", "Message": json.dumps({"a": 1})}}]}
    assert parse.sns_messages(ev) == [("arn:t", {"a": 1})]
