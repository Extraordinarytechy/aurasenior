import json
import re

import boto3
import pytest
from botocore.stub import Stubber

from aurasenior import aws, schedules

HID = "a" * 12
EID = "b" * 12


@pytest.fixture(autouse=True)
def _fresh_sim():
    schedules.reset_sim()
    yield
    schedules.reset_sim()


def test_every_name_fits_the_scheduler_pattern():
    names = [schedules.name_checkin(HID), schedules.name_weekly(HID),
             schedules.name_followup(HID, "2026-10-12"), schedules.name_missed(HID, "2026-10-12"),
             schedules.name_recheck(EID, 12), schedules.name_delivery_check("x" * 300),
             schedules.name_approval_expiry(EID)]
    for n in names:
        assert len(n) <= 64 and re.fullmatch(r"[0-9a-zA-Z\-_.]+", n), n


def test_chain_times_and_delete_count(frozen):
    sim = schedules.client()
    schedules.create_followup("hh1", "2026-10-12", "Asia/Kolkata")
    schedules.create_missed_checkin("hh1", "2026-10-12", "Asia/Kolkata")
    exprs = {n: s["ScheduleExpression"] for (_, n), s in sim.schedules.items()}
    assert exprs["aurasenior-fu-hh1-20261012"] == "at(2026-10-12T10:30:00)"
    assert exprs["aurasenior-mc-hh1-20261012"] == "at(2026-10-12T10:00:00)"
    payload = json.loads(sim.schedules[("aurasenior", "aurasenior-fu-hh1-20261012")]["Target"]["Input"])
    assert payload["event_id"] == "followup#hh1#2026-10-12"
    assert schedules.delete_checkin_chain("hh1", "2026-10-12") == 2
    assert schedules.delete_checkin_chain("hh1", "2026-10-12") == 0


def test_conflict_counts_as_already_scheduled(frozen):
    assert schedules.create_recheck("hh1", EID, 1, "Asia/Kolkata") is True
    assert schedules.create_recheck("hh1", EID, 1, "Asia/Kolkata") is False
    assert schedules.delete_recheck(EID, 1) is True
    assert schedules.delete_recheck(EID, 1) is False


def test_real_client_request_params(frozen, monkeypatch):
    monkeypatch.setenv("AURASENIOR_MODE_SCHEDULER", "aws")
    c = boto3.client("scheduler", region_name="us-east-1")
    aws.override("scheduler", c)
    with Stubber(c) as stub:
        stub.add_response("create_schedule", {"ScheduleArn": "arn:aws:scheduler:us-east-1:000000000000:schedule/aurasenior/x"}, {
            "Name": "aurasenior-checkin-hh1", "GroupName": "aurasenior", "ScheduleExpression": "cron(0 9 * * ? *)",
            "ScheduleExpressionTimezone": "Asia/Kolkata", "FlexibleTimeWindow": {"Mode": "OFF"},
            "Target": {"Arn": "arn:aws:lambda:us-east-1:000000000000:function:aurasenior-scheduled",
                       "RoleArn": "arn:aws:iam::000000000000:role/aurasenior-scheduler",
                       "Input": json.dumps({"kind": "checkin", "household_id": "hh1"})},
            "State": "ENABLED"})
        stub.add_client_error("delete_schedule", "ResourceNotFoundException", expected_params={
            "Name": "aurasenior-fu-hh1-20261012", "GroupName": "aurasenior"})
        assert schedules.create_checkin("hh1", "09:00", "Asia/Kolkata")
        assert schedules.delete("aurasenior-fu-hh1-20261012") is False
        stub.assert_no_pending_responses()


def test_one_time_schedules_delete_after_completion(frozen):
    sim = schedules.client()
    schedules.create_approval_expiry("hh1", EID, "Asia/Kolkata")
    s = sim.schedules[("aurasenior", schedules.name_approval_expiry(EID))]
    assert s["ActionAfterCompletion"] == "DELETE"
    assert s["FlexibleTimeWindow"] == {"Mode": "OFF"}
