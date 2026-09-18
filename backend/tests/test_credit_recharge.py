"""算力中心在线充值：换算、幂等、托管拒单。"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ops import OperationLog
from app.models.tenant import Tenant
from app.models.user import User
from app.services.credit_recharge_service import (
    create_credit_recharge_order,
    fulfill_credit_recharge_order_paid,
    is_credit_recharge_out_trade_no,
)
from app.services.credit_service import BILLING_MODE_CREDIT, BILLING_MODE_HOSTED, credits_from_yuan


def test_credits_from_yuan_default_rate(db: Session) -> None:
    tenant = Tenant(
        name="rate-test",
        code=f"RT{uuid4().hex[:6]}",
        billing_mode=BILLING_MODE_CREDIT,
        credit_policy_json={"credits_per_yuan": 4.2},
    )
    db.add(tenant)
    db.flush()
    assert credits_from_yuan(tenant, Decimal("100")) == Decimal("420.0")


def test_is_credit_recharge_out_trade_prefix() -> None:
    assert is_credit_recharge_out_trade_no("CR20260916120000ABCD")
    assert not is_credit_recharge_out_trade_no("H520260916120000ABCD")


def test_create_order_rejects_hosted(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "wechat_pay_dev_mode", True)
    tenant = Tenant(
        name="hosted-recharge",
        code=f"HR{uuid4().hex[:6]}",
        billing_mode=BILLING_MODE_HOSTED,
        status=True,
    )
    db.add(tenant)
    db.flush()
    with pytest.raises(ValueError, match="托管"):
        create_credit_recharge_order(
            db,
            tenant=tenant,
            payer_user_id=1,
            yuan_amount=10,
            pay_channel="wechat",
        )


def test_fulfill_paid_idempotent(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "wechat_pay_dev_mode", True)
    suffix = uuid4().hex[:6]
    tenant = Tenant(
        name=f"recharge-{suffix}",
        code=f"RC{suffix}",
        billing_mode=BILLING_MODE_CREDIT,
        status=True,
        credit_balance=Decimal("10"),
        credit_reserved=Decimal("0"),
        credit_policy_json={"credits_per_yuan": 4.2},
    )
    user = User(
        username=f"recharge_u_{suffix}",
        password_hash="x",
        display_name="充值测",
        status=True,
    )
    db.add(tenant)
    db.add(user)
    db.flush()

    order = create_credit_recharge_order(
        db,
        tenant=tenant,
        payer_user_id=user.id,
        yuan_amount=100,
        pay_channel="wechat",
    )
    assert order["credits_amount"] == 420.0
    assert order["code_url"]

    first = fulfill_credit_recharge_order_paid(
        db,
        out_trade_no=order["out_trade_no"],
        transaction_id="TX-1",
    )
    db.refresh(tenant)
    assert first["status"] == "paid"
    assert Decimal(str(tenant.credit_balance)) == Decimal("430.0")
    logs = list(
        db.scalars(
            select(OperationLog).where(
                OperationLog.tenant_id == tenant.id,
                OperationLog.action_type == "充值",
            )
        )
    )
    assert len(logs) == 1
    assert "到账" in (logs[0].description or "")
    assert logs[0].operator_name == "充值测"

    second = fulfill_credit_recharge_order_paid(
        db,
        out_trade_no=order["out_trade_no"],
        transaction_id="TX-1",
    )
    db.refresh(tenant)
    assert second["status"] == "paid"
    assert Decimal(str(tenant.credit_balance)) == Decimal("430.0")
    logs_again = list(
        db.scalars(
            select(OperationLog).where(
                OperationLog.tenant_id == tenant.id,
                OperationLog.action_type == "充值",
            )
        )
    )
    assert len(logs_again) == 1


def test_create_order_rejects_invalid_amount(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "wechat_pay_dev_mode", True)
    tenant = Tenant(
        name="amt-test",
        code=f"AM{uuid4().hex[:6]}",
        billing_mode=BILLING_MODE_CREDIT,
        status=True,
    )
    db.add(tenant)
    db.flush()
    with pytest.raises(ValueError, match="最低"):
        create_credit_recharge_order(
            db,
            tenant=tenant,
            payer_user_id=1,
            yuan_amount=0.5,
            pay_channel="wechat",
        )


def test_get_status_rejects_other_tenant(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.credit_recharge_service import get_credit_recharge_order_status

    monkeypatch.setattr(settings, "wechat_pay_dev_mode", True)
    suffix = uuid4().hex[:6]
    owner = Tenant(
        name=f"owner-{suffix}",
        code=f"OW{suffix}",
        billing_mode=BILLING_MODE_CREDIT,
        status=True,
        credit_policy_json={"credits_per_yuan": 4.2},
    )
    other = Tenant(
        name=f"other-{suffix}",
        code=f"OT{suffix}",
        billing_mode=BILLING_MODE_CREDIT,
        status=True,
    )
    user = User(
        username=f"owner_u_{suffix}",
        password_hash="x",
        display_name="owner",
        status=True,
    )
    db.add_all([owner, other, user])
    db.flush()
    order = create_credit_recharge_order(
        db,
        tenant=owner,
        payer_user_id=user.id,
        yuan_amount=10,
        pay_channel="wechat",
    )
    with pytest.raises(ValueError, match="订单不存在"):
        get_credit_recharge_order_status(
            db,
            out_trade_no=order["out_trade_no"],
            tenant_id=other.id,
        )
