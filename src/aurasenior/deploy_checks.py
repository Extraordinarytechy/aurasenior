"""Post-deploy wiring and deploy permission checks. Run locally with the developer's own credentials.

Everything here is idempotent and touches only resources whose names start with aurasenior.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from . import config

STACK = "aurasenior"
SRC_CONFIG = Path(__file__).resolve().parent.parent / "config"

# Deploy-time actions to simulate for the deploy user, beyond full-access services.
MEMORY_HANDLER_ACTIONS = [
    "bedrock-agentcore:CreateMemory", "bedrock-agentcore:GetMemory", "bedrock-agentcore:UpdateMemory",
    "bedrock-agentcore:DeleteMemory", "bedrock-agentcore:TagResource", "bedrock-agentcore:UntagResource",
    "bedrock-agentcore:ListTagsForResource", "bedrock-agentcore:ListMemories", "iam:PassRole",
    "kms:DescribeKey", "kms:CreateGrant", "kms:Decrypt", "kms:GenerateDataKey",
    "kms:GenerateDataKeyWithoutPlaintext", "kms:ReEncryptTo", "kms:ReEncryptFrom",
]
DEPLOY_ACTIONS = [
    "cloudformation:CreateChangeSet", "cloudformation:ExecuteChangeSet", "cloudformation:DescribeStacks",
    "lambda:CreateFunction", "lambda:PutFunctionEventInvokeConfig", "lambda:AddPermission",
    "iam:CreateRole", "iam:CreatePolicy", "iam:AttachRolePolicy", "iam:PutRolePolicy",
    "dynamodb:CreateTable", "s3:CreateBucket", "sns:CreateTopic", "sns:Subscribe", "sns:SetTopicAttributes",
    "events:PutRule", "events:PutTargets", "scheduler:CreateScheduleGroup",
    "ses:CreateConfigurationSet", "ses:CreateConfigurationSetEventDestination", "ses:CreateContactList",
    "ses:CreateEmailTemplate", "ses:GetEmailIdentity",
    "sms-voice:RequestPhoneNumber", "sms-voice:CreateOptOutList", "sms-voice:CreateConfigurationSet",
    "sms-voice:CreateEventDestination", "sms-voice:UpdateRcsAgent", "sms-voice:DescribeVerifiedDestinationNumbers",
    "social-messaging:PutWhatsAppBusinessAccountEventDestinations", "social-messaging:CreateWhatsAppMessageTemplate",
    "social-messaging:ListWhatsAppMessageTemplates",
    "bedrock:CreateGuardrail", "bedrock:CreateGuardrailVersion",
    "logs:CreateLogGroup", "logs:PutRetentionPolicy", "logs:PutMetricFilter", "cloudwatch:PutMetricAlarm",
    "budgets:ModifyBudget",
]
LIVE_TEST_ACTIONS = ["bedrock:InvokeModel", "bedrock-agentcore:CreateEvent", "bedrock-agentcore:RetrieveMemoryRecords"]


def action_list() -> list[str]:
    seen, out = set(), []
    for a in DEPLOY_ACTIONS + MEMORY_HANDLER_ACTIONS + LIVE_TEST_ACTIONS:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


# Policies scoped to aurasenior names only allow these actions on the matching resource, so simulate with it.
SCOPED = {
    "events:PutRule": "arn:aws:events:{r}:{a}:rule/aurasenior-transcribe-done",
    "events:PutTargets": "arn:aws:events:{r}:{a}:rule/aurasenior-transcribe-done",
    "logs:CreateLogGroup": "arn:aws:logs:{r}:{a}:log-group:/aws/lambda/aurasenior-inbound",
    "logs:PutRetentionPolicy": "arn:aws:logs:{r}:{a}:log-group:/aws/lambda/aurasenior-inbound",
    "logs:PutMetricFilter": "arn:aws:logs:{r}:{a}:log-group:/aws/lambda/aurasenior-inbound",
    "budgets:ModifyBudget": "arn:aws:budgets::{a}:budget/aurasenior-monthly",
}


def simulate(iam, sts, region: str = "us-east-1") -> dict:
    ident = sts.get_caller_identity()
    arn, account = ident["Arn"], ident["Account"]
    allowed, denied = [], []
    actions = action_list()
    plain = [a for a in actions if a not in SCOPED]
    batches = [(plain[i:i + 20], None) for i in range(0, len(plain), 20)]
    batches += [([a], SCOPED[a].format(r=region, a=account)) for a in actions if a in SCOPED]
    for names, resource in batches:
        kw = {"PolicySourceArn": arn, "ActionNames": names}
        if resource:
            kw["ResourceArns"] = [resource]
        for r in iam.simulate_principal_policy(**kw)["EvaluationResults"]:
            (allowed if r["EvalDecision"] == "allowed" else denied).append(r["EvalActionName"])
    return {"allowed": allowed, "denied": denied}


def stack_outputs(cfn) -> dict:
    stack = cfn.describe_stacks(StackName=STACK)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}


def check_memory(agentcore_control, outputs: dict) -> tuple[bool, str]:
    memory_id = outputs.get("AgentCoreMemoryId")
    if not memory_id:
        return True, "AgentCore Memory off, DynamoDB memory only"
    status = agentcore_control.get_memory(memoryId=memory_id)["memory"]["status"]
    if status != "ACTIVE":
        return False, f"AgentCore Memory {memory_id} is {status}, expected ACTIVE"
    return True, f"AgentCore Memory {memory_id} is ACTIVE"


def template_definitions() -> list[dict]:
    """WhatsApp template definitions with {brand} replaced; Meta positional variables stay as they are."""
    with (SRC_CONFIG / "whatsapp_templates.toml").open("rb") as f:
        data = tomllib.load(f)
    out = []
    for base, langs in data.items():
        if base == "actions":
            continue
        for lang, t in langs.items():
            row = {"hi": ("_hi", "hi"), "en": ("_en", "en_US")}[lang]
            body = {"type": "BODY", "text": t["body"].replace("{brand}", config.brand())}
            if t.get("example"):
                # Meta reviews a body with {{n}} variables only with sample values, one per variable.
                body["example"] = {"body_text": [list(t["example"])]}
            comps = [body]
            if t["buttons"]:
                comps.append({"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": b} for b in t["buttons"]]})
            out.append({"name": base + row[0], "language": row[1], "category": "UTILITY", "components": comps})
    return out


TEMPLATE_NAME = re.compile(r"^[a-z0-9_]{1,512}$")
VARIABLE = re.compile(r"\{\{(\d+)\}\}")


def template_problems(defs: list[dict] | None = None) -> list[tuple[str, str, str]]:
    """(level, template, problem) for Meta's documented template rules: name lowercase letters, digits and
    underscores (max 512), body max 1024 characters, positional variables numbered from 1 in order, one example
    value per variable, at most 10 buttons with labels of at most 25 characters. Placement of a variable at the
    very start or end of the body, and a repeated variable, are reported as warnings: review commonly rejects them."""
    out = []
    for d in template_definitions() if defs is None else defs:
        name = f"{d['name']} ({d['language']})"
        if not TEMPLATE_NAME.match(d["name"]):
            out.append(("error", name, "name must be lowercase letters, digits and underscores, max 512"))
        body = next(c for c in d["components"] if c["type"] == "BODY")
        text = body["text"]
        if len(text) > 1024:
            out.append(("error", name, f"body is {len(text)} characters, max 1024"))
        nums = [int(n) for n in VARIABLE.findall(text)]
        distinct = list(dict.fromkeys(nums))
        if distinct != list(range(1, len(distinct) + 1)):
            out.append(("error", name, f"variables {distinct} are not numbered 1..n in order"))
        examples = (body.get("example") or {}).get("body_text") or [[]]
        if nums and len(examples[0]) != len(distinct):
            out.append(("error", name, f"{len(examples[0])} example values for {len(distinct)} variables"))
        if any(not str(v).strip() for v in examples[0]):
            out.append(("error", name, "an example value is empty"))
        if len(nums) != len(distinct):
            out.append(("warning", name, "a variable appears more than once"))
        bare = text.strip().rstrip(".!?।:")
        if VARIABLE.match(bare) or re.search(r"\{\{\d+\}\}$", bare):
            out.append(("warning", name, "body starts or ends with a variable"))
        buttons = [b for c in d["components"] if c["type"] == "BUTTONS" for b in c["buttons"]]
        if len(buttons) > 10:
            out.append(("error", name, f"{len(buttons)} buttons, max 10"))
        for b in buttons:
            if not 1 <= len(b["text"]) <= 25:
                out.append(("error", name, f"button label {b['text']!r} must be 1 to 25 characters"))
    return out


def submit_templates(social, waba_id: str, dry_run: bool = False) -> list[str]:
    existing = {t["templateName"] for t in social.list_whatsapp_message_templates(id=waba_id).get("templates", [])}
    submitted = []
    for d in template_definitions():
        if d["name"] in existing:
            continue
        if not dry_run:
            social.create_whatsapp_message_template(id=waba_id, templateDefinition=json.dumps(d).encode())
        submitted.append(d["name"])
    return submitted


def unverified_identities(sesv2, addresses: list[str]) -> list[str]:
    out = []
    for a in addresses:
        try:
            if not sesv2.get_email_identity(EmailIdentity=a).get("VerifiedForSendingStatus"):
                out.append(a)
        except sesv2.exceptions.NotFoundException:
            out.append(a)
    return out
