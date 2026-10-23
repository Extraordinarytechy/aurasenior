import io
import json
import re

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber

from aurasenior import aws
from aurasenior.channels.base import OutboundMessage
from aurasenior.channels.email_aws import EmailAws
from aurasenior.channels.rcs_aws import RcsAws
from aurasenior.channels.sms_aws import SmsAws
from aurasenior.channels.whatsapp_aws import WhatsAppAws


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "phone-number-id-0001")
    monkeypatch.setenv("MEDIA_BUCKET", "aurasenior-media-test")
    monkeypatch.setenv("RCS_AGENT_ID", "rcs-agent-0001")
    monkeypatch.setenv("SMS_ORIGINATION_NUMBER_ARN", "arn:aws:sms-voice:us-east-1:000000000000:phone-number/phone-0001")
    monkeypatch.setenv("SENDER_EMAIL", "sender@example.com")


def _client(name):
    c = boto3.client(name, region_name="us-east-1")
    aws.override(name, c)
    return c


def test_whatsapp_template_request(env):
    c = _client("socialmessaging")
    msg = OutboundMessage(person_id="k", to="+910000000001", kind="template", template="aurasenior_checkin_hi",
                          template_params=["Kamala"])
    body = {"messaging_product": "whatsapp", "to": "+910000000001", "type": "template",
            "template": {"name": "aurasenior_checkin_hi", "language": {"code": "hi"},
                         "components": [{"type": "body", "parameters": [{"type": "text", "text": "Kamala"}]}]}}
    with Stubber(c) as s:
        s.add_response("send_whatsapp_message", {"messageId": "wamid.OUT1"},
                       {"originationPhoneNumberId": "phone-number-id-0001", "message": json.dumps(body).encode(),
                        "metaApiVersion": "v20.0"})
        r = WhatsAppAws().send(msg)
    assert r.ok and r.provider_id == "wamid.OUT1"


def test_whatsapp_voice_note_uses_polly_s3_and_media(env):
    polly, s3, sm = _client("polly"), _client("s3"), _client("socialmessaging")
    msg = OutboundMessage(person_id="k", to="+910000000001", kind="voice", text="सुप्रभात", language="hi-IN",
                          household_id="hh1")
    with Stubber(polly) as sp, Stubber(s3) as ss, Stubber(sm) as sw:
        sp.add_response("synthesize_speech", {"AudioStream": StreamingBody(io.BytesIO(b"ogg"), 3)},
                        {"Text": "सुप्रभात", "OutputFormat": "ogg_opus", "SampleRate": "48000", "VoiceId": "Kajal",
                         "Engine": "neural", "LanguageCode": "hi-IN"})
        ss.add_response("put_object", {}, {"Bucket": "aurasenior-media-test", "Key": ANY, "Body": b"ogg",
                                           "ContentType": "audio/ogg"})
        sw.add_response("post_whatsapp_message_media", {"mediaId": "media-1"},
                        {"originationPhoneNumberId": "phone-number-id-0001",
                         "sourceS3File": {"bucketName": "aurasenior-media-test", "key": ANY}})
        sw.add_response("send_whatsapp_message", {"messageId": "wamid.OUT2"},
                        {"originationPhoneNumberId": "phone-number-id-0001", "message": ANY, "metaApiVersion": "v20.0"})
        r = WhatsAppAws().send(msg)
    assert r.ok and r.provider_id == "wamid.OUT2"


class _Recorder:
    """Records the calls an adapter makes, so each can be checked against the SDK model."""

    def __init__(self, response):
        self.calls, self.response = [], response

    def __getattr__(self, op):
        def call(**kw):
            self.calls.append((op, kw))
            return self.response
        return call


def test_whatsapp_requests_fit_the_sdk_model(env):
    rec = _Recorder({"messageId": "wamid.OUT3", "mimeType": "audio/ogg", "fileSize": 3})
    aws.override("socialmessaging", rec)
    wa = WhatsAppAws()
    assert wa.send(OutboundMessage(person_id="k", to="+910000000001", kind="text", text="नमस्ते")).ok
    assert wa.send(OutboundMessage(person_id="k", to="+910000000001", kind="template",
                                   template="aurasenior_family_refill_en", template_params=["Mom", "BP tablets"])).ok
    wa.mark_read("wamid.IN1")
    wa.fetch_media("1234567890", "hh1", "wamid.IN1")
    model = boto3.client("socialmessaging", region_name="us-east-1").meta.service_model
    for op, kw in rec.calls:
        shape = model.operation_model({"send_whatsapp_message": "SendWhatsAppMessage",
                                       "get_whatsapp_message_media": "GetWhatsAppMessageMedia"}[op]).input_shape
        assert _problems(shape, kw) == [], op
    bodies = [json.loads(kw["message"]) for op, kw in rec.calls if op == "send_whatsapp_message"]
    assert bodies[0] == {"messaging_product": "whatsapp", "to": "+910000000001", "type": "text",
                         "text": {"body": "नमस्ते"}}
    assert bodies[1]["template"]["language"] == {"code": "en_US"}
    assert bodies[2] == {"messaging_product": "whatsapp", "status": "read", "message_id": "wamid.IN1"}


