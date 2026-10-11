"""One boto3 client per service per container, with an override registry for sims and tests."""
from __future__ import annotations

from typing import Any

import boto3
from botocore.config import Config

_clients: dict[str, Any] = {}
_overrides: dict[str, Any] = {}

_CONFIGS = {
    # Memory calls are best effort: short timeouts so a slow call never stalls a turn (fallback to DynamoDB).
    "bedrock-agentcore": Config(retries={"mode": "standard", "max_attempts": 2}, connect_timeout=2, read_timeout=3),
    "bedrock-runtime": Config(retries={"mode": "standard", "max_attempts": 3}),
}
_DEFAULT = Config(retries={"mode": "standard", "max_attempts": 3})


def client(name: str):
    if name in _overrides:
        return _overrides[name]
    if name not in _clients:
        _clients[name] = boto3.client(name, config=_CONFIGS.get(name, _DEFAULT))
    return _clients[name]


def resource_dynamodb():
    if "dynamodb-resource" in _overrides:
        return _overrides["dynamodb-resource"]
    if "dynamodb-resource" not in _clients:
        _clients["dynamodb-resource"] = boto3.resource("dynamodb", config=_DEFAULT)
    return _clients["dynamodb-resource"]


def has_override(name: str) -> bool:
    return name in _overrides


def override(name: str, obj: Any) -> None:
    _overrides[name] = obj


def reset() -> None:
    _clients.clear()
    _overrides.clear()
