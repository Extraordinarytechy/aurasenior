import json
import re
from pathlib import Path

from aurasenior import config
from cfn_yaml import load

T = load(Path(__file__).resolve().parent.parent / "template.yaml")
R = T["Resources"]


def _of(kind):
    return {k: v for k, v in R.items() if v["Type"] == kind}


def test_metric_filters_and_alarm_shape():
    filters = _of("AWS::Logs::MetricFilter")
    assert {f["Properties"]["LogGroupName"] for f in filters.values()} == {"/aws/lambda/aurasenior-inbound",
                                                                          "/aws/lambda/aurasenior-scheduled"}
    for f in filters.values():
        assert f["Properties"]["FilterPattern"] == '{ $.level = "ERROR" }'
        assert f["Properties"]["MetricTransformations"][0]["MetricName"] == "ErrorLogs"
    alarm = R["ErrorsAlarm"]["Properties"]
    assert alarm["AlarmName"] == "aurasenior-errors" and alarm["Threshold"] == 0
    assert [m["Id"] for m in alarm["Metrics"] if m.get("ReturnData")] == ["total"]


def test_functions_have_no_logging_config_and_depend_on_log_groups():
    for name in ("InboundFunction", "ScheduledFunction"):
        fn = R[name]
        assert "LoggingConfig" not in fn["Properties"]
        assert fn["DependsOn"].endswith("LogGroup")
    assert T["Globals"]["Function"]["Runtime"] == "python3.13"
    assert T["Globals"]["Function"]["Architectures"] == ["arm64"]


def _statements():
    out = []
    for res in list(_of("AWS::IAM::ManagedPolicy").values()) + list(_of("AWS::IAM::Role").values()):
        docs = [res["Properties"].get("PolicyDocument")] + [p["PolicyDocument"] for p in res["Properties"].get("Policies", [])]
        for d in filter(None, docs):
            for s in d["Statement"]:
                if "Fn::If" in s:
                    s = s["Fn::If"][1]
                out.append(s)
    return out


def test_iam_star_only_for_documented_actions():
    for s in _statements():
        res = s["Resource"] if isinstance(s["Resource"], list) else [s["Resource"]]
        if "*" in res:
            assert s["Action"] in ("transcribe:StartTranscriptionJob", "polly:SynthesizeSpeech"), s


def test_named_resources_start_with_aurasenior():
    keys = ("TableName", "TopicName", "FunctionName", "RoleName", "ManagedPolicyName", "AlarmName", "LogGroupName",
            "ConfigurationSetName", "OptOutListName", "ContactListName", "RuleName")
    for res in R.values():
        props = res.get("Properties", {})
        for k in keys:
            v = props.get(k)
            if isinstance(v, str):
                assert v.startswith(("aurasenior", "/aws/lambda/aurasenior")), (k, v)
    assert R["Guardrail"]["Properties"]["Name"] == "aurasenior-safety"
    assert R["SchedulerGroup"]["Properties"]["Name"] == "aurasenior"


def test_brand_value_not_in_ses_template_text():
    word = re.compile(r"\b" + re.escape(config.brand()) + r"\b")
    for t in _of("AWS::SES::Template").values():
        tpl = t["Properties"]["Template"]
        for part in ("SubjectPart", "TextPart", "HtmlPart"):
            assert not word.search(tpl[part])
        assert tpl["SubjectPart"].startswith("{{brand}}: ")
    assert len(_of("AWS::SES::Template")) == 6


def test_agentcore_memory_output_and_name():
    out = T["Outputs"]["AgentCoreMemoryId"]
    assert out["Condition"] == "HasAgentCoreMemory"
    assert out["Value"] == {"Fn::GetAtt": ["AuraSeniorMemory", "MemoryId"]}
    mem = R["AuraSeniorMemory"]
    assert mem["Condition"] == "HasAgentCoreMemory"
    assert re.fullmatch(r"^[a-zA-Z][a-zA-Z0-9_]{0,47}$", mem["Properties"]["Name"])
    ns = [list(s.values())[0]["Namespaces"][0] for s in mem["Properties"]["MemoryStrategies"]]
    assert ns == ["/aurasenior/facts/{actorId}/", "/aurasenior/checkins/{actorId}/{sessionId}/"]


def test_event_invoke_config_on_latest_with_failure_topic():
    for c in _of("AWS::Lambda::EventInvokeConfig").values():
        p = c["Properties"]
        assert p["Qualifier"] == "$LATEST" and p["MaximumRetryAttempts"] == 2
        assert p["DestinationConfig"]["OnFailure"]["Destination"] == {"Ref": "FailedEventsTopic"}


def test_topic_policies_have_one_allow_and_no_deny():
    for pol in _of("AWS::SNS::TopicPolicy").values():
        st = pol["Properties"]["PolicyDocument"]["Statement"]
        assert len(st) == 1 and st[0]["Effect"] == "Allow"