def test_whatsapp_phone_number_id_pattern_rejects_a_meta_number_id():
    shape = boto3.client("socialmessaging", region_name="us-east-1").meta.service_model \
        .operation_model("SendWhatsAppMessage").input_shape
    ok = {"originationPhoneNumberId": "phone-number-id-0123456789abcdef0123456789abcdef", "metaApiVersion": "v20.0"}
    assert _problems(shape, ok) == ["request.message is required"]
    assert any("does not match" in p for p in _problems(shape, {**ok, "originationPhoneNumberId": "123456789012345"}))


def test_rcs_card_request_shape_and_context(env):
    # A real destination gets no SMS fallback: the only SMS origination identity is a US simulator number, and
    # attaching it for a real destination fails the whole send (AWS: INVALID_IDENTITY_FOR_DESTINATION_COUNTRY).
    c = _client("pinpoint-sms-voice-v2")
    msg = OutboundMessage(person_id="r", to="+12025550101", kind="card", correlation_id="ev#1",
                          card={"title": "Mom's BP tablets ran out", "description": "Order a refill?",
                                "suggestions": [("Order refill", "refill:approve:0123456789ab")]},
                          sms_fallback="Reply 1 to order")
    expected = {"DestinationPhoneNumber": "+12025550101", "OriginationIdentity": "rcs-agent-0001",
                "RcsMessageContent": {"Content": {"RichCard": {"CardOrientation": "VERTICAL", "CardContent": {
                    "Title": "Mom's BP tablets ran out", "Description": "Order a refill?",
                    "Suggestions": [{"Reply": {"Text": "Order refill", "PostbackData": "refill:approve:0123456789ab"}}]}}}},
                "ConfigurationSetName": "aurasenior-sms", "Context": {"correlation_id": "ev#1"}}
    with Stubber(c) as s:
        s.add_response("send_rcs_message", {"MessageId": "rcs-1"}, expected)
        assert RcsAws().send(msg).provider_id == "rcs-1"


AGENT = "rcs-d2d5c9c54eab443fbc5d5659136d3085"
AGENT_ARN = f"arn:aws:sms-voice:us-east-1:000000000000:rcs-agent/{AGENT}"


def _problems(shape, value, path="request") -> list[str]:
    """Check a request against the SDK model, including the max length and pattern rules that the client's own
    parameter validation does not check."""
    out = []
    if shape.type_name == "structure":
        for r in shape.required_members:
            if r not in value:
                out.append(f"{path}.{r} is required")
        for k, v in value.items():
            if k not in shape.members:
                out.append(f"{path}.{k} is not in the model")
            else:
                out += _problems(shape.members[k], v, f"{path}.{k}")
    elif shape.type_name == "list":
        out += [p for i, v in enumerate(value) for p in _problems(shape.member, v, f"{path}[{i}]")]
    elif shape.type_name == "map":
        out += [p for k, v in value.items() for p in _problems(shape.value, v, f"{path}[{k}]")]
    elif shape.type_name == "string":
        md = shape.metadata
        if not md.get("min", 0) <= len(value) <= md.get("max", 10**9):
            out.append(f"{path} has length {len(value)}")
        if "pattern" in md and not re.fullmatch(md["pattern"], value):
            out.append(f"{path} does not match {md['pattern']}")
        if shape.enum and value not in shape.enum:
            out.append(f"{path} is not one of {shape.enum}")
    return out


@pytest.mark.parametrize("origin", [AGENT, AGENT_ARN])
def test_rcs_text_with_suggestions_for_an_agent_id_or_arn(env, monkeypatch, origin):
    monkeypatch.setenv("RCS_AGENT_ID", origin)
    c = _client("pinpoint-sms-voice-v2")
    msg = OutboundMessage(person_id="r", to="+447700900123", kind="text", text="No reply from Mom this morning.",
                          correlation_id="ev#3", suggestions=[("I'm on it", "esc:ack:0123456789ab")],
                          sms_fallback="Reply 4 if you are on it.")
    expected = {"DestinationPhoneNumber": "+447700900123", "OriginationIdentity": origin,
                "RcsMessageContent": {"Content": {"TextMessage": {"Body": "No reply from Mom this morning."}},
                                      "Suggestions": [{"Reply": {"Text": "I'm on it",
                                                                 "PostbackData": "esc:ack:0123456789ab"}}]},
                "ConfigurationSetName": "aurasenior-sms", "Context": {"correlation_id": "ev#3"}}
    with Stubber(c) as s:
        s.add_response("send_rcs_message", {"MessageId": "rcs-2"}, expected)
        assert RcsAws().send(msg).provider_id == "rcs-2"


