"""Amazon Bedrock AgentCore Memory for the elder, with DynamoDB notes as the automatic fallback.

No AgentCore error leaves this class: recoverable errors log WARN and fall back, access denied, validation and
not found disable AgentCore for the rest of the invocation and log ERROR once.
"""
from __future__ import annotations

import hashlib
import re

from botocore.exceptions import BotoCoreError, ClientError

from .. import aws, clock, log, wording
from .dynamo import DynamoMemoryStore

FACTS = "/aurasenior/facts/{actor}/"
CHECKINS = "/aurasenior/checkins/{actor}/"
DEFAULT_QUERY = "routine, people and recent check-ins"
MAX_EVENT_TEXT = 2000
MAX_RECORD = 300
MAX_BLOCK = 1500
FATAL = {"AccessDeniedException", "ValidationException", "ResourceNotFoundException"}
_TAG = re.compile(r"</?[a-zA-Z_][^>]*>")

# One flag per invocation: the handlers call reset_invocation() at the start of each event.
_disabled = {"value": False, "logged": False}


def reset_invocation() -> None:
    _disabled["value"] = False
    _disabled["logged"] = False


def actor_id(hid: str, pid: str) -> str:
    return f"{hid}-{pid}"


def session_id(hid: str, pid: str, local_date: str) -> str:
    return f"{hid}-{pid}-{local_date.replace('-', '')}"


def checkin_token(hid: str, pid: str, local_date: str) -> str:
    return hashlib.sha256(f"checkin#{hid}#{pid}#{local_date}".encode()).hexdigest()[:32]


def strip_tags(text: str) -> str:
    return " ".join(_TAG.sub(" ", text).split())


class AgentCoreMemoryStore:
    source = "agentcore"

    def __init__(self, memory_id: str, language: str, timezone: str | None = None):
        self.memory_id = memory_id
        self.language = language
        self.timezone = timezone
        self.fallback = DynamoMemoryStore(language)

    @property
    def client(self):
        return aws.client("bedrock-agentcore")

    def _tz(self, hid: str) -> str:
        if self.timezone:
            return self.timezone
        from .. import store

        h = store.get_household(hid)
        return h.timezone if h else "UTC"

    def _failed(self, op: str, e: Exception) -> None:
        code = e.response.get("Error", {}).get("Code", "") if isinstance(e, ClientError) else type(e).__name__
        if code in FATAL:
            _disabled["value"] = True
            if not _disabled["logged"]:
                _disabled["logged"] = True
                log.get().error("agentcore memory disabled for this invocation", extra={"op": op, "code": code})
        else:
            log.get().warning("agentcore memory call failed, using dynamodb", extra={"op": op, "code": code})

    def _event(self, hid: str, pid: str, payload: list[dict], local_date: str | None = None,
               token: str | None = None) -> None:
        if _disabled["value"]:
            return
        local_date = local_date or clock.local_date(self._tz(hid))
        kw = {"memoryId": self.memory_id, "actorId": actor_id(hid, pid), "sessionId": session_id(hid, pid, local_date),
              "eventTimestamp": clock.now(), "payload": payload}
        if token:
            kw["clientToken"] = token
        try:
            self.client.create_event(**kw)
        except (ClientError, BotoCoreError) as e:
            self._failed("CreateEvent", e)

    @staticmethod
    def _msg(text: str, role: str) -> dict:
        return {"conversational": {"content": {"text": text[:MAX_EVENT_TEXT]}, "role": role}}

    def remember(self, household_id: str, person_id: str, note: str) -> None:
        self.fallback.remember(household_id, person_id, note)  # DynamoDB first, so the note survives any failure
        self._event(household_id, person_id, [self._msg(f"Note: {note}", "ASSISTANT")])

    def record_turn(self, household_id: str, person_id: str, user_text: str, reply_text: str) -> None:
        # CreateEvent rejects empty conversational text (min length 1), so empty sides are left out.
        payload = [self._msg(t, role) for t, role in ((user_text, "USER"), (reply_text, "ASSISTANT")) if t.strip()]
        if payload:
            self._event(household_id, person_id, payload)

    def record_checkin(self, household_id: str, person_id: str, local_date: str, line: str) -> None:
        self._event(household_id, person_id, [self._msg(line, "ASSISTANT")], local_date,
                    checkin_token(household_id, person_id, local_date))

    def _retrieve(self, namespace: str, query: str, top_k: int) -> list[tuple[float, str]]:
        if _disabled["value"]:
            return []
        try:
            resp = self.client.retrieve_memory_records(memoryId=self.memory_id, namespace=namespace,
                                                       searchCriteria={"searchQuery": query, "topK": top_k})
        except (ClientError, BotoCoreError) as e:
            self._failed("RetrieveMemoryRecords", e)
            return []
        out = []
        for r in resp.get("memoryRecordSummaries", []):
            text = strip_tags((r.get("content") or {}).get("text", ""))
            if text:
                out.append((float(r.get("score", 0.0)), text))
        out.sort(key=lambda x: -x[0])
        return out

    def recall(self, household_id: str, person_id: str, query: str | None = None) -> list[str]:
        actor = actor_id(household_id, person_id)
        q = (query or DEFAULT_QUERY)[:500]
        notes = self.fallback.recall(household_id, person_id)
        facts = [t for _, t in self._retrieve(FACTS.format(actor=actor), q, 5)]
        checkins = [t for _, t in self._retrieve(CHECKINS.format(actor=actor), q, 3)]
        block, seen, used = [], set(), 0
        for source, items in (("dynamodb", notes), ("agentcore", facts), ("agentcore", checkins)):
            for text in items:
                if text in seen:
                    continue
                if source == "agentcore":
                    if len(text) > MAX_RECORD:
                        continue
                    rule = wording.check(text, self.language)
                    if rule:
                        log.get().warning("recalled memory dropped", extra={"rule": rule, "source": "agentcore"})
                        continue
                if used + len(text) > MAX_BLOCK:
                    return block
                seen.add(text)
                block.append(text)
                used += len(text)
        return block
