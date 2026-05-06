from orchestrator.core.iso639 import normalize, name_to_code


def test_normalize_already_iso6392() -> None:
    assert normalize("eng") == "eng"
    assert normalize("ita") == "ita"


def test_normalize_iso6391() -> None:
    assert normalize("en") == "eng"
    assert normalize("it") == "ita"


def test_normalize_aliases() -> None:
    assert normalize("italian") == "ita"
    assert normalize("English") == "eng"


def test_name_to_code_unknown_returns_none() -> None:
    assert name_to_code("klingon") is None


def test_normalize_unknown_raises() -> None:
    import pytest
    with pytest.raises(ValueError):
        normalize("xxxxx")
