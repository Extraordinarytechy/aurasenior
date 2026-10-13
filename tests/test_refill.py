import pytest

from aurasenior import aws, channels, refill, schedules, sim, store
from aurasenior.channels.base import SendResult
from aurasenior.router import RetryableSendError


class NoModel:
    def converse(self, **kw):
        raise AssertionError("the pharmacy order path must not call the model")


@pytest.fixture
def approval(sample):
    aws.override("bedrock-runtime", NoModel())
    r = refill.request_refill_approval(sample, "bp", "rohan", correlation_id="ev#1")
    return r["approval_id"]


def test_request_sends_card_and_creates_expiry(sample, approval):
    card = sim.read("rcs")[-1]
    assert card["kind"] == "card" and card["card"]["suggestions"][0][1] == f"refill:approve:{approval}"
    assert schedules.name_approval_expiry(approval) in schedules.client().names()


def test_second_request_for_a_pending_medicine_sends_nothing(sample, approval):
    sends, expiries = len(sim.read("rcs")), len(schedules.client().names())
    again = refill.request_refill_approval(sample, "bp", "rohan", correlation_id="ev2#1")
    assert again["approval_id"] == approval and again["note"] == "already asked"
    assert len(sim.read("rcs")) == sends and len(schedules.client().names()) == expiries
    assert len([a for a in store.approvals(sample) if a.medicine_id == "bp"]) == 1


def test_request_after_a_recent_approval_returns_it(sample, approval):
    refill.handle_action(sample, "rohan", "refill:approve", approval, correlation_id="t1")
    sends = len(sim.read("rcs"))
    again = refill.request_refill_approval(sample, "bp", "rohan", correlation_id="ev2#1")
    assert again["approval_id"] == approval and again["approval_status"] == "ordered"
    assert len(sim.read("rcs")) == sends and len(store.approvals(sample)) == 1


def test_request_after_family_said_they_will_handle_it_sends_nothing(sample, approval, frozen):
    refill.handle_action(sample, "rohan", "refill:self", approval, correlation_id="t1")
    sends, expiries = len(sim.read("rcs")), len(schedules.client().names())
    frozen.advance(3 * 60)
    again = refill.request_refill_approval(sample, "bp", "rohan", correlation_id="ev2#1")
    assert again["approval_id"] == approval and again["approval_status"] == "self" and again["asked"] is True
    assert len(sim.read("rcs")) == sends and len(schedules.client().names()) == expiries
    assert len(store.approvals(sample)) == 1


def test_request_a_day_after_an_order_asks_again(sample, approval, frozen):
    refill.handle_action(sample, "rohan", "refill:approve", approval, correlation_id="t1")
    frozen.advance(25 * 60)
    again = refill.request_refill_approval(sample, "bp", "rohan", correlation_id="ev2#1")
    assert again["approval_id"] != approval and len(store.approvals(sample)) == 2


def test_double_tap_gives_one_order(sample, approval):
    assert refill.handle_action(sample, "rohan", "refill:approve", approval, correlation_id="t1") == "ordered"
    assert refill.handle_action(sample, "rohan", "refill:approve", approval, correlation_id="t2") == "already_handled"
    orders = [x for x in sim.read("email") if x.get("template") == "aurasenior-refill-order"]
    assert len(orders) == 1 and orders[0]["template_data"]["medicine_name"] == "Amlodipine 5"
    assert store.get_medicine(sample, "bp").stock == "ordered"
    assert store.get_approval(sample, approval).status == "ordered"
    assert schedules.name_approval_expiry(approval) not in schedules.client().names()


def test_order_confirmations_go_to_elder_and_family(sample, approval):
    refill.handle_action(sample, "rohan", "refill:approve", approval, correlation_id="t1")
    elder = [x for x in sim.read("whatsapp") if x["person_id"] == "kamala"][-1]
    assert elder["template"] == "aurasenior_refill_update_hi"
    assert "Order sent to City Pharmacy" in sim.read("rcs")[-1]["text"]


def test_missing_pharmacy_consent_gives_order_failed(sample, approval, capsys):
    store.set_consent(sample, "pharmacy", "email", "pending", "test")
    assert refill.handle_action(sample, "rohan", "refill:approve", approval, correlation_id="t1") == "order_failed"
    assert sim.read("rcs")[-1]["text"] == "The order email could not be sent. Please call the pharmacy."
    assert store.get_approval(sample, approval).status == "approved"
    assert '"ERROR"' in capsys.readouterr().out


def test_retried_approve_tap_sends_the_order_once(sample, approval, monkeypatch):
    email = channels.get("email")
    real = email.send
    state = {"n": 0}

    def flaky(msg):
        state["n"] += 1
        if state["n"] == 1:
            return SendResult.failed("TooManyRequestsException", True, simulated=True)
        return real(msg)

    monkeypatch.setattr(email, "send", flaky)
    with pytest.raises(RetryableSendError):
        refill.handle_action(sample, "rohan", "refill:approve", approval, correlation_id="t1")
    assert store.get_approval(sample, approval).status == "approved"
    assert refill.handle_action(sample, "rohan", "refill:approve", approval, correlation_id="t1") == "ordered"
    assert refill.handle_action(sample, "rohan", "refill:approve", approval, correlation_id="t1") == "ordered"
    assert len([x for x in sim.read("email") if x.get("template") == "aurasenior-refill-order"]) == 1
    assert len([x for x in sim.read("whatsapp") if x["person_id"] == "kamala"]) == 1
    assert store.get_approval(sample, approval).status == "ordered"


def test_retry_after_a_failed_order_email_does_not_claim_the_order(sample, approval, monkeypatch):
    email = channels.get("email")
    monkeypatch.setattr(email, "send", lambda msg: SendResult.failed("MessageRejected", False, simulated=True))
    rcs = channels.get("rcs")
    real = rcs.send
    state = {"done": False}

    def throttled_once(msg):
        if not state["done"]:
            state["done"] = True
            return SendResult.failed("ThrottlingException", True, simulated=True)
        return real(msg)

    monkeypatch.setattr(rcs, "send", throttled_once)
    with pytest.raises(RetryableSendError):
        refill.handle_action(sample, "rohan", "refill:approve", approval, correlation_id="t1")
    assert refill.handle_action(sample, "rohan", "refill:approve", approval, correlation_id="t1") == "order_failed"
    assert store.get_approval(sample, approval).status == "approved"
    assert store.get_medicine(sample, "bp").stock != "ordered"
    assert [x for x in sim.read("whatsapp") if x["person_id"] == "kamala"] == []
    assert sim.read("rcs")[-1]["text"] == "The order email could not be sent. Please call the pharmacy."


def test_wrong_person_tap_is_ignored(sample, approval):
    assert refill.handle_action(sample, "nbr", "refill:approve", approval, correlation_id="t1") == "ignored"


def test_expiry_sends_once_and_ignores_handled(sample, approval):
    refill.expiry_run(sample, approval)
    refill.expiry_run(sample, approval)
    assert len([x for x in sim.read("rcs") if "has closed" in x.get("text", "")]) == 1
    r2 = refill.request_refill_approval(sample, "sugar", "rohan", correlation_id="ev#2")["approval_id"]
    refill.handle_action(sample, "rohan", "refill:self", r2, correlation_id="t3")
    refill.expiry_run(sample, r2)
    assert store.get_approval(sample, r2).status == "self"


def test_call_sends_the_elder_number(sample, approval):
    refill.handle_action(sample, "rohan", "refill:call", approval, correlation_id="t9")
    assert sim.read("rcs")[-1]["text"] == "Mom's WhatsApp number is +910000000001."
