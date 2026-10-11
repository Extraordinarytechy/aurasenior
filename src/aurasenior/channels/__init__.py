"""Adapter per channel, chosen by [channels] in app.toml (or AURASENIOR_MODE_<CHANNEL>)."""
from __future__ import annotations

from .. import config

_cache: dict[tuple[str, str], object] = {}


def get(channel: str):
    mode = config.mode(channel)
    key = (channel, mode)
    if key not in _cache:
        _cache[key] = _build(channel, mode)
    return _cache[key]


def _build(channel: str, mode: str):
    if mode == "sim":
        from . import sim

        return {"whatsapp": sim.WhatsAppSim, "rcs": sim.RcsSim, "sms": sim.SmsSim, "email": sim.EmailSim}[channel]()
    if channel == "whatsapp":
        from .whatsapp_aws import WhatsAppAws

        return WhatsAppAws()
    if channel == "rcs":
        from .rcs_aws import RcsAws

        return RcsAws()
    if channel == "sms":
        from .sms_aws import SmsAws

        return SmsAws()
    if channel == "email":
        from .email_aws import EmailAws

        return EmailAws()
    raise ValueError(f"unknown channel {channel}")


def reset() -> None:
    _cache.clear()
