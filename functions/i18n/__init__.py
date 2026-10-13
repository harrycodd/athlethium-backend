"""
Message catalog for user-visible text written by the backend (workout names, coaching notes,
step names, exercise cues...).

    t(lang, "session.rest.name")                    -> "Rest & Recovery Day"
    t(lang, "notes.guardrail", reason=reason)       -> "Adaptive Guardrail: ..."

Each language has a flat {key: template} dict in i18n/messages/<lang>.py. Templates use named
`str.format` placeholders, so translators can reorder them freely. A key missing from a catalog,
or a language we don't support, falls back to English. English is the source of truth: every key
must exist in messages/en.py (an unknown key is a programming error and raises KeyError).
"""

from typing import Any, Dict

from i18n.messages import de, en, es, fr, it, ja

SUPPORTED = ("en", "es", "fr", "de", "it", "ja")
DEFAULT_LANGUAGE = "en"

CATALOGS: Dict[str, Dict[str, str]] = {
    "en": en.MESSAGES,
    "es": es.MESSAGES,
    "fr": fr.MESSAGES,
    "de": de.MESSAGES,
    "it": it.MESSAGES,
    "ja": ja.MESSAGES,
}


def normalize_language(value: Any) -> str:
    """A supported language code, or English for anything else (missing, unknown, not a string)."""
    return value if isinstance(value, str) and value in SUPPORTED else DEFAULT_LANGUAGE


def has(key: str) -> bool:
    """Whether `key` is a known message (i.e. present in the English catalog)."""
    return key in en.MESSAGES


def t(lang: Any, key: str, **params: Any) -> str:
    """The template for `key` in `lang` (English if missing there), formatted with `params`."""
    template = CATALOGS[normalize_language(lang)].get(key)
    if template is None:
        template = en.MESSAGES[key]
    return template.format(**params)


def sport_text(lang: Any, sport: str, form: str = "name") -> str:
    """
    A sport's display text. `form` is "name" (in a sentence: "cycling"), "title" (in a title:
    "Cycling") or "label" (short title prefix: "Bike"). Sports without messages show as their code.
    """
    key = f"sport.{sport}.{form}"
    if has(key):
        return t(lang, key)
    return sport if form == "name" else sport.capitalize()
