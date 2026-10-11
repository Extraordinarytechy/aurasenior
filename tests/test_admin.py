import boto3
from botocore.stub import Stubber

from aurasenior import admin, aws, sim, store


def test_email_consent_works_and_other_channels_exit_1(sample):
    assert admin.main(["consent", sample, "doctor", "email", "opted_out", "--source", "phone call"]) == 0
    assert store.get_person(sample, "doctor").consent["email"]["source"] == "admin:phone call"
    assert admin.main(["consent", sample, "kamala", "whatsapp", "opted_in", "--source", "x"]) == 1
    assert admin.main(["consent", sample, "doctor", "email", "opted_in"]) == 1
    assert admin.main(["consent", sample, "nobody", "email", "opted_in", "--source", "x"]) == 1


def test_rcs_ask_refuses_unverified_and_second_ask(sample, monkeypatch):
    monkeypatch.setenv("RCS_AGENT_ID", "agent-1")
    store.set_consent(sample, "rohan", "rcs", "pending", "test")
    c = boto3.client("pinpoint-sms-voice-v2", region_name="us-east-1")
    aws.override("pinpoint-sms-voice-v2", c)
    params = {"DestinationPhoneNumbers": ["+12025550101"], "Filters": [{"Name": "rcs-agent-id", "Values": ["agent-1"]}]}
    ok = {"VerifiedDestinationNumbers": [{"VerifiedDestinationNumberArn": "arn:x", "VerifiedDestinationNumberId": "v1",
                                          "DestinationPhoneNumber": "+12025550101", "Status": "VERIFIED",
                                          "CreatedTimestamp": "2026-10-11T00:00:00Z"}]}
    with Stubber(c) as s:
        s.add_response("describe_verified_destination_numbers", {"VerifiedDestinationNumbers": []}, params)
        s.add_response("describe_verified_destination_numbers", ok, params)
        s.add_response("describe_verified_destination_numbers", ok, params)
        assert admin.main(["rcs-ask", sample, "rohan"]) == 1
        assert admin.main(["rcs-ask", sample, "rohan"]) == 0
        assert admin.main(["rcs-ask", sample, "rohan"]) == 1
    assert [x["phrase_key"] for x in sim.read("rcs")] == ["optin_ask_admin"]
