"""
Message catalog (functions/i18n): formatting, English fallback, and catalog parity.

Translators fill es/fr/de/it/ja later. Until then a catalog is empty; once it has any key it must
have every English key, with exactly the same {placeholders}, and nothing else.
"""

import string

import pytest

import i18n
from i18n import SUPPORTED, normalize_language, sport_text, t
from i18n.messages import en


def placeholders(template: str) -> set:
    return {field for _, field, _, _ in string.Formatter().parse(template) if field is not None}


def catalog_problems(catalog: dict) -> list:
    """Why `catalog` is not a valid translation of the English catalog (empty list = valid)."""
    if not catalog:
        return []
    problems = [f"missing key {k}" for k in en.MESSAGES if k not in catalog]
    problems += [f"unknown key {k}" for k in catalog if k not in en.MESSAGES]
    for key, template in catalog.items():
        if key not in en.MESSAGES:
            continue
        try:
            fields = placeholders(template)
        except ValueError as exc:
            problems.append(f"{key}: malformed template ({exc})")
            continue
        if fields != placeholders(en.MESSAGES[key]):
            problems.append(f"{key}: placeholders {sorted(fields)} != {sorted(placeholders(en.MESSAGES[key]))}")
    return problems


class TestTranslate:
    def test_formats_named_params(self):
        assert t("en", "endurance.threshold.name", sport="Bike", reps=3, minutes=10) == "Bike Threshold: 3 × 10 min"
        assert t("en", "rest.planned") == "Planned rest day"

    def test_unused_params_are_ignored(self):
        assert t("en", "notes.header", week="Load week", phase="Base", weeks=None) == "Load week (Base phase)"

    def test_uses_the_language_catalog(self, monkeypatch):
        monkeypatch.setitem(i18n.CATALOGS, "fr", {"rest.planned": "Jour de repos prévu",
                                                   "rest.description": "Repos : {reason}."})
        assert t("fr", "rest.planned") == "Jour de repos prévu"
        assert t("fr", "rest.description", reason="x") == "Repos : x."

    def test_missing_key_falls_back_to_english(self, monkeypatch):
        monkeypatch.setitem(i18n.CATALOGS, "es", {"rest.planned": "Día de descanso"})
        assert t("es", "rest.name") == "Rest & Recovery Day"
        assert t("es", "notes.guardrail", reason="r") == "Adaptive Guardrail: r"

    @pytest.mark.parametrize("lang", ["pt", "", None, "EN", "de-DE", 3, ["de"]])
    def test_unsupported_language_falls_back_to_english(self, lang, monkeypatch):
        monkeypatch.setitem(i18n.CATALOGS, "de", {"rest.planned": "Geplanter Ruhetag"})
        assert t(lang, "rest.planned") == "Planned rest day"
        assert normalize_language(lang) == "en"

    def test_unknown_key_is_a_programming_error(self):
        with pytest.raises(KeyError):
            t("en", "no.such.key")

    @pytest.mark.parametrize("lang", SUPPORTED)
    def test_supported_languages_normalise_to_themselves(self, lang):
        assert normalize_language(lang) == lang

    def test_has(self):
        assert i18n.has("rest.name") and not i18n.has("rest.nope")

    def test_sport_text(self, monkeypatch):
        assert [sport_text("en", "cycling", f) for f in ("name", "title", "label")] == ["cycling", "Cycling", "Bike"]
        assert sport_text("en", "running") == "running"
        # sports without messages show as their code
        assert [sport_text("en", "rowing", f) for f in ("name", "title", "label")] == ["rowing", "Rowing", "Rowing"]
        monkeypatch.setitem(i18n.CATALOGS, "it", {"sport.cycling.title": "Ciclismo"})
        assert sport_text("it", "cycling", "title") == "Ciclismo"


class TestCatalogs:
    def test_every_supported_language_has_a_catalog(self):
        assert SUPPORTED[0] == "en" and set(i18n.CATALOGS) == set(SUPPORTED)

    def test_english_templates_are_well_formed(self):
        assert len(en.MESSAGES) > 300
        for key, template in en.MESSAGES.items():
            assert isinstance(template, str) and template, key
            fields = placeholders(template)  # raises on a malformed template
            assert all(f.isidentifier() for f in fields), key

    @pytest.mark.parametrize("lang", [lang for lang in SUPPORTED if lang != "en"])
    def test_catalog_is_empty_or_complete_with_matching_placeholders(self, lang):
        assert catalog_problems(i18n.CATALOGS[lang]) == []

    def test_parity_check_catches_bad_catalogs(self):
        complete = {k: "X " + v for k, v in en.MESSAGES.items()}
        assert catalog_problems({}) == [] and catalog_problems(complete) == []

        partial = dict(complete)
        partial.pop("rest.name")
        assert catalog_problems(partial) == ["missing key rest.name"]

        assert catalog_problems({**complete, "rest.bogus": "x"}) == ["unknown key rest.bogus"]

        renamed = {**complete, "rest.description": "Ruhetag: {grund}."}
        assert catalog_problems(renamed) == [
            "rest.description: placeholders ['grund'] != ['reason']"]

        dropped = {**complete, "endurance.threshold.name": "{sport}: {reps} ×"}
        assert catalog_problems(dropped) == [
            "endurance.threshold.name: placeholders ['reps', 'sport'] != ['minutes', 'reps', 'sport']"]

        malformed = {**complete, "rest.description": "Ruhetag: {reason."}
        assert catalog_problems(malformed)[0].startswith("rest.description: malformed template")
