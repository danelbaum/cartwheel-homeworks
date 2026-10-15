from datetime import timedelta

import pytest

from agent import db, tools
from agent.auth import AuthContext

SHOPPER = AuthContext(1, "shopper")


def test_demo_reason_permissions_and_registration(world):
    result = tools.check_refund_eligibility(SHOPPER, 3980)
    assert result["ok"] and not result["eligible"]
    assert result["reason_code"] == "return_window_expired"
    assert result["days_since_delivery"] == 45
    assert result["return_window_days"] == 30
    assert result["evaluated_as_of"] == "2026-07-01"
    assert tools.check_refund_eligibility(SHOPPER, 4127)["eligible"]
    denied = tools.check_refund_eligibility(AuthContext(9002, "merchant", 2), 3980)
    assert denied["error"] == "permission_denied"
    assert "days_since_delivery" not in denied
    assert tools.check_refund_eligibility(AuthContext(9501, "support"), 3980)["ok"]
    assert tools.check_refund_eligibility(SHOPPER, 999999)["error"] == "not_found"
    from agent.agent import TOOLS_BY_ROLE
    assert all(any(t.name == "check_refund_eligibility" for t in ts) for ts in TOOLS_BY_ROLE.values())


@pytest.mark.parametrize("status,days,flag,code", [
    ("delivered", 30, 1, "within_return_window"),
    ("delivered", 31, 0, "return_window_expired"),
    ("shipped", None, 0, "status_not_delivered"),
    ("cancelled", None, 0, "status_not_delivered"),
    ("refunded", 10, 0, "status_not_delivered"),
    ("delivered", None, 0, "missing_delivery_date"),
    ("delivered", -1, 0, "future_delivery_date"),
])
def test_reasons_and_inclusive_boundary(world_copy, status, days, flag, code):
    with db.connection() as conn:
        date = (db.world_asof(conn) - timedelta(days=days)).isoformat() if days is not None else None
        conn.execute("UPDATE orders SET status=?, delivered_at=?, refund_eligible=? WHERE id=4127", (status, date, flag))
        conn.commit()
        before = list(conn.iterdump())
        result = tools.check_refund_eligibility(SHOPPER, 4127)
        assert list(conn.iterdump()) == before
    assert result["reason_code"] == code
    assert result["eligible"] == bool(flag)


def test_override_and_mismatch(world_copy, world, tmp_path, monkeypatch):
    import shutil
    from agent.config import load_facts
    from seed.policies import render_store_policy
    policies = tmp_path / "policies"
    shutil.copytree(world["policies"], policies)
    monkeypatch.setenv("CARTWHEEL_POLICIES_DIR", str(policies))
    doc = render_store_policy(load_facts(), "Blue Heron Ceramics", "blue-heron-ceramics", 7, False)
    (policies / (doc.policy_id + ".md")).write_text(doc.to_markdown())
    with db.connection() as conn:
        conn.execute("UPDATE stores SET return_window_days_override=7 WHERE id=1")
        conn.commit()
    result = tools.check_refund_eligibility(SHOPPER, 4127)
    assert result["error"] == "data_inconsistent"
    assert result["eligible"] is None
    assert result["calculated_reason_code"] == "return_window_expired"
    assert result["return_window_days"] == 7
    with db.connection() as conn:
        conn.execute("UPDATE orders SET refund_eligible=0 WHERE id=4127")
        conn.commit()
    assert tools.check_refund_eligibility(SHOPPER, 4127)["reason_code"] == "return_window_expired"
