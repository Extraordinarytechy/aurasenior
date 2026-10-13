"""Keyword matching used before any model call: STOP, START, YES, fall and help, mentions."""
from __future__ import annotations

import unicodedata

from . import config, languages


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "").lower()
    text = "".join(" " if unicodedata.category(c).startswith("P") else c for c in text)
    return " ".join(text.split())


def tokens(text: str) -> list[str]:
    n = normalise(text)
    return n.split(" ") if n else []


def _contains_phrase(toks: list[str], phrase: str) -> bool:
    p = tokens(phrase)
    return bool(p) and any(toks[i : i + len(p)] == p for i in range(len(toks) - len(p) + 1))


def _set(kind: str, lang_key: str) -> set[str]:
    sets = config.get(kind, file="keywords")
    return {normalise(x) for x in sets.get(languages.phrase_lang(lang_key), [])} | {
        normalise(x) for x in sets.get("en", [])
    }


def is_stop(text: str, lang_key: str) -> bool:
    return normalise(text) in _set("stop", lang_key)


def is_start(text: str, lang_key: str) -> bool:
    return normalise(text) in _set("start", lang_key)


def is_yes(text: str, lang_key: str) -> bool:
    return normalise(text) in _set("yes", lang_key)


def fall_or_help(text: str) -> bool:
    toks = tokens(text)
    for entry in config.get("fall_help", file="keywords"):
        word = normalise(entry["text"])
        match = entry["match"]
        if match == "token" and word in toks:
            return True
        if match == "prefix" and any(t.startswith(word) for t in toks):
            return True
        if match == "phrase" and _contains_phrase(toks, word):
            return True
    return False


def mentions_refill(text: str, lang_key: str) -> bool:
    """True when a reply talks about a refill or an order (prefix match on tokens)."""
    words = _set("refill_words", lang_key)
    return any(t.startswith(w) for t in tokens(text) for w in words)


def mentions(text: str) -> dict[str, int]:
    toks = tokens(text)
    out = {}
    for kind, lists in config.get("mentions", file="keywords").items():
        n = sum(toks.count(normalise(w)) for w in lists.get("token", []))
        n += sum(1 for p in lists.get("phrase", []) if _contains_phrase(toks, p))
        out[kind] = n
    return out
