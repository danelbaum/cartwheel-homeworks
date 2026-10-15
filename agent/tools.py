"""Homework 1: the remaining commerce-agent tools.

The three lecture tools (`search_help_center`, `get_order`, `issue_refund`)
are implemented in agent/agent.py and are worked examples of the pattern:
check permissions first, go through agent/db.py for data, and return a
structured dict, never a prose error. The homework tools follow the same
pattern. agent/agent.py already wraps each function below as an SDK tool, so
once a function works here it works in chat with no further wiring.

Result convention (see agent/auth.py):
  - Success: a dict with "ok": True plus the payload fields named in each
    docstring.
  - Failure: {"ok": False, "error": <code>, "reason": <human-readable str>}.

Run the contract tests with: uv run pytest tests/test_hw_holes.py -k hw1
They are marked xfail and flip to passing as you implement each function.
"""

from __future__ import annotations

from typing import Any
from datetime import timedelta

from agent import db
from agent.auth import AuthContext, can_cancel_order, can_view_order, permission_denied, order_permission_denied
from seed.eligibility import is_refund_eligible
from agent.helpcenter import load_policy_docs
from agent.killswitch import kill_switch
from agent.return_policy import resolve_return_policy

MAX_SEARCH_LIMIT = 25
DEFAULT_ORDER_LIMIT = 20


def get_applicable_policies(ctx: AuthContext, order_id: int, topic: str = "returns") -> dict[str, Any]:
    """Resolve the applicable return rules for an authorized order, read-only.

    Supports returns only. Selects explicit store policies and platform rules
    without search ranking. Unknown conditions and procedural deadlines remain
    unknown; a calculated eligibility cutoff is not a ship-by/receive-by promise.
    """
    if topic != "returns":
        return {"ok": False, "error": "invalid_argument", "reason": "Only the returns topic is supported."}
    with db.connection() as conn:
        order = db.get_order(conn, order_id)
        if order is None:
            return {"ok": False, "error": "not_found", "reason": "Order not found."}
        if not can_view_order(ctx, order.user_id, order.store_id):
            return order_permission_denied(ctx, order_id, "access")
        store = db.get_store(conn, order.store_id)
        if store is None:
            return {"ok": False, "error": "data_inconsistent", "reason": "Store record is missing."}
        products = db.list_products(conn, store.id)
        product = next((p for p in products if p.id == order.product_id), None)
        as_of = db.world_asof(conn)
    policy = resolve_return_policy(store)
    if not policy["ok"]:
        return policy
    delivered = order.delivered_at
    elapsed = (as_of - delivered).days if delivered else None
    valid_date = elapsed is not None and elapsed >= 0
    policy.update(
        order_id=order_id, topic=topic, store_name=store.name,
        product_name=product.title if product else None,
        listing_description=product.description if product else None,
        evaluated_as_of=as_of.isoformat(), status=order.status,
        delivered_at=delivered.isoformat() if delivered else None,
        days_since_delivery=elapsed,
        eligibility_cutoff_date=(delivered + timedelta(days=policy["return_window_days"])).isoformat() if valid_date else None,
        days_remaining=policy["return_window_days"] - elapsed if valid_date else None,
        date_warning=None if valid_date else "Delivery date is missing or after the evaluation date.",
    )
    return policy


