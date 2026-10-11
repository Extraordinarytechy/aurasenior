import os
from datetime import datetime, timezone

import pytest

# Unit tests never reach AWS: fake credentials and a fixed region.
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ.pop("AWS_PROFILE", None)
os.environ.setdefault("TABLE_NAME", "aurasenior-household")
os.environ.setdefault("MEDIA_BUCKET", "aurasenior-media-test")
for _k in [k for k in os.environ if k.startswith("AURASENIOR_MODE_")]:
    del os.environ[_k]
os.environ.pop("AGENTCORE_MEMORY_ID", None)
os.environ.pop("GUARDRAIL_ID", None)

from aurasenior import aws, clock  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("AURASENIOR_SIM_DIR", str(tmp_path / "sim"))
    aws.reset()
    yield
    aws.reset()
    clock.unfreeze()


@pytest.fixture
def frozen():
    clock.freeze(datetime(2026, 10, 12, 3, 30, tzinfo=timezone.utc))  # 09:00 in Asia/Kolkata
    return clock


@pytest.fixture
def table():
    from moto import mock_aws

    with mock_aws():
        from aurasenior import store

        store.create_table()
        yield store.table()


@pytest.fixture
def sample(table, frozen):
    """The sample household seeded with simulators, every person opted in on every channel they have."""
    from pathlib import Path

    from aurasenior import channels, schedules, seed, store

    schedules.reset_sim()
    channels.reset()
    data = seed.load_file(Path(__file__).resolve().parent.parent / "households" / "sample.toml")
    seed.seed(data)
    for p in store.people("sample01"):
        for ch in p.addresses:
            store.set_consent("sample01", p.person_id, ch, "opted_in", "test")
    yield "sample01"
    schedules.reset_sim()
    channels.reset()


def open_window(hid, pid):
    from aurasenior import store

    store.set_wa_inbound(hid, pid)
