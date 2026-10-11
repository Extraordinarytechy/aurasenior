"""Household seed file validation and loading."""
from __future__ import annotations

import re
import tomllib
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import clock, config, schedules, store, wording
from .models import Household, Medicine, Person

ID = re.compile(r"^[a-z0-9]{1,12}$")
E164 = re.compile(r"^\+[1-9]\d{6,14}$")
CHANNELS = {"whatsapp", "rcs", "sms", "email", "none"}
ROLES = {"elder", "family", "neighbour", "doctor", "pharmacy"}
REQUIRED = ("role", "display_name", "country", "language", "preferred_channel")


class SeedError(ValueError):
    pass


def load_file(path: str | Path) -> dict:
    with Path(path).open("rb") as f:
        return tomllib.load(f)


def validate(data: dict) -> None:
    hid = data.get("household_id", "")
    if not ID.match(str(hid)):
        raise SeedError("household_id must match ^[a-z0-9]{1,12}$")
    try:
        ZoneInfo(data.get("timezone", ""))
    except (ZoneInfoNotFoundError, ValueError):
        raise SeedError("timezone is not a valid IANA name") from None
    if not re.fullmatch(r"\d{2}:\d{2}", str(data.get("checkin_time", ""))):
        raise SeedError("checkin_time must be HH:MM")
    people = data.get("people", [])
    langs = config.language_keys()
    sim_numbers = set(config.simulator_destinations())
    by_id = {}
    for i, p in enumerate(people):
        where = f"people[{i}]"
        if "consent" in p:
            raise SeedError(f"{where}.consent cannot be set in a seed file")
        for f in REQUIRED:
            if not p.get(f):
                raise SeedError(f"{where}.{f} is required")
        pid = p.get("person_id", "")
        if not ID.match(str(pid)):
            raise SeedError(f"{where}.person_id must match ^[a-z0-9]{{1,12}}$")
        if p["role"] not in ROLES:
            raise SeedError(f"{where}.role is not one of {sorted(ROLES)}")
        if p["language"] not in langs:
            raise SeedError(f"{where}.language is not a language row")
        addrs = p.get("addresses", {})
        for key in ("preferred_channel", "fallback_channel"):
            ch = p.get(key, "none")
            if ch not in CHANNELS:
                raise SeedError(f"{where}.{key} is not a known channel")
            if ch != "none" and not addrs.get(ch):
                raise SeedError(f"{where}.addresses.{ch} is missing for {key}")
        for ch in ("whatsapp", "rcs", "sms"):
            if ch in addrs and not E164.match(addrs[ch]):
                raise SeedError(f"{where}.addresses.{ch} is not E.164")
        if "sms" in addrs and not addrs["sms"].startswith("+1"):
            raise SeedError(f"{where}.addresses.sms is only allowed for US numbers")
        is_sim = any(addrs.get(ch) in sim_numbers for ch in ("sms", "rcs"))
        if is_sim != bool(p.get("simulated", False)):
            raise SeedError(f"{where}.simulated must be true exactly when an address is a simulator destination")
        if p["role"] in ("family", "neighbour"):
            label = p.get("relation_label", "")
            if not (1 <= len(label) <= 30):
                raise SeedError(f"{where}.relation_label is required (1 to 30 characters)")
        by_id[pid] = p
    elders = [p for p in people if p["role"] == "elder"]
    if len(elders) != 1:
        raise SeedError("people must have exactly one elder")
    admin = data.get("admin_person_id")
    if admin not in by_id or by_id[admin]["role"] != "family":
        raise SeedError("admin_person_id must be a family member")
    for pid in data.get("escalation_order", []):
        if pid not in by_id:
            raise SeedError(f"escalation_order has unknown person {pid}")
    viewer_langs = {p["language"] for p in people}
    for p in people:
        for f in ("display_name", "relation_label"):
            if p.get(f):
                for lang in viewer_langs:
                    if wording.check(p[f], lang):
                        raise SeedError(f"people.{p['person_id']}.{f} fails the wording rule")
    for i, m in enumerate(data.get("medicines", [])):
        where = f"medicines[{i}]"
        if not ID.match(str(m.get("medicine_id", ""))):
            raise SeedError(f"{where}.medicine_id must match ^[a-z0-9]{{1,12}}$")
        label = m.get("display_label", "")
        if not (1 <= len(label) <= 40):
            raise SeedError(f"{where}.display_label is required (1 to 40 characters)")
        for lang in viewer_langs:
            if wording.check(label, lang):
                raise SeedError(f"{where}.display_label fails the wording rule")
        if m.get("pharmacy_person_id") not in by_id:
            raise SeedError(f"{where}.pharmacy_person_id is not a person")


def to_records(data: dict) -> tuple[Household, list[Person], list[Medicine]]:
    hid = data["household_id"]
    elder = next(p for p in data["people"] if p["role"] == "elder")
    h = Household(hid, data.get("name", hid), data["timezone"], data["checkin_time"], elder["person_id"],
                  data["admin_person_id"], list(data.get("escalation_order", [])),
                  bool(data.get("share_transcripts", False)))
    people = [Person(hid, p["person_id"], p["role"], p["display_name"], p["country"], p["language"],
                     p["preferred_channel"], p.get("fallback_channel", "none"), p.get("relation_label"),
                     dict(p.get("addresses", {})), {}, None, bool(p.get("simulated", False)))
              for p in data["people"]]
    meds = [Medicine(hid, m["medicine_id"], m.get("name", m["display_label"]), m["display_label"],
                     m.get("time_of_day", "morning"), "ok", m["pharmacy_person_id"]) for m in data.get("medicines", [])]
    return h, people, meds


def seed(data: dict, *, simulated_baseline: bool = False, create_schedules: bool = True) -> Household:
    validate(data)
    h, people, meds = to_records(data)
    store.put_household(h)
    for p in people:
        store.put_person(p)
        for ch, addr in p.addresses.items():
            store.put_addr(ch, addr, h.household_id, p.person_id)
    for m in meds:
        store.put_medicine(m)
    if create_schedules:
        schedules.create_checkin(h.household_id, h.checkin_time, h.timezone)
        schedules.create_weekly(h.household_id, h.timezone)
    if simulated_baseline:
        write_simulated_baseline(h)
    return h


def write_simulated_baseline(h: Household, notes: int = 10) -> None:
    """Labelled baseline SIGNAL# items for a demo without real history. Every one is simulated=true."""
    for i in range(notes):
        day = clock.local_now(h.timezone) - timedelta(days=notes - i)
        d = day.strftime("%Y-%m-%d")
        store.put({"PK": store.hh(h.household_id), "SK": f"SIGNAL#{d}#sim{i:02d}", "date": d,
                   "person_id": h.elder_person_id, "included": True, "simulated": True,
                   "features": {"words_per_minute": 110.0 + (i % 3), "pause_count": 2.0 + (i % 2),
                                "pause_mean": 1.3, "reply_delay": 600.0 + 10 * (i % 4), "word_count": 30.0 + i % 5,
                                "speaking_time": 16.0 + (i % 3)},
                   "mentions": {"pain": 0, "low_mood": 0}, "ttl": store.ttl("SIGNAL")})
