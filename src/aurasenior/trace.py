"""Agent trace view: one line per step from TRACE# items, with simulated parts labelled.

python -m aurasenior.trace <household_id> [--since 2h] [--limit N]
"""
from __future__ import annotations

import argparse
import re
from datetime import timedelta

from . import clock, store

FIELDS = ("tool", "channel", "person_id", "to", "phrase", "template", "kind", "reason", "outcome", "stop_reason")


def labels(item: dict) -> list[str]:
    out = []
    if item.get("model") == "scripted":
        out.append("[SCRIPTED MODEL]")
    if item.get("simulated_baseline"):
        out.append("[SIMULATED BASELINE]")
    if item.get("simulated") and item.get("model") != "scripted":
        out.append("[SIMULATED]")
    return out


def format_line(item: dict) -> str:
    when = item.get("at", "")[5:16].replace("T", " ") + "Z"  # UTC, month-day hour:minute
    parts = [when, f"{item.get('step', ''):<14}"]
    for f in FIELDS:
        v = item.get(f)
        if v not in (None, "", [], {}):
            parts.append(f"{f}={v}")
    if item.get("text"):
        parts.append(f"text=\"{item['text'][:80]}\"")
    if item.get("inputs"):
        parts.append(f"inputs={item['inputs']}")
    return " ".join(parts + labels(item))


def format_trace(items: list[dict]) -> str:
    return "\n".join(format_line(i) for i in items)


def _since(s: str) -> str:
    m = re.fullmatch(r"(\d+)([mhd])", s)
    if not m:
        raise SystemExit("--since must look like 30m, 2h or 1d")
    n, unit = int(m.group(1)), m.group(2)
    delta = {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}[unit]
    return clock.iso(clock.now() - delta)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m aurasenior.trace")
    ap.add_argument("household_id")
    ap.add_argument("--since", default="2h")
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args(argv)
    print(format_trace(store.traces(args.household_id, since=_since(args.since), limit=args.limit)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
