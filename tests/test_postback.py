from aurasenior import escalation, postback, refill, router, store
from aurasenior.channels.base import InboundMessage


def test_regex_accepts_valid_and_rejects_mixed_actions():
    assert postback.parse_postback("refill:approve:0123456789ab") == ("refill:approve", "0123456789ab")
    assert postback.parse_postback("esc:ack:0123456789ab") == ("esc:ack", "0123456789ab")
    assert postback.parse_postback("info:number") == ("info:number", None)
    for bad in ("esc:approve:0123456789ab", "refill:ack:0123456789ab", "refill:approve:XYZ", "refill:approve"):
        assert postback.parse_postback(bad) is None


def test_all_four_digits_and_no_target(sample):
    rohan = store.get_person(sample, "rohan")
    assert postback.digit(rohan, "1") == "help"
    aid = refill.request_refill_approval(sample, "bp", "rohan", correlation_id="x")["approval_id"]
    assert postback.digit(rohan, "1") == ("refill:approve", aid)
    assert postback.digit(rohan, "2") == ("refill:self", aid)
    assert postback.digit(rohan, "3") == ("info:number", None)
    assert postback.digit(rohan, "4") == "help"
    eid = escalation.escalate(sample, "missed_checkin")
    assert postback.digit(rohan, "4") == ("esc:ack", eid)
    assert postback.digit(rohan, "How was Mom this week?") is None


def test_button_with_context_resolves_through_msg_ref(sample):
    nbr = store.get_person(sample, "nbr")
    store.set_wa_inbound(sample, "nbr")
    eid = escalation.escalate(sample, "missed_checkin")
    msg = next(m for m in store.query_prefix(sample, "MSG#") if m["person_id"] == "nbr")
    tap = InboundMessage(channel="whatsapp", event_id="w1", sender="+910000000002", kind="button",
                         button_payload="मैं देख रहा हूँ", context_id=msg["SK"][4:])
    assert postback.whatsapp_button(nbr, tap) == ("esc:ack", eid)


def test_button_without_context_uses_digit_rule(sample):
    nbr = store.get_person(sample, "nbr")
    eid = escalation.escalate(sample, "missed_checkin")
    tap = InboundMessage(channel="whatsapp", event_id="w2", sender="+910000000002", kind="button",
                         button_payload="I'm on it")
    assert postback.whatsapp_button(nbr, tap) == ("esc:ack", eid)


def test_listen_button_resolves_to_listen_action(sample):
    kamala = store.get_person(sample, "kamala")
    r = router.send(kamala, router.Content(phrase="checkin_voice", vars={"display_label": "BP"}, voice=True,
                                           wa_template="aurasenior_checkin", wa_params=["Kamala"],
                                           ref={"kind": "listen", "id": "checkin"}), correlation_id="c1")
    tap = InboundMessage(channel="whatsapp", event_id="w3", sender="+910000000001", kind="button",
                         button_payload="सुनें", context_id=r.provider_id)
    assert postback.whatsapp_button(kamala, tap) == ("listen:checkin", None)
