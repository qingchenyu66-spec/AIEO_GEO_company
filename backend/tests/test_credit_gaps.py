"""算力一期缺口：hosted 403、terms 挂变更、销售通知、平台闸。"""
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.credit import BillingModeChangeLog, CreditTermsVersion, TenantCreditLedger
from app.models.tenant import Tenant
from app.models.user import User
from app.services.billing_mode_service import BILLING_MODE_CREDIT, BILLING_MODE_HOSTED
from app.services.credit_service import (
    publish_policy_change_terms,
    upsert_price_rule,
    can_submit_platform,
    preflight_schedule_submit,
)
from app.services.system_notification_service import (
    notify_billing_mode_switched_to_sales,
    upsert_credit_runway_alert,
)




def test_hosted_tenant_credit_guard_403(db):
    from app.api.v1.endpoints.customer_enterprise import _require_credit_tenant

    suffix = uuid4().hex[:8]
    tenant = Tenant(name="h", code=f"H{suffix}", billing_mode=BILLING_MODE_HOSTED, status=True)
    db.add(tenant)
    db.flush()
    with pytest.raises(HTTPException) as exc:
        _require_credit_tenant(db, tenant.id)
    assert exc.value.status_code == 403


def test_publish_policy_change_terms(db):
    row = publish_policy_change_terms(
        db,
        title="测试变更",
        content_html="<p>日硬顶 10 → 20</p>",
        notice_days=3,
    )
    assert row.id
    saved = db.get(CreditTermsVersion, row.id)
    assert saved is not None
    assert saved.version_code.startswith("auto-")


def test_upsert_price_rule_does_not_publish_terms(db):
    before_ids = set(db.scalars(select(CreditTermsVersion.id)).all())
    upsert_price_rule(
        db,
        scope="global",
        tenant_id=None,
        platform_code=None,
        credits_per_subtask=Decimal("1.5"),
    )
    after_ids = set(db.scalars(select(CreditTermsVersion.id)).all())
    assert after_ids == before_ids


def test_notify_billing_mode_switched_to_sales(db):
    suffix = uuid4().hex[:8]
    sales = User(username=f"sales_{suffix}", password_hash="x", display_name="销售", status=True)
    db.add(sales)
    db.flush()
    tenant = Tenant(
        name="t",
        code=f"T{suffix}",
        billing_mode=BILLING_MODE_CREDIT,
        owner_user_id=sales.id,
        status=True,
    )
    db.add(tenant)
    db.flush()
    log = BillingModeChangeLog(
        tenant_id=tenant.id,
        from_mode=BILLING_MODE_CREDIT,
        to_mode=BILLING_MODE_HOSTED,
        reason="测试转托管",
        operator_user_id=1,
    )
    db.add(log)
    db.flush()
    sent = notify_billing_mode_switched_to_sales(db, tenant, log, operator_name="运营")
    assert sent == 1


def test_can_submit_platform_respects_balance(db, monkeypatch):
    """方案乙：evaluate 仍能识别不足；can_submit_platform 恒 True。"""
    monkeypatch.setattr(
        "app.services.credit_service.fetch_molizhishu_balance",
        lambda: {"available": True, "current_balance": 100},
    )
    monkeypatch.setattr(
        "app.services.credit_service.get_cached_platform_window_estimate",
        lambda: {"estimated_yuan": 1000.0},
    )
    monkeypatch.setattr("app.services.credit_service._config_decimal", lambda k, d: Decimal("500"))
    monkeypatch.setattr("app.services.credit_service._config_int", lambda k, d: 1)
    from app.services.credit_service import evaluate_platform_runway

    ok, balance, estimate = can_submit_platform(db)
    assert ok is True
    assert balance == Decimal("100")
    sufficient, _, _ = evaluate_platform_runway(db)
    assert sufficient is False
    assert estimate == Decimal("1000")


def test_preflight_ignores_unacked_terms(db, monkeypatch):
    """2026-09-08 - 服务条款不再硬闸提交。"""
    suffix = uuid4().hex[:8]
    tenant = Tenant(
        name="t",
        code=f"T{suffix}",
        billing_mode=BILLING_MODE_CREDIT,
        credit_balance=Decimal("100"),
        status=True,
    )
    db.add(tenant)
    db.flush()
    terms = publish_policy_change_terms(
        db,
        title="需确认",
        content_html="<p>请确认</p>",
        notice_days=0,
    )
    terms.effective_at = terms.effective_at.replace(year=2020)
    db.flush()
    monkeypatch.setattr(
        "app.services.credit_service.can_submit_platform",
        lambda _db: (True, Decimal("999"), Decimal("1")),
    )
    with patch("app.services.credit_service.pending_terms_block", return_value=terms):
        gate = preflight_schedule_submit(
            db,
            tenant,
            window_key="w1",
            reserve_ref="r1",
            credits_needed=Decimal("1"),
            reserve=False,
        )
    assert gate.allowed is True
    assert gate.reason != "terms"

