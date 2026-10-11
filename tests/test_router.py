from aurasenior import clock, router, schedules, sim, store
from aurasenior.router import Content
from conftest import open_window


def _checkin():
    return Content(phrase="checkin_voice", vars={"display_label": "BP tablets"}, voice=True,
                   wa_template="aurasenior_checkin", wa_params=["Kamala"], ref={"kind": "listen", "id": "checkin"})


def test_simulator_receipt_marks_delivered_and_skips_fallback(sample):
    p = store.get_person(sample, "rohan")
    c = Content(phrase="urgent_alert", quote="I fell", vars={"relation_label": "Mom"}, sms_phrase="urgent_sms")
    r = router.send(p, c, urgency="urgent", correlation_id="e9#1")
    assert store.get_msg(sample, r.provider_id)["last_status"] == "delivered"
    router.delivery_check_run(sample, "e9#1")
    assert sim.read("sms") == []


def test_elder_window_closed_gets_template(sample):
    r = router.send(store.get_person(sample, "kamala"), _checkin(), correlation_id="e1#1")
    assert r.outcome == "sent" and r.simulated
    line = sim.read("whatsapp")[-1]
    assert line["kind"] == "template" and line["template"] == "aurasenior_checkin_hi"
    assert store.get_msg(sample, r.provider_id)["ref"] == {"kind": "listen", "id": "checkin"}


def test_elder_window_open_gets_voice_note(sample):
    open_window(sample, "kamala")
    router.send(store.get_person(sample, "kamala"), _checkin(), correlation_id="e2#1")
    line = sim.read("whatsapp")[-1]
    assert line["kind"] == "voice" and "BP tablets" in line["text"]


def test_free_text_outside_window_without_template_is_blocked(sample):
    r = router.send(store.get_person(sample, "kamala"), Content(text="hello"), correlation_id="e3#1")
    assert r.outcome == "blocked_window"
    assert sim.read("whatsapp") == []


def test_family_us_gets_rcs_card_with_sms_fallback_body(sample):
    c = Content(phrase="refill_approval_title", vars={"relation_label": "Mom", "display_label": "BP tablets"},
                rcs_card={"title": "refill_approval_title", "description": "refill_approval_desc",
                          "suggestions": [["label_order_refill", "refill:approve:0123456789ab"]]},
                sms_phrase="refill_sms")
    r = router.send(store.get_person(sample, "rohan"), c, correlation_id="e4#1")
    line = sim.read("rcs")[-1]
    assert r.channel == "rcs" and line["kind"] == "card"
    assert line["card"]["suggestions"][0] == ["Order refill", "refill:approve:0123456789ab"]
    assert "Reply 1" in line["sms_fallback"]


def test_neighbour_falls_back_to_email_when_whatsapp_blocked(sample):
    c = Content(phrase="checkin_late_family", vars={"relation_label": "Kamala ji"},
                email_template="aurasenior-update", email_data={"update_text": "replied"})
    r = router.send(store.get_person(sample, "nbr"), c, correlation_id="e5#1")
    assert r.outcome == "sent" and r.channel == "email"


def test_consent_block_without_fallback_consent_sends_nothing(sample):
    store.set_consent(sample, "nbr", "whatsapp", "pending", "test")
    store.set_consent(sample, "nbr", "email", "pending", "test")
    c = Content(phrase="checkin_late_family", vars={"relation_label": "Kamala ji"}, email_template="aurasenior-update")
    r = router.send(store.get_person(sample, "nbr"), c, correlation_id="e6#1")
    assert r.outcome == "blocked_consent"
    assert sim.read("whatsapp") == [] and sim.read("email") == []


def test_retried_send_goes_out_once(sample):
    p = store.get_person(sample, "rohan")
    c = Content(phrase="esc_ack_family", vars={"ack_name": "Sunita"})
    assert router.send(p, c, correlation_id="e7#1").outcome == "sent"
    assert router.send(p, c, correlation_id="e7#1").outcome == "skipped"
    assert len(sim.read("rcs")) == 1


def test_urgent_send_gets_delivery_check_and_falls_back(sample, monkeypatch):
    from aurasenior import channels

    monkeypatch.setattr(channels.get("rcs"), "deliver", False)  # the phone never gets the RCS message
    p = store.get_person(sample, "rohan")
    c = Content(phrase="urgent_alert", quote="I fell", vars={"relation_label": "Mom"}, sms_phrase="urgent_sms")
    r = router.send(p, c, urgency="urgent", correlation_id="e8#1")
    assert schedules.name_delivery_check("e8#1") in schedules.client().names()
    clock.advance(3)
    router.delivery_check_run(sample, "e8#1")
    assert r.outcome == "sent" and sim.read("sms")[-1]["text"].startswith("URGENT")


def test_failed_status_triggers_fallback(sample):
    p = store.get_person(sample, "rohan")
    r = router.send(p, Content(phrase="esc_ack_family", vars={"ack_name": "Sunita"}), correlation_id="e9#1")
    router.on_status(sample, r.provider_id, "failed")
    assert len(sim.read("sms")) == 1


def test_fallback_none_is_undeliverable(sample):
    p = store.get_person(sample, "kamala")
    r = router.send(p, Content(text="hi"), correlation_id="e10#1")
    assert r.outcome == "blocked_window"
    assert any(t["step"] == "route" for t in store.traces(sample))