def check_refund_eligibility(ctx: AuthContext, order_id: int) -> dict[str, Any]:
    """Explain refund eligibility for an authorized order without changing it.

    Uses the database's evaluation date and existing eligibility oracle.
    Ineligibility has a specific reason code and explanation. Inconsistent
    records return data_inconsistent rather than an invented denial reason.
    This checks eligibility only, not refund amount approval or completion.
    """
    with db.connection() as conn:
        order = db.get_order(conn, order_id)
        if order is None:
            return {"ok": False, "error": "not_found", "reason": f"No order found with id {order_id}."}
        if not can_view_order(ctx, order.user_id, order.store_id):
            return order_permission_denied(ctx, order_id, "access")
        store = db.get_store(conn, order.store_id)
        if store is None:
            return {"ok": False, "error": "data_inconsistent", "reason": "The order's store record is missing."}
        as_of = db.world_asof(conn)
    policy = resolve_return_policy(store)
    if not policy["ok"]:
        return policy
    window = policy["return_window_days"]
    elapsed = (as_of - order.delivered_at).days if order.delivered_at else None
    eligible = is_refund_eligible(
        status=order.status, delivered_at=order.delivered_at,
        as_of=as_of, return_window_days=window,
    )
    if order.status != "delivered":
        code = "status_not_delivered"
        reason = f"The order status is '{order.status}'; only delivered orders are eligible."
    elif order.delivered_at is None:
        code, reason = "missing_delivery_date", "The order has no delivery date, so its return window cannot be verified."
    elif elapsed < 0:
        code, reason = "future_delivery_date", "The recorded delivery date is after the evaluation date."
    elif elapsed > window:
        code = "return_window_expired"
        reason = f"The {window}-day return window has expired: {elapsed} days elapsed since delivery."
    else:
        code = "within_return_window"
        reason = f"The order is delivered and is within its {window}-day return window ({elapsed} days since delivery)."
    result = {
        "ok": True, "order_id": order_id, "eligible": eligible,
        "reason_code": code, "reason": reason, "status": order.status,
        "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
        "evaluated_as_of": as_of.isoformat(), "days_since_delivery": elapsed,
        "return_window_days": window,
        "store_override_days": store.return_window_days_override,
        "stored_refund_eligible": order.refund_eligible,
        "policy_references": policy["policy_references"],
        "scope": "Recorded order eligibility rules only; does not issue refunds or approve amounts.",
    }
    if eligible != order.refund_eligible:
        result.update(ok=False, error="data_inconsistent", eligible=None,
                      calculated_eligible=eligible, calculated_reason_code=code,
                      reason_code="eligibility_mismatch",
                      reason="Stored eligibility disagrees with the existing eligibility rules; human review is required.")
    return result


def get_policy(ctx: AuthContext, policy_id: str) -> dict[str, Any]:
    """Fetch one policy doc by its exact id. Risk tier: read.

    Every role may read every policy doc (the corpus is public help-center
    content), so this tool needs no permission check.

    Args:
        ctx: The caller's auth context. Unused here, but every tool takes it.
        policy_id: An exact policy id, e.g. "cw-returns" or
            "store-juniper-home-goods-policy". Matching is exact and
            case-sensitive; ids are the `policy_id` front-matter field of the
            files in data/policies/.

    Returns:
        On success: {"ok": True, "policy_id": str, "title": str,
        "audience": str, "body": str} where body is the markdown body of the
        doc without the front matter.
        If no doc has that id: {"ok": False, "error": "not_found",
        "reason": ...} naming the id that was requested.

    Implementation notes:
        agent.helpcenter.load_policy_docs() returns every parsed doc.
    """
    for doc in load_policy_docs():
        if doc.policy_id == policy_id:
            return {
                "ok": True,
                "policy_id": doc.policy_id,
                "title": doc.title,
                "audience": doc.audience,
                "body": doc.body,
            }
    return {
        "ok": False,
        "error": "not_found",
        "reason": f"No policy found with id '{policy_id}'.",
    }


