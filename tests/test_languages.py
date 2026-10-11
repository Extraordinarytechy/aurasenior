import pytest

from aurasenior import config, languages


@pytest.mark.parametrize("key", ["hi-IN", "en-IN", "en-US"])
def test_every_row_resolves(key):
    r = languages.row(key)
    assert r.transcribe_code == key
    assert r.polly_voice
    assert r.template_suffix in ("_hi", "_en")
    assert r.phrases in ("hi", "en")


def test_hindi_row_uses_kajal_and_hi_templates():
    r = languages.row("hi-IN")
    assert (r.polly_voice, r.polly_engine, r.meta_language) == ("Kajal", "neural", "hi")


def test_unknown_row_raises():
    with pytest.raises(config.ConfigError):
        languages.row("es-US")
