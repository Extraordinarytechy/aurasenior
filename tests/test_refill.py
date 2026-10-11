import pytest

from aurasenior import aws, refill, schedules, sim, store


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
