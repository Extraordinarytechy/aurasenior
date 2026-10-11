import json
from pathlib import Path

import boto3
from botocore.stub import Stubber

from aurasenior import deploy_checks

EVIDENCE = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "cfn-agentcore-memory-handlers-2026-10-11.json"


def test_missing_memory_output_skips_get_memory():
    c = boto3.client("bedrock-agentcore-control", region_name="us-east-1")
    with Stubber(c):
        ok, msg = deploy_checks.check_memory(c, {"TableName": "aurasenior-household"})
    assert ok and msg == "AgentCore Memory off, DynamoDB memory only"


def test_non_active_memory_fails():
    c = boto3.client("bedrock-agentcore-control", region_name="us-east-1")
    mem = {"arn": "arn:aws:bedrock-agentcore:us-east-1:000000000000:memory/aurasenior_memory-abc",
           "id": "aurasenior_memory-abc", "name": "aurasenior_memory", "eventExpiryDuration": 30,
           "status": "CREATING", "createdAt": "2026-10-11T00:00:00Z", "updatedAt": "2026-10-11T00:00:00Z"}
    with Stubber(c) as s:
        s.add_response("get_memory", {"memory": mem}, {"memoryId": "aurasenior_memory-abc"})
        ok, _ = deploy_checks.check_memory(c, {"AgentCoreMemoryId": "aurasenior_memory-abc"})
    assert not ok


def test_template_submission_replaces_brand_and_skips_existing():
    c = boto3.client("socialmessaging", region_name="us-east-1")
    defs = deploy_checks.template_definitions()
    assert len(defs) == 14
    assert all("{brand}" not in json.dumps(d, ensure_ascii=False) for d in defs)
    existing = [{"templateName": "aurasenior_checkin_hi"}]
    with Stubber(c) as s:
        s.add_response("list_whatsapp_message_templates", {"templates": existing}, {"id": "waba-1"})
        names = deploy_checks.submit_templates(c, "waba-1", dry_run=True)
    assert "aurasenior_checkin_hi" not in names and "aurasenior_checkin_en" in names and len(names) == 13


def test_every_body_variable_has_one_example_value():
    import re

    for d in deploy_checks.template_definitions():
        body = d["components"][0]
        n = len(set(re.findall(r"\{\{(\d+)\}\}", body["text"])))
        assert n > 0, d["name"]
        assert len(body["example"]["body_text"][0]) == n, d["name"]


def test_action_list_includes_every_memory_handler_permission():
    data = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    needed = set()
    for k in ("create", "update", "delete", "list"):
        needed |= set(data["handlers"][k])
    acts = set(deploy_checks.action_list())
    assert needed <= acts
    assert {"logs:CreateLogGroup", "logs:PutRetentionPolicy", "logs:PutMetricFilter", "cloudwatch:PutMetricAlarm",
            "bedrock-agentcore:CreateEvent", "bedrock-agentcore:RetrieveMemoryRecords", "bedrock:InvokeModel"} <= acts


def test_simulate_splits_allowed_and_denied():
    iam = boto3.client("iam", region_name="us-east-1")
    sts = boto3.client("sts", region_name="us-east-1")
    acts = deploy_checks.action_list()
    plain = [a for a in acts if a not in deploy_checks.SCOPED]
    with Stubber(iam) as si, Stubber(sts) as ss:
        ss.add_response("get_caller_identity", {"Arn": "arn:aws:iam::000000000000:user/dev", "Account": "000000000000",
                                                "UserId": "AIDEXAMPLE"})
        for i in range(0, len(plain), 20):
            si.add_response("simulate_principal_policy", {"EvaluationResults": [
                {"EvalActionName": a, "EvalDecision": "implicitDeny" if a.startswith("kms:") else "allowed"}
                for a in plain[i:i + 20]]})
        for a in [a for a in acts if a in deploy_checks.SCOPED]:
            si.add_response("simulate_principal_policy", {"EvaluationResults": [
                {"EvalActionName": a, "EvalDecision": "allowed"}]},
                {"PolicySourceArn": "arn:aws:iam::000000000000:user/dev", "ActionNames": [a],
                 "ResourceArns": [deploy_checks.SCOPED[a].format(r="us-east-1", a="000000000000")]})
        r = deploy_checks.simulate(iam, sts)
    assert r["denied"] and all(a.startswith("kms:") for a in r["denied"])
    assert "events:PutRule" in r["allowed"]
