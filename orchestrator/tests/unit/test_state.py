import pytest

from orchestrator.core.state import allowed_transitions, validate_transition
from orchestrator.db.models import ItemStatus


def test_pending_can_become_analyzing() -> None:
    validate_transition(ItemStatus.PENDING, ItemStatus.ANALYZING)


def test_promoted_cannot_become_pending() -> None:
    with pytest.raises(ValueError):
        validate_transition(ItemStatus.PROMOTED, ItemStatus.PENDING)


def test_incomplete_to_merging_to_promoted() -> None:
    validate_transition(ItemStatus.INCOMPLETE, ItemStatus.MERGING)
    validate_transition(ItemStatus.MERGING, ItemStatus.PROMOTED)


def test_failed_can_be_retried_to_analyzing() -> None:
    validate_transition(ItemStatus.FAILED, ItemStatus.ANALYZING)


def test_allowed_transitions_listed() -> None:
    assert ItemStatus.ANALYZING in allowed_transitions(ItemStatus.PENDING)