def test_get_ledger_entry_detail_with_subtasks(db):
    from app.services.credit_service import settle_credits, get_ledger_entry_detail

    suffix = uuid4().hex[:8]
    tenant = Tenant(
        name="t",
        code=f"L{suffix}",
        billing_mode=BILLING_MODE_CREDIT,
        credit_balance=Decimal("50"),
        status=True,
    )
    db.add(tenant)
    db.flush()
    settle_credits(
        db,
        tenant_id=tenant.id,
        ref_id="batch-1",
        credits=Decimal("2"),
        platform_code="doubao",
        keyword="测试词",
        window_key="20260827-09",
    )
    row = db.scalar(
        select(TenantCreditLedger).where(TenantCreditLedger.tenant_id == tenant.id).order_by(TenantCreditLedger.id.desc())
    )
    detail = get_ledger_entry_detail(db, tenant.id, row.id)
    assert detail is not None
    assert detail["subtasks"]
    assert detail["subtasks"][0]["platform_code"] == "doubao"


def test_upsert_credit_runway_alert(db):
    row = upsert_credit_runway_alert(
        db,
        runway_windows=0.5,
        runway_threshold=1,
        molizhishu_balance=100.0,
        next_window_yuan=200.0,
        platform_gate_ok=True,
    )
    assert row is not None
    assert "Runway" in row.title


def test_switch_billing_mode_next_window_defers_mode_and_balance(db):
    from app.services.billing_mode_service import apply_pending_billing_mode_for_tenant, switch_billing_mode

    suffix = uuid4().hex[:8]
    tenant = Tenant(name="nw", code=f"NW{suffix}", billing_mode=BILLING_MODE_HOSTED, status=True)
    db.add(tenant)
    db.flush()
    switch_billing_mode(
        db,
        tenant.id,
        target_mode=BILLING_MODE_CREDIT,
        reason="测试下窗生效",
        operator_user_id=1,
        effective_policy="next_window",
        opening_credit_amount=Decimal("120"),
    )
    db.flush()
    db.refresh(tenant)
    assert tenant.billing_mode == BILLING_MODE_HOSTED
    assert Decimal(str(tenant.credit_balance or 0)) == Decimal("0")
    # 2026-09-08 - 须按企业提交入口落地，不再依赖 beat 盲切
    apply_pending_billing_mode_for_tenant(db, tenant.id)
    db.refresh(tenant)
    assert tenant.billing_mode == BILLING_MODE_CREDIT
    assert Decimal(str(tenant.credit_balance or 0)) == Decimal("120")


def test_next_window_pending_supersede_and_cancel(db):
    from app.models.credit import BillingModeChangeLog
    from app.services.billing_mode_service import (
        billing_mode_log_status,
        cancel_pending_billing_mode,
        list_pending_billing_mode_logs,
        switch_billing_mode,
    )

    suffix = uuid4().hex[:8]
    tenant = Tenant(name="pend", code=f"PD{suffix}", billing_mode=BILLING_MODE_HOSTED, status=True)
    db.add(tenant)
    db.flush()
    first = switch_billing_mode(
        db,
        tenant.id,
        target_mode=BILLING_MODE_CREDIT,
        reason="旧 opening",
        operator_user_id=1,
        effective_policy="next_window",
        opening_credit_amount=Decimal("100"),
    )
    second = switch_billing_mode(
        db,
        tenant.id,
        target_mode=BILLING_MODE_CREDIT,
        reason="新 opening",
        operator_user_id=1,
        effective_policy="next_window",
        opening_credit_amount=Decimal("200"),
    )
    db.flush()
    db.refresh(first)
    pending = list_pending_billing_mode_logs(db, tenant.id)
    assert len(pending) == 1
    assert pending[0].id == second.id
    assert Decimal(str(pending[0].opening_credit_amount or 0)) == Decimal("200")
    assert billing_mode_log_status(first) == "superseded"
    cancelled = cancel_pending_billing_mode(db, tenant.id, operator_user_id=1)
    assert cancelled == 1
    assert list_pending_billing_mode_logs(db, tenant.id) == []
    db.refresh(tenant)
    assert tenant.billing_mode == BILLING_MODE_HOSTED
    assert db.scalar(select(BillingModeChangeLog).where(BillingModeChangeLog.id == second.id)) is not None


