"""DynamoDB single-table access for household state (table aurasenior-household, PK/SK, TTL attribute ttl)."""
from __future__ import annotations

import os
import secrets
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from . import aws, clock, log
from .models import Approval, Escalation, Household, Medicine, Person

TTL_DAYS = {"MSG": 30, "SIGNAL": 30, "USAGE": 30, "TRACE": 30, "LOG": 90, "APPROVAL": 90, "ESC": 90,
            "TURN": 7, "TJOB": 7, "DEDUP": 7, "SEND": 7}


def table_name() -> str:
    return os.environ.get("TABLE_NAME", "aurasenior-household")


def table():
    return aws.resource_dynamodb().Table(table_name())


def create_table():
    """Used by tests and the offline demo (moto). The stack creates the real table."""
    ddb = aws.resource_dynamodb()
    t = ddb.create_table(
        TableName=table_name(),
        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"},
                              {"AttributeName": "SK", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    t.wait_until_exists()
    return t


def new_id() -> str:
    return secrets.token_hex(6)


def ttl(kind: str) -> int:
    return clock.epoch(clock.now() + timedelta(days=TTL_DAYS[kind]))


def hh(hid: str) -> str:
    return f"HH#{hid}"


def is_conditional_failure(e: ClientError) -> bool:
    return e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"


def to_dynamo(v: Any) -> Any:
    if isinstance(v, float):
        return Decimal(str(v))
    if isinstance(v, dict):
        return {k: to_dynamo(x) for k, x in v.items() if x is not None}
    if isinstance(v, (list, tuple)):
        return [to_dynamo(x) for x in v]
    return v


def plain(v: Any) -> Any:
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [plain(x) for x in v]
    return v


def put(item: dict, **kw) -> None:
    table().put_item(Item=to_dynamo(item), **kw)


def get(pk: str, sk: str) -> dict | None:
    item = table().get_item(Key={"PK": pk, "SK": sk}).get("Item")
    return plain(item) if item else None


def query_prefix(hid: str, prefix: str, *, newest_first: bool = False, limit: int | None = None) -> list[dict]:
    kw: dict[str, Any] = {"KeyConditionExpression": Key("PK").eq(hh(hid)) & Key("SK").begins_with(prefix),
                          "ScanIndexForward": not newest_first}
    if limit:
        kw["Limit"] = limit
    out: list[dict] = []
    while True:
        resp = table().query(**kw)
        out.extend(plain(i) for i in resp.get("Items", []))
        if limit and len(out) >= limit:
            return out[:limit]
        if "LastEvaluatedKey" not in resp:
            return out
        kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _strip(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in ("PK", "SK", "ttl")}


# Profile, people, medicines

def put_household(h: Household) -> None:
    put({"PK": hh(h.household_id), "SK": "PROFILE", **asdict(h)})


def get_household(hid: str) -> Household | None:
    item = get(hh(hid), "PROFILE")
    return Household(**_strip(item)) if item else None


def put_person(p: Person) -> None:
    put({"PK": hh(p.household_id), "SK": f"PERSON#{p.person_id}", **asdict(p)})


def get_person(hid: str, pid: str) -> Person | None:
    item = get(hh(hid), f"PERSON#{pid}")
    return Person(**_strip(item)) if item else None


def people(hid: str) -> list[Person]:
    return [Person(**_strip(i)) for i in query_prefix(hid, "PERSON#")]


def elder(hid: str) -> Person:
    h = get_household(hid)
    return get_person(hid, h.elder_person_id)


def put_medicine(m: Medicine) -> None:
    put({"PK": hh(m.household_id), "SK": f"MED#{m.medicine_id}", **asdict(m)})


def get_medicine(hid: str, mid: str) -> Medicine | None:
    item = get(hh(hid), f"MED#{mid}")
    return Medicine(**_strip(item)) if item else None


def medicines(hid: str) -> list[Medicine]:
    return [Medicine(**_strip(i)) for i in query_prefix(hid, "MED#")]


def set_stock(hid: str, mid: str, stock: str) -> None:
    table().update_item(Key={"PK": hh(hid), "SK": f"MED#{mid}"}, UpdateExpression="SET stock = :s",
                        ExpressionAttributeValues={":s": stock})


# Address reverse lookup

def put_addr(channel: str, address: str, hid: str, pid: str) -> None:
    put({"PK": f"ADDR#{channel}#{address}", "SK": "ADDR", "household_id": hid, "person_id": pid})


def lookup_addr(channel: str, address: str) -> tuple[str, str] | None:
    item = get(f"ADDR#{channel}#{address}", "ADDR")
    return (item["household_id"], item["person_id"]) if item else None


def set_consent(hid: str, pid: str, channel: str, status: str, source: str, simulated: bool = False) -> dict:
    rec = {"status": status, "at": clock.iso(), "source": source}
    if simulated:
        rec["simulated"] = True
    table().update_item(Key={"PK": hh(hid), "SK": f"PERSON#{pid}"},
                        UpdateExpression="SET consent.#c = :r", ExpressionAttributeNames={"#c": channel},
                        ExpressionAttributeValues={":r": rec}, ConditionExpression="attribute_exists(PK)")
    trace(hid, "consent", person_id=pid, channel=channel, outcome=status, source=source, simulated=simulated)
    return rec


def set_wa_inbound(hid: str, pid: str) -> None:
    table().update_item(Key={"PK": hh(hid), "SK": f"PERSON#{pid}"},
                        UpdateExpression="SET wa_last_inbound_at = :t", ExpressionAttributeValues={":t": clock.iso()})


# Medicine log

def log_medicine(hid: str, mid: str, local_date: str, *, taken: bool, out_of_stock: bool = False,
                 source_msg: str | None = None) -> None:
    put({"PK": hh(hid), "SK": f"LOG#{local_date}#{mid}", "medicine_id": mid, "date": local_date, "taken": taken,
         "out_of_stock": out_of_stock, "source_msg": source_msg, "at": clock.iso(), "ttl": ttl("LOG")})
    med = get_medicine(hid, mid)
    if out_of_stock:
        set_stock(hid, mid, "out")
    elif taken and med and med.stock == "ordered":
        set_stock(hid, mid, "ok")


def logs_between(hid: str, start: str, end: str) -> list[dict]:
    return [i for i in query_prefix(hid, "LOG#") if start <= i["date"] <= end]


# Turns

def put_turn(hid: str, pid: str, role: str, text: str) -> None:
    put({"PK": hh(hid), "SK": f"TURN#{pid}#{clock.iso()}#{new_id()[:4]}", "role": role, "text": text,
         "ttl": ttl("TURN")})


def last_turns(hid: str, pid: str, n: int = 10) -> list[dict]:
    items = query_prefix(hid, f"TURN#{pid}#", newest_first=True, limit=n)
    return list(reversed(items))


# Messages

def put_msg(hid: str, provider_id: str, *, channel: str, person_id: str, correlation_id: str,
            direction: str = "out", ref: dict | None = None, **extra) -> None:
    put({"PK": hh(hid), "SK": f"MSG#{provider_id}", "channel": channel, "person_id": person_id,
         "correlation_id": correlation_id, "direction": direction, "ref": ref, "at": clock.iso(),
         "statuses": [], "ttl": ttl("MSG"), **extra})
    # Status events carry only the provider id, so keep a reverse lookup to the household.
    put({"PK": f"MSGID#{provider_id}", "SK": "MSGID", "household_id": hid, "ttl": ttl("MSG")})


def msg_household(provider_id: str) -> str | None:
    item = get(f"MSGID#{provider_id}", "MSGID")
    return item["household_id"] if item else None


def get_msg(hid: str, provider_id: str) -> dict | None:
    return get(hh(hid), f"MSG#{provider_id}")


def append_status(hid: str, provider_id: str, status: str) -> bool:
    try:
        table().update_item(
            Key={"PK": hh(hid), "SK": f"MSG#{provider_id}"},
            UpdateExpression="SET statuses = list_append(if_not_exists(statuses, :e), :s), last_status = :v",
            ExpressionAttributeValues={":e": [], ":s": [{"status": status, "at": clock.iso()}], ":v": status},
            ConditionExpression="attribute_exists(PK)")
        return True
    except ClientError as e:
        if is_conditional_failure(e):
            return False
        raise


def msgs_by_correlation(hid: str, correlation_id: str) -> list[dict]:
    return [m for m in query_prefix(hid, "MSG#") if m.get("correlation_id") == correlation_id]


# Transcribe jobs

def put_tjob(job: str, hid: str, pid: str, wamid: str) -> None:
    put({"PK": f"TJOB#{job}", "SK": "TJOB", "household_id": hid, "person_id": pid, "wamid": wamid,
         "at": clock.iso(), "ttl": ttl("TJOB")})


def get_tjob(job: str) -> dict | None:
    return get(f"TJOB#{job}", "TJOB")


# Usage counters (household-local date)

def _usage_key(hid: str, local_date: str) -> dict:
    return {"PK": hh(hid), "SK": f"USAGE#{local_date}"}


def incr_converse(hid: str, local_date: str) -> int:
    r = table().update_item(Key=_usage_key(hid, local_date),
                            UpdateExpression="ADD converse_calls :one SET #t = if_not_exists(#t, :ttl)",
                            ExpressionAttributeNames={"#t": "ttl"},
                            ExpressionAttributeValues={":one": 1, ":ttl": ttl("USAGE")}, ReturnValues="UPDATED_NEW")
    return int(r["Attributes"]["converse_calls"])


def converse_count(hid: str, local_date: str) -> int:
    item = get(hh(hid), f"USAGE#{local_date}") or {}
    return int(item.get("converse_calls", 0))


def incr_normal(hid: str, local_date: str, hour: str) -> int:
    r = table().update_item(Key=_usage_key(hid, local_date),
                            UpdateExpression="ADD #h :one SET #t = if_not_exists(#t, :ttl)",
                            ExpressionAttributeNames={"#h": f"normal_{hour}", "#t": "ttl"},
                            ExpressionAttributeValues={":one": 1, ":ttl": ttl("USAGE")}, ReturnValues="UPDATED_NEW")
    return int(r["Attributes"][f"normal_{hour}"])


def set_usage_flag(hid: str, local_date: str, flag: str) -> bool:
    """Set a once-per-day flag. True only for the first caller."""
    try:
        table().update_item(Key=_usage_key(hid, local_date), UpdateExpression="SET #f = :t, #ttl = if_not_exists(#ttl, :x)",
                            ConditionExpression="attribute_not_exists(#f)",
                            ExpressionAttributeNames={"#f": flag, "#ttl": "ttl"},
                            ExpressionAttributeValues={":t": clock.iso(), ":x": ttl("USAGE")})
        return True
    except ClientError as e:
        if is_conditional_failure(e):
            return False
        raise


# Trace

_seq = 0
_MASK_KEYS = {"to", "address", "number", "from", "phone", "email", "sender"}


def _mask(v: Any, key: str = "") -> Any:
    if isinstance(v, dict):
        return {k: _mask(x, k) for k, x in v.items()}
    if isinstance(v, list):
        return [_mask(x, key) for x in v]
    if isinstance(v, str):
        if key in _MASK_KEYS:
            return log.mask_email(v) if "@" in v else log.mask_phone(v)
        return log.mask_text(v)
    return v


def trace(hid: str, step: str, *, simulated: bool = False, **fields) -> dict:
    global _seq
    _seq += 1
    item = {"PK": hh(hid), "SK": f"TRACE#{clock.iso()}#{_seq:06d}", "step": step, "at": clock.iso(),
            "simulated": bool(simulated), "ttl": ttl("TRACE"), **_mask(fields)}
    put(item)
    return item


def traces(hid: str, since: str | None = None, limit: int | None = None) -> list[dict]:
    items = query_prefix(hid, "TRACE#")
    if since:
        items = [i for i in items if i["at"] >= since]
    return items[-limit:] if limit else items


# Approvals and escalations

def put_approval(a: Approval) -> None:
    put({"PK": hh(a.household_id), "SK": f"APPROVAL#{a.approval_id}", **asdict(a), "ttl": ttl("APPROVAL")})


def get_approval(hid: str, aid: str) -> Approval | None:
    item = get(hh(hid), f"APPROVAL#{aid}")
    return Approval(**_strip(item)) if item else None


def approvals(hid: str) -> list[Approval]:
    return [Approval(**_strip(i)) for i in query_prefix(hid, "APPROVAL#")]


def transition(pk: str, sk: str, field_name: str, frm: str, to: str, **sets) -> bool:
    """Conditional state change. False when the item is not in state frm."""
    names = {"#f": field_name}
    values = {":from": frm, ":to": to}
    expr = ["#f = :to"]
    for i, (k, v) in enumerate(sets.items()):
        names[f"#s{i}"] = k
        values[f":s{i}"] = to_dynamo(v)
        expr.append(f"#s{i} = :s{i}")
    try:
        table().update_item(Key={"PK": pk, "SK": sk}, UpdateExpression="SET " + ", ".join(expr),
                            ConditionExpression="#f = :from", ExpressionAttributeNames=names,
                            ExpressionAttributeValues=values)
        return True
    except ClientError as e:
        if is_conditional_failure(e):
            return False
        raise


def put_escalation(e: Escalation, condition: str | None = None) -> None:
    kw = {"ConditionExpression": condition} if condition else {}
    put({"PK": hh(e.household_id), "SK": f"ESC#{e.escalation_id}", **asdict(e), "ttl": ttl("ESC")}, **kw)


def get_escalation(hid: str, eid: str) -> Escalation | None:
    item = get(hh(hid), f"ESC#{eid}")
    return Escalation(**_strip(item)) if item else None


def escalations(hid: str) -> list[Escalation]:
    return [Escalation(**_strip(i)) for i in query_prefix(hid, "ESC#")]


def update(pk: str, sk: str, **sets) -> None:
    names = {f"#k{i}": k for i, k in enumerate(sets)}
    values = {f":v{i}": to_dynamo(v) for i, v in enumerate(sets.values())}
    table().update_item(Key={"PK": pk, "SK": sk},
                        UpdateExpression="SET " + ", ".join(f"#k{i} = :v{i}" for i in range(len(sets))),
                        ExpressionAttributeNames=names, ExpressionAttributeValues=values)
