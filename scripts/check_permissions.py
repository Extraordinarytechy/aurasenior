"""Simulate the deploy and live-test actions for the current caller and print allowed and denied.

Usage: AWS_PROFILE=<profile> python scripts/check_permissions.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import boto3  # noqa: E402

from aurasenior import deploy_checks  # noqa: E402


def main() -> int:
    s = boto3.Session(region_name="us-east-1")
    result = deploy_checks.simulate(s.client("iam"), s.client("sts"))
    print(json.dumps(result, indent=1))
    return 0 if not result["denied"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
