from aurasenior import clock, store
from aurasenior.models import Household, Medicine, Person


def _hh():
    return Household("hh1", "Sample", "Asia/Kolkata", "09:00", "p1", "p2", ["p2", "p3"])


def _elder():
    return Person("hh1", "p1", "elder", "Kamala", "IN", "hi-IN", "whatsapp", "none",
                  addresses={"whatsapp": "+910000000001"})


def test_profile_person_and_medicine_round_trip(table):
    store.put_household(_hh())
    store.put_person(_elder())
    store.put_medicine(Medicine("hh1", "m1", "Amlodipine", "BP tablets", "morning", "ok", "p5"))
    assert store.get_household("hh1").escalation_order == ["p2", "p3"]
    p = store.get_person("hh1", "p1")
    assert p.language == "hi-IN" and p.consent_status("whatsapp") == "pending"
    assert store.medicines("hh1")[0].display_label == "BP tablets"
    assert store.elder("hh1").person_id == "p1"


def test_address_lookup_and_consent(table, frozen):
    store.put_person(_elder())
    store.put_addr("whatsapp", "+910000000001", "hh1", "p1")
    assert store.lookup_addr("whatsapp", "+910000000001") == ("hh1", "p1")
    assert store.lookup_addr("whatsapp", "+919999999999") is None
    store.set_consent("hh1", "p1", "whatsapp", "opted_in", "wa_inbound_yes")
    assert store.get_person("hh1", "p1").consent["whatsapp"]["source"] == "wa_inbound_yes"


def test_ttl_values_per_type(table, frozen):
    now = clock.epoch()
    assert store.ttl("TRACE") - now == 30 * 86400
    assert store.ttl("LOG") - now == 90 * 86400
    assert store.ttl("TURN") - now == 7 * 86400
    assert store.ttl("DEDUP") - now == 7 * 86400


def test_medicine_stock_lifecycle(table, frozen):
    store.put_medicine(Medicine("hh1", "m1", "Amlodipine", "BP tablets", "morning", "ok", "p5"))
    store.log_medicine("hh1", "m1", "2026-10-12", taken=False, out_of_stock=True)
    assert store.get_medicine("hh1", "m1").stock == "out"
    store.set_stock("hh1", "m1", "ordered")
    store.log_medicine("hh1", "m1", "2026-10-13", taken=True)
    assert store.get_medicine("hh1", "m1").stock == "ok"
    assert len(store.logs_between("hh1", "2026-10-12", "2026-10-13")) == 2


def test_turns_keep_last_ten_in_order(table, frozen):
    for i in range(12):
        store.put_turn("hh1", "p1", "user", f"t{i}")
        clock.advance(1)
    turns = store.last_turns("hh1", "p1")
    assert [t["text"] for t in turns] == [f"t{i}" for i in range(2, 12)]


def test_usage_counter_is_atomic_and_flag_sets_once(table, frozen):
    assert [store.incr_converse("hh1", "2026-10-12") for _ in range(3)] == [1, 2, 3]
    assert store.set_usage_flag("hh1", "2026-10-12", "agent_unavailable_sent") is True
    assert store.set_usage_flag("hh1", "2026-10-12", "agent_unavailable_sent") is False
    assert store.incr_normal("hh1", "2026-10-12", "09") == 1


def test_trace_masks_numbers_and_emails(table, frozen):
    store.trace("hh1", "send", to="+12025550101", note="mail someone@example.com", simulated=True)
    t = store.traces("hh1")[0]
    assert t["to"].endswith("0101") and "2025550" not in t["to"]
    assert "someone@" not in t["note"]
    assert t["simulated"] is True


def test_msg_status_append(table, frozen):
    store.put_msg("hh1", "wamid.1", channel="whatsapp", person_id="p1", correlation_id="c1", ref={"kind": "listen"})
    assert store.append_status("hh1", "wamid.1", "delivered")
    assert store.get_msg("hh1", "wamid.1")["last_status"] == "delivered"
    assert not store.append_status("hh1", "unknown", "delivered")
