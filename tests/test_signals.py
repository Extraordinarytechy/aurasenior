import json
import re
from pathlib import Path

from aurasenior import clock, signals, sim, store

FIX = Path(__file__).parent / "fixtures" / "transcribe"


def _note(hid, day, i, wpm=110.0, simulated=False, pain=0, included=True):
    store.put({"PK": store.hh(hid), "SK": f"SIGNAL#{day}#m{i:02d}", "date": day, "included": included,
               "simulated": simulated, "features": {"words_per_minute": wpm, "pause_count": 2.0, "pause_mean": 1.2,
                                                    "word_count": 30.0, "speaking_time": 16.0} if included else {},
               "mentions": {"pain": pain, "low_mood": 0}})


def test_extract_features_from_transcribe_json():
    data = json.loads((FIX / "hindi_reply.json").read_text(encoding="utf-8"))
    s = signals.extract(data, reply_delay=840.0)
    assert s["included"] and s["features"]["word_count"] == 11
    assert s["features"]["pause_count"] == 1 and s["features"]["reply_delay"] == 840.0
    assert s["mentions"]["pain"] == 1


def test_short_note_is_excluded_but_mentions_count():
    data = json.loads((FIX / "short_note.json").read_text(encoding="utf-8"))
    s = signals.extract(data, reply_delay=10.0)
    assert s["included"] is False and s["features"] == {} and s["mentions"]["pain"] == 1


def test_under_five_notes_gives_no_signal(sample):
    for i in range(4):
        _note(sample, f"2026-10-0{i + 5}", i, wpm=60.0)
    assert signals.changes(sample, "2026-10-12")[0] == []


def test_three_of_five_rule(sample):
    for i in range(8):
        _note(sample, f"2026-10-0{i + 1}", i, wpm=110.0 + (i % 2))
    for i, wpm in enumerate([70.0, 72.0, 110.0, 69.0, 111.0]):
        _note(sample, f"2026-10-{i + 8:02d}", 20 + i, wpm=wpm)
    assert "words_per_minute" in signals.changes(sample, "2026-10-12")[0]


def test_two_of_five_is_not_a_change(sample):
    for i in range(8):
        _note(sample, f"2026-10-0{i + 1}", i)
    for i, wpm in enumerate([70.0, 72.0, 110.0, 110.0, 111.0]):
        _note(sample, f"2026-10-{i + 8:02d}", 20 + i, wpm=wpm)
    assert "words_per_minute" not in signals.changes(sample, "2026-10-12")[0]


def test_mad_of_zero_uses_the_floor(sample):
    for i in range(13):
        _note(sample, f"2026-10-{i:02d}" if i else "2026-09-30", i, wpm=110.0)
    assert signals.changes(sample, "2026-10-12")[0] == []


def test_one_message_a_day_and_no_numbers(sample):
    for i in range(6):
        _note(sample, f"2026-10-{i + 6:02d}", i, pain=1 if i >= 3 else 0)
    r1 = signals.worth_a_call(sample, correlation_id="sig#1")
    r2 = signals.worth_a_call(sample, correlation_id="sig#2")
    assert r1.outcome == "sent" and r2 is None
    text = sim.read("rcs")[-1]["text"]
    assert text.startswith("Worth a call today: Mom") and not re.search(r"\d|score|risk", text, re.IGNORECASE)


def test_fewer_pauses_gives_the_neutral_phrase(sample):
    def note(day, i, pauses):
        store.put({"PK": store.hh(sample), "SK": f"SIGNAL#{day}#p{i:02d}", "date": day, "included": True,
                   "simulated": False, "features": {"pause_count": pauses}, "mentions": {"pain": 0, "low_mood": 0}})

    for i in range(8):
        note(f"2026-10-0{i + 1}", i, 4.0 + (i % 2))
    for i, pauses in enumerate([0.0, 0.0, 4.0, 0.0, 5.0]):
        note(f"2026-10-{i + 8:02d}", 20 + i, pauses)
    changed, _ = signals.changes(sample, "2026-10-12")
    assert changed == ["pause_count"]
    assert signals.phrase_for(changed, "en-IN", "Mom") == "Worth a call today: Mom has been pausing differently from usual this week."
    assert "अलग ढंग से रुक" in signals.phrase_for(changed, "hi-IN", "माँ")


def test_hindi_mentions_join_cleanly():
    out = signals.phrase_for(["pain", "low_mood"], "hi-IN", "माँ")
    assert out == "आज फ़ोन कर लें: माँ कई बार दर्द की बात कर चुकी हैं और कई बार उदास होने की बात कर चुकी हैं।"


def test_simulated_baseline_is_labelled(sample):
    for i in range(6):
        _note(sample, f"2026-10-{i + 6:02d}", i, pain=1 if i >= 3 else 0, simulated=i < 3)
    signals.worth_a_call(sample, correlation_id="sig#3")
    t = [x for x in store.traces(sample) if x["step"] == "signal"][0]
    assert t["simulated_baseline"] is True and t["simulated"] is True
    clock.advance(0)
