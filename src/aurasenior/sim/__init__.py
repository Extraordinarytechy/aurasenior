"""Local simulators for AWS services. Everything they produce is labelled simulated."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .. import clock


def sim_dir() -> Path:
    d = Path(os.environ.get("AURASENIOR_SIM_DIR", ".sim"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def append(name: str, record: dict) -> None:
    with (sim_dir() / f"{name}.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": clock.iso(), "simulated": True, **record}, ensure_ascii=False, default=str) + "\n")


def read(name: str) -> list[dict]:
    p = sim_dir() / f"{name}.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
