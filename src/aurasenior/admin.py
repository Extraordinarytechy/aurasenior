"""Household admin commands, run locally with the developer's own AWS credentials.

python -m aurasenior.admin consent <household_id> <person_id> email opted_in|opted_out --source "phone call"
python -m aurasenior.admin rcs-ask <household_id> <person_id>
"""
from __future__ import annotations

import argparse
import os
import sys

from . import aws, clock, consent, store


def _fail(msg: str) -> int:
    print(msg, file=sys.stderr)
    return 1


def cmd_consent(hid: str, pid: str, channel: str, status: str, source: str | None) -> int:
    if channel != "email":
        return _fail("only email consent can be set by the admin; other channels need the person's own reply")
    if status not in ("opted_in", "opted_out"):
        return _fail("status must be opted_in or opted_out")
    if not source or not (1 <= len(source) <= 200):
        return _fail("--source is required (1 to 200 characters)")
    p = store.get_person(hid, pid)
    if not p:
        return _fail("unknown household or person")
    if not p.addresses.get("email"):
        return _fail("person has no email address")
    store.set_consent(hid, pid, "email", status, f"admin:{source}")
    print(f"email consent for {pid} set to {status}")
    return 0


def cmd_rcs_ask(hid: str, pid: str) -> int:
    p = store.get_person(hid, pid)
    if not p or not p.addresses.get("rcs"):
        return _fail("unknown person or no RCS number")
    agent = os.environ.get("RCS_AGENT_ID", "")
    resp = aws.client("pinpoint-sms-voice-v2").describe_verified_destination_numbers(
        DestinationPhoneNumbers=[p.addresses["rcs"]], Filters=[{"Name": "rcs-agent-id", "Values": [agent]}])
    verified = [v for v in resp.get("VerifiedDestinationNumbers", []) if v.get("Status") == "VERIFIED"]
    if not verified:
        return _fail("number is not a verified RCS test device for the agent")
    r = consent._ask(p, "rcs", None, f"rcsask#{hid}#{pid}#{clock.local_date('UTC')}", rcs_verified=True)
    if r.outcome != "sent":
        return _fail(f"not sent: {r.outcome} (the ask is allowed once per day)")
    print("opt-in ask sent")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m aurasenior.admin")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("consent")
    c.add_argument("household_id")
    c.add_argument("person_id")
    c.add_argument("channel")
    c.add_argument("status")
    c.add_argument("--source")
    r = sub.add_parser("rcs-ask")
    r.add_argument("household_id")
    r.add_argument("person_id")
    args = ap.parse_args(argv)
    if args.cmd == "consent":
        return cmd_consent(args.household_id, args.person_id, args.channel, args.status, args.source)
    return cmd_rcs_ask(args.household_id, args.person_id)


if __name__ == "__main__":
    raise SystemExit(main())
