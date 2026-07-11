"""Full transition matrix for the report lifecycle (TEST_PLAN §2)."""

import pytest
from bullwright_core.status import (
    TRANSITIONS,
    ReportAction,
    ReportStatus,
    TransitionError,
    check_transition,
    is_owner_only,
    required_scope,
)

ALL = list(ReportStatus)


def test_every_action_has_exactly_one_legal_source() -> None:
    for action in ReportAction:
        legal = [s for s in ALL if _allowed(action, s)]
        assert legal == [TRANSITIONS[action][0]]


def _allowed(action: ReportAction, status: ReportStatus) -> bool:
    try:
        check_transition(action, status)
        return True
    except TransitionError:
        return False


@pytest.mark.parametrize(
    ("action", "current", "target"),
    [
        (ReportAction.SUBMIT, ReportStatus.DRAFT, ReportStatus.SUBMITTED),
        (ReportAction.REVISE, ReportStatus.SUBMITTED, ReportStatus.DRAFT),
        (ReportAction.APPROVE, ReportStatus.SUBMITTED, ReportStatus.APPROVED),
        (ReportAction.REJECT, ReportStatus.SUBMITTED, ReportStatus.REJECTED),
        (ReportAction.PUBLISH, ReportStatus.APPROVED, ReportStatus.PUBLISHED),
    ],
)
def test_happy_transitions(
    action: ReportAction, current: ReportStatus, target: ReportStatus
) -> None:
    assert check_transition(action, current) is target


def test_a2_nothing_reaches_published_without_admin() -> None:
    """Safety invariant A2: the only action landing on published is
    admin-scoped, and nothing transitions OUT of rejected."""
    for action, (_, to_status, scope, _) in TRANSITIONS.items():
        if to_status is ReportStatus.PUBLISHED:
            assert scope == "admin", f"{action} publishes without admin!"
        assert TRANSITIONS[action][0] is not ReportStatus.REJECTED

    assert required_scope(ReportAction.APPROVE) == "admin"
    assert required_scope(ReportAction.PUBLISH) == "admin"


def test_agent_actions_are_owner_scoped() -> None:
    assert is_owner_only(ReportAction.SUBMIT)
    assert is_owner_only(ReportAction.REVISE)
    assert not is_owner_only(ReportAction.APPROVE)
