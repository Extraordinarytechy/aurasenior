import pytest

from aurasenior import keywords as kw


def test_normalise_strips_punctuation_and_case():
    assert kw.normalise("  Stop. ") == "stop"
    assert kw.normalise("can't get up!") == "can t get up"


@pytest.mark.parametrize("text", ["Stop.", "STOP", "बंद", "band"])
def test_stop_words_opt_out(text):
    assert kw.is_stop(text, "hi-IN")


def test_stop_inside_sentence_is_not_stop():
    assert not kw.is_stop("please stop the tablets", "en-IN")


@pytest.mark.parametrize("text", ["हाँ", "haan", "ha", "Yes!"])
def test_yes_words(text):
    assert kw.is_yes(text, "hi-IN")


def test_start():
    assert kw.is_start("START", "en-US")
    assert kw.is_start("start", "hi-IN")


@pytest.mark.parametrize("text", ["helpful", "Rohan helps me", "I took my tablets"])
def test_no_escalation_for_harmless_text(text):
    assert not kw.fall_or_help(text)


@pytest.mark.parametrize("text", ["मैं गिर गई", "I fell", "I can't get up", "help!", "kursi ke paas fisal gayi"])
def test_fall_and_help_words_escalate(text):
    assert kw.fall_or_help(text)


def test_mentions_count_pain_and_low_mood():
    m = kw.mentions("Knee hurts a bit today, घुटने में दर्द. Feeling lonely")
    assert m["pain"] == 2
    assert m["low_mood"] == 1
