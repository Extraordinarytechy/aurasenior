"""Agent turn loop on the Bedrock Converse API with tool use, behind the AgentRunner interface."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from botocore.exceptions import ClientError

from .. import aws, clock, config, log, phrases, router, store
from ..memory import build_store
from ..router import Content
from . import prompt, tools

FATAL = {"AccessDeniedException", "ValidationException", "ResourceNotFoundException", "ModelNotReadyException",
         "ModelErrorException", "UnrecognizedClientException"}


class ScriptedModelMissing(RuntimeError):
    pass


@dataclass
class TurnResult:
    reply: str = ""
    tools: list[str] = field(default_factory=list)
    iterations: int = 0
    outcome: str = "ok"  # ok, capped, unavailable, max_iterations


def converse_client():
    if config.mode("converse") == "sim":
        if not aws.has_override("bedrock-runtime"):
            raise ScriptedModelMissing("converse mode is sim but no scripted model is loaded")
    return aws.client("bedrock-runtime")


def _model_label(client) -> str:
    return getattr(client, "label", "bedrock")


class AgentRunner:
    def run_turn(self, household_id: str, person_id: str, event: dict) -> TurnResult:
        hid = household_id
        speaker = store.get_person(hid, person_id)
        h = store.get_household(hid)
        today = clock.local_date(h.timezone)
        agent_cfg = config.agent()
        text = event.get("text", "")
        ctx = tools.ToolContext(hid, speaker, event["event_id"], voice_reply=bool(event.get("voice")))
        system, memory = prompt.system_prompt(hid, speaker, event)
        messages = prompt.history(hid, speaker) + [{"role": "user", "content": [{"text": text or "(scheduled)"}]}]
        client = converse_client()
        label = _model_label(client)
        guardrail = os.environ.get("GUARDRAIL_ID", "")
        result = TurnResult()
        ended = False
        for i in range(agent_cfg["max_iterations"]):
            if store.incr_converse(hid, today) > agent_cfg["daily_converse_cap"]:
                self._unavailable(hid, speaker, today, "cost_cap", event)
                result.outcome = "capped"
                return result
            kw = {"modelId": config.model_id(), "system": [{"text": system}], "messages": messages,
                  "inferenceConfig": {"maxTokens": agent_cfg["max_tokens"]}, "toolConfig": tools.tool_config()}
            if guardrail:
                kw["guardrailConfig"] = {"guardrailIdentifier": guardrail,
                                         "guardrailVersion": os.environ.get("GUARDRAIL_VERSION", "DRAFT")}
            try:
                resp = client.converse(**kw)
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                if code in FATAL:
                    self._unavailable(hid, speaker, today, "converse_error", event, code=code)
                    result.outcome = "unavailable"
                    return result
                raise
            result.iterations = i + 1
            msg = resp["output"]["message"]
            messages.append(msg)
            stop = resp.get("stopReason")
            store.trace(hid, "converse", model=label, stop_reason=stop, iteration=i + 1,
                        guardrail_mode=os.environ.get("GUARDRAIL_MODE", "none") if guardrail else "none",
                        memory_items=len(memory), simulated=label == "scripted")
            if stop == "guardrail_intervened":
                self._guardrail_blocked(hid, speaker, ctx, event)
                result.outcome = "guardrail_blocked"
                return result
            if stop == "tool_use":
                results = []
                for block in msg["content"]:
                    if "toolUse" not in block:
                        continue
                    tu = block["toolUse"]
                    status, out = tools.run(ctx, tu["name"], tu.get("input"))
                    result.tools.append(tu["name"])
                    store.trace(hid, "tool", tool=tu["name"], outcome=status, inputs=tu.get("input"),
                                simulated=label == "scripted")
                    results.append({"toolResult": {"toolUseId": tu["toolUseId"], "content": [{"json": out}],
                                                   "status": status}})
                messages.append({"role": "user", "content": results})
                continue
            result.reply = " ".join(b["text"] for b in msg["content"] if "text" in b).strip()
            ended = True
            break
        if not ended:
            log.get().warning("agent turn hit the iteration limit", extra={"household_id": hid})
            result.outcome = "max_iterations"
        if result.reply and speaker.person_id not in ctx.messaged:
            router.send(speaker, Content(text=result.reply, voice=speaker.is_elder and ctx.voice_reply),
                        correlation_id=f"{event['event_id']}#reply", inbound_text=text)
        if text:
            store.put_turn(hid, speaker.person_id, "user", text)
        if result.reply:
            store.put_turn(hid, speaker.person_id, "assistant", result.reply)
        build_store(speaker).record_turn(hid, speaker.person_id, text, result.reply)
        return result

    def _guardrail_blocked(self, hid: str, speaker, ctx, event: dict) -> None:
        """Fixed reply in the speaker's language that promises nothing. No family notice. The question stays only
        in the inbound TRACE item: it is not kept in turn history or memory."""
        store.trace(hid, "guardrail", outcome="blocked", person_id=speaker.person_id)
        router.send(speaker, Content(phrase="guardrail_blocked", voice=speaker.is_elder and ctx.voice_reply),
                    correlation_id=f"{event['event_id']}#guardrail", inbound_text=event.get("text"))

    def _unavailable(self, hid: str, speaker, today: str, why: str, event: dict, code: str | None = None) -> None:
        """Cost cap or a fatal model error: keep the cost_cap promise, tell family once a day."""
        if store.set_usage_flag(hid, today, f"agent_error_logged_{why}"):
            log.get().error("agent unavailable", extra={"household_id": hid, "reason": why, "code": code})
        store.trace(hid, "agent", outcome=why, code=code)
        if not speaker.is_elder:
            return
        h = store.get_household(hid)
        names = router.names_for(hid)
        if store.set_usage_flag(hid, today, "agent_unavailable_sent"):
            family_ok = False
            first = store.get_person(hid, h.escalation_order[0]) if h.escalation_order else None
            if first:
                rl = first.relation_label or ""
                note = phrases.render("agent_unavailable_family", first.language, relation_label=rl)
                r = router.send(first, Content(phrase="agent_unavailable_family", vars={"relation_label": rl},
                                               wa_template="aurasenior_family_update", wa_params=[rl, note],
                                               email_template="aurasenior-update", email_data={"update_text": note}),
                                correlation_id=f"{event['event_id']}#unavailable")
                family_ok = r.ok
            # Later turns today read this, so the elder is only promised what was actually sent.
            store.update(store.hh(hid), f"USAGE#{today}", agent_unavailable_ok=family_ok)
        else:
            family_ok = bool((store.get(store.hh(hid), f"USAGE#{today}") or {}).get("agent_unavailable_ok"))
        phrase = "cost_cap" if family_ok else "not_heard"
        router.send(speaker, Content(phrase=phrase, vars={"family_name": names.get("family_name", "")}, voice=True),
                    correlation_id=f"{event['event_id']}#{phrase}", inbound_text=event.get("text"))


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
