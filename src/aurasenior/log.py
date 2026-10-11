"""JSON log lines on stdout.

One logger named "aurasenior" with propagate=False and a single stdout handler, so the Lambda runtime's own
handler never adds a text prefix and every line is one JSON object for the { $.level = "ERROR" } metric filter.
"""
from __future__ import annotations

import json
import logging
import re
import sys

_LEVELS = {"DEBUG": "DEBUG", "INFO": "INFO", "WARNING": "WARN", "ERROR": "ERROR", "CRITICAL": "ERROR"}
_STD = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}
_context: dict[str, str] = {}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "level": _LEVELS.get(record.levelname, record.levelname),
            "msg": record.getMessage(),
            "household_id": getattr(record, "household_id", _context.get("household_id")),
            "correlation_id": getattr(record, "correlation_id", _context.get("correlation_id")),
        }
        for k, v in vars(record).items():
            if k not in _STD and k not in out:
                out[k] = v
        if record.exc_info:
            out["error_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(out, default=str, ensure_ascii=False)


class _StdoutHandler(logging.StreamHandler):
    # Resolve sys.stdout on every emit so a replaced stdout (pytest capture, Lambda) still receives the line.
    def __init__(self):
        super().__init__(sys.stdout)

    @property
    def stream(self):
        return sys.stdout

    @stream.setter
    def stream(self, _value):
        pass


def get() -> logging.Logger:
    logger = logging.getLogger("aurasenior")
    if not any(isinstance(h, _StdoutHandler) for h in logger.handlers):
        h = _StdoutHandler()
        h.setFormatter(JsonFormatter())
        logger.addHandler(h)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def set_context(**kw: str | None) -> None:
    for k, v in kw.items():
        if v is None:
            _context.pop(k, None)
        else:
            _context[k] = v


def clear_context() -> None:
    """Called at handler entry: a warm container must not carry the last invocation's household into new lines."""
    _context.clear()


def mask_phone(number: str | None) -> str | None:
    if not number:
        return number
    digits = re.sub(r"\D", "", number)
    return "*" * max(len(digits) - 4, 0) + digits[-4:]


def mask_email(addr: str | None) -> str | None:
    if not addr or "@" not in addr:
        return addr
    return "***@" + addr.split("@", 1)[1]


_PHONE = re.compile(r"\+?\d[\d ]{8,15}\d")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")


def mask_text(text: str) -> str:
    text = _EMAIL.sub(lambda m: mask_email(m.group(0)), text)
    return _PHONE.sub(lambda m: mask_phone(m.group(0)), text)
