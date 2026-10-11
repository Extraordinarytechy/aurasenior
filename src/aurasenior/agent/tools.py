"""The nine tools the model sees. Channel choice, scheduling and the pharmacy order are not model decisions."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .. import clock, escalation, refill, router, signals, store, summary
from ..memory import build_store
from ..models import Person


@dataclass
class ToolContext:
    household_id: str
    speaker: Person
    event_id: str
    voice_reply: bool = False
    step: int = 0
    messaged: set = field(default_factory=set)

    def correlation(self, what: str) -> str:
        self.step += 1
        return f"{self.event_id}#tool{self.step}#{what}"

    @property
    def local_date(self) -> str:
        return clock.local_date(store.get_household(self.household_id).timezone)


def _schema(props: dict, required: list[str]) -> dict:
    return {"json": {"type": "object", "properties": props, "required": required}}


SPECS: list[dict] = [
    {"name": "get_household", "description": "People, medicines, today's medicine log, open approvals and escalations.",
     "inputSchema": _schema({}, [])},
    {"name": "get_week", "description": "Facts for the last 7 days: medicines taken, refills, escalations, mentions.",
     "inputSchema": _schema({}, [])},
    {"name": "log_medicine", "description": "Record whether a medicine was taken today and whether it ran out.",
     "inputSchema": _schema({"medicine_id": {"type": "string"}, "taken": {"type": "boolean"},
                             "out_of_stock": {"type": "boolean"}}, ["medicine_id", "taken", "out_of_stock"])},
    {"name": "message_person", "description": "Send a message to a person in the household. The channel is chosen for you.",
     "inputSchema": _schema({"person_id": {"type": "string"}, "text": {"type": "string", "minLength": 1, "maxLength": 600},
                             "as_voice": {"type": "boolean"}, "urgency": {"type": "string", "enum": ["normal", "urgent"]}},
                            ["person_id", "text"])},
    {"name": "request_refill_approval", "description": "Ask a family member to approve a refill. Nothing is ordered until they tap.",
     "inputSchema": _schema({"medicine_id": {"type": "string"}, "ask_person_id": {"type": "string"}},
                            ["medicine_id", "ask_person_id"])},
    {"name": "escalate", "description": "Alert family now when the elder may need help.",
     "inputSchema": _schema({"reason": {"type": "string", "enum": ["fall_or_help", "missed_checkin"]},
                             "quote": {"type": "string", "maxLength": 200}}, ["reason"])},
    {"name": "ack_escalation", "description": "Mark an open escalation as handled by the person speaking.",
     "inputSchema": _schema({"escalation_id": {"type": "string"}}, ["escalation_id"])},
    {"name": "remember", "description": "Keep a short note about the person speaking (routine, people they mention).",
     "inputSchema": _schema({"note": {"type": "string", "minLength": 1, "maxLength": 200}}, ["note"])},
    {"name": "suggest_call", "description": "Send the fixed worth-a-call suggestion to family if one is due.",
     "inputSchema": _schema({}, [])},
]

_TYPES = {"string": str, "boolean": bool, "integer": int}


def validate(name: str, args: Any) -> str | None:
    spec = next((s for s in SPECS if s["name"] == name), None)
    if not spec:
        return f"unknown tool {name}"
    if not isinstance(args, dict):
        return "input must be an object"
    schema = spec["inputSchema"]["json"]
    for r in schema["required"]:
        if r not in args:
            return f"{r} is required"
    for k, v in args.items():
        p = schema["properties"].get(k)
        if p is None:
            return f"unknown field {k}"
        if not isinstance(v, _TYPES[p["type"]]):
            return f"{k} must be {p['type']}"
        if "enum" in p and v not in p["enum"]:
            return f"{k} must be one of {p['enum']}"
        if isinstance(v, str) and not (p.get("minLength", 0) <= len(v) <= p.get("maxLength", 10**6)):
            return f"{k} has the wrong length"
    return None


def get_household(ctx: ToolContext, _args: dict) -> dict:
    hid = ctx.household_id
    h = store.get_household(hid)
    today = ctx.local_date
    return {
        "people": [{"person_id": p.person_id, "role": p.role, "display_name": p.display_name, "language": p.language,
                    "relation_label": p.relation_label, "preferred_channel": p.preferred_channel}
                   for p in store.people(hid)],
        "medicines": [{"medicine_id": m.medicine_id, "display_label": m.display_label, "stock": m.stock,
                       "time_of_day": m.time_of_day} for m in store.medicines(hid)],
        "today_log": [{"medicine_id": x["medicine_id"], "taken": x["taken"]} for x in store.logs_between(hid, today, today)],
        "open_approvals": [a.approval_id for a in store.approvals(hid) if a.status == "pending"],
        "open_escalations": [{"escalation_id": e.escalation_id, "reason": e.reason}
                             for e in escalation.open_escalations(hid)],
        "escalation_order": h.escalation_order,
    }


def get_week(ctx: ToolContext, _args: dict) -> dict:
    return summary.build_week(ctx.household_id, ctx.local_date).to_dict()


def log_medicine(ctx: ToolContext, args: dict) -> dict:
    if not store.get_medicine(ctx.household_id, args["medicine_id"]):
        return {"status": "error", "reason": "unknown medicine_id"}
    store.log_medicine(ctx.household_id, args["medicine_id"], ctx.local_date, taken=args["taken"],
                       out_of_stock=args["out_of_stock"], source_msg=ctx.event_id)
    return {"status": "ok"}


def message_person(ctx: ToolContext, args: dict) -> dict:
    p = store.get_person(ctx.household_id, args["person_id"])
    if not p:
        return {"status": "error", "reason": "unknown person_id"}
    voice = bool(args.get("as_voice")) and p.is_elder
    r = router.send(p, router.Content(text=args["text"], voice=voice), urgency=args.get("urgency", "normal"),
                    correlation_id=ctx.correlation(f"msg-{p.person_id}"))
    if r.ok:
        ctx.messaged.add(p.person_id)
    return {"status": "ok" if r.ok else r.outcome, "channel": r.channel}


def request_refill_approval_tool(ctx: ToolContext, args: dict) -> dict:
    return refill.request_refill_approval(ctx.household_id, args["medicine_id"], args["ask_person_id"],
                                          correlation_id=ctx.correlation("refill"))


def escalate_tool(ctx: ToolContext, args: dict) -> dict:
    hid = ctx.household_id
    eid = escalation.escalate(hid, args["reason"], args.get("quote", ""), event_id=ctx.event_id)
    if args["reason"] == "fall_or_help" and escalation.fall_raised_by(hid, ctx.event_id):
        # escalate() already sent the elder esc_told_elder; a model reply would only repeat it.
        ctx.messaged.add(store.get_household(hid).elder_person_id)
        return {"status": "ok", "escalation_id": eid, "elder_already_told": True}
    return {"status": "ok", "escalation_id": eid}


def ack_escalation_tool(ctx: ToolContext, args: dict) -> dict:
    ok = escalation.ack_escalation(ctx.household_id, args["escalation_id"], ctx.speaker.person_id)
    return {"status": "ok" if ok else "error", "reason": None if ok else "not open or not allowed"}


def remember_tool(ctx: ToolContext, args: dict) -> dict:
    build_store(ctx.speaker).remember(ctx.household_id, ctx.speaker.person_id, args["note"])
    return {"status": "ok"}


def suggest_call(ctx: ToolContext, _args: dict) -> dict:
    r = signals.worth_a_call(ctx.household_id, correlation_id=ctx.correlation("signal"))
    return {"status": "sent" if r and r.ok else "nothing_due"}


HANDLERS: dict[str, Callable[[ToolContext, dict], dict]] = {
    "get_household": get_household, "get_week": get_week, "log_medicine": log_medicine,
    "message_person": message_person, "request_refill_approval": request_refill_approval_tool,
    "escalate": escalate_tool, "ack_escalation": ack_escalation_tool, "remember": remember_tool,
    "suggest_call": suggest_call,
}


def run(ctx: ToolContext, name: str, args: Any) -> tuple[str, dict]:
    """Returns (status, result) for a toolResult block. Invalid input goes back to the model as an error."""
    err = validate(name, args)
    if err:
        return "error", {"error": err}
    result = HANDLERS[name](ctx, args)
    return ("error" if result.get("status") == "error" else "success"), result


def tool_config() -> dict:
    return {"tools": [{"toolSpec": s} for s in SPECS]}
