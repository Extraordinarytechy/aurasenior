"""Mask account ids, ARNs' account part, request ids, emails and phone numbers before saving evidence."""
import re

_ACCOUNT = re.compile(r"(?<![\d_])\d{12}(?!\d)")  # "_<yyyymmddhhmm>" name suffixes are timestamps, not accounts
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_PHONE = re.compile(r"\+\d{8,15}")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")


def text(s: str) -> str:
    s = _ACCOUNT.sub("REDACTED_ACCOUNT", s)
    s = _EMAIL.sub("REDACTED_EMAIL", s)
    s = _PHONE.sub("REDACTED_PHONE", s)
    return _UUID.sub("REDACTED_ID", s)


def obj(o):
    if isinstance(o, dict):
        return {k: obj(v) for k, v in o.items() if k not in ("RequestId", "HostId", "HTTPHeaders")}
    if isinstance(o, list):
        return [obj(v) for v in o]
    if isinstance(o, str):
        return text(o)
    return o
