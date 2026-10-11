"""Polly voice notes for WhatsApp: ogg_opus at 48 kHz, voice per language row."""
from __future__ import annotations

from .. import aws, languages


def synthesize(text: str, lang_key: str) -> bytes:
    row = languages.row(lang_key)
    resp = aws.client("polly").synthesize_speech(Text=text, OutputFormat="ogg_opus", SampleRate="48000",
                                                 VoiceId=row.polly_voice, Engine=row.polly_engine,
                                                 LanguageCode=row.polly_language_code)
    return resp["AudioStream"].read()
