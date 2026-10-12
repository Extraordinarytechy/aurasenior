from pathlib import Path

from aurasenior import channels, store
from aurasenior.agent import tools
from aurasenior.channels.base import SendResult

SRC = Path(__file__).resolve().parent.parent / "src" / "aurasenior" / "agent" / "tools.py"


def test_no_scheduling_tool_and_no_schedules_import():
    names = [s["name"] for s in tools.SPECS]
    assert len(names) == 9
    assert not any("schedule" in n or "followup" in n for n in names)
    src = SRC.read_text(encoding="utf-8")
    assert "import schedules" not in src and "schedules," not in src and ", schedules" not in src


def test_invalid_input_gives_error_result(sample):
    ctx = tools.ToolContext(sample, store.get_person(sample, "kamala"), "ev1")
    assert tools.run(ctx, "log_medicine", {"medicine_id": "bp"})[0] == "error"
    assert tools.run(ctx, "escalate", {"reason": "bored"})[0] == "error"
    assert tools.run(ctx, "message_person", {"person_id": "rohan", "text": "x" * 601})[0] == "error"
    assert tools.run(ctx, "nope", {})[0] == "error"
    assert tools.run(ctx, "log_medicine", {"medicine_id": "zz", "taken": True, "out_of_stock": False})[0] == "error"


def test_log_medicine_and_get_household(sample):
    ctx = tools.ToolContext(sample, store.get_person(sample, "kamala"), "ev2")
    assert tools.run(ctx, "log_medicine", {"medicine_id": "bp", "taken": False, "out_of_stock": True})[0] == "success"
    status, hh = tools.run(ctx, "get_household", {})
    assert status == "success" and {"medicine_id": "bp", "taken": False} in hh["today_log"]
    assert next(m for m in hh["medicines"] if m["medicine_id"] == "bp")["stock"] == "out"


def test_retried_message_after_a_failed_send_is_not_reported_ok(sample, monkeypatch):
    rcs = channels.get("rcs")
    monkeypatch.setattr(rcs, "send", lambda msg: SendResult.failed("ValidationException", False, simulated=True))
    outcomes = []
    for _ in range(2):
        ctx = tools.ToolContext(sample, store.get_person(sample, "kamala"), "ev3")
        _, result = tools.run(ctx, "message_person", {"person_id": "simfam", "text": "Please call Mom."})
        outcomes.append(result["status"])
        assert "simfam" not in ctx.messaged
    assert outcomes == ["failed", "skipped"]


def test_tool_config_shape():
    cfg = tools.tool_config()
    assert all("toolSpec" in t and "json" in t["toolSpec"]["inputSchema"] for t in cfg["tools"])
