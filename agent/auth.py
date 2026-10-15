"""Auth context and permission checks. Instructor-provided and complete.

This module implements the access matrix from SPEC.md section 3. The rule the
course states as a key takeaway: authorization is not a prompt. The server
injects the auth context per session, tools call these checks before touching
data, and the model cannot request data outside the caller's row of the
matrix. Do not weaken these checks; Module 4 attacks them.

Tool-result convention used across the repo:
  - Success: a dict containing "ok": True plus payload fields.
  - Failure: {"ok": False, "error": <machine-readable code>, "reason": <str>}.
    Error codes used by the starter code: "permission_denied", "not_found",
    "not_eligible", "invalid_argument", "not_implemented".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ROLES = ("shopper", "merchant", "support")


@dataclass(frozen=True)
class AuthContext:
    """Who is on the other end of the session.

    The server (or the CLI) builds this from the users table and passes it to
    every tool. `store_id` is set only for merchants.
    """

    user_id: int
    role: str
    store_id: int | None = None

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"unknown role: {self.role!r}")
        if self.role == "merchant" and self.store_id is None:
            raise ValueError("merchant auth context requires a store_id")


def permission_denied(reason: str) -> dict[str, Any]:
    """The structured error every denied action returns."""
    return {"ok": False, "error": "permission_denied", "reason": reason}


def order_permission_denied(ctx: AuthContext, order_id: int, action: str) -> dict[str, Any]:
    """Explain an already-denied order scope check without revealing its owner,
    store, status, or other private order fields. Does not grant permissions.
    """
    if ctx.role == "merchant":
        code = "outside_merchant_store_scope"
        explanation = "Merchants may access orders only within their own store; this request is outside that permitted scope."
    elif ctx.role == "shopper":
        code = "outside_shopper_ownership_scope"
        explanation = "Shoppers may access only their own orders; this request is outside that permitted scope."
    else:
        code = "outside_authorized_scope"
        explanation = "This request is outside the caller's authorized scope."
    return {
        "ok": False, "error": "permission_denied", "denial_reason": code,
        "reason": explanation,
    }


def can_view_order(ctx: AuthContext, order_user_id: int, order_store_id: int) -> bool:
    """Access matrix rows 'view own orders' and 'view store's orders'.

    Shoppers see only their own orders. Merchants see only their own store's
    orders. Support sees any order.
    """
    if ctx.role == "shopper":
        return order_user_id == ctx.user_id
    if ctx.role == "merchant":
        return order_store_id == ctx.store_id
    return True  # support


def can_refund_order(ctx: AuthContext, order_user_id: int, order_store_id: int) -> bool:
    """Scope check for `issue_refund` (the amount threshold is separate).

    The refund scope equals the view scope: shoppers may refund only their own
    orders, merchants only their own store's orders, support any order. The
    above-threshold rule applies to every role and is enforced by the tool,
    not here.
    """
    return can_view_order(ctx, order_user_id, order_store_id)


def can_cancel_order(ctx: AuthContext, order_user_id: int, order_store_id: int) -> bool:
    """Scope check for `cancel_order` (the pre-shipment rule is separate).

    Shoppers may cancel only their own orders, merchants only their own
    store's orders, support any order. The pre-shipment rule (facts.yaml
    `cancel_cutoff`) applies to every role and is enforced by the tool.
    """
    return can_view_order(ctx, order_user_id, order_store_id)
