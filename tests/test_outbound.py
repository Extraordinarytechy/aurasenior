from aurasenior import clock, outbound, store
from aurasenior.channels.base import OutboundMessage
from conftest import open_window


def _msg(**kw):
    base = dict(person_id="kamala", to="+910000000001", kind="voice", text="Good morning", language="hi-IN")
    base.update(kw)
    return OutboundMessage(**base)


def test_window_boundary(sample):
    open_window(sample, "kamala")
    clock.advance(23 * 60 + 29)
    p = store.get_person(sample, "kamala")
    assert outbound.guard(p, "whatsapp", _msg()).ok
    clock.advance(2)
    p = store.get_person(sample, "kamala")
    assert outbound.guard(p, "whatsapp", _msg()).reason == "blocked_window"


def test_template_passes_outside_window(sample):
    p = store.get_person(sample, "kamala")
    assert outbound.guard(p, "whatsapp", _msg(kind="template", template="aurasenior_checkin_hi")).ok


def test_optin_ask_once_per_day_for_pending_person(sample):
    store.set_consent(sample, "kamala", "whatsapp", "pending", "test")
    open_window(sample, "kamala")
    p = store.get_person(sample, "kamala")
    m = _msg(phrase_key="optin_ask")
    assert outbound.guard(p, "whatsapp", m, inbound_text="START").exemption == "optin_ask"
    assert outbound.guard(p, "whatsapp", m, inbound_text="START").reason == "blocked_consent"


def test_checkin_voice_to_pending_person_is_blocked(sample):
    store.set_consent(sample, "kamala", "whatsapp", "pending", "test")
    open_window(sample, "kamala")
    p = store.get_person(sample, "kamala")
    assert outbound.guard(p, "whatsapp", _msg(phrase_key="checkin_voice"), inbound_text="hi").reason == "blocked_consent"


def test_stop_confirm_passes_once(sample):
    store.set_consent(sample, "kamala", "whatsapp", "opted_out", "wa_inbound_stop")
    open_window(sample, "kamala")
    p = store.get_person(sample, "kamala")
    m = _msg(phrase_key="stop_confirm")
    assert outbound.guard(p, "whatsapp", m, inbound_text="STOP").ok
    assert not outbound.guard(p, "whatsapp", m, inbound_text="STOP").ok


def test_wording_replacement_for_elder_and_family(sample):
    open_window(sample, "kamala")
    p = store.get_person(sample, "kamala")
    g = outbound.guard(p, "whatsapp", _msg(text="This looks like diabetes"), names={"family_name": "Rohan"})
    assert g.replaced == "disease" and "Rohan" in g.message.text and "diabetes" not in g.message.text
    r = store.get_person(sample, "rohan")
    g = outbound.guard(r, "rcs", _msg(person_id="rohan", kind="text", text="Her dementia", language="en-US"),
                       names={"elder_name": "Kamala"})
    assert g.message.text == "Please call Kamala."


def test_urgent_quote_is_withheld_but_template_stays(sample):
    p = store.get_person(sample, "nbr")
    m = _msg(person_id="nbr", kind="template", template="aurasenior_urgent_alert_hi", urgency="urgent",
             template_params=["Kamala ji", "my diabetes is bad"], template_data={"quote": "my diabetes is bad"},
             phrase_key="urgent_alert")
    g = outbound.guard(p, "whatsapp", m)
    assert g.ok and g.message.template == "aurasenior_urgent_alert_hi"
    assert g.message.template_params[1] == "मदद के शब्द"


def test_rate_cap_stops_normal_sends_but_not_urgent(sample):
    p = store.get_person(sample, "rohan")
    m = _msg(person_id="rohan", kind="text", text="update", language="en-US")
    results = [outbound.guard(p, "rcs", m).ok for _ in range(31)]
    assert results[:30] == [True] * 30 and results[30] is False
    urgent = _msg(person_id="rohan", kind="text", text="URGENT", language="en-US", urgency="urgent")
    assert all(outbound.guard(p, "rcs", urgent).ok for _ in range(5))