def test_rcs_fallback_attached_only_for_simulator_destinations(env):
    # The SMS fallback uses the simulator origination number, which can only reach the AWS SMS simulator
    # destination. It must be attached for a simulator destination and omitted for any real number.
    base = dict(person_id="r", kind="text", text="No reply from Mom this morning.", correlation_id="ev#fb",
                sms_fallback="Reply 4 if you are on it.")
    to_sim = RcsAws().request(OutboundMessage(to="+14254147755", **base))
    assert to_sim["FallbackConfiguration"] == {
        "Channel": "SMS", "MessageBody": "Reply 4 if you are on it.",
        "OriginationIdentity": "arn:aws:sms-voice:us-east-1:000000000000:phone-number/phone-0001"}
    to_real = RcsAws().request(OutboundMessage(to="+447700900123", **base))
    assert "FallbackConfiguration" not in to_real


def test_every_rcs_message_the_product_sends_fits_the_sdk_model(env, monkeypatch, sample):
    from dataclasses import fields

    from aurasenior import consent, escalation, refill, sim, store

    monkeypatch.setenv("RCS_AGENT_ID", AGENT_ARN)
    refill.request_refill_approval(sample, "bp", "rohan", correlation_id="ev#card")
    escalation.escalate(sample, "missed_checkin")
    store.set_consent(sample, "rohan", "rcs", "opted_out", "test")
    consent._ask(store.get_person(sample, "rohan"), "rcs", None, "ev#ask", rcs_verified=True)
    records = sim.read("rcs")
    assert {r["kind"] for r in records} >= {"card", "text"}
    shape = boto3.client("pinpoint-sms-voice-v2", region_name="us-east-1").meta.service_model \
        .operation_model("SendRcsMessage").input_shape
    names = {f.name for f in fields(OutboundMessage)}
    for rec in records:
        msg = OutboundMessage(**{k: v for k, v in rec.items() if k in names})
        assert _problems(shape, RcsAws().request(msg)) == [], rec.get("phrase_key")


def test_sms_request(env):
    c = _client("pinpoint-sms-voice-v2")
    msg = OutboundMessage(person_id="s", to="+14254147755", kind="text", text="Reply 4", correlation_id="ev#2")
    with Stubber(c) as s:
        s.add_response("send_text_message", {"MessageId": "sms-1"}, {
            "DestinationPhoneNumber": "+14254147755",
            "OriginationIdentity": "arn:aws:sms-voice:us-east-1:000000000000:phone-number/phone-0001",
            "MessageBody": "Reply 4", "MessageType": "TRANSACTIONAL", "ConfigurationSetName": "aurasenior-sms",
            "Context": {"correlation_id": "ev#2"}})
        assert SmsAws().send(msg).ok


def test_email_summary_request_has_list_management(env):
    c = _client("sesv2")
    msg = OutboundMessage(person_id="d", to="doctor@example.com", kind="email_template",
                          template="aurasenior-weekly-summary", template_data={"elder_name": "Kamala"},
                          list_management=True)
    with Stubber(c) as s:
        s.add_response("send_email", {"MessageId": "ses-1"}, {
            "FromEmailAddress": "sender@example.com", "Destination": {"ToAddresses": ["doctor@example.com"]},
            "Content": {"Template": {"TemplateName": "aurasenior-weekly-summary",
                                     "TemplateData": json.dumps({"brand": "AuraSenior", "elder_name": "Kamala"})}},
            "ConfigurationSetName": "aurasenior-email",
            "ListManagementOptions": {"ContactListName": "aurasenior-contacts", "TopicName": "updates"}})
        assert EmailAws().send(msg).ok


@pytest.mark.parametrize("code,retryable", [("ThrottlingException", True), ("ValidationException", False),
                                            ("AccessDeniedException", False)])
def test_error_mapping(env, code, retryable):
    c = _client("pinpoint-sms-voice-v2")
    msg = OutboundMessage(person_id="s", to="+14254147755", kind="text", text="x", correlation_id="e")
    with Stubber(c) as s:
        s.add_client_error("send_text_message", code, http_status_code=400)
        r = SmsAws().send(msg)
    assert not r.ok and r.code == code and r.retryable is retryable


def test_server_error_is_retryable(env):
    c = _client("sesv2")
    msg = OutboundMessage(person_id="d", to="a@example.com", kind="email_template", template="aurasenior-update")
    with Stubber(c) as s:
        s.add_client_error("send_email", "InternalFailure", http_status_code=500)
        assert EmailAws().send(msg).retryable
