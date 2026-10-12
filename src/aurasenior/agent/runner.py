"""Agent turn loop on the Bedrock Converse API with tool use, behind the AgentRunner interface."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from botocore.exceptions import ClientError

from .. import aws, clock, config, log, phrases, router, store
from ..channels.errors import error_message
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
        if event.get("elder_told"):
            ctx.messaged.add(speaker.person_id)  # she just heard esc_told_elder from the fall path
        system, memory = prompt.system_prompt(hid, speaker, event)
        messages = prompt.history(hid, speaker) + [{"role": "user", "content": [{"text": text or "(scheduled)"}]}]
        client = converse_client()
        label = _model_label(client)
        guardrail = os.environ.get("GUARDRAIL_ID", "")
        result = TurnResult()
        done: list[tuple[str, dict, dict]] = []  # tools that succeeded this turn: name, input, result
        ended = False
        for i in range(agent_cfg["max_iterations"]):
            if store.incr_converse(hid, today) > agent_cfg["daily_converse_cap"]:
                self._unavailable(hid, speaker, today, "cost_cap", event)
                result.outcome = "capped"
                return result
            kw = {"modelId": config.model_id(), "system": [{"text": system}], "messages": messages,
                  "inferenceConfig": {"maxTokens": agent_cfg["max_tokens"]}, "toolConfig": tools.tool_config()}
            if guardrail:
                # The trace says which policy fired and whether on her words or on the model's reply.
                kw["guardrailConfig"] = {"guardrailIdentifier": guardrail,
                                         "guardrailVersion": os.environ.get("GUARDRAIL_VERSION", "DRAFT"),
                                         "trace": "enabled"}
            try:
                resp = client.converse(**kw)
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                if code in FATAL:
                    self._unavailable(hid, speaker, today, "converse_error", event, code=code,
                                      error=error_message(e))
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
                findings = guardrail_findings(resp)
                said = self._guardrail_blocked(hid, speaker, ctx, event, findings, done)
                if findings is not None and not findings["input"]:
                    # Her words passed the guardrail, only the model's reply did not: keep the turn with the
                    # fixed line she actually heard, so memory has this check-in too.
                    self._keep(hid, speaker, text, said)
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
                    if status == "success":
                        done.append((tu["name"], tu.get("input") or {}, out))
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
        reply = result.reply
        if reply and speaker.person_id in ctx.messaged:
            # Already messaged this turn (fall alert or message_person): do not send a second, similar reply,
            # and do not keep words she never heard in history or memory.
            store.trace(hid, "reply", person_id=speaker.person_id, outcome="skipped_already_messaged")
            reply = ""
        if reply:
            router.send(speaker, Content(text=reply, voice=speaker.is_elder and ctx.voice_reply),
                        correlation_id=f"{event['event_id']}#reply", inbound_text=text)
        self._keep(hid, speaker, text, reply)
        return result

    @staticmethod
    def _keep(hid: str, speaker, text: str, reply: str) -> None:
        """Turn history in DynamoDB and the speaker's long-term memory."""
        if text:
            store.put_turn(hid, speaker.person_id, "user", text)
        if reply:
            store.put_turn(hid, speaker.person_id, "assistant", reply)
        build_store(speaker).record_turn(hid, speaker.person_id, text, reply)

    def _guardrail_blocked(self, hid: str, speaker, ctx, event: dict, findings: dict | None,
                           done: list[tuple[str, dict, dict]]) -> str:
        """No family notice. When tools already ran and only the reply was blocked, the elder hears a fixed line
        built from the tool results; otherwise a fixed reply in her language that promises nothing. A blocked
        question stays only in the inbound TRACE item: it is not kept in turn history or memory. Returns the text
        that went out, or an empty string."""
        input_blocked = bool(findings and findings["input"])
        content = None if input_blocked else self._confirmation(hid, speaker, ctx, done)
        store.trace(hid, "guardrail", outcome="blocked", person_id=speaker.person_id,
                    input_topics=(findings or {}).get("input"), output_topics=(findings or {}).get("output"),
                    reply=content.phrase if content else "guardrail_blocked")
        if content is None:
            content = Content(phrase="guardrail_blocked", voice=speaker.is_elder and ctx.voice_reply)
        r = router.send(speaker, content, correlation_id=f"{event['event_id']}#guardrail",
                        inbound_text=event.get("text"))
        if not r.went_out:
            return ""
        return phrases.render(content.phrase, speaker.language, speaker.audience, **content.vars)

    @staticmethod
    def _confirmation(hid: str, speaker, ctx, done: list[tuple[str, dict, dict]]) -> Content | None:
        """Only what the tools really did: a refill ask whose card went out, else a medicine that was logged."""
        if not speaker.is_elder or not done:
            return None
        voice = ctx.voice_reply
        asked = [(i, out) for name, i, out in done if name == "request_refill_approval" and out.get("asked")]
        if asked:
            labels = []
            for i, _ in asked:
                med = store.get_medicine(hid, i.get("medicine_id", ""))
                if med and med.display_label not in labels:
                    labels.append(med.display_label)
            family = store.get_person(hid, asked[0][1].get("ask_person_id", ""))
            if labels and family:
                return Content(phrase="refill_asked_elder", voice=voice,
                               vars={"family_name": family.display_name, "display_label": ", ".join(labels)})
        if any(name == "log_medicine" for name, _, _ in done):
            return Content(phrase="noted_elder", voice=voice)
        return None

    def _unavailable(self, hid: str, speaker, today: str, why: str, event: dict, code: str | None = None,
                     error: str | None = None) -> None:
        """Cost cap or a fatal model error: keep the cost_cap promise, tell family once a day."""
        if store.set_usage_flag(hid, today, f"agent_error_logged_{why}"):
            log.get().error("agent unavailable", extra={"household_id": hid, "reason": why, "code": code,
                                                        "error": error})
        store.trace(hid, "agent", outcome=why, code=code)
        if not speaker.is_elder:
            return
        h = store.get_household(hid)
        names = router.names_for(hid)
        first_today = store.set_usage_flag(hid, today, "agent_unavailable_sent")
        usage = {} if first_today else (store.get(store.hh(hid), f"USAGE#{today}") or {})
        if first_today or "agent_unavailable_ok" not in usage:
            # Also reached when an earlier attempt claimed the flag but its send raised: the send is SEND# deduped.
            family_ok = False
            known = True
            first = store.get_person(hid, h.escalation_order[0]) if h.escalation_order else None
            if first:
                rl = first.relation_label or ""
                note = phrases.render("agent_unavailable_family", first.language, relation_label=rl)
                r = router.send(first, Content(phrase="agent_unavailable_family", vars={"relation_label": rl},
                                               wa_template="aurasenior_family_update", wa_params=[rl, note],
                                               email_template="aurasenior-update", email_data={"update_text": note}),
                                correlation_id=f"unavailable#{today}")
                family_ok = r.went_out
                # Skipped with no provider id: failed before or still in flight elsewhere, so leave the flag unset.
                known = r.outcome != "skipped" or family_ok
            # Later turns today read this, so the elder is only promised what was actually sent.
            if known:
                store.update(store.hh(hid), f"USAGE#{today}", agent_unavailable_ok=family_ok)
        else:
            family_ok = bool(usage["agent_unavailable_ok"])
        phrase = "cost_cap" if family_ok else "not_heard"
        router.send(speaker, Content(phrase=phrase, vars={"family_name": names.get("family_name", "")}, voice=True),
                    correlation_id=f"{event['event_id']}#{phrase}", inbound_text=event.get("text"))


def guardrail_findings(resp: dict) -> dict | None:
    """Names of the guardrail policies that blocked, on the input and on the model output. None without a trace."""
    trace = (resp.get("trace") or {}).get("guardrail")
    if not trace:
        return None

    def blocked(node) -> list[str]:
        if isinstance(node, list):
            return [n for x in node for n in blocked(x)]
        if not isinstance(node, dict):
            return []
        own = [str(node.get("name") or node.get("type") or "policy")] if node.get("action") == "BLOCKED" else []
        return own + [n for v in node.values() for n in blocked(v)]

    return {"input": blocked(list((trace.get("inputAssessment") or {}).values())),
            "output": blocked(list((trace.get("outputAssessments") or {}).values()))}


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
