"""System prompt and message history for one turn. Only the speaker's own turns and memory are included."""
from __future__ import annotations

from .. import clock, config, languages, store
from ..memory import build_store
from ..models import Person

RULES = """You are {brand}, a warm companion for an older person and their family.
Rules:
- You are not a medical service. Never diagnose, never name an illness, never give a score, never suggest a dose.
- Never give health or treatment advice. For a health question, only say that their doctor can help.
- Use the tools to record medicines, ask for refills, alert family and message people. Never invent facts.
- Act only on what this message says. Earlier turns are already handled: never repeat their tool calls.
- Keep replies short and kind: two or three sentences. Reply in {reply_language}.
"""

ELDER_RULES = """You are talking with the elder herself.
- If she mentions a fall or needs help, call escalate with reason fall_or_help.
- When she says a medicine has run out, call log_medicine with out_of_stock true, then request_refill_approval
  for the first family member in the escalation order.
- After each voice note from her, call suggest_call once. It sends a fixed note to family only when one is
  due. Never mention it to her.
"""

FAMILY_RULES = """You are talking with {name}, not with the elder. {name} calls the elder "{label}".
- Talk to {name} about {label}. Never address {name} as {label} and never reply as if {name} were the elder.
- Answer questions about {label} from get_week and get_household. Call log_medicine, request_refill_approval or
  suggest_call only when {name} asks for that in this message.
"""


def query_for(event: dict) -> str | None:
    text = event.get("text") or ""
    return text[:500] if text and not event.get("scheduled") else None


def system_prompt(hid: str, speaker: Person, event: dict) -> tuple[str, list[str]]:
    h = store.get_household(hid)
    row = languages.row(speaker.language)
    elder = store.get_person(hid, h.elder_person_id)
    today = clock.local_date(h.timezone)
    meds = ", ".join(f"{m.medicine_id} ({m.display_label}, stock {m.stock})" for m in store.medicines(hid))
    taken = ", ".join(f"{x['medicine_id']}={'taken' if x['taken'] else 'not taken'}"
                      for x in store.logs_between(hid, today, today)) or "nothing logged yet"
    memory = build_store(speaker).recall(hid, speaker.person_id, query_for(event))
    if speaker.is_elder:
        persona = ELDER_RULES
    else:
        persona = FAMILY_RULES.format(name=speaker.display_name,
                                      label=speaker.relation_label or elder.display_name)
    parts = [RULES.format(brand=config.brand(), reply_language=row.reply_language), persona,
             f"Person speaking: {speaker.display_name} (person_id {speaker.person_id}, role {speaker.role}).",
             f"Elder: {elder.display_name} (person_id {elder.person_id}). Escalation order: {', '.join(h.escalation_order)}.",
             f"Today ({today}) medicines: {meds}. Log: {taken}."]
    if event.get("elder_told"):
        parts.append("The elder has just been told that family was alerted. Do not repeat that.")
    if memory:
        parts.append("What you remember about the person speaking:\n- " + "\n- ".join(memory))
    return "\n".join(parts), memory


def history(hid: str, speaker: Person) -> list[dict]:
    """Last 10 turns of the speaker only, so the elder's words never reach a family member's prompt."""
    msgs = []
    for t in store.last_turns(hid, speaker.person_id, 10):
        role = "user" if t["role"] == "user" else "assistant"
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"][0]["text"] += "\n" + t["text"]
        else:
            msgs.append({"role": role, "content": [{"text": t["text"]}]})
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    if msgs and msgs[-1]["role"] == "user":
        msgs.pop()
    return msgs
