"""Live checks against real AWS (Bedrock Converse tool use, AgentCore Memory round trip).

Skipped unless AURASENIOR_LIVE=1. Uses AWS_PROFILE (default the-unsent) in us-east-1. Writes redacted results
to docs/evidence/.
"""
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from aurasenior import aws, config
from aurasenior.agent import tools
from aurasenior.memory import agentcore
from aurasenior.memory.agentcore import AgentCoreMemoryStore

from . import redact

pytestmark = pytest.mark.live
EVIDENCE = Path(__file__).resolve().parents[2] / "docs" / "evidence"
TODAY = date.today().isoformat()
HINDI = "शुगर की गोली ले ली। BP वाली खत्म हो गई। आज घुटने में थोड़ा दर्द है।"


class _NoTable:
    def recall(self, *a, **k):
        return []

    def remember(self, *a, **k):
        return None


def _save(name: str, data: dict) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / f"{name}-{TODAY}.json").write_text(
        json.dumps(redact.obj(data), indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def test_converse_tool_use_round_trip():
    client = aws.client("bedrock-runtime")
    system = ("You are a companion for an older person. Medicines: sugar (sugar tablet), bp (BP tablets). "
              "Use log_medicine for each medicine mentioned, then reply briefly in Hindi. Never diagnose.")
    messages = [{"role": "user", "content": [{"text": HINDI}]}]
    record = {"model_id": config.model_id(), "guardrail": "none (the guardrail is a stack resource, not deployed)",
              "calls": []}
    used = []
    stop = None
    for _ in range(4):
        resp = client.converse(modelId=config.model_id(), system=[{"text": system}], messages=messages,
                               inferenceConfig={"maxTokens": 800}, toolConfig=tools.tool_config())
        stop = resp["stopReason"]
        msg = resp["output"]["message"]
        record["calls"].append({"stopReason": stop, "content": msg["content"], "usage": resp.get("usage")})
        messages.append(msg)
        if stop != "tool_use":
            break
        results = []
        for b in msg["content"]:
            if "toolUse" in b:
                used.append(b["toolUse"]["name"])
                results.append({"toolResult": {"toolUseId": b["toolUse"]["toolUseId"],
                                               "content": [{"json": {"status": "ok"}}], "status": "success"}})
        messages.append({"role": "user", "content": results})
    record["tools_used"] = used
    record["final_stop_reason"] = stop
    _save("bedrock-converse-live", record)
    assert "log_medicine" in used
    assert stop == "end_turn"


def test_agentcore_memory_round_trip():
    control = aws.client("bedrock-agentcore-control")
    name = "aurasenior_livetest_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    record = {"memory_name": name, "steps": []}
    memory_id = None
    try:
        created = control.create_memory(
            name=name, eventExpiryDuration=3, description="Temporary memory for a live round trip",
            memoryStrategies=[
                {"semanticMemoryStrategy": {"name": "facts", "namespaces": ["/aurasenior/facts/{actorId}/"]}},
                {"summaryMemoryStrategy": {"name": "checkins",
                                           "namespaces": ["/aurasenior/checkins/{actorId}/{sessionId}/"]}}],
            tags={"project": "aurasenior"})
        memory_id = created["memory"]["id"]
        record["steps"].append({"create_memory": created["memory"]["status"]})
        status, t0 = None, time.time()
        while time.time() - t0 < 600:
            status = control.get_memory(memoryId=memory_id)["memory"]["status"]
            if status in ("ACTIVE", "FAILED"):
                break
            time.sleep(15)
        record["steps"].append({"status_after_wait": status, "seconds": int(time.time() - t0)})
        assert status == "ACTIVE"

        agentcore.reset_invocation()
        store = AgentCoreMemoryStore(memory_id, "hi-IN", timezone="Asia/Kolkata")
        store.fallback = _NoTable()  # no stack is deployed, so the DynamoDB notes are stubbed for this check
        hid, pid = "livetest01", "elder01"
        turns = [("मैं रोज़ सुबह छह बजे उठती हूँ और चाय के साथ गोली लेती हूँ।", "बहुत अच्छा।"),
                 ("मेरी पोती प्रिया हर रविवार को फ़ोन करती है।", "यह सुनकर अच्छा लगा।"),
                 ("आज शुगर की गोली ले ली, BP वाली खत्म हो गई।", "मैंने रोहन से पूछ लिया है।")]
        for user, reply in turns:
            store.record_turn(hid, pid, user, reply)
        local = datetime.now(timezone.utc).date().isoformat()
        store.record_checkin(hid, pid, local, f"Check-in {local}: replied 09:14")
        store.record_checkin(hid, pid, local, f"Check-in {local}: replied 09:14")  # same clientToken: no error
        record["steps"].append({"events_written": len(turns) + 2, "agentcore_disabled": agentcore._disabled["value"]})
        assert agentcore._disabled["value"] is False

        found, t0 = [], time.time()
        while time.time() - t0 < 300:
            found = store.recall(hid, pid, "routine, people and recent check-ins")
            if found:
                break
            time.sleep(30)
        record["steps"].append({"recall_items": len(found), "recall_seconds": int(time.time() - t0),
                                "recalled": found})
        assert agentcore._disabled["value"] is False
    finally:
        if memory_id:
            try:
                control.delete_memory(memoryId=memory_id)
                record["steps"].append({"delete_memory": "requested"})
            except Exception as e:  # noqa: BLE001
                record["steps"].append({"delete_memory": f"failed {type(e).__name__}",
                                        "cleanup": f"aws bedrock-agentcore-control delete-memory --memory-id {memory_id}"})
        _save("agentcore-memory-live", record)