def search_products(
    ctx: AuthContext,
    query: str,
    store: str | None = None,
    max_price_usd: float | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Search the product catalog. Risk tier: read.

    Every role may search products. Matching is deterministic keyword
    matching, not semantic search: a product matches when every whitespace
    token of `query` appears case-insensitively as a substring of the
    product's title or description.

    Args:
        ctx: The caller's auth context.
        query: Free-text query. Must be non-empty after stripping whitespace;
            otherwise return {"ok": False, "error": "invalid_argument",
            "reason": ...}.
        store: Optional store filter. Matched with
            agent.db.get_store_by_name (case-insensitive name or slug). If
            given and no store matches, return {"ok": False, "error":
            "not_found", "reason": ...} naming the store string.
        max_price_usd: Optional inclusive price ceiling. If given and not
            strictly positive, return an "invalid_argument" error.
        limit: Maximum products to return. Clamp to the range
            [1, MAX_SEARCH_LIMIT]; do not error on out-of-range values.

    Returns:
        {"ok": True, "products": [...], "count": <len(products)>} where each
        product is {"product_id": int, "store_id": int, "title": str,
        "price_usd": float}. Sort matches by price_usd ascending, then by
        product_id ascending, and truncate to `limit`. No matches is still a
        success: {"ok": True, "products": [], "count": 0}.

    Implementation notes:
        agent.db.list_products(conn, store_id) gives the candidate set.
        Use `with db.connection() as conn:` to close the database automatically.
    """
    tokens = query.lower().split()
    if not tokens:
        return {"ok": False, "error": "invalid_argument", "reason": "Query must not be empty."}
    if max_price_usd is not None and not max_price_usd > 0:
        return {"ok": False, "error": "invalid_argument", "reason": "Price ceiling must be strictly positive."}
    limit = max(1, min(limit, MAX_SEARCH_LIMIT))
    with db.connection() as conn:
        store_id = None
        if store is not None:
            matched_store = db.get_store_by_name(conn, store)
            if matched_store is None:
                return {"ok": False, "error": "not_found", "reason": f"No store found matching '{store}'."}
            store_id = matched_store.id
        candidates = db.list_products(conn, store_id)
    matches = [
        product for product in candidates
        if all(token in f"{product.title} {product.description}".lower() for token in tokens)
        and (max_price_usd is None or product.price_usd <= max_price_usd)
    ]
    matches.sort(key=lambda product: (product.price_usd, product.id))
    products = [
        {"product_id": product.id, "store_id": product.store_id,
         "title": product.title, "price_usd": product.price_usd}
        for product in matches[:limit]
    ]
    return {"ok": True, "products": products, "count": len(products)}


def list_my_orders(ctx: AuthContext) -> dict[str, Any]:
    """List recent orders in the caller's own scope. Risk tier: read.

    Role behavior, straight from the access matrix in SPEC.md:
        - shopper: the caller's own orders.
        - merchant: the caller's store's orders (ctx.store_id).
        - support: support staff have no orders of their own and look up
          specific orders with get_order instead, so return {"ok": False,
          "error": "invalid_argument", "reason": ...} saying exactly that.

    Returns:
        For shopper and merchant: {"ok": True, "orders": [...],
        "count": <len(orders)>} where each order is
        agent.db.Order.to_public_dict() and the list holds at most
        DEFAULT_ORDER_LIMIT orders, newest first (agent.db.list_orders_for_user
        and list_orders_for_store already sort and limit this way).

    Implementation notes:
        No permission check is needed beyond the role dispatch, because the
        scope is baked into which query you run. That is the point of the
        tool: the model cannot ask for someone else's orders through it.
    """
    if ctx.role == "support":
        return {
            "ok": False,
            "error": "invalid_argument",
            "reason": "Support staff have no orders of their own; use get_order to look up specific orders.",
        }
    with db.connection() as conn:
        if ctx.role == "shopper":
            orders = db.list_orders_for_user(conn, ctx.user_id, DEFAULT_ORDER_LIMIT)
        elif ctx.role == "merchant":
            orders = db.list_orders_for_store(conn, ctx.store_id, DEFAULT_ORDER_LIMIT)
        else:
            return {"ok": False, "error": "invalid_argument", "reason": "Unsupported caller role."}
    public_orders = [order.to_public_dict() for order in orders]
    return {"ok": True, "orders": public_orders, "count": len(public_orders)}


def cancel_order(ctx: AuthContext, order_id: int, reason: str) -> dict[str, Any]:
    """Cancel an order. Risk tier: write.

    This is the homework's write tool, and it must enforce two independent
    rules in this order:

    1. The access matrix (scope): use agent.auth.can_cancel_order. Shoppers
       may cancel only their own orders, merchants only their own store's
       orders, support any order. On failure return
       agent.auth.permission_denied(...) with a reason naming the role and
       the order id. Scope is checked before the status rule so that an
       out-of-scope caller learns nothing about the order's state.
    2. The pre-shipment rule (facts.yaml `cancel_cutoff`): only orders whose
       status is exactly "placed" can be cancelled, for every role. If the
       order is in scope but its status is not "placed", return
       {"ok": False, "error": "not_eligible", "reason": ...} that names the
       current status and states that orders can be cancelled only before
       shipment.

    Args:
        ctx: The caller's auth context.
        order_id: The order to cancel.
        reason: Free-text reason from the user; not validated.

    Returns:
        If no order has this id: {"ok": False, "error": "not_found",
        "reason": ...}.
        On success: {"ok": True, "order_id": order_id, "status": "cancelled"}
        after persisting the new status with agent.db.set_order_status.

    Implementation notes:
        Fetch with agent.db.get_order. Note the argument order of
        can_cancel_order(ctx, order_user_id, order_store_id).

    The Module 4 kill switch is checked first (before the scope and
    status rules and before your code), so that a paused write tool touches
    nothing. It is provided; the default ("off") returns None and falls
    through to your implementation.
    """
    paused = kill_switch("cancel_order")
    if paused is not None:
        return {"ok": False, "error": "paused", "reason": paused}
    with db.connection() as conn:
        order = db.get_order(conn, order_id)
        if order is None:
            return {"ok": False, "error": "not_found", "reason": f"No order found with id {order_id}."}
        if not can_cancel_order(ctx, order.user_id, order.store_id):
            return order_permission_denied(ctx, order_id, "cancel")
        if order.status != "placed":
            return {
                "ok": False,
                "error": "not_eligible",
                "reason": f"Order {order_id} has status '{order.status}'; orders can be cancelled only before shipment.",
            }
        db.set_order_status(conn, order_id, "cancelled")
    return {"ok": True, "order_id": order_id, "status": "cancelled"}


def find_order(ctx: AuthContext, query: str) -> dict[str, Any]:
    """Search the caller's orders by product name. Risk tier: read.

    Takes a natural-language query (e.g., "earmuffs I bought last week")
    and searches the authenticated user's orders for products whose name
    matches. Use fuzzy string matching (e.g., thefuzz.fuzz.partial_ratio
    or case-insensitive substring matching) to find orders whose product name is close to the
    query.

    Access rules: a shopper searches only the shopper's own orders, a
    merchant searches orders from the merchant's store, and support staff
    can search any orders. Use agent.db.list_order_search_candidates with
    user_id=ctx.user_id for shoppers, store_id=ctx.store_id for merchants,
    or all_orders=True only for support. Derive the scope from ctx, never
    from the query; reject unsupported roles or missing required identity.
    Use agent.db.list_products to map product IDs to product titles.

    The helper returns the complete authorised scope, newest first with
    order ID descending as the tie-breaker. Match product names first,
    preserve that order, then return at most five matches. Do not search
    only the 20 most recent orders. Convert matches with to_public_dict().

    Args:
        ctx: The caller's auth context.
        query: A natural-language description of the product.

    Returns:
        {"ok": True, "orders": [...]} with a list of matching orders
        (at most 5), each as the dict returned by agent.db. If no orders
        match, return {"ok": True, "orders": []}.
    """
    if ctx.role == "shopper" and ctx.user_id is not None:
        scope = {"user_id": ctx.user_id}
    elif ctx.role == "merchant" and ctx.store_id is not None:
        scope = {"store_id": ctx.store_id}
    elif ctx.role == "support":
        scope = {"all_orders": True}
    else:
        return permission_denied("Order search requires a supported role and authenticated identity.")
    normalized_query = query.strip().lower()
    if not normalized_query:
        return {"ok": True, "orders": []}
    with db.connection() as conn:
        candidates = db.list_order_search_candidates(conn, **scope)
        titles = {product.id: product.title.lower() for product in db.list_products(conn)}
    matches = []
    for order in candidates:
        title = titles.get(order.product_id)
        if title and (normalized_query in title or title in normalized_query):
            matches.append(order.to_public_dict())
            if len(matches) == 5:
                break
    return {"ok": True, "orders": matches}
