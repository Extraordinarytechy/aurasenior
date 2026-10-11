"""Long-term memory interface. The prompt builder and the remember tool only see MemoryStore."""
from __future__ import annotations

import os
from typing import Protocol

from ..models import Person


class MemoryStore(Protocol):
    def recall(self, household_id: str, person_id: str, query: str | None = None) -> list[str]: ...
    def remember(self, household_id: str, person_id: str, note: str) -> None: ...
    def record_turn(self, household_id: str, person_id: str, user_text: str, reply_text: str) -> None: ...
    def record_checkin(self, household_id: str, person_id: str, local_date: str, line: str) -> None: ...


def build_store(person: Person) -> MemoryStore:
    """AgentCore Memory only for the elder, and only when the stack created it. Family memory stays in DynamoDB."""
    from .dynamo import DynamoMemoryStore

    memory_id = os.environ.get("AGENTCORE_MEMORY_ID", "")
    if memory_id and person.role == "elder":
        from .agentcore import AgentCoreMemoryStore

        return AgentCoreMemoryStore(memory_id, person.language)
    return DynamoMemoryStore(person.language)
