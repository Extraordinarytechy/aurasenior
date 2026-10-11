import json
import logging
import re
from pathlib import Path

from aurasenior import log


def _matches_error_filter(line: str) -> bool:
    """Same rule as the CloudWatch filter { $.level = "ERROR" }: the line is one JSON object with level ERROR."""
    try:
        obj = json.loads(line)
    except ValueError:
        return False
    return isinstance(obj, dict) and obj.get("level") == "ERROR"


def test_error_line_is_one_json_object(capsys):
    log.get().error("selftest_error", extra={"household_id": "hh1"})
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["level"] == "ERROR"
    assert obj["msg"] == "selftest_error"
    assert obj["household_id"] == "hh1"
    assert lines[0].startswith("{")


def test_selftest_line_after_a_household_run_carries_no_household(capsys):
    from aurasenior.handlers import scheduled

    log.set_context(household_id="hh1", correlation_id="checkin#hh1#2026-10-12")
    scheduled.handler({"kind": "selftest_error"})
    obj = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert obj["msg"] == "selftest_error"
    assert obj["household_id"] is None and obj["correlation_id"] is None


def test_logger_does_not_propagate_and_has_one_handler():
    a = log.get()
    b = log.get()
    assert a is b
    assert a.propagate is False
    assert len(a.handlers) == 1


def test_error_filter_matches_error_not_warn(capsys):
    log.get().warning("w")
    log.get().error("e")
    warn, err = capsys.readouterr().out.splitlines()
    assert json.loads(warn)["level"] == "WARN"
    assert not _matches_error_filter(warn)
    assert _matches_error_filter(err)
    assert not _matches_error_filter("[ERROR] 2026-10-12 text prefix")


def test_no_root_logger_use_in_package():
    src = Path(__file__).resolve().parent.parent / "src" / "aurasenior"
    bad = re.compile(r"logging\.getLogger\(\s*\)|logging\.basicConfig")
    hits = [p.name for p in src.rglob("*.py") if bad.search(p.read_text(encoding="utf-8"))]
    assert hits == []


def test_masking_keeps_last_four_digits_and_domain():
    assert log.mask_phone("+12025550101") == "*******0101"
    assert log.mask_email("someone@example.com") == "***@example.com"
    assert "0101" in log.mask_text("call +12025550101 now") and "2025550" not in log.mask_text("+12025550101")


def test_root_logger_level_is_untouched():
    log.get()
    assert logging.getLogger().handlers == [] or all(
        not isinstance(h, type(log.get().handlers[0])) for h in logging.getLogger().handlers
    )
