"""Weekly facts, computed from stored items with no model call."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from . import clock, config, store


@dataclass
class WeekFacts:
    days: int
    week_start: str
    week_end: str
    medicines: list[dict] = field(default_factory=list)
    refills: dict = field(default_factory=dict)
    escalations: list[dict] = field(default_factory=list)
    missed_checkins: int = 0
    mentions: dict = field(default_factory=lambda: {"pain": 0, "low_mood": 0})
    quotes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _local_day(iso: str, tz: str) -> str:
    return clock.parse(iso).astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d")


def _minutes(a: str | None, b: str | None) -> int | None:
    if not a or not b:
        return None
    return int((clock.parse(b) - clock.parse(a)).total_seconds() // 60)


def build_week(household_id: str, end_date: str, days: int = 7) -> WeekFacts:
    h = store.get_household(household_id)
    tz = h.timezone
    end = date.fromisoformat(end_date)
    start = (end - timedelta(days=days - 1)).isoformat()
    in_week = lambda d: start <= d <= end_date  # noqa: E731
    facts = WeekFacts(days=days, week_start=start, week_end=end_date)
    logs = store.logs_between(household_id, start, end_date)
    # Days the morning check-in went out to the elder: only those can be "no answer".
    asked = {_local_day(x["at"], tz) for x in store.query_prefix(household_id, "MSG#")
             if x.get("person_id") == h.elder_person_id and (x.get("ref") or {}).get("kind") == "listen"
             and in_week(_local_day(x["at"], tz))}
    for m in store.medicines(household_id):
        taken = {x["date"] for x in logs if x["medicine_id"] == m.medicine_id and x["taken"]}
        not_taken = {x["date"] for x in logs if x["medicine_id"] == m.medicine_id and not x["taken"]} - taken
        no_answer = asked - taken - not_taken
        facts.medicines.append({"display_label": m.display_label, "days_taken": len(taken),
                                "days_not_taken": len(not_taken), "days_no_answer": len(no_answer),
                                "days_nothing_recorded": days - len(taken) - len(not_taken) - len(no_answer)})
    approvals = [a for a in store.approvals(household_id) if in_week(_local_day(a.created_at, tz))]
    ordered = [a for a in approvals if a.status == "ordered"]
    facts.refills = {"requested": len(approvals), "ordered": len(ordered),
                     "minutes_to_order": [_minutes(a.ran_out_at or a.created_at, a.ordered_at) for a in ordered]}
    for e in store.escalations(household_id):
        if not in_week(_local_day(e.created_at, tz)):
            continue
        if e.reason == "missed_checkin":
            facts.missed_checkins += 1
        ack = _minutes(e.created_at, e.acknowledged_at)
        facts.escalations.append({"reason": e.reason, "status": e.status,
                                  "minutes_to_ack": ack if ack is not None else "unacknowledged"})
    for s in store.query_prefix(household_id, "SIGNAL#"):
        if in_week(s["date"]) and not s.get("simulated"):
            for k in facts.mentions:
                facts.mentions[k] += int(s.get("mentions", {}).get(k, 0))
    if h.share_transcripts:
        for t in store.query_prefix(household_id, f"TURN#{h.elder_person_id}#"):
            if t["role"] == "user" and in_week(_local_day(t["SK"].split("#")[2], tz)):
                facts.quotes.append(t["text"])
    return facts


def _days(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


def medicine_line(m: dict) -> str:
    """Taken, not taken, no answer to a check-in, and nothing recorded (no check-in went out) apart, so a day
    nobody asked about never reads as a missed dose or a missed answer."""
    return (f"{m['display_label']}: taken {_days(m['days_taken'])}, not taken {_days(m['days_not_taken'])}, "
            f"no answer {_days(m['days_no_answer'])}, nothing recorded {_days(m['days_nothing_recorded'])}")


def to_template_data(facts: WeekFacts, elder_name: str) -> dict:
    meds = "; ".join(medicine_line(m) for m in facts.medicines)
    escs = "; ".join(f"{e['reason'].replace('_', ' ')}: " + (f"acknowledged in {e['minutes_to_ack']} min"
                     if e["minutes_to_ack"] != "unacknowledged" else "not acknowledged") for e in facts.escalations)
    return {"brand": config.brand(), "elder_name": elder_name, "week_start": facts.week_start,
            "medicines": meds or "no medicine answers", "refills": f"{facts.refills.get('ordered', 0)} ordered",
            "missed_checkins": str(facts.missed_checkins), "escalations": escs or "none",
            "pain_mentions": str(facts.mentions["pain"]), "low_mood_mentions": str(facts.mentions["low_mood"]),
            "quotes": " / ".join(facts.quotes)}
