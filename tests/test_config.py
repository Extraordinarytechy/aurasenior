import tomllib
from datetime import datetime, timezone

import pytest

from aurasenior import clock, config


def _app():
    with (config.config_dir() / "app.toml").open("rb") as f:
        return tomllib.load(f)


def test_brand_and_model_come_from_app_toml():
    app = _app()
    assert config.brand() == app["brand"]["name"]
    assert config.model_id() == app["agent"]["model_id"]


def test_unknown_language_raises():
    with pytest.raises(config.ConfigError):
        config.language("fr-FR")


def test_env_override_beats_config(monkeypatch):
    assert config.mode("rcs") == "sim"
    monkeypatch.setenv("AURASENIOR_MODE_RCS", "aws")
    assert config.mode("rcs") == "aws"


def test_missing_key_raises():
    with pytest.raises(config.ConfigError):
        config.get("agent", "nope")


def test_clock_freeze_and_advance():
    clock.freeze(datetime(2026, 10, 12, 3, 30, tzinfo=timezone.utc))
    assert clock.local_now("Asia/Kolkata").strftime("%H:%M") == "09:00"
    clock.advance(90)
    assert clock.local_now("Asia/Kolkata").strftime("%H:%M") == "10:30"
    assert clock.local_date("Asia/Kolkata") == "2026-10-12"
