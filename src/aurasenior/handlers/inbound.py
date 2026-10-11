"""aurasenior-inbound: WhatsApp, SMS and RCS messages, delivery events, and Transcribe completion.

Order for a person's message: dedupe, sender lookup, elder check-in chain, consent, fall and help words, Listen
taps, approval and ack taps, then one agent turn. Everything before the agent turn is deterministic.
"""
from __future__ import annotations

import os

from .. import channels as channel_adapters
from .. import (clock, config, consent, dedupe, escalation, keywords, log, postback, refill, router, schedules,
                signals, store, transcribe)
from ..agent.runner import AgentRunner
from ..channels import parse
from ..channels.base import InboundMessage
from ..memory import agentcore, build_store
from ..models import Person
from ..router import Content

TOPICS = {"whatsapp": "aurasenior-whatsapp-events", "sms-rcs": "aurasenior-sms-rcs-events",
          "email": "aurasenior-email-events"}


def _topic_kind(arn: str) -> str | None:
    env = {"whatsapp": "WHATSAPP_TOPIC_ARN", "sms-rcs": "SMS_RCS_TOPIC_ARN", "email": "EMAIL_TOPIC_ARN"}
    for kind, var in env.items():
        if os.environ.get(var) and arn == os.environ[var]:
            return kind
    for kind, name in TOPICS.items():
        if arn.endswith(":" + name):
            return kind
    return None


def handler(event: dict, context=None) -> dict:
    agentcore.reset_invocation()
    if event.get("source") == "aws.transcribe":
        on_transcribe_event(event)
        return {"ok": True}
    for arn, msg in parse.sns_messages(event):
        kind = _topic_kind(arn)
        if kind == "whatsapp":
            m = parse.whatsapp_inbound(msg)
            if m:
                if config.mode("whatsapp") == "sim":
                    m.simulated = True
                process(m)
                continue
            st = parse.whatsapp_status(msg)
        elif kind == "sms-rcs":
            m = parse.sms_rcs_inbound(msg)
            if m:
                process(m)
                continue
            st = parse.sms_rcs_status(msg)
        elif kind == "email":
            st = parse.ses_status(msg)
        else:
            st = None
        if st:
            on_status(st)
        else:
            log.get().warning("unknown event shape dropped", extra={"topic_kind": kind})
    return {"ok": True}


def on_status(st) -> None:
    hid = store.msg_household(st.provider_id)
    if not hid or not dedupe.claim(f"status#{st.event_id}"):
        return
    try:
        router.on_status(hid, st.provider_id, st.status)
        dedupe.done(f"status#{st.event_id}")
    except Exception:
        dedupe.release(f"status#{st.event_id}")
        raise


def _lookup(m: InboundMessage) -> tuple[str, str] | None:
    chans = ["whatsapp"] if m.channel == "whatsapp" else [m.channel, "rcs", "sms"]
    for ch in chans:
        found = store.lookup_addr(ch, m.sender)
        if found:
            return found
    return None


def process(m: InboundMessage) -> None:
    eid = f"{m.channel}#{m.event_id}"
    if not dedupe.claim(eid):
        return
    try:
        _process(m, eid)
        dedupe.done(eid)
    except Exception:
        log.get().warning("inbound event failed, released for retry", extra={"event_id": eid})
        dedupe.release(eid)
        raise


def _elder_replied(person: Person, eid: str) -> None:
    h = store.get_household(person.household_id)
    now = clock.local_now(h.timezone)
    local_date = now.strftime("%Y-%m-%d")
    if schedules.delete_checkin_chain(person.household_id, local_date) >= 1:
        build_store(person).record_checkin(person.household_id, person.person_id, local_date,
                                           f"Check-in {local_date}: replied {now.strftime('%H:%M')}")
    escalation.resolve_by_elder(person.household_id, eid)


