import re
import string

import pytest

from aurasenior import config, phrases, wording

SAMPLE = {
    "relation_label": "Maa",
    "display_label": "BP tablets",
    "family_name": "Rohan",
    "elder_name": "Kamala",
    "admin_name": "Rohan",
    "quote": "I slipped near the chair",
    "pharmacy_name": "City Pharmacy",
    "ack_name": "Rohan",
    "number": "+910000000001",
    "name": "Rohan",
}
LANG_FOR = {"en": "en-IN", "hi": "hi-IN"}


def _tables():
    p = config.load("phrases")
    return p["en"], p["hi"]


def _flat(t):
    return {k: v for k, v in t.items() if not isinstance(v, dict)}


def test_every_language_has_every_key():
    en, hi = _tables()
    assert _flat(en).keys() == _flat(hi).keys()
    assert en["elder"].keys() == hi["elder"].keys()


REQUIRED = {"optin_ask", "optin_ask_admin", "missed_checkin", "missed_checkin_sms", "checkin_late_family",
            "refill_sms", "refill_ordered_family", "refill_order_failed", "refill_expired", "urgent_alert",
            "urgent_sms", "esc_ack_family", "elder_number", "agent_unavailable_family", "sms_help",
            "quote_withheld", "guard_replacement"}
REQUIRED_ELDER = {"optin_ask", "checkin_voice", "followup_voice", "refill_ordered_elder", "refill_self_elder",
                  "esc_told_elder", "esc_reassure_elder", "esc_ack_elder", "stop_confirm", "cost_cap",
                  "send_voice_note", "not_heard", "guard_replacement"}


def test_required_keys_present():
    en, _ = _tables()
    assert REQUIRED <= _flat(en).keys()
    assert REQUIRED_ELDER <= en["elder"].keys()


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_every_phrase_renders_and_passes_wording(lang):
    t = config.load("phrases")[lang]
    for audience, table in (("family", _flat(t)), ("elder", t["elder"])):
        for key in table:
            out = phrases.render(key, LANG_FOR[lang], audience, **SAMPLE)
            assert "{" not in out, key
            assert wording.check(out, LANG_FOR[lang]) is None, key


@pytest.mark.parametrize("lang_key", ["en-IN", "hi-IN"])
def test_every_template_fills_and_passes_wording(lang_key):
    for base in phrases.template_names():
        t = phrases.template(base, lang_key)
        n = len(set(re.findall(r"\{\{(\d+)\}\}", t["body"])))
        body = phrases.template_body(base, lang_key, ["Maa", "BP tablets", "Rohan"][:n] or [])
        assert wording.check(body, lang_key) is None, base
        for label in t["buttons"]:
            assert len(label) <= 25
            assert phrases.action_for_label(label, lang_key), label


def test_missing_variable_raises():
    with pytest.raises(phrases.PhraseError):
        phrases.render("missed_checkin", "en-IN")


def test_brand_value_appears_only_in_brand_entry():
    brand = config.brand()
    word = re.compile(r"\b" + re.escape(brand) + r"\b")
    ident = re.compile(r"aurasenior[-_][a-z_-]+", re.IGNORECASE)
    for path in config.config_dir().glob("*.toml"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if path.name == "app.toml" and line.strip().startswith("name ="):
                continue
            assert not word.search(ident.sub("", line)), f"{path.name}: {line}"


def test_english_rows_use_neutral_words():
    en, _ = _tables()
    texts = list(_flat(en).values()) + list(en["elder"].values()) + list(config.load("signals")["en"].values())
    for base in phrases.template_names():
        texts.append(config.load("whatsapp_templates")[base]["en"]["body"])
    bad = re.compile(r"\b(her|him|she|he|his|hers)\b", re.IGNORECASE)
    assert [t for t in texts if bad.search(t)] == []


def test_hindi_agent_lines_are_feminine_and_family_labels_neutral():
    _, hi = _tables()
    masculine = re.compile(r"रहा हूँ|रहा था|लूँगा|करूँगा|दे सका|आया है|पूछ रहे हैं")
    texts = list(_flat(hi).values()) + list(hi["elder"].values())
    for base in phrases.template_names():
        t = config.load("whatsapp_templates")[base]["hi"]
        texts += [t["body"], *t["buttons"]]
    assert [t for t in texts if masculine.search(t)] == []


def test_told_elder_has_no_physical_instruction():
    for lang in ("en-IN", "hi-IN"):
        out = phrases.render("esc_told_elder", lang, "elder", family_name="Rohan").lower()
        for word in ("stand", "get up", "move", "lie", "sit", "उठ", "लेट", "बैठ"):
            assert word not in out


def test_signals_phrases_have_no_score_or_risk_words():
    sig = config.load("signals")
    for lang in ("en", "hi"):
        for v in sig[lang].values():
            assert wording.check(v, LANG_FOR[lang]) is None
            assert not re.search(r"\b(score|risk|diagnosis|level)\b|\d", v, re.IGNORECASE)


def test_phrase_placeholders_are_known():
    known = set(SAMPLE) | {"brand"}
    for lang in ("en", "hi"):
        t = config.load("phrases")[lang]
        for v in list(_flat(t).values()) + list(t["elder"].values()):
            names = {f for _, f, _, _ in string.Formatter().parse(v) if f}
            assert names <= known, v
