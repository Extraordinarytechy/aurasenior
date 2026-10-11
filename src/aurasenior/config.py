"""Loads the TOML files under the config directory once per container."""
from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path


class ConfigError(Exception):
    pass


def config_dir() -> Path:
    # src/config locally, /var/task/config in Lambda (the package and config ship together).
    env = os.environ.get("AURASENIOR_CONFIG_DIR")
    return Path(env) if env else Path(__file__).resolve().parent.parent / "config"


@lru_cache(maxsize=None)
def load(name: str) -> dict:
    path = config_dir() / f"{name}.toml"
    if not path.exists():
        raise ConfigError(f"missing config file {path.name}")
    with path.open("rb") as f:
        return tomllib.load(f)


def get(*keys: str, file: str = "app"):
    node = load(file)
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            raise ConfigError(f"missing config key {'.'.join(keys)} in {file}.toml")
        node = node[k]
    return node


def brand() -> str:
    return get("brand", "name")


def model_id() -> str:
    return get("agent", "model_id")


def agent() -> dict:
    return get("agent")


def language(key: str) -> dict:
    rows = get("languages")
    if key not in rows:
        raise ConfigError(f"unknown language {key}")
    return rows[key]


def language_keys() -> list[str]:
    return list(get("languages").keys())


def mode(name: str) -> str:
    """Channel or service mode, "aws" or "sim". The environment variable wins over app.toml."""
    env = os.environ.get(f"AURASENIOR_MODE_{name.upper()}")
    if env:
        return env
    for section in ("channels", "services"):
        sec = get(section)
        if name in sec:
            return sec[name]
    raise ConfigError(f"no mode for {name}")


def limits() -> dict:
    return get("limits")


def simulator_destinations() -> list[str]:
    return list(get("sms", "simulator_destinations"))
