import pytest

from agent.auth import AuthContext
from agent.agent import get_order_logic, issue_refund_logic
from agent.tools import cancel_order, check_refund_eligibility


@pytest.mark.parametrize("call", [
    lambda ctx: get_order_logic(ctx, 4127),
    lambda ctx: issue_refund_logic(ctx, 4127, 1, "test"),
    lambda ctx: cancel_order(ctx, 4127, "test"),
    lambda ctx: check_refund_eligibility(ctx, 4127),
])
@pytest.mark.parametrize("ctx,code", [
    (AuthContext(9002, "merchant", 2), "outside_merchant_store_scope"),
    (AuthContext(2, "shopper"), "outside_shopper_ownership_scope"),
])
def test_denials_explain_scope_without_private_data(world, call, ctx, code):
    result = call(ctx)
    assert result["error"] == "permission_denied"
    assert result["denial_reason"] == code
    assert set(result) == {"ok", "error", "denial_reason", "reason"}
    assert "delivered" not in result["reason"]
    assert "Blue Heron" not in result["reason"]
    assert "store 1" not in result["reason"]
    assert not result["reason"].startswith("Role")
    assert "4127" not in result["reason"]
