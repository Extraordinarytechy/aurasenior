import io
import json

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
    body = {"messaging_product": "whatsapp", "to": "910000000001", "type": "template",
            "template": {"name": "aurasenior_checkin_hi", "language": {"code": "hi"},
                         "components": [{"type": "body", "parameters": [{"type": "text", "text": "Kamala"}]}]}}
    with Stubber(c) as s:
        s.add_response("send_whatsapp_message", {"messageId": "wamid.OUT1"},
                       {"originationPhoneNumberId": "phone-number-id-0001", "message": json.dumps(body).encode(),
                        "metaApiVersion": "v25.0"})
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
                        {"originationPhoneNumberId": "phone-number-id-0001", "message": ANY, "metaApiVersion": "v25.0"})
        r = WhatsAppAws().send(msg)
    assert r.ok and r.provider_id == "wamid.OUT2"


def test_rcs_card_request_has_fallback_and_context(env):
    c = _client("pinpoint-sms-voice-v2")
    msg = OutboundMessage(person_id="r", to="+12025550101", kind="card", correlation_id="ev#1",
                          card={"title": "Mom's BP tablets ran out", "description": "Order a refill?",
                                "suggestions": [("Order refill", "refill:approve:0123456789ab")]},
                          sms_fallback="Reply 1 to order")
    expected = {"DestinationPhoneNumber": "+12025550101", "OriginationIdentity": "rcs-agent-0001",
                "RcsMessageContent": {"Content": {"RichCard": {"CardOrientation": "VERTICAL", "CardContent": {
                    "Title": "Mom's BP tablets ran out", "Description": "Order a refill?",
                    "Suggestions": [{"Reply": {"Text": "Order refill", "PostbackData": "refill:approve:0123456789ab"}}]}}}},
                "ConfigurationSetName": "aurasenior-sms", "Context": {"correlation_id": "ev#1"},
                "FallbackConfiguration": {"Channel": "SMS", "MessageBody": "Reply 1 to order",
                                          "OriginationIdentity": "arn:aws:sms-voice:us-east-1:000000000000:phone-number/phone-0001"}}
    with Stubber(c) as s:
        s.add_response("send_rcs_message", {"MessageId": "rcs-1"}, expected)
        assert RcsAws().send(msg).provider_id == "rcs-1"


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
