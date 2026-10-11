"""In-memory EventBridge Scheduler with the same error codes as the real service (simulated)."""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from botocore.exceptions import ClientError

from . import append

simulated = True


def _err(code: str, op: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, op)


class SchedulerSim:
    def __init__(self):
        self.schedules: dict[tuple[str, str], dict] = {}

    def create_schedule(self, **kw) -> dict:
        key = (kw.get("GroupName", "default"), kw["Name"])
        if key in self.schedules:
            raise _err("ConflictException", "CreateSchedule")
        self.schedules[key] = kw
        append("schedules", {"op": "create", "name": kw["Name"], "expression": kw["ScheduleExpression"]})
        return {"ScheduleArn": f"arn:sim:scheduler:schedule/{key[0]}/{key[1]}"}

    def delete_schedule(self, **kw) -> dict:
        key = (kw.get("GroupName", "default"), kw["Name"])
        if key not in self.schedules:
            raise _err("ResourceNotFoundException", "DeleteSchedule")
        del self.schedules[key]
        append("schedules", {"op": "delete", "name": kw["Name"]})
        return {}

    def names(self) -> list[str]:
        return sorted(n for _, n in self.schedules)

    def due(self, now: datetime) -> list[dict]:
        """One-time schedules whose at() time has passed, oldest first, with their decoded payload."""
        out = []
        for (_, name), s in self.schedules.items():
            expr = s["ScheduleExpression"]
            if not expr.startswith("at("):
                continue
            when = datetime.fromisoformat(expr[3:-1]).replace(tzinfo=ZoneInfo(s.get("ScheduleExpressionTimezone", "UTC")))
            if when <= now:
                out.append((when, name, json.loads(s["Target"]["Input"])))
        out.sort()
        return [{"name": n, "payload": p, "when": w} for w, n, p in out]

    def pop(self, name: str) -> None:
        """ActionAfterCompletion DELETE: a fired one-time schedule removes itself."""
        for key in list(self.schedules):
            if key[1] == name:
                del self.schedules[key]
