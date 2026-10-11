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


def test_simulator_record_consent_is_simulated(sample):
    p = _pending(sample, "simfam", "sms")
    consent.handle(p, "sms", "YES", correlation_id="c7", simulated=True)
    rec = store.get_person(sample, "simfam").consent["sms"]
    assert rec["source"] == "sms_sim_inbound_yes" and rec["simulated"] is True


def test_opted_in_text_is_not_consent(sample):
    assert not consent.handle(store.get_person(sample, "rohan"), "rcs", "How was Mom this week?", correlation_id="c8")
