import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("AURASENIOR_LIVE") == "1":
        return
    # This hook sees every collected test, so only mark the ones in this folder.
    skip = pytest.mark.skip(reason="live AWS test: set AURASENIOR_LIVE=1")
    here = str(__import__("pathlib").Path(__file__).resolve().parent)
    for item in items:
        if str(item.path).startswith(here):
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _real_aws(monkeypatch):
    """Undo the unit-test fake credentials so boto3 uses the named profile."""
    if os.environ.get("AURASENIOR_LIVE") != "1":
        yield
        return
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AWS_PROFILE", os.environ.get("AURASENIOR_LIVE_PROFILE", "the-unsent"))
    from aurasenior import aws

    aws.reset()
    yield
    aws.reset()
