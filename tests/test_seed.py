import copy
from pathlib import Path

import pytest

from aurasenior import schedules, seed, store

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = seed.load_file(ROOT / "households" / "sample.toml")


@pytest.mark.parametrize("name", ["sample.toml", "sample-us.toml"])
def test_sample_files_pass(name):
    seed.validate(seed.load_file(ROOT / "households" / name))


def _person(d, pid):
    return next(p for p in d["people"] if p["person_id"] == pid)


def _bad(mutate):
    d = copy.deepcopy(SAMPLE)
    mutate(d)
    with pytest.raises(seed.SeedError) as e:
        seed.validate(d)
    return str(e.value)


def test_rejections_name_the_field():
    assert "role" in _bad(lambda d: _person(d, "rohan").pop("role"))
    assert "language" in _bad(lambda d: _person(d, "rohan").update(language="fr-FR"))
    assert "preferred_channel" in _bad(lambda d: _person(d, "rohan").update(preferred_channel="fax"))
    assert "addresses.email" in _bad(lambda d: _person(d, "doctor").update(addresses={}))
    assert "E.164" in _bad(lambda d: _person(d, "kamala").update(addresses={"whatsapp": "0123"}))
    assert "US numbers" in _bad(lambda d: _person(d, "nbr")["addresses"].update(sms="+910000000002"))
    assert "timezone" in _bad(lambda d: d.update(timezone="Mars/Base"))
    assert "one elder" in _bad(lambda d: _person(d, "nbr").update(role="elder"))
    assert "admin_person_id" in _bad(lambda d: d.update(admin_person_id="doctor"))
    assert "relation_label" in _bad(lambda d: _person(d, "rohan").pop("relation_label"))
    assert "display_label" in _bad(lambda d: d["medicines"][0].update(display_label=""))
    assert "household_id" in _bad(lambda d: d.update(household_id="Bad-ID"))
    assert "person_id" in _bad(lambda d: _person(d, "rohan").update(person_id="ROHAN_1"))
    assert "wording" in _bad(lambda d: d["medicines"][0].update(display_label="diabetes tablets"))
    assert "simulated" in _bad(lambda d: _person(d, "simfam").update(simulated=False))
    assert "simulated" in _bad(lambda d: _person(d, "rohan").update(simulated=True))


def test_seed_file_cannot_set_consent():
    assert "consent" in _bad(lambda d: _person(d, "rohan").update(consent={"rcs": {"status": "opted_in"}}))


def test_seed_writes_items_with_pending_consent(table, frozen):
    schedules.reset_sim()
    seed.seed(copy.deepcopy(SAMPLE))
    assert store.get_person("sample01", "rohan").consent_status("rcs") == "pending"
    assert store.lookup_addr("whatsapp", "+910000000001") == ("sample01", "kamala")
    assert "aurasenior-checkin-sample01" in schedules.client().names()
    assert "aurasenior-weekly-sample01" in schedules.client().names()


def test_simulated_baseline_is_labelled(table, frozen):
    schedules.reset_sim()
    seed.seed(copy.deepcopy(SAMPLE), simulated_baseline=True)
    items = store.query_prefix("sample01", "SIGNAL#")
    assert items and all(i["simulated"] for i in items)
