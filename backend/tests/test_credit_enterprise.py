"""算力自助：校验、审计隔离、成员服务 smoke。"""

from decimal import Decimal

from app.schemas.brand import BrandAssetSaveRequest, BrandKeywordGroupSaveRequest
from app.services.credit_service import pending_terms_block, validate_credit_monitor_save


def test_validate_credit_monitor_allows_many_schedule_slots():
    # 2026-09-07 - 方案 A：日场次不设上限
    from app.models.tenant import Tenant

    tenant = Tenant(
        billing_mode="credit",
        platform_whitelist_json=["doubao"],
        credit_policy_json={"schedule_slots_limit": 2, "keyword_limit": 30},
    )
    payload = BrandAssetSaveRequest(
        company_full_name="测试企业有限公司",
        brand_name="测试",
        schedule_times=["09:00", "12:00", "18:00", "21:00"],
        keyword_groups=[],
    )
    validate_credit_monitor_save(tenant, payload)


def test_validate_credit_monitor_allows_any_platform():
    # 2026-09-07 - 方案 A：平台白名单不再生效
    from app.models.tenant import Tenant

    tenant = Tenant(
        billing_mode="credit",
        platform_whitelist_json=["doubao"],
        credit_policy_json={},
    )
    payload = BrandAssetSaveRequest(
        company_full_name="测试企业有限公司",
        brand_name="测试",
        schedule_times=["09:00"],
        keyword_groups=[],
        platforms=[{"platform": "kimi", "enabled": True}],
    )
    validate_credit_monitor_save(tenant, payload)


def test_credit_enterprise_menus_derived_without_identity_rows(db):
    """方案甲：credit 客户不依赖身份表落库也能看到企业配置菜单。"""
    from uuid import uuid4

    from app.models.permission import Menu, UserIdentityMenu
    from app.models.tenant import Tenant
    from app.models.user import User
    from app.models.user_identity import UserIdentity
    from app.services.menu_permission_service import (
        get_identity_menus,
        has_identity_menu_permission,
    )
    from sqlalchemy import select

    suffix = uuid4().hex[:8]
    tenant = Tenant(
        name=f"派生菜单-{suffix}",
        code=f"DM{suffix}",
        billing_mode="credit",
        credit_balance=Decimal("10"),
        status=True,
    )
    user = User(username=f"dm_{suffix}", password_hash="x", display_name="dm")
    db.add_all([tenant, user])
    db.flush()
    identity = UserIdentity(
        identity_code=f"CUSTOMER_{user.id}_TENANT_ADMIN",
        user_id=user.id,
        tenant_id=tenant.id,
        identity_type="CUSTOMER",
        identity_name="企业管理员",
        role_code="TENANT_ADMIN",
        status=True,
    )
    db.add(identity)
    db.flush()
    # 只挂一个普通门户菜单，故意不写 enterprise_*
    ws = db.scalar(select(Menu).where(Menu.menu_code == "customer.workspace", Menu.deleted.is_(False)))
    assert ws is not None
    db.add(
        UserIdentityMenu(
            identity_id=identity.id,
            menu_id=ws.id,
            can_create=False,
            can_update=False,
            can_delete=False,
            can_export=True,
        )
    )
    db.flush()

    codes = {m.menu_code for m in get_identity_menus(db, identity)}
    assert "customer.workspace" in codes
    assert "customer.enterprise_config" in codes
    assert "customer.enterprise_credit" in codes
    assert has_identity_menu_permission(db, identity.id, "customer.enterprise_credit", "can_export")
    assert has_identity_menu_permission(db, identity.id, "customer.enterprise_config", "can_export")


def test_pending_terms_helpers_importable():
    assert callable(pending_terms_block)
    assert callable(validate_credit_monitor_save)
    assert Decimal("1") > 0
