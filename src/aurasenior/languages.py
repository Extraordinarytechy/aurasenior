"""Language rows: Transcribe code, reply language, Polly voice and WhatsApp template language per person."""
from __future__ import annotations

from dataclasses import dataclass

from . import config


@dataclass(frozen=True)
class LanguageRow:
    key: str
    transcribe_code: str
    reply_language: str
    polly_voice: str
    polly_engine: str
    polly_language_code: str
    polly_fallback_voice: str
    template_suffix: str
    meta_language: str
    phrases: str


def row(key: str) -> LanguageRow:
    r = config.language(key)
    return LanguageRow(key=key, **{f: r[f] for f in LanguageRow.__dataclass_fields__ if f != "key"})


def keys() -> list[str]:
    return config.language_keys()


def phrase_lang(key: str) -> str:
    """Phrase table ("hi" or "en") for a language row key."""
    return row(key).phrases
