"""Fixed message text: phrases, RCS and SMS bodies, and WhatsApp template content."""
from __future__ import annotations

import re
import string

from . import config, languages


class PhraseError(KeyError):
    pass


def _table(lang_key: str, audience: str) -> tuple[dict, dict]:
    t = config.get(languages.phrase_lang(lang_key), file="phrases")
    elder = t.get("elder", {}) if audience == "elder" else {}
    return elder, t


def text(key: str, lang_key: str, audience: str = "family") -> str:
    elder, t = _table(lang_key, audience)
    if key in elder:
        return elder[key]
    if key in t and not isinstance(t[key], dict):
        return t[key]
    raise PhraseError(f"no phrase {key} for {lang_key}")


def fill(template: str, **vars: str) -> str:
    names = {f for _, f, _, _ in string.Formatter().parse(template) if f}
    values = {"brand": config.brand(), **vars}
    missing = names - values.keys()
    if missing:
        raise PhraseError(f"missing variables {sorted(missing)}")
    return template.format(**{n: values[n] for n in names})


def render(key: str, lang_key: str, audience: str = "family", **vars: str) -> str:
    return fill(text(key, lang_key, audience), **vars)


# WhatsApp templates

def template(base: str, lang_key: str) -> dict:
    row = languages.row(lang_key)
    t = config.get(base, file="whatsapp_templates")[row.phrases]
    return {"name": base + row.template_suffix, "language": row.meta_language, "body": t["body"],
            "buttons": list(t["buttons"])}


def template_names() -> list[str]:
    return [k for k in config.load("whatsapp_templates") if k != "actions"]


def template_body(base: str, lang_key: str, params: list[str]) -> str:
    """The text a person sees for a template send, used by the guard and the simulators."""
    body = template(base, lang_key)["body"].replace("{brand}", config.brand())
    for i, p in enumerate(params, 1):
        body = body.replace("{{%d}}" % i, p)
    if re.search(r"\{\{\d+\}\}", body):
        raise PhraseError(f"template {base} has unfilled variables")
    return body


def action_for_label(label: str, lang_key: str) -> str | None:
    acts = config.get("actions", file="whatsapp_templates")
    return acts.get(languages.phrase_lang(lang_key), {}).get(label) or acts.get("en", {}).get(label)
