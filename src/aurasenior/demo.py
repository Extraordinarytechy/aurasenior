"""Offline replay of the sample household on simulators, and the sim-inbound command.

python -m aurasenior.demo replay
    Runs fully offline (in-memory AWS mocks, local channel simulators, scripted model) and prints the trace.
python -m aurasenior.demo sim-inbound <household_id> <person_id> "<text>"
    Publishes a two-way SMS shaped message for a simulator record to aurasenior-sms-rcs-events.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DATA = Path(__file__).resolve().parent / "demo_data"
SAMPLE = Path(__file__).resolve().parent.parent.parent / "households" / "sample.toml"
ELDER = "+910000000001"
NEIGHBOUR = "+910000000002"
SON = "+12025550101"


def _sns(topic: str, message: dict) -> dict:
    return {"Records": [{"EventSource": "aws:sns", "Sns": {"TopicArn": f"arn:aws:sns:us-east-1:000000000000:{topic}",
                                                            "Message": json.dumps(message, ensure_ascii=False)}}]}


def _wa(sender: str, wamid: str, **message) -> dict:
    m = {"from": sender.lstrip("+"), "id": wamid, **message}
    entry = {"id": "100000000000001", "changes": [{"field": "messages", "value": {"messaging_product": "whatsapp",
                                                                                 "messages": [m]}}]}
    return _sns("aurasenior-whatsapp-events", {"whatsAppWebhookEntry": json.dumps(entry, ensure_ascii=False)})


def _two_way(sender: str, msg_id: str, body: str, postback: str | None = None) -> dict:
    # RCS replies arrive in the two-way SMS shape; the channel marker is how the replay tells them apart.
    m = {"originationNumber": sender, "destinationNumber": "+12025550199", "messageBody": body,
         "inboundMessageId": msg_id, "channel": "RCS"}
    if postback:
        m["postbackData"] = postback
    return _sns("aurasenior-sms-rcs-events", m)


class Replay:
    def __init__(self, sample_file: Path = SAMPLE):
        from . import aws, channels, schedules, transcribe
        from .sim.converse import ScriptedConverse

        self.sample_file = sample_file
        self.turns = json.loads((DATA / "scripted_turns.json").read_text(encoding="utf-8"))
        self.model = ScriptedConverse([])
        aws.reset()
        channels.reset()
        schedules.reset_sim()
        transcribe.reset_sim()
        aws.override("bedrock-runtime", self.model)
        self.n = 0
        self.steps: list[str] = []

    def step(self, title: str) -> None:
        from . import store

        self.steps.append(title)
        store.trace(self.hid, "story", outcome=title, simulated=True)

    def wa_text(self, sender: str, text: str) -> None:
        from .handlers import inbound

        self.n += 1
        inbound.handler(_wa(sender, f"wamid.DEMO{self.n:03d}", type="text", text={"body": text}))

    def wa_button(self, sender: str, label: str, context_id: str) -> None:
        from .handlers import inbound

        self.n += 1
        inbound.handler(_wa(sender, f"wamid.DEMO{self.n:03d}", type="button", button={"payload": label, "text": label},
                            context={"id": context_id}))

    def voice(self, sender: str, transcript_file: str, scripted: str | None) -> None:
        from . import aws, transcribe
        from .handlers import inbound

        self.n += 1
        wamid = f"wamid.DEMOVOICE{self.n:03d}=="
        inbound.handler(_wa(sender, wamid, type="audio",
                            audio={"id": f"media{self.n}", "mime_type": "audio/ogg; codecs=opus", "file_size": 24000}))
        job = transcribe.job_name(self.hid, wamid)
        data = json.loads((DATA / transcript_file).read_text(encoding="utf-8"))
        aws.client("s3").put_object(Bucket=os.environ["MEDIA_BUCKET"], Key=f"transcripts/{job}.json",
                                    Body=json.dumps(data, ensure_ascii=False).encode())
        if scripted:
            self.model.add(self.turns[scripted])
        inbound.handler({"id": f"evb-{self.n}", "source": "aws.transcribe", "detail-type": "Transcribe Job State Change",
                         "detail": {"TranscriptionJobName": job, "TranscriptionJobStatus": "COMPLETED"}})

    def rcs(self, body: str, postback: str | None = None, scripted: str | None = None) -> None:
        from .handlers import inbound

        self.n += 1
        if scripted:
            self.model.add(self.turns[scripted])
        inbound.handler(_two_way(SON, f"in-demo-{self.n:03d}", body, postback))

    def advance(self, minutes: float) -> None:
        from . import clock

        self.advance_to(clock.now() + timedelta(minutes=minutes))

    def at(self, day: int, hh: int, mm: int) -> None:
        """Move to a household-local time in October 2026, firing due schedules on the way."""
        self.advance_to(datetime(2026, 10, day, hh, mm, tzinfo=ZoneInfo("Asia/Kolkata")))

    def advance_to(self, target: datetime) -> None:
        """Move the clock and fire one-time schedules that came due, like EventBridge Scheduler would."""
        from . import clock, schedules
        from .handlers import scheduled

        while True:
            due = [d for d in schedules.client().due(target)]
            if not due:
                break
            d = due[0]
            if d["when"] > clock.now():
                clock.freeze(d["when"])
            schedules.client().pop(d["name"])
            scheduled.handler(d["payload"])
        clock.freeze(target)

    def run(self) -> dict:
        from . import admin, clock, consent, seed, store
        from .handlers import scheduled

        clock.freeze(datetime(2026, 10, 11, 4, 0, tzinfo=timezone.utc))  # Sunday 09:30 in Asia/Kolkata
        store.create_table()
        from . import aws

        aws.client("s3").create_bucket(Bucket=os.environ["MEDIA_BUCKET"])
        h = seed.seed(seed.load_file(self.sample_file))
        self.hid = h.household_id
        # Labelled simulated history: knee pain mentioned on 6 and 9 October, so the Monday note makes three.
        seed.write_simulated_baseline(h, pain_notes=(5, 8))
        self.step("Day 0: opt-in. The elder and the neighbour send START, then YES on WhatsApp")
        self.wa_text(ELDER, "START")
        self.wa_text(ELDER, "हाँ")
        self.wa_text(NEIGHBOUR, "START")
        self.wa_text(NEIGHBOUR, "हाँ")
        self.step("Admin asks the son on RCS (test device check is simulated), son replies YES")
        consent._ask(store.get_person(self.hid, "rohan"), "rcs", None, "rcsask#demo", rcs_verified=True)
        self.rcs("YES")
        self.step("Admin records email consent for son, doctor and pharmacy")
        for pid in ("rohan", "doctor", "pharmacy"):
            admin.cmd_consent(self.hid, pid, "email", "opted_in", "phone call (sample)")

        self.at(12, 9, 0)  # Monday 09:00, the WhatsApp window has closed
        self.step("Day 1, 09:00: scheduled check-in template with a Listen button")
        scheduled.handler({"kind": "checkin", "household_id": self.hid})
        tmpl = [m for m in store.query_prefix(self.hid, "MSG#") if (m.get("ref") or {}).get("kind") == "listen"][-1]
        self.advance(4)
        self.step("Elder taps Listen: check-in voice note, no model call")
        self.wa_button(ELDER, "सुनें", tmpl["SK"][4:])
        self.advance(10)
        self.step("Elder replies by voice in Hindi: sugar tablet taken, BP tablets finished, knee hurts "
                  "(third pain mention this week, so the son gets a worth-a-call note)")
        self.voice(ELDER, "hindi_reply.json", "hindi_reply")
        self.advance(3)
        self.step("Elder sends a second voice note in English")
        self.voice(ELDER, "english_reply.json", "english_reply")
        approval = [a for a in store.approvals(self.hid) if a.status == "pending"][0]
        self.advance(12)
        self.step("Son taps Order refill on the RCS card: pharmacy email and confirmation voice note, no model call")
        self.rcs("Order refill", postback=f"refill:approve:{approval.approval_id}")

        self.at(13, 9, 0)  # Tuesday 09:00
        self.step("Day 2, 09:00: check-in, no reply, follow-up at 10:30, missed check-in alert at 11:30")
        scheduled.handler({"kind": "checkin", "household_id": self.hid})
        self.at(13, 11, 42)
        self.step("Elder says she slipped near the chair: late reply closes the missed check-in, fall alert at once")
        self.voice(ELDER, "fall_note.json", "fall_note")
        esc = [e for e in store.escalations(self.hid) if e.reason == "fall_or_help"][0]
        self.advance(7)
        self.step("Son taps I'm on it: elder hears who is coming, neighbour is told, rechecks stop")
        self.rcs("I'm on it", postback=f"esc:ack:{esc.escalation_id}")

        self.advance(60)
        self.step("Son asks over RCS: How was Mom this week?")
        self.rcs("How was Mom this week?", scripted="how_was_mom")

        self.at(18, 18, 0)  # Sunday 18:00
        self.step("Sunday 18:00: weekly summary email to every recipient with email consent")
        scheduled.handler({"kind": "weekly_summary", "household_id": self.hid})
        self.advance(30)
        self.step("Elder sends STOP")
        self.wa_text(ELDER, "STOP")
        return {"household_id": self.hid, "model_calls": len(self.model.calls), "steps": self.steps,
                "unused_scripted": len(self.model.responses)}


def replay(print_trace: bool = True) -> dict:
    os.environ.setdefault("TABLE_NAME", "aurasenior-household")
    os.environ.setdefault("MEDIA_BUCKET", "aurasenior-media-demo")
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        os.environ.setdefault(k, "demo")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    from moto import mock_aws

    from . import store, trace

    with mock_aws():
        result = Replay().run()
        items = store.traces(result["household_id"])
        result["trace"] = trace.format_trace(items)
        result["items"] = items
        if print_trace:
            print("Sample household replay. Channels, AWS services and the model are simulated or scripted.")
            print(result["trace"])
    return result


def sim_inbound(hid: str, pid: str, text: str) -> int:
    from . import aws, config, store

    p = store.get_person(hid, pid)
    number = (p.addresses.get("sms") or p.addresses.get("rcs")) if p else None
    if not p or number not in config.simulator_destinations():
        print("sim-inbound only works for simulator records", file=sys.stderr)
        return 1
    topic = os.environ.get("SMS_RCS_TOPIC_ARN", "")
    if not topic:
        print("set SMS_RCS_TOPIC_ARN to the aurasenior-sms-rcs-events topic ARN", file=sys.stderr)
        return 1
    msg = {"originationNumber": number, "destinationNumber": "simulator", "messageBody": text,
           "inboundMessageId": f"sim-{store.new_id()}", "simulated": True}
    aws.client("sns").publish(TopicArn=topic, Message=json.dumps(msg))
    print("published simulated inbound message")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["replay"]:
        replay()
        return 0
    if argv[:1] == ["sim-inbound"] and len(argv) == 4:
        return sim_inbound(argv[1], argv[2], argv[3])
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
