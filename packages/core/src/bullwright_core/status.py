"""Report lifecycle state machine (docs/API.md §4).

draft --submit--> submitted --approve--> approved --publish--> published
  ^                   |
  +------revise-------+---reject--> rejected (terminal)

Agents may submit/revise their OWN reports; approve/reject/publish are
operator (admin) actions. This module is the single source of truth —
the API layer asks it, never re-encodes the rules.
"""

from enum import StrEnum


class ReportStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    PUBLISHED = "published"
    REJECTED = "rejected"


class ReportAction(StrEnum):
    SUBMIT = "submit"
    REVISE = "revise"
    APPROVE = "approve"
    REJECT = "reject"
    PUBLISH = "publish"


# action -> (from_status, to_status, required_scope, owner_only)
TRANSITIONS: dict[ReportAction, tuple[ReportStatus, ReportStatus, str, bool]] = {
    ReportAction.SUBMIT: (ReportStatus.DRAFT, ReportStatus.SUBMITTED, "reports:write", True),
    ReportAction.REVISE: (ReportStatus.SUBMITTED, ReportStatus.DRAFT, "reports:write", True),
    ReportAction.APPROVE: (ReportStatus.SUBMITTED, ReportStatus.APPROVED, "admin", False),
    ReportAction.REJECT: (ReportStatus.SUBMITTED, ReportStatus.REJECTED, "admin", False),
    ReportAction.PUBLISH: (ReportStatus.APPROVED, ReportStatus.PUBLISHED, "admin", False),
}

TERMINAL_STATUSES = frozenset({ReportStatus.REJECTED})
EDITABLE_STATUSES = frozenset({ReportStatus.DRAFT, ReportStatus.SUBMITTED})


class TransitionError(Exception):
    def __init__(self, action: ReportAction, current: ReportStatus) -> None:
        self.action = action
        self.current = current
        super().__init__(f"cannot {action.value} a report in status {current.value!r}")


def check_transition(action: ReportAction, current: ReportStatus) -> ReportStatus:
    """Return the target status, or raise TransitionError. Scope/ownership
    enforcement is the caller's job using required_scope()/is_owner_only()."""
    from_status, to_status, _, _ = TRANSITIONS[action]
    if current != from_status:
        raise TransitionError(action, current)
    return to_status


def required_scope(action: ReportAction) -> str:
    return TRANSITIONS[action][2]


def is_owner_only(action: ReportAction) -> bool:
    return TRANSITIONS[action][3]