def test_submit_paths_wire_pending_billing_mode_before_credit_gate():
    # 2026-09-09 - 防回归：调度/手动提交口必须先落地 next_window
    import inspect

    from app.services import monitor_service, schedule_service

    schedule_src = inspect.getsource(schedule_service._submit_schedule_group_locked)
    monitor_src = inspect.getsource(monitor_service.submit_monitor_task)
    assert "apply_pending_billing_mode_for_tenant" in schedule_src
    assert "apply_pending_billing_mode_for_tenant" in monitor_src
    # 比较真实调用点，勿被顶部 import 行干扰
    assert schedule_src.index("if apply_pending_billing_mode_for_tenant") < schedule_src.index(
        "gate = apply_schedule_credit_gate"
    )
    assert monitor_src.index("if apply_pending_billing_mode_for_tenant") < monitor_src.index(
        "apply_manual_monitor_credit_gate("
    )
    # 瞬时失败路径须释放已 commit 的预扣
    assert "_SCHEDULE_TRANSIENT_ERRORS" in schedule_src
    transient_block = schedule_src[schedule_src.index("except _SCHEDULE_TRANSIENT_ERRORS") :]
    assert '_release_credit_reserve("failed")' in transient_block.split("except (IntegrityError")[0]


def test_create_tenant_credit_optional_opening(db):
    from app.services.management_service import apply_tenant_billing_mode_on_create, create_platform_tenant

    suffix = uuid4().hex[:8]
    bare = create_platform_tenant(
        db,
        name=f"新建自助空余额-{suffix}",
        owner_user_id=1,
        preferred_code=f"NZ{suffix}",
        billing_mode="credit",
    )
    db.flush()
    db.refresh(bare)
    assert bare.billing_mode == BILLING_MODE_CREDIT
    assert Decimal(str(bare.credit_balance or 0)) == Decimal("0")

    charged = create_platform_tenant(
        db,
        name=f"新建自助充值-{suffix}",
        owner_user_id=1,
        preferred_code=f"NC{suffix}",
        billing_mode="credit",
        opening_credit_amount=Decimal("88"),
    )
    db.flush()
    db.refresh(charged)
    assert Decimal(str(charged.credit_balance or 0)) == Decimal("88")

    hosted = Tenant(name="h", code=f"H{suffix}", billing_mode="hosted")
    apply_tenant_billing_mode_on_create(db, hosted, "hosted")
    assert hosted.billing_mode == "hosted"


def test_brand_config_allows_customer_identity():
    import inspect

    from app.api.v1.endpoints import platforms

    src = inspect.getsource(platforms.platforms_for_brand_config)
    assert '"PLATFORM", "CUSTOMER"' in src or "'PLATFORM', 'CUSTOMER'" in src
    assert "require_platform(current)" not in src



def test_inject_enterprise_menus_follows_customer_position(db):
    # 2026-09-08 - 转自助按职位注入：viewer 无成员写权限，admin 有
    from app.models.permission import CustomerPosition, Menu, UserIdentityMenu
    from app.models.user import User
    from app.models.user_identity import UserIdentity
    from app.services.billing_mode_service import inject_enterprise_menus_for_tenant

    suffix = uuid4().hex[:8]
    tenant = Tenant(name="pos", code=f"POS{suffix}", billing_mode=BILLING_MODE_CREDIT, status=True)
    db.add(tenant)
    db.flush()
    admin_pos = db.scalar(
        select(CustomerPosition).where(
            CustomerPosition.position_code == "enterprise_admin",
            CustomerPosition.tenant_id.is_(None),
            CustomerPosition.deleted.is_(False),
        )
    )
    viewer_pos = db.scalar(
        select(CustomerPosition).where(
            CustomerPosition.position_code == "enterprise_viewer",
            CustomerPosition.tenant_id.is_(None),
            CustomerPosition.deleted.is_(False),
        )
    )
    if admin_pos is None or viewer_pos is None:
        pytest.skip("customer positions missing")
    members_menu = db.scalar(
        select(Menu).where(Menu.menu_code == "customer.enterprise_members", Menu.deleted.is_(False))
    )
    if members_menu is None:
        pytest.skip("enterprise_members menu missing")

    def _mk_identity(code: str, position_id: int) -> UserIdentity:
        user = User(username=f"{code}_{suffix}", password_hash="x", display_name=code)
        db.add(user)
        db.flush()
        ident = UserIdentity(
            identity_code=f"CUSTOMER_{user.id}_{code}",
            user_id=user.id,
            tenant_id=tenant.id,
            identity_type="CUSTOMER",
            identity_name=code,
            role_code="customer",
            customer_position_id=position_id,
            is_default=True,
            status=True,
        )
        db.add(ident)
        db.flush()
        return ident

    admin_ident = _mk_identity("adm", admin_pos.id)
    viewer_ident = _mk_identity("view", viewer_pos.id)
    inject_enterprise_menus_for_tenant(db, tenant.id)
    db.flush()

    from app.services.menu_permission_service import has_identity_menu_permission

    assert has_identity_menu_permission(db, admin_ident.id, "customer.enterprise_members", "can_create") is True
    assert has_identity_menu_permission(db, viewer_ident.id, "customer.enterprise_members", "can_create") is False
    assert db.scalar(
        select(UserIdentityMenu).where(
            UserIdentityMenu.identity_id == admin_ident.id,
            UserIdentityMenu.menu_id == members_menu.id,
        )
    ) is None


