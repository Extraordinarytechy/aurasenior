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


def test_family_prompt_speaks_to_the_family_member_not_the_elder(sample):
    family, _ = prompt.system_prompt(sample, store.get_person(sample, "rohan"), {"text": "YES please"})
    elder, _ = prompt.system_prompt(sample, store.get_person(sample, "kamala"), {"text": "हाँ"})
    assert "You are talking with Rohan, not with the elder" in family
    assert 'Never address Rohan as Mom' in family
    assert "talking with the elder herself" not in family and "call suggest_call once" not in family
    assert "talking with the elder herself" in elder and "Rohan, not with the elder" not in elder
    for system in (family, elder):
        assert "never repeat their tool calls" in system


def test_rules_forbid_symptom_and_medicine_advice(sample):
    system, _ = prompt.system_prompt(sample, store.get_person(sample, "kamala"), {"text": "hi"})
    assert "never say how, when or whether to take a medicine" in system
    assert "only say you are sorry to hear it" in system
    assert "Say only what a tool result in this turn shows" in system
    assert "Never say you asked, told or ordered anything unless a tool" in system


def test_prompt_names_refills_already_open(sample):
    from aurasenior import clock
    from aurasenior.models import Approval

    kamala = store.get_person(sample, "kamala")
    assert "Refills open in the last day: none." in prompt.system_prompt(sample, kamala, {"text": "hi"})[0]
    store.put_approval(Approval(sample, "a" * 12, "refill", "bp", "ordered", "rohan", clock.iso(),
                                handled_at=clock.iso()))
    system, _ = prompt.system_prompt(sample, kamala, {"text": "hi"})
    assert "Refills open in the last day: bp ordered (family member rohan)." in system


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


def test_hindi_prompt_sets_feminine_first_person(sample):
    hindi, _ = prompt.system_prompt(sample, store.get_person(sample, "kamala"), {"text": "hi"})
    english, _ = prompt.system_prompt(sample, store.get_person(sample, "rohan"), {"text": "hi"})
    assert "speak as a woman" in hindi and "सकती हूँ" in hindi
    assert "speak as a woman" not in english
