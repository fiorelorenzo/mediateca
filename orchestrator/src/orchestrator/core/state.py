from __future__ import annotations

from orchestrator.db.models import ItemStatus

_ALLOWED: dict[ItemStatus, set[ItemStatus]] = {
    ItemStatus.PENDING: {ItemStatus.ANALYZING, ItemStatus.FAILED},
    ItemStatus.ANALYZING: {ItemStatus.PROMOTING, ItemStatus.INCOMPLETE, ItemStatus.FAILED},
    ItemStatus.PROMOTING: {ItemStatus.ENCODING, ItemStatus.PROMOTED, ItemStatus.FAILED},
    ItemStatus.INCOMPLETE: {
        ItemStatus.MERGING,
        ItemStatus.FROZEN_AS_IS,
        ItemStatus.POLICY_OVERRIDDEN,
        ItemStatus.PROMOTED,
        ItemStatus.FAILED,
    },
    ItemStatus.MERGING: {
        ItemStatus.ENCODING,
        ItemStatus.PROMOTED,
        ItemStatus.INCOMPLETE,
        ItemStatus.FAILED,
    },
    ItemStatus.ENCODING: {ItemStatus.PROMOTED, ItemStatus.FAILED},
    ItemStatus.PROMOTED: {
        ItemStatus.INCOMPLETE,  # re-acquire
        ItemStatus.POLICY_OVERRIDDEN,
    },
    ItemStatus.FROZEN_AS_IS: {
        ItemStatus.INCOMPLETE,  # un-freeze
        ItemStatus.POLICY_OVERRIDDEN,
    },
    ItemStatus.POLICY_OVERRIDDEN: {
        ItemStatus.INCOMPLETE,
        ItemStatus.PROMOTED,
        ItemStatus.FROZEN_AS_IS,
    },
    ItemStatus.FAILED: {ItemStatus.ANALYZING, ItemStatus.INCOMPLETE},
    ItemStatus.LEGACY: {ItemStatus.ANALYZING},  # re-acquire
}


def allowed_transitions(current: ItemStatus) -> set[ItemStatus]:
    return _ALLOWED.get(current, set())


def validate_transition(current: ItemStatus, target: ItemStatus) -> None:
    if target not in allowed_transitions(current):
        raise ValueError(
            f"invalid transition {current} → {target}; "
            f"allowed: {sorted(allowed_transitions(current))}"
        )
