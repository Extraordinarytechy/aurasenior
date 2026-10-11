"""DynamoDB memory: up to 50 short notes per person in one MEMORY#<pid> item. Also the AgentCore fallback."""
from __future__ import annotations

from .. import clock, log, store, wording

MAX_NOTES = 50


class DynamoMemoryStore:
    source = "dynamodb"

    def __init__(self, language: str):
        self.language = language

    def notes(self, household_id: str, person_id: str) -> list[dict]:
        item = store.get(store.hh(household_id), f"MEMORY#{person_id}") or {}
        return item.get("notes", [])

    def recall(self, household_id: str, person_id: str, query: str | None = None) -> list[str]:
        """Newest first. A note that fails the wording rule never reaches the prompt."""
        out = []
        for n in reversed(self.notes(household_id, person_id)):
            rule = wording.check(n["text"], self.language)
            if rule:
                log.get().warning("recalled memory dropped", extra={"rule": rule, "source": "dynamodb"})
                continue
            out.append(n["text"])
        return out

    def remember(self, household_id: str, person_id: str, note: str) -> None:
        notes = self.notes(household_id, person_id) + [{"text": note[:200], "at": clock.iso()}]
        store.put({"PK": store.hh(household_id), "SK": f"MEMORY#{person_id}", "notes": notes[-MAX_NOTES:]})

    def record_turn(self, household_id: str, person_id: str, user_text: str, reply_text: str) -> None:
        return None  # turns are already TURN# items

    def record_checkin(self, household_id: str, person_id: str, local_date: str, line: str) -> None:
        return None  # check-ins are already LOG#, MSG# and ESC# items
