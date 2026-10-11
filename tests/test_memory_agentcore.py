import json
import re

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError

from aurasenior import aws, store
from aurasenior.memory import agentcore, build_store
from aurasenior.memory.agentcore import AgentCoreMemoryStore
from aurasenior.memory.dynamo import DynamoMemoryStore

HID, PID = "a" * 12, "b" * 12


class StubClient:
    """Records every bedrock-agentcore call; responses and errors are set per test."""

    def __init__(self, records=None, error=None):
        self.calls = []
        self.records = records or {}
        self.error = error

    def create_event(self, **kw):
        self.calls.append(("create_event", kw))
        if self.error:
            raise self.error
        return {"event": {"eventId": "e1"}}

    def retrieve_memory_records(self, **kw):
        self.calls.append(("retrieve_memory_records", kw))
        if self.error:
            raise self.error
        key = "facts" if "/facts/" in kw["namespace"] else "checkins"
        return {"memoryRecordSummaries": self.records.get(key, [])}


def _err(code):
    return ClientError({"Error": {"Code": code, "Message": code}}, "Op")


@pytest.fixture
def stub():
    agentcore.reset_invocation()
    s = StubClient()
    aws.override("bedrock-agentcore", s)
    yield s
    agentcore.reset_invocation()


def _store():
    return AgentCoreMemoryStore("aurasenior_memory-abc", "hi-IN", timezone="Asia/Kolkata")


def test_ids_match_sdk_patterns():
    a = agentcore.actor_id(HID, PID)
    s = agentcore.session_id(HID, PID, "2026-10-12")
    assert re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-_/]*", a) and len(a) <= 255
    assert re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-_]*", s) and len(s) <= 100
    assert agentcore.FACTS.format(actor=a).endswith("/")


@pytest.mark.parametrize("error", [_err("ThrottlingException"), ReadTimeoutError(endpoint_url="x")])
def test_recoverable_error_falls_back_and_turn_completes(table, frozen, stub, error, capsys):
    stub.error = error
    m = _store()
    m.remember(HID, PID, "Priya is the granddaughter")
    m.record_turn(HID, PID, "hello", "namaste")
    assert m.recall(HID, PID, "hello") == ["Priya is the granddaughter"]
    levels = [json.loads(x)["level"] for x in capsys.readouterr().out.splitlines()]
    assert "ERROR" not in levels and "WARN" in levels


def test_access_denied_logs_error_once_and_disables(table, frozen, stub, capsys):
    stub.error = _err("AccessDeniedException")
    m = _store()
    m.record_turn(HID, PID, "a", "b")
    m.record_turn(HID, PID, "c", "d")
    m.recall(HID, PID)
    assert len(stub.calls) == 1
    levels = [json.loads(x)["level"] for x in capsys.readouterr().out.splitlines()]
    assert levels.count("ERROR") == 1


def test_remember_writes_dynamodb_before_create_event(table, frozen, stub):
    seen = {}

    def create_event(**kw):
        seen["notes"] = DynamoMemoryStore("hi-IN").notes(HID, PID)
        return {}

    stub.create_event = create_event
    _store().remember(HID, PID, "wakes at 6")
    assert seen["notes"][0]["text"] == "wakes at 6"


def test_build_store_is_elder_only(sample, monkeypatch, stub):
    assert isinstance(build_store(store.get_person(sample, "kamala")), DynamoMemoryStore)
    monkeypatch.setenv("AGENTCORE_MEMORY_ID", "aurasenior_memory-abc")
    assert isinstance(build_store(store.get_person(sample, "kamala")), AgentCoreMemoryStore)
    for pid in ("rohan", "nbr", "doctor", "pharmacy", "simfam"):
        m = build_store(store.get_person(sample, pid))
        assert isinstance(m, DynamoMemoryStore)
        m.recall(sample, pid, "How was Mom?")
        m.record_turn(sample, pid, "How was Mom?", "fine")
    assert stub.calls == []


def test_cap_and_order(table, frozen, stub):
    stub.records = {
        "facts": [{"content": {"text": "F low"}, "score": 0.1}, {"content": {"text": "F high " + "x" * 600}, "score": 0.9},
                  {"content": {"text": "<topic name='people'>Priya visits on Sundays</topic>"}, "score": 0.5},
                  {"content": {"text": "y" * 301}, "score": 0.95}],
        "checkins": [{"content": {"text": "C " + "z" * 700}, "score": 0.8}],
    }
    m = _store()
    m.fallback.remember(HID, PID, "N old")
    m.fallback.remember(HID, PID, "N new")
    block = m.recall(HID, PID)
    assert block[:2] == ["N new", "N old"]
    assert block[2] == "Priya visits on Sundays"  # tags stripped; the 301-character record is dropped
    assert sum(len(b) for b in block) <= 1500
    assert all(len(b) <= 300 for b in block[2:])


def test_search_query_is_first_500_chars_or_fixed_text(table, frozen, stub):
    m = _store()
    m.recall(HID, PID, "q" * 800)
    m.recall(HID, PID, None)
    queries = [kw["searchCriteria"]["searchQuery"] for op, kw in stub.calls]
    assert queries[0] == "q" * 500 and queries[2] == agentcore.DEFAULT_QUERY
    tops = [kw["searchCriteria"]["topK"] for op, kw in stub.calls[:2]]
    assert tops == [5, 3]


def test_recalled_record_with_wording_phrase_is_dropped(table, frozen, stub, capsys):
    stub.records = {"facts": [{"content": {"text": "has diabetes"}, "score": 0.9},
                              {"content": {"text": "मधुमेह है"}, "score": 0.8},
                              {"content": {"text": "likes chai"}, "score": 0.7}]}
    assert _store().recall(HID, PID) == ["likes chai"]
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert len(lines) == 2 and all(x["source"] == "agentcore" and x["rule"] for x in lines)
    assert "diabetes" not in json.dumps(lines)


def test_checkin_token_is_stable_and_event_is_assistant(table, frozen, stub):
    m = _store()
    m.record_checkin(HID, PID, "2026-10-12", "Check-in 2026-10-12: no reply")
    m.record_checkin(HID, PID, "2026-10-12", "Check-in 2026-10-12: no reply")
    t1, t2 = (kw["clientToken"] for _, kw in stub.calls)
    assert t1 == t2 == agentcore.checkin_token(HID, PID, "2026-10-12") and len(t1) == 32
    kw = stub.calls[0][1]
    assert kw["payload"][0]["conversational"]["role"] == "ASSISTANT"
    assert kw["sessionId"] == f"{HID}-{PID}-20261012"


def test_event_text_is_capped(table, frozen, stub):
    _store().record_turn(HID, PID, "u" * 3000, "r")
    assert len(stub.calls[0][1]["payload"][0]["conversational"]["content"]["text"]) == 2000
