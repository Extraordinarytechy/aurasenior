"""Scripted model: replays recorded Converse responses in order. Every turn it serves is traced model=scripted."""
from __future__ import annotations

import copy
import json
from pathlib import Path

simulated = True


class ScriptedConverse:
    label = "scripted"

    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    @classmethod
    def from_file(cls, path: str | Path) -> "ScriptedConverse":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def add(self, responses: list[dict]) -> None:
        self.responses.extend(responses)

    def converse(self, **kw) -> dict:
        self.calls.append(copy.deepcopy(kw))  # the caller keeps appending to the same messages list
        if not self.responses:
            raise AssertionError("scripted model has no recorded response left")
        r = copy.deepcopy(self.responses.pop(0))
        r.setdefault("usage", {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0})
        return r


def tool_use(name: str, tool_input: dict, tool_use_id: str = "t1", text: str | None = None) -> dict:
    content = ([{"text": text}] if text else []) + [{"toolUse": {"toolUseId": tool_use_id, "name": name,
                                                                "input": tool_input}}]
    return {"output": {"message": {"role": "assistant", "content": content}}, "stopReason": "tool_use"}


def end_turn(text: str) -> dict:
    return {"output": {"message": {"role": "assistant", "content": [{"text": text}]}}, "stopReason": "end_turn"}