def _process(m: InboundMessage, eid: str) -> None:
    found = _lookup(m)
    if not found:
        log.get().info("unknown sender dropped", extra={"sender": log.mask_phone(m.sender)})
        return
    hid, pid = found
    log.set_context(household_id=hid, correlation_id=eid)
    person = store.get_person(hid, pid)
    if m.channel in ("sms", "rcs") and m.simulated and m.sender not in config.simulator_destinations():
        log.get().warning("simulated inbound refused for a non-simulator number", extra={"household_id": hid})
        return
    simulated = m.simulated or person.simulated or config.mode(m.channel) == "sim"
    if m.channel == "whatsapp":
        store.set_wa_inbound(hid, pid)
        person = store.get_person(hid, pid)
        adapter = channel_adapters.get("whatsapp")
        if hasattr(adapter, "mark_read"):
            adapter.mark_read(m.event_id)
    store.trace(hid, "inbound", channel=m.channel, person_id=pid, kind=m.kind,
                text=(m.text or m.button_payload or m.postback or "")[:200], simulated=simulated)
    if person.is_elder:
        _elder_replied(person, eid)
    if m.channel == "whatsapp" and m.kind == "audio":
        if (m.audio_size or 0) > transcribe.MAX_MEDIA or not (m.audio_mime or "audio").startswith("audio"):
            router.send(person, Content(phrase="send_voice_note"), correlation_id=f"{eid}#1")
            return
        transcribe.start(person, m.event_id, m.audio_media_id or "")
        return
    if m.kind not in ("text", "button", "postback"):
        router.send(person, Content(phrase="send_voice_note"), correlation_id=f"{eid}#1")
        return
    if m.kind == "button":
        res = postback.whatsapp_button(person, m)
        if res and isinstance(res, tuple) and res[0].startswith("listen:"):
            _listen(person, res[0], eid)
            return
        if res is not None:
            _tap(person, res, eid)
            return
    if m.kind == "postback":
        res = postback.parse_postback(m.postback or "")
        if res:
            _tap(person, res, eid)
        else:
            log.get().info("postback ignored", extra={"household_id": hid})
        return
    handle_text(person, m.channel, m.text, eid, voice=False, simulated=simulated)


def _listen(person: Person, action: str, eid: str) -> None:
    which = action.split(":", 1)[1]
    phrase = "followup_voice" if which == "followup" else "checkin_voice"
    meds = [x for x in store.medicines(person.household_id) if x.time_of_day == "morning"]
    router.send(person, Content(phrase=phrase, vars={"display_label": meds[0].display_label if meds else ""},
                                voice=True), correlation_id=f"{eid}#listen")


def _tap(person: Person, res, eid: str) -> None:
    if res == "help":
        router.send(person, Content(phrase="sms_help"), correlation_id=f"{eid}#help")
        return
    action, target = res
    refill.handle_action(person.household_id, person.person_id, action, target, correlation_id=eid)


def handle_text(person: Person, channel: str, text: str, eid: str, *, voice: bool, simulated: bool = False) -> None:
    if consent.handle(person, channel, text, correlation_id=f"{eid}#consent", simulated=simulated):
        return
    if person.is_elder and keywords.fall_or_help(text):
        escalation.escalate(person.household_id, "fall_or_help", text[:200])
    if channel in ("sms", "rcs") and not person.is_elder:
        res = postback.digit(person, text)
        if res is not None:
            _tap(person, res, eid)
            return
    AgentRunner().run_turn(person.household_id, person.person_id, {"event_id": eid, "text": text, "voice": voice})


def _reply_delay(hid: str, pid: str) -> float | None:
    outs = [x for x in store.query_prefix(hid, "MSG#") if x.get("person_id") == pid and x.get("direction") == "out"]
    if not outs:
        return None
    last = max(outs, key=lambda x: x["at"])
    return (clock.now() - clock.parse(last["at"])).total_seconds()


def on_transcribe_event(event: dict) -> None:
    detail = event.get("detail", {})
    job = detail.get("TranscriptionJobName", "")
    tjob = store.get_tjob(job)
    if not tjob:
        return
    eid = f"transcribe#{event.get('id', job)}"
    if not dedupe.claim(eid):
        return
    try:
        hid, pid = tjob["household_id"], tjob["person_id"]
        log.set_context(household_id=hid, correlation_id=eid)
        person = store.get_person(hid, pid)
        if detail.get("TranscriptionJobStatus") != "COMPLETED":
            log.get().error("transcription failed", extra={"household_id": hid})
            router.send(person, Content(phrase="not_heard", voice=True), correlation_id=f"{eid}#nh")
            dedupe.done(eid)
            return
        data = transcribe.read_transcript(job)
        text = transcribe.text_of(data)
        simulated = config.mode("transcribe") == "sim"
        store.trace(hid, "transcript", person_id=pid, text=text[:200], simulated=simulated)
        if not consent.handle(person, "whatsapp", text, correlation_id=f"{eid}#consent", simulated=simulated):
            if person.is_elder and keywords.fall_or_help(text):
                escalation.escalate(hid, "fall_or_help", text[:200])
            if person.is_elder:
                sig = signals.extract(data, _reply_delay(hid, pid))
                h = store.get_household(hid)
                signals.store_signal(hid, pid, tjob["wamid"][-16:], clock.local_date(h.timezone), sig)
            AgentRunner().run_turn(hid, pid, {"event_id": eid, "text": text, "voice": True})
        dedupe.done(eid)
    except Exception:
        dedupe.release(eid)
        raise

