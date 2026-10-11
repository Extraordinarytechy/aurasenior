"""Wire up what CloudFormation cannot create, then check identities and memory. Safe to run again.

Usage: AWS_PROFILE=<profile> python scripts/post_deploy.py --household households/<name>.toml
           [--waba-id <id>] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import boto3  # noqa: E402

from aurasenior import deploy_checks, seed  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--household", required=True)
    ap.add_argument("--waba-id", default="", help="WhatsApp Business Account ID, once linked")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    s = boto3.Session(region_name="us-east-1")
    outputs = deploy_checks.stack_outputs(s.client("cloudformation"))
    params = {p["ParameterKey"]: p.get("ParameterValue", "")
              for p in s.client("cloudformation").describe_stacks(StackName="aurasenior")["Stacks"][0]["Parameters"]}
    ok = True
    if params.get("WhatsAppPhoneNumberId") and args.waba_id:
        social = s.client("socialmessaging")
        if not args.dry_run:
            social.put_whatsapp_business_account_event_destinations(
                id=args.waba_id, eventDestinations=[{"eventDestinationArn": outputs["WhatsAppEventsTopicArn"]}])
        names = deploy_checks.submit_templates(social, args.waba_id, dry_run=args.dry_run)
        print(f"WhatsApp templates submitted: {names or 'none new'}")
    else:
        print("WhatsApp not linked yet: skipped event destination and templates")
    if params.get("RcsAgentId"):
        if not args.dry_run:
            s.client("pinpoint-sms-voice-v2").update_rcs_agent(
                RcsAgentId=params["RcsAgentId"], TwoWayEnabled=True, TwoWayChannelArn=outputs["SmsRcsEventsTopicArn"],
                OptOutListName="aurasenior-optout")
        print("RCS agent wired to the two-way topic and opt-out list")
    data = seed.load_file(args.household)
    emails = [params.get("SenderEmail", "")] + [p["addresses"]["email"] for p in data["people"]
                                                 if p.get("addresses", {}).get("email")]
    missing = deploy_checks.unverified_identities(s.client("sesv2"), [e for e in emails if e])
    print(f"SES identities not verified yet: {missing or 'none'}")
    good, msg = deploy_checks.check_memory(s.client("bedrock-agentcore-control"), outputs)
    print(msg)
    ok = ok and good
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
