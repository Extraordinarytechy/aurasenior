import pytest

from aurasenior import consent, sim, store
from conftest import open_window


def _pending(hid, pid, ch):
    store.set_consent(hid, pid, ch, "pending", "test")
    return store.get_person(hid, pid)


def test_start_then_yes_opts_in(sample):
    p = _pending(sample, "kamala", "whatsapp")
    open_window(sample, "kamala")
    p = store.get_person(sample, "kamala")
    assert consent.handle(p, "whatsapp", "START", correlation_id="c1")
    assert sim.read("whatsapp")[-1]["phrase_key"] == "optin_ask"
    assert consent.handle(store.get_person(sample, "kamala"), "whatsapp", "हाँ", correlation_id="c2")
    rec = store.get_person(sample, "kamala").consent["whatsapp"]
    assert rec["status"] == "opted_in" and rec["source"] == "wa_inbound_yes"


def test_no_template_to_person_not_opted_in(sample):
    p = _pending(sample, "kamala", "whatsapp")
    assert consent.handle(p, "whatsapp", "hello", correlation_id="c3")
    assert not any(x.get("kind") == "template" for x in sim.read("whatsapp"))


def test_stop_and_confirm_once(sample):
    open_window(sample, "kamala")
    p = store.get_person(sample, "kamala")
    assert consent.handle(p, "whatsapp", "बंद", correlation_id="c4")
    assert store.get_person(sample, "kamala").consent_status("whatsapp") == "opted_out"
    assert [x["phrase_key"] for x in sim.read("whatsapp")] == ["stop_confirm"]


def test_rcs_yes_and_stop(sample):
    p = _pending(sample, "rohan", "rcs")
    assert consent.handle(p, "rcs", "YES", correlation_id="c5")
    assert store.get_person(sample, "rohan").consent["rcs"]["source"] == "rcs_inbound_yes"
    assert consent.handle(store.get_person(sample, "rohan"), "rcs", "STOP", correlation_id="c6")
    assert store.get_person(sample, "rohan").consent_status("rcs") == "opted_out"


def test_sms_yes_records_the_sms_source(sample):
    p = _pending(sample, "rohan", "sms")
    assert consent.handle(p, "sms", "YES", correlation_id="c9")
    assert store.get_person(sample, "rohan").consent["sms"]["source"] == "sms_inbound_yes"


def test_simulator_record_consent_is_simulated(sample):
    p = _pending(sample, "simfam", "sms")
    consent.handle(p, "sms", "YES", correlation_id="c7", simulated=True)
    rec = store.get_person(sample, "simfam").consent["sms"]
    assert rec["source"] == "sms_sim_inbound_yes" and rec["simulated"] is True


class NoModel:
    def converse(self, **kw):
        raise AssertionError("a repeated YES or START must not start a model turn")


@pytest.mark.parametrize("pid,channel,text,expected", [
    ("rohan", "rcs", "YES", "You already get updates about Mom from AuraSenior. Send STOP to stop."),
    ("rohan", "rcs", "START", "You already get updates about Mom from AuraSenior. Send STOP to stop."),
    ("kamala", "whatsapp", "हाँ", "ठीक है, धन्यवाद।"),
])
def test_repeated_yes_from_an_opted_in_sender_is_acknowledged_without_a_turn(sample, pid, channel, text,
                                                                             expected):
    from aurasenior import aws
    from aurasenior.handlers import inbound

    store.set_consent(sample, pid, channel, "opted_in", "test")
    if channel == "whatsapp":
        open_window(sample, pid)
    aws.override("bedrock-runtime", NoModel())
    approvals, logs = store.approvals(sample), store.logs_between(sample, "2026-01-01", "2026-12-31")
    inbound.handle_text(store.get_person(sample, pid), channel, text, "ev#yes", voice=False)
    sent = [x for x in sim.read(channel) if x["person_id"] == pid]
    assert [x["phrase_key"] for x in sent] == ["consent_ack"] and sent[0]["text"] == expected
    assert store.get_person(sample, pid).consent_status(channel) == "opted_in"
    assert store.approvals(sample) == approvals
    assert store.logs_between(sample, "2026-01-01", "2026-12-31") == logs
    assert not any(t["step"] in ("converse", "tool") for t in store.traces(sample))


def test_opted_in_text_is_not_consent(sample):
    assert not consent.handle(store.get_person(sample, "rohan"), "rcs", "How was Mom this week?", correlation_id="c8")
