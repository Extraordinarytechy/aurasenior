"""Validate a household file and write it to the table, with its check-in and weekly schedules.

Usage: python scripts/seed_household.py households/<name>.toml [--simulated-baseline] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from aurasenior import seed  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--simulated-baseline", action="store_true",
                    help="write labelled simulated voice baseline items (demo backup only)")
    ap.add_argument("--dry-run", action="store_true", help="validate and print the plan, write nothing")
    args = ap.parse_args(argv)
    try:
        data = seed.load_file(args.file)
        seed.validate(data)
    except (seed.SeedError, OSError, ValueError) as e:
        print(f"invalid household file: {e}", file=sys.stderr)
        return 1
    h, people, meds = seed.to_records(data)
    if args.dry_run:
        print(f"household {h.household_id}: {len(people)} people, {len(meds)} medicines, consent pending")
        print(f"schedules: aurasenior-checkin-{h.household_id} at {h.checkin_time} {h.timezone}, "
              f"aurasenior-weekly-{h.household_id} Sunday 18:00")
        return 0
    seed.seed(data, simulated_baseline=args.simulated_baseline)
    print(f"seeded household {h.household_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
