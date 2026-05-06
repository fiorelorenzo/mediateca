# orchestrator/src/orchestrator/core/policy.py
from __future__ import annotations

from dataclasses import dataclass

from orchestrator.core.iso639 import normalize

ORIGINAL_TOKEN = "@original"


@dataclass(frozen=True)
class PolicyVerdict:
    complete: bool
    missing: list[str]
    resolved_required: list[str]


class PolicyEngine:
    def __init__(self, default_required: list[str]) -> None:
        self._default = default_required

    def evaluate(
        self,
        *,
        present: list[str],
        original_lang: str | None,
        override_required: list[str] | None = None,
    ) -> PolicyVerdict:
        spec = override_required if override_required is not None else self._default
        resolved: list[str] = []
        for entry in spec:
            if entry == ORIGINAL_TOKEN:
                if original_lang is None:
                    continue
                resolved.append(normalize(original_lang))
            else:
                resolved.append(normalize(entry))
        # de-dupe preserving order
        seen: set[str] = set()
        ordered: list[str] = []
        for code in resolved:
            if code not in seen:
                seen.add(code)
                ordered.append(code)
        present_set = {normalize(p) for p in present if p != "und"}
        missing = [c for c in ordered if c not in present_set]
        return PolicyVerdict(
            complete=len(missing) == 0,
            missing=missing,
            resolved_required=ordered,
        )
