"""Minimal ISO-639 helper. We only care about a small set of languages
that show up in audio tracks of media we ingest."""

from __future__ import annotations

# Canonical 3-letter codes we use internally.
_ISO_6392 = {
    "eng",
    "ita",
    "fra",
    "spa",
    "deu",
    "jpn",
    "kor",
    "zho",
    "rus",
    "por",
    "nld",
    "pol",
    "tur",
    "ara",
    "swe",
    "nor",
    "dan",
    "fin",
    "ces",
    "hun",
}

_ISO_6391_TO_2 = {
    "en": "eng",
    "it": "ita",
    "fr": "fra",
    "es": "spa",
    "de": "deu",
    "ja": "jpn",
    "ko": "kor",
    "zh": "zho",
    "ru": "rus",
    "pt": "por",
    "nl": "nld",
    "pl": "pol",
    "tr": "tur",
    "ar": "ara",
    "sv": "swe",
    "no": "nor",
    "da": "dan",
    "fi": "fin",
    "cs": "ces",
    "hu": "hun",
}

_NAMES = {
    "english": "eng",
    "italian": "ita",
    "french": "fra",
    "spanish": "spa",
    "german": "deu",
    "japanese": "jpn",
    "korean": "kor",
    "chinese": "zho",
    "russian": "rus",
    "portuguese": "por",
    "dutch": "nld",
    "polish": "pol",
    "turkish": "tur",
    "arabic": "ara",
    "swedish": "swe",
    "norwegian": "nor",
    "danish": "dan",
    "finnish": "fin",
    "czech": "ces",
    "hungarian": "hun",
}


def normalize(value: str) -> str:
    """Take an ISO-639-1, ISO-639-2 code, or English name; return ISO-639-2.
    Raises ValueError on unknown inputs."""
    v = value.strip().lower()
    if v in _ISO_6392:
        return v
    if v in _ISO_6391_TO_2:
        return _ISO_6391_TO_2[v]
    if v in _NAMES:
        return _NAMES[v]
    raise ValueError(f"unknown language code/name: {value!r}")


def name_to_code(name: str) -> str | None:
    try:
        return normalize(name)
    except ValueError:
        return None
