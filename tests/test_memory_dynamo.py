import json

from aurasenior import store
from aurasenior.memory import build_store
from aurasenior.memory.dynamo import DynamoMemoryStore


def test_fifty_first_note_drops_the_oldest(table, frozen):
    m = DynamoMemoryStore("hi-IN")
    for i in range(51):
        m.remember("hh1", "p1", f"note {i}")
    notes = m.recall("hh1", "p1")
    assert len(notes) == 50 and notes[0] == "note 50" and "note 0" not in notes


def test_note_with_wording_phrase_is_dropped_without_text_in_log(table, frozen, capsys):
    m = DynamoMemoryStore("hi-IN")
    m.remember("hh1", "p1", "Priya is her granddaughter")
    m.remember("hh1", "p1", "she has मधुमेह")
    m.remember("hh1", "p1", "talked about dementia")
    assert m.recall("hh1", "p1") == ["Priya is her granddaughter"]
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert [x["level"] for x in lines] == ["WARN", "WARN"]
    assert all(x["source"] == "dynamodb" and x["rule"] == "disease" for x in lines)
    assert not any("मधुमेह" in json.dumps(x, ensure_ascii=False) or "dementia" in json.dumps(x) for x in lines)


def test_record_checkin_and_turn_write_nothing(table, frozen):
    m = DynamoMemoryStore("hi-IN")
    m.record_checkin("hh1", "p1", "2026-10-12", "Check-in 2026-10-12: replied 09:14")
    m.record_turn("hh1", "p1", "hello", "hi")
    assert store.table().scan()["Items"] == []


def test_family_person_gets_dynamo_store(sample, monkeypatch):
    monkeypatch.setenv("AGENTCORE_MEMORY_ID", "aurasenior_memory-abc")
    assert isinstance(build_store(store.get_person(sample, "rohan")), DynamoMemoryStore)
