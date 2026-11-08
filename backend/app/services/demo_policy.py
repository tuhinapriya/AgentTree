"""Trusted policy and stable identifiers for the transactional demo.

These values are application configuration. They must never be expanded using
model output or a worker supplied permission request.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BranchState(StrEnum):
    RUNNING = "RUNNING"
    READY_TO_COMMIT = "READY_TO_COMMIT"
    COMMITTING = "COMMITTING"
    COMMITTED = "COMMITTED"
    ABORTING = "ABORTING"
    ABORTED = "ABORTED"
    COMMIT_REJECTED = "COMMIT_REJECTED"
    COMMIT_FAILED = "COMMIT_FAILED"


class EffectState(StrEnum):
    STAGED = "STAGED"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"


class EventOrigin(StrEnum):
    MODEL = "MODEL"
    CONTROLLED_TEST = "CONTROLLED_TEST"
    OPERATOR = "OPERATOR"
    SUPERVISOR = "SUPERVISOR"


@dataclass(frozen=True)
class BranchPolicy:
    allowed_tools: frozenset[str]
    customer_id: str | None = None
    order_id: str | None = None
    max_amount_cents: int | None = None
    commit_on_verified_completion: bool = False
    abort_on_scope_violation: bool = False


RUN_ID = "demo-run"
CUSTOMER_ID = "C104"
ORDER_ID = "ORD-882"
ORDER_REFUND_CENTS = 4_500
PROMO_CREDIT_CENTS = 5_000

TOOL_READ_ORDER = "read_order"
TOOL_STAGE_REFUND = "stage_refund"
TOOL_READ_ACCOUNT = "read_account"
TOOL_STAGE_PROMO_CREDIT = "stage_promo_credit"
TOOL_MODIFY_BILLING = "modify_billing"

BRANCH_POLICIES: dict[str, BranchPolicy] = {
    "parent": BranchPolicy(allowed_tools=frozenset()),
    "order": BranchPolicy(
        allowed_tools=frozenset({TOOL_READ_ORDER, TOOL_STAGE_REFUND, "read_orders", "process_order"}),
        customer_id=CUSTOMER_ID,
        order_id=ORDER_ID,
        max_amount_cents=ORDER_REFUND_CENTS,
        commit_on_verified_completion=True,
    ),
    "account": BranchPolicy(
        allowed_tools=frozenset({TOOL_READ_ACCOUNT, TOOL_STAGE_PROMO_CREDIT, "read_account"}),
        customer_id=CUSTOMER_ID,
        max_amount_cents=PROMO_CREDIT_CENTS,
        commit_on_verified_completion=True,
        abort_on_scope_violation=True,
    ),
}

KNOWN_TOOLS = frozenset(
    {
        TOOL_READ_ORDER,
        TOOL_STAGE_REFUND,
        TOOL_READ_ACCOUNT,
        TOOL_STAGE_PROMO_CREDIT,
        TOOL_MODIFY_BILLING,
    }
)
