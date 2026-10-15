import shutil
import pytest
from agent import db, tools
from agent.auth import AuthContext


def test_override_evidence_deadline_and_readonly(world):
    with db.connection() as conn:
        before = list(conn.iterdump())
        result = tools.get_applicable_policies(AuthContext(480, "shopper"), 9050)
        assert list(conn.iterdump()) == before
    assert result["ok"]
    assert result["return_window_days"] == 45
    assert result["window_source"] == "store-northwind-books-policy"
    assert result["eligibility_cutoff_date"] == "2026-08-14"
    assert result["days_remaining"] == 44
    assert result["deadline_semantics"]["required_event"] is None
    assert result["deadline_semantics"]["eligibility_day_boundary"] == "inclusive"
    assert result["specific_condition_requirements"] is None
    assert not result["restocking_fee"]["store_opted_in"]
    assert result["product_name"] == "Portable Field Guide"
    assert "store-northwind-books-policy" in {p["policy_id"] for p in result["policy_references"]}
    assert tools.check_refund_eligibility(AuthContext(480, "shopper"), 9050)["return_window_days"] == 45


def test_default_and_scopes(world):
    assert tools.get_applicable_policies(AuthContext(1,"shopper"),4127)["return_window_days"] == 30
    result=tools.get_applicable_policies(AuthContext(9002,"merchant",2),9050)
    assert result["error"]=="permission_denied"
    assert "store_name" not in result
    assert tools.get_applicable_policies(AuthContext(9501,"support"),9050)["ok"]
    assert tools.get_applicable_policies(AuthContext(1,"shopper"),999999)["error"]=="not_found"
    assert tools.get_applicable_policies(AuthContext(1,"shopper"),4127,"shipping")["error"]=="invalid_argument"


@pytest.mark.parametrize("change", ["missing", "conflicting"])
def test_missing_or_conflicting_published_override(world,tmp_path,monkeypatch,change):
    policies=tmp_path/"policies"
    shutil.copytree(world["policies"],policies)
    p=policies/"store-northwind-books-policy.md"
    if change=="missing": p.rename(p.with_suffix(".disabled"))
    else: p.write_text(p.read_text().replace("45 days", "14 days"))
    monkeypatch.setenv("CARTWHEEL_POLICIES_DIR",str(policies))
    assert tools.get_applicable_policies(AuthContext(480,"shopper"),9050)["error"]=="data_inconsistent"
    assert tools.check_refund_eligibility(AuthContext(480,"shopper"),9050)["error"]=="data_inconsistent"


def test_shorter_override_fee_and_registration(world):
    with db.connection() as conn:
        order=conn.execute("SELECT id,user_id FROM orders WHERE store_id=2 LIMIT 1").fetchone()
    result=tools.get_applicable_policies(AuthContext(order["user_id"],"shopper"),order["id"])
    assert result["return_window_days"]==14
    with db.connection() as conn:
        order=conn.execute("SELECT o.id,o.user_id FROM orders o JOIN stores s ON o.store_id=s.id WHERE s.restocking_fee_opt_in=1 LIMIT 1").fetchone()
    result=tools.get_applicable_policies(AuthContext(order["user_id"],"shopper"),order["id"])
    assert result["restocking_fee"]["max_percent"]==15
    from agent.agent import TOOLS_BY_ROLE
    assert all(any(t.name=="get_applicable_policies" for t in ts) for ts in TOOLS_BY_ROLE.values())


def test_missing_delivery_does_not_invent_deadline(world_copy):
    with db.connection() as conn:
        conn.execute("UPDATE orders SET delivered_at=NULL WHERE id=9050")
        conn.commit()
    result=tools.get_applicable_policies(AuthContext(480,"shopper"),9050)
    assert result["eligibility_cutoff_date"] is None
    assert result["days_remaining"] is None
    assert result["date_warning"]
