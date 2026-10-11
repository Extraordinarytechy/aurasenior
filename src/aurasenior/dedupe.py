"""Event dedupe and idempotent sends, so Lambda async retries never repeat work or messages."""
from __future__ import annotations

from datetime import timedelta
from typing import Callable

from botocore.exceptions import ClientError

from . import clock, log, store

TAKEOVER = timedelta(minutes=5)


def claim(event_id: str) -> bool:
    """True when this invocation may process the event."""
    stale = clock.iso(clock.now() - TAKEOVER)
    try:
        store.table().put_item(
            Item={"PK": f"DEDUP#{event_id}", "SK": "DEDUP", "status": "processing", "at": clock.iso(),
                  "ttl": store.ttl("DEDUP")},
            ConditionExpression="attribute_not_exists(PK) OR (#s = :p AND #a < :stale)",
            ExpressionAttributeNames={"#s": "status", "#a": "at"},
            ExpressionAttributeValues={":p": "processing", ":stale": stale})
        return True
    except ClientError as e:
        if store.is_conditional_failure(e):
            log.get().debug("duplicate event skipped", extra={"event_id": event_id})
            return False
        raise


def done(event_id: str) -> None:
    store.update(f"DEDUP#{event_id}", "DEDUP", status="done")


def release(event_id: str) -> None:
    store.table().delete_item(Key={"PK": f"DEDUP#{event_id}", "SK": "DEDUP"})


def send_once(hid: str, correlation_id: str, fn: Callable[[], str | None]) -> tuple[bool, str | None]:
    """Run fn (which returns a provider id) at most once per correlation id. Returns (ran, provider_id)."""
    key = {"PK": store.hh(hid), "SK": f"SEND#{correlation_id}"}
    existing = store.get(key["PK"], key["SK"])
    if existing and existing.get("status") == "sent":
        return False, existing.get("provider_id")
    stale = clock.iso(clock.now() - TAKEOVER)
    try:
        store.table().put_item(
            Item={**key, "status": "sending", "at": clock.iso(), "ttl": store.ttl("SEND")},
            ConditionExpression="attribute_not_exists(PK) OR (#s = :sending AND #a < :stale)",
            ExpressionAttributeNames={"#s": "status", "#a": "at"},
            ExpressionAttributeValues={":sending": "sending", ":stale": stale})
    except ClientError as e:
        if store.is_conditional_failure(e):
            return False, None
        raise
    try:
        provider_id = fn()
    except Exception:
        store.table().delete_item(Key=key)
        raise
    store.update(key["PK"], key["SK"], status="sent", provider_id=provider_id or "")
    return True, provider_id


# Event ids for scheduled runs, built from the payload, never from the invocation.

def scheduled_event_id(kind: str, hid: str | None = None, *, local_date: str | None = None,
                       escalation_id: str | None = None, run: int | None = None,
                       correlation_id: str | None = None, approval_id: str | None = None) -> str:
    if kind == "checkin":
        return f"checkin#{hid}#{local_date}"
    if kind == "weekly_summary":
        return f"weekly#{hid}#{local_date}"
    if kind in ("followup", "missed_checkin"):
        return f"{kind}#{hid}#{local_date}"
    if kind == "escalation_recheck":
        return f"recheck#{escalation_id}#{run}"
    if kind == "delivery_check":
        return f"dcheck#{correlation_id}"
    if kind == "approval_expiry":
        return f"expiry#{approval_id}"
    raise ValueError(f"unknown kind {kind}")
