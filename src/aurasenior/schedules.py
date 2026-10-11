"""Every schedule AuraSenior creates. Plain code on a fixed chain; the model has no scheduling tool."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from botocore.exceptions import ClientError

from . import aws, clock, config, dedupe, log
from .sim.scheduler import SchedulerSim

GROUP = "aurasenior"
FOLLOWUP_AFTER = timedelta(minutes=90)
MISSED_AFTER = timedelta(minutes=60)
RECHECK_EVERY = timedelta(minutes=5)
DELIVERY_CHECK_AFTER = timedelta(minutes=3)
APPROVAL_EXPIRY_AFTER = timedelta(hours=12)

_sim: SchedulerSim | None = None


def client():
    global _sim
    if config.mode("scheduler") == "sim":
        if _sim is None:
            _sim = SchedulerSim()
        return _sim
    return aws.client("scheduler")


def reset_sim() -> None:
    global _sim
    _sim = None


def ymd(local_date: str) -> str:
    return local_date.replace("-", "")


# Names (at most 64 characters, [0-9a-zA-Z-_.]+)

def name_checkin(hid: str) -> str:
    return f"aurasenior-checkin-{hid}"


def name_weekly(hid: str) -> str:
    return f"aurasenior-weekly-{hid}"


def name_followup(hid: str, local_date: str) -> str:
    return f"aurasenior-fu-{hid}-{ymd(local_date)}"


def name_missed(hid: str, local_date: str) -> str:
    return f"aurasenior-mc-{hid}-{ymd(local_date)}"


def name_recheck(eid: str, run: int) -> str:
    return f"aurasenior-er-{eid}-{run}"


def name_delivery_check(correlation_id: str) -> str:
    return "aurasenior-dc-" + hashlib.sha256(correlation_id.encode()).hexdigest()[:16]


def name_approval_expiry(aid: str) -> str:
    return f"aurasenior-ax-{aid}"


def _target(payload: dict) -> dict:
    return {"Arn": os.environ.get("SCHEDULED_FUNCTION_ARN", "arn:aws:lambda:us-east-1:000000000000:function:aurasenior-scheduled"),
            "RoleArn": os.environ.get("SCHEDULER_ROLE_ARN", "arn:aws:iam::000000000000:role/aurasenior-scheduler"),
            "Input": json.dumps(payload)}


def _create(name: str, expression: str, tz: str, payload: dict, one_time: bool) -> bool:
    kw = {"Name": name, "GroupName": GROUP, "ScheduleExpression": expression, "ScheduleExpressionTimezone": tz,
          "FlexibleTimeWindow": {"Mode": "OFF"}, "Target": _target(payload), "State": "ENABLED"}
    if one_time:
        kw["ActionAfterCompletion"] = "DELETE"
    try:
        client().create_schedule(**kw)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConflictException":
            log.get().debug("schedule exists", extra={"schedule": name})
            return False
        raise


def delete(name: str) -> bool:
    """True when a schedule was actually deleted; not found counts as done."""
    try:
        client().delete_schedule(Name=name, GroupName=GROUP)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            log.get().debug("schedule not found", extra={"schedule": name})
            return False
        raise


def _at(when_utc: datetime, tz: str) -> str:
    return "at(" + when_utc.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%dT%H:%M:%S") + ")"


def create_checkin(hid: str, checkin_time: str, tz: str) -> bool:
    hh, mm = checkin_time.split(":")
    return _create(name_checkin(hid), f"cron({int(mm)} {int(hh)} * * ? *)", tz,
                   {"kind": "checkin", "household_id": hid}, one_time=False)


def create_weekly(hid: str, tz: str) -> bool:
    return _create(name_weekly(hid), "cron(0 18 ? * SUN *)", tz, {"kind": "weekly_summary", "household_id": hid},
                   one_time=False)


def create_followup(hid: str, local_date: str, tz: str) -> bool:
    payload = {"kind": "followup", "household_id": hid, "local_date": local_date,
               "event_id": dedupe.scheduled_event_id("followup", hid, local_date=local_date)}
    return _create(name_followup(hid, local_date), _at(clock.now() + FOLLOWUP_AFTER, tz), tz, payload, True)


def create_missed_checkin(hid: str, local_date: str, tz: str) -> bool:
    payload = {"kind": "missed_checkin", "household_id": hid, "local_date": local_date,
               "event_id": dedupe.scheduled_event_id("missed_checkin", hid, local_date=local_date)}
    return _create(name_missed(hid, local_date), _at(clock.now() + MISSED_AFTER, tz), tz, payload, True)


def delete_checkin_chain(hid: str, local_date: str) -> int:
    return sum(delete(n) for n in (name_followup(hid, local_date), name_missed(hid, local_date)))


def create_recheck(hid: str, eid: str, run: int, tz: str) -> bool:
    payload = {"kind": "escalation_recheck", "household_id": hid, "escalation_id": eid, "run": run,
               "event_id": dedupe.scheduled_event_id("escalation_recheck", escalation_id=eid, run=run)}
    return _create(name_recheck(eid, run), _at(clock.now() + RECHECK_EVERY, tz), tz, payload, True)


def delete_recheck(eid: str, run: int) -> bool:
    return delete(name_recheck(eid, run))


def create_delivery_check(hid: str, correlation_id: str, tz: str) -> bool:
    payload = {"kind": "delivery_check", "household_id": hid, "correlation_id": correlation_id,
               "event_id": dedupe.scheduled_event_id("delivery_check", correlation_id=correlation_id)}
    return _create(name_delivery_check(correlation_id), _at(clock.now() + DELIVERY_CHECK_AFTER, tz), tz, payload, True)


def create_approval_expiry(hid: str, aid: str, tz: str) -> bool:
    payload = {"kind": "approval_expiry", "household_id": hid, "approval_id": aid,
               "event_id": dedupe.scheduled_event_id("approval_expiry", approval_id=aid)}
    return _create(name_approval_expiry(aid), _at(clock.now() + APPROVAL_EXPIRY_AFTER, tz), tz, payload, True)


def delete_approval_expiry(aid: str) -> bool:
    return delete(name_approval_expiry(aid))
