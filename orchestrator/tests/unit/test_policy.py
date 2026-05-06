# orchestrator/tests/unit/test_policy.py
import pytest

from orchestrator.core.policy import PolicyEngine


def test_all_languages_present() -> None:
    engine = PolicyEngine(default_required=["ita", "@original"])
    verdict = engine.evaluate(present=["ita", "eng"], original_lang="eng")
    assert verdict.complete is True
    assert verdict.missing == []


def test_missing_original() -> None:
    engine = PolicyEngine(default_required=["ita", "@original"])
    verdict = engine.evaluate(present=["ita"], original_lang="eng")
    assert verdict.complete is False
    assert verdict.missing == ["eng"]


def test_resolves_original_to_actual_lang() -> None:
    engine = PolicyEngine(default_required=["@original"])
    verdict = engine.evaluate(present=["jpn"], original_lang="jpn")
    assert verdict.complete is True


def test_per_item_override_takes_precedence() -> None:
    engine = PolicyEngine(default_required=["ita", "@original"])
    verdict = engine.evaluate(
        present=["jpn"],
        original_lang="jpn",
        override_required=["jpn", "eng"],
    )
    assert verdict.complete is False
    assert verdict.missing == ["eng"]


def test_unknown_language_in_required_raises() -> None:
    engine = PolicyEngine(default_required=["xxxxxxx"])
    with pytest.raises(ValueError):
        engine.evaluate(present=["ita"], original_lang="eng")