def test_switch_billing_mode_allows_empty_reason(db):
    # 2026-09-08 - 备注选填，空串不得再拒
    from app.services.billing_mode_service import switch_billing_mode

    suffix = uuid4().hex[:8]
    tenant = Tenant(name="empty-reason", code=f"ER{suffix}", billing_mode=BILLING_MODE_HOSTED, status=True)
    db.add(tenant)
    db.flush()
    log = switch_billing_mode(
        db,
        tenant.id,
        target_mode=BILLING_MODE_CREDIT,
        reason="   ",
        operator_user_id=1,
        effective_policy="immediate",
        opening_credit_amount=Decimal("10"),
    )
    db.flush()
    db.refresh(tenant)
    assert log.reason == ""
    assert tenant.billing_mode == BILLING_MODE_CREDIT
    assert Decimal(str(tenant.credit_balance or 0)) == Decimal("10")


def test_estimate_daily_credits_sums_platform_prices(db):
    from unittest.mock import MagicMock, patch

    from app.services.credit_service import estimate_daily_credits

    suffix = uuid4().hex[:8]
    tenant = Tenant(
        name="est",
        code=f"EST{suffix}",
        billing_mode=BILLING_MODE_CREDIT,
        platform_whitelist_json=["doubao", "kimi"],
        status=True,
    )
    db.add(tenant)
    db.flush()
    upsert_price_rule(db, scope="global", tenant_id=None, platform_code=None, credits_per_subtask=Decimal("1"))
    upsert_price_rule(db, scope="global", tenant_id=None, platform_code="kimi", credits_per_subtask=Decimal("2"))
    asset = MagicMock()
    asset.monitor_keywords_json = ["词1"]
    asset.region_codes_json = ["110000"]
    with (
        patch("app.services.brand_service.tenant_purchased_platforms", return_value=["doubao", "kimi"]),
        patch("app.services.schedule_service.schedule_times_for_asset", return_value=["09:00"]),
    ):
        est = estimate_daily_credits(db, tenant, asset, keyword_count=1)
    assert est["subtasks_per_day"] == 2
    assert est["credits_per_day"] == 3.0


def test_upsert_price_rule_global_default_is_unique(db):
    from sqlalchemy import func, select

    from app.models.credit import CreditPriceRule

    upsert_price_rule(db, scope="global", tenant_id=None, platform_code=None, credits_per_subtask=Decimal("1.1"))
    upsert_price_rule(db, scope="global", tenant_id=None, platform_code=None, credits_per_subtask=Decimal("1.2"))
    db.flush()
    count = db.scalar(
        select(func.count())
        .select_from(CreditPriceRule)
        .where(
            CreditPriceRule.scope == "global",
            CreditPriceRule.tenant_key == 0,
            CreditPriceRule.platform_key == "__default__",
        )
    )
    assert count == 1
    row = db.scalar(
        select(CreditPriceRule).where(
            CreditPriceRule.scope == "global",
            CreditPriceRule.tenant_key == 0,
            CreditPriceRule.platform_key == "__default__",
        )
    )
    assert row is not None
    assert Decimal(str(row.credits_per_subtask)) == Decimal("1.2")
