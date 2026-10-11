"""Tier 1 voice signals: change from her own usual, from Transcribe word timings.

The only output is a fixed "worth a call" phrase to family. No number, score, condition or cause is ever produced.
"""
from __future__ import annotations

import statistics
from datetime import date, timedelta

from . import clock, config, keywords, languages, log, phrases, store

FEATURES = ("words_per_minute", "pause_count", "pause_mean", "reply_delay", "word_count", "speaking_time")


def _rules() -> dict:
    return config.get("rules", file="signals")


def extract(transcribe_json: dict, reply_delay: float | None) -> dict:
    """Features from Transcribe results.items (pronunciation items carry start_time and end_time)."""
    items = [i for i in transcribe_json.get("results", {}).get("items", []) if i.get("type") == "pronunciation"]
    text = " ".join(t.get("transcript", "") for t in transcribe_json.get("results", {}).get("transcripts", []))
    words = [(float(i["start_time"]), float(i["end_time"])) for i in items if "start_time" in i]
    mentions = keywords.mentions(text)
    r = _rules()
    if not words:
        return {"included": False, "features": {}, "mentions": mentions, "text": text}
    span = words[-1][1] - words[0][0]
    gaps = [b[0] - a[1] for a, b in zip(words, words[1:])]
    pauses = [g for g in gaps if g > 1.0]
    included = len(words) >= r["min_words"] and span >= r["min_seconds"]
    features = {"words_per_minute": round(len(words) / span * 60, 2) if span > 0 else 0.0,
                "pause_count": float(len(pauses)), "pause_mean": round(sum(pauses) / len(pauses), 3) if pauses else 0.0,
                "word_count": float(len(words)), "speaking_time": round(span, 3)}
    if reply_delay is not None:
        features["reply_delay"] = round(reply_delay, 1)
    return {"included": included, "features": features if included else {}, "mentions": mentions, "text": text}


def store_signal(hid: str, pid: str, msg_id: str, local_date: str, sig: dict, *, simulated: bool) -> None:
    """simulated is required so a note from the Transcribe simulator is never stored as real."""
    store.put({"PK": store.hh(hid), "SK": f"SIGNAL#{local_date}#{msg_id}", "date": local_date, "person_id": pid,
               "included": sig["included"], "features": sig["features"], "mentions": sig["mentions"],
               "simulated": simulated, "ttl": store.ttl("SIGNAL")})


def _floor(feature: str, median: float) -> float:
    f = config.get("floors", feature, file="signals")
    return max(f["fraction"] * abs(median), f["minimum"])


def changes(hid: str, today: str) -> tuple[list[str], bool]:
    """(changed features and mention kinds, whether any simulated item was used)."""
    r = _rules()
    start = (date.fromisoformat(today) - timedelta(days=r["baseline_days"])).isoformat()
    items = sorted((s for s in store.query_prefix(hid, "SIGNAL#") if start <= s["date"] <= today), key=lambda s: s["SK"])
    simulated = any(s.get("simulated") for s in items)
    included = [s for s in items if s.get("included")]
    changed: list[str] = []
    if len(included) >= r["min_notes"]:
        recent = included[-r["window"]:]
        baseline = included[:-r["window"]] or included
        for f in FEATURES:
            base = [s["features"][f] for s in baseline if f in s.get("features", {})]
            if len(base) < 3:
                continue
            med = statistics.median(base)
            mad = statistics.median([abs(x - med) for x in base])
            scale = max(1.4826 * mad, _floor(f, med))
            over = sum(1 for s in recent if f in s["features"] and abs(s["features"][f] - med) / scale > r["threshold"])
            if over >= r["needed"]:
                changed.append(f)
    week_start = (date.fromisoformat(today) - timedelta(days=6)).isoformat()
    for kind in ("pain", "low_mood"):
        week = sum(int(s.get("mentions", {}).get(kind, 0)) for s in items if s["date"] >= week_start)
        before = sum(int(s.get("mentions", {}).get(kind, 0)) for s in items if s["date"] < week_start)
        weeks_before = max((r["baseline_days"] - 7) / 7, 1)
        if week >= 3 and before / weeks_before < 1:
            changed.append(kind)
    return changed, simulated


def phrase_for(changed: list[str], lang_key: str, relation_label: str) -> str:
    t = config.get(languages.phrase_lang(lang_key), file="signals")
    parts = [t[c] for c in changed]
    return phrases.fill(t["opening"], relation_label=relation_label) + " " + t["joiner"].join(parts) + t["closing"]


def worth_a_call(hid: str, *, correlation_id: str):
    """At most one fixed-phrase suggestion per household per day, to the first family member."""
    from . import router

    h = store.get_household(hid)
    today = clock.local_date(h.timezone)
    changed, simulated = changes(hid, today)
    if not changed:
        return None
    family = next((store.get_person(hid, p) for p in h.escalation_order
                   if (store.get_person(hid, p) or None) and store.get_person(hid, p).role == "family"), None)
    if not family or not store.set_usage_flag(hid, today, "worth_a_call_sent"):
        return None
    text = phrase_for(changed, family.language, family.relation_label or "")
    log.get().info("worth a call suggested", extra={"household_id": hid, "simulated_baseline": simulated})
    store.trace(hid, "signal", outcome="worth_a_call", features=changed, simulated_baseline=simulated,
                simulated=simulated)
    # phrase labels the trace only; the text is the fixed signals.toml sentence built above.
    return router.send(family, router.Content(phrase="worth_a_call", text=text, wa_template="aurasenior_family_update",
                                              wa_params=[family.relation_label or "", text],
                                              email_template="aurasenior-update", email_data={"update_text": text}),
                       correlation_id=correlation_id)
