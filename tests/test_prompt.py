from aurasenior import store
from aurasenior.agent import prompt
from aurasenior.memory.dynamo import DynamoMemoryStore


def test_family_prompt_excludes_elder_turns(sample):
    store.put_turn(sample, "kamala", "user", "मेरे घुटने में दर्द है")
    store.put_turn(sample, "kamala", "assistant", "ठीक है")
    store.put_turn(sample, "rohan", "user", "Hi")
    store.put_turn(sample, "rohan", "assistant", "Hello")
    rohan = store.get_person(sample, "rohan")
    system, _ = prompt.system_prompt(sample, rohan, {"text": "How was Mom this week?"})
    hist = prompt.history(sample, rohan)
    assert "घुटने" not in system and all("घुटने" not in m["content"][0]["text"] for m in hist)
    assert "Mom" in system


def test_memory_block_present_for_elder(sample):
    DynamoMemoryStore("hi-IN").remember(sample, "kamala", "Granddaughter Priya calls on Sundays")
    system, mem = prompt.system_prompt(sample, store.get_person(sample, "kamala"), {"text": "hello"})
    assert "Priya" in system and mem


def test_query_is_none_on_scheduled_turns():
    assert prompt.query_for({"text": "x" * 900})== "x" * 500
    assert prompt.query_for({"scheduled": True, "text": "check-in"}) is None
    assert prompt.query_for({}) is None


def test_reply_language_follows_language_row(sample):
    system, _ = prompt.system_prompt(sample, store.get_person(sample, "kamala"), {"text": "hi"})
    assert "Hindi, Devanagari script" in system
