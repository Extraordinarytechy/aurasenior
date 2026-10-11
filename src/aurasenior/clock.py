"""Single time source so tests and the offline demo can pin and move time."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_frozen: datetime | None = None


def now() -> datetime:
    return _frozen if _frozen is not None else datetime.now(timezone.utc)


def local_now(tz: str) -> datetime:
    return now().astimezone(ZoneInfo(tz))


def local_date(tz: str) -> str:
    return local_now(tz).strftime("%Y-%m-%d")


def freeze(dt: datetime) -> None:
    global _frozen
    if dt.tzinfo is None:
        raise ValueError("freeze needs an aware datetime")
    _frozen = dt.astimezone(timezone.utc)


def advance(minutes: float = 0, **kw) -> datetime:
    global _frozen
    if _frozen is None:
        raise RuntimeError("clock is not frozen")
    _frozen = _frozen + timedelta(minutes=minutes, **kw)
    return _frozen


def unfreeze() -> None:
    global _frozen
    _frozen = None


def iso(dt: datetime | None = None) -> str:
    return (dt or now()).astimezone(timezone.utc).isoformat(timespec="seconds")


def parse(s: str) -> datetime:
    return datetime.fromisoformat(s)


def epoch(dt: datetime | None = None) -> int:
    return int((dt or now()).timestamp())
