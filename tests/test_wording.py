import pytest

from aurasenior import wording


@pytest.mark.parametrize(
    "text,lang,rule",
    [
        ("Her diabetes is getting worse", "en-IN", "disease"),
        ("Please double the dose tonight", "en-US", "dose"),
        ("Her health score is 7", "en-US", "score"),
        ("मधुमेह की वजह से", "hi-IN", "disease"),
        ("आज दोगुनी खुराक लें", "hi-IN", "dose"),
        ("yeh madhumeh hai", "hi-IN", "disease"),
        ("doguni khurak lo", "hi-IN", "dose"),
        ("आपका स्कोर अच्छा है", "hi-IN", "score"),
        ("यह स्ट्रोक हो सकता है", "hi-IN", "disease"),
        ("घुटने में इन्फेक्शन है", "hi-IN", "disease"),
        ("हाइपरटेंशन की दवा", "hi-IN", "disease"),
    ],
)
def test_wording_hits_return_rule_id(text, lang, rule):
    assert wording.check(text, lang) == rule


@pytest.mark.parametrize(
    "text,lang",
    [
        ("Good morning. Did you sleep well? Have you taken your BP tablets with your chai?", "en-IN"),
        ("सुप्रभात। आप कैसी हैं? क्या आपने चाय के साथ अपनी BP की गोली ले ली?", "hi-IN"),
        ("Rohan has ordered your BP tablets.", "en-US"),
    ],
)
def test_normal_checkin_text_passes(text, lang):
    assert wording.check(text, lang) is None


def test_matching_ignores_case_and_punctuation():
    assert wording.check("DIAGNOSIS!", "en-US") == "score"
