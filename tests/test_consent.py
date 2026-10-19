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


def _checkin_sent(hid):
    from aurasenior.handlers import scheduled

    open_window(hid, "kamala")
    scheduled.run_checkin(hid, {}, "2026-10-12", "checkin#t")


def test_bare_yes_after_the_check_in_logs_the_morning_tablet(sample):
    from aurasenior import aws
    from aurasenior.handlers import inbound

    _checkin_sent(sample)
    aws.override("bedrock-runtime", NoModel())
    inbound.handle_text(store.get_person(sample, "kamala"), "whatsapp", "हाँ", "ev#y1", voice=False)
    log = store.get(store.hh(sample), "LOG#2026-10-12#bp")
    assert log["taken"] is True and log["source_msg"] == "ev#y1#consent"
    assert store.get(store.hh(sample), "LOG#2026-10-12#sugar") is None
    reply = sim.read("whatsapp")[-1]
    assert reply["phrase_key"] == "checkin_yes_logged" and reply["kind"] != "voice"
    label = store.get_medicine(sample, "bp").display_label
    assert reply["text"] == f"ठीक है, मैंने लिख लिया कि आपने {label} ले ली। अगर ऐसा नहीं है, तो बता दीजिए।"
    assert [t["outcome"] for t in store.traces(sample) if t["step"] == "consent"][-1] == "checkin_yes"


def test_logged_yes_phrase_in_english_says_back_the_tablet():
    from aurasenior import phrases

    assert phrases.render("checkin_yes_logged", "en-US", "elder", display_label="BP tablets") == (
        "Okay, I have noted that you took your BP tablets. If that is not right, just tell me.")


def test_no_after_the_logged_yes_corrects_the_log_through_a_turn(sample):
    from aurasenior import aws
    from aurasenior.handlers import inbound
    from aurasenior.sim.converse import ScriptedConverse, end_turn, tool_use

    _checkin_sent(sample)
    aws.override("bedrock-runtime", NoModel())
    inbound.handle_text(store.get_person(sample, "kamala"), "whatsapp", "हाँ", "ev#y2", voice=False)
    assert store.get(store.hh(sample), "LOG#2026-10-12#bp")["taken"] is True
    aws.override("bedrock-runtime", ScriptedConverse([
        tool_use("log_medicine", {"medicine_id": "bp", "taken": False, "out_of_stock": False}),
        end_turn("ठीक है।")]))
    inbound.handle_text(store.get_person(sample, "kamala"), "whatsapp", "नहीं, नहीं ली", "ev#n2", voice=False)
    log = store.get(store.hh(sample), "LOG#2026-10-12#bp")
    assert log["taken"] is False and log["source_msg"] != "ev#y2#consent"
    assert any(t["step"] == "converse" for t in store.traces(sample))


def test_bare_yes_after_the_tablet_was_logged_only_acknowledges(sample):
    _checkin_sent(sample)
    store.log_medicine(sample, "bp", "2026-10-12", taken=False, out_of_stock=True)
    assert consent.handle(store.get_person(sample, "kamala"), "whatsapp", "हाँ", correlation_id="c10")
    log = store.get(store.hh(sample), "LOG#2026-10-12#bp")
    assert log["taken"] is False and log["out_of_stock"] is True


def test_bare_yes_without_a_check_in_today_logs_nothing(sample):
    open_window(sample, "kamala")
    assert consent.handle(store.get_person(sample, "kamala"), "whatsapp", "हाँ", correlation_id="c11")
    assert store.logs_between(sample, "2026-10-12", "2026-10-12") == []


def test_family_yes_after_the_check_in_logs_nothing(sample):
    _checkin_sent(sample)
    assert consent.handle(store.get_person(sample, "rohan"), "rcs", "YES", correlation_id="c12")
    assert store.logs_between(sample, "2026-10-12", "2026-10-12") == []


def test_opted_in_text_is_not_consent(sample):
    assert not consent.handle(store.get_person(sample, "rohan"), "rcs", "How was Mom this week?", correlation_id="c8")
