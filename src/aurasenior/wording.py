"""The one wording rule shared by the outbound guard, memory recall and seed validation."""
from __future__ import annotations

from . import config, keywords, languages

RULES = ("disease", "dose", "score")


def _lists(lang_key: str) -> dict:
    return config.get(languages.phrase_lang(lang_key), file="wording")


def _hit(toks: list[str], entry: str) -> bool:
    e = keywords.tokens(entry)
    return bool(e) and any(toks[i : i + len(e)] == e for i in range(len(toks) - len(e) + 1))


def check(text: str, lang_key: str) -> str | None:
    """Return the rule id that matched (for example "disease"), or None when the text is fine.

    English lists are always checked too, because Hindi speakers mix English words.
    """
    toks = keywords.tokens(text)
    tables = [_lists(lang_key)]
    if languages.phrase_lang(lang_key) != "en":
        tables.append(config.get("en", file="wording"))
    for table in tables:
        for rule in RULES:
            if any(_hit(toks, e) for e in table.get(rule, [])):
                return rule
    return None
