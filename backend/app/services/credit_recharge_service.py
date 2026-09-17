"""客户算力中心在线充值（微信 Native / 支付宝当面付）。"""

from __future__ import annotations

import secrets
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.credit_recharge_order import CreditRechargeOrder
from app.models.tenant import Tenant
from app.services.alipay_pay_service import AlipayPayError, create_precreate_qr_code
from app.services.credit_service import (
    credits_from_yuan,
    is_credit_tenant,
    merge_credit_policy,
    recharge_credits,
    tenant_available_credits,
)
from app.services.wechat_pay_service import WechatPayError, create_native_code_url

OUT_TRADE_PREFIX = "CR"
MIN_YUAN = Decimal("1")
MAX_YUAN = Decimal("50000")


def is_credit_recharge_out_trade_no(out_trade_no: str) -> bool:
    return str(out_trade_no or "").strip().upper().startswith(OUT_TRADE_PREFIX)


def _gen_out_trade_no() -> str:
    return f"{OUT_TRADE_PREFIX}{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{secrets.token_hex(4).upper()}"[:32]


def _normalize_yuan(yuan: Decimal | float | int | str) -> Decimal:
    value = Decimal(str(yuan)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if value < MIN_YUAN:
        raise ValueError(f"最低充值 {MIN_YUAN} 元")
    if value > MAX_YUAN:
        raise ValueError(f"单笔最高 {MAX_YUAN} 元")
    return value


def _order_status_payload(order: CreditRechargeOrder, tenant: Tenant | None = None) -> dict[str, Any]:
    available = None
    if tenant is not None:
        available = float(tenant_available_credits(tenant))
    return {
        "out_trade_no": order.out_trade_no,
        "status": order.status,
        "pay_channel": order.pay_channel,
        "yuan_amount": float(order.yuan_amount),
        "credits_amount": float(order.credits_amount),
        "credits_per_yuan": float(order.credits_per_yuan_locked),
        "code_url": order.code_url,
        "paid_at": order.paid_at.isoformat(sep=" ", timespec="seconds") if order.paid_at else None,
        "available": available,
    }


def create_credit_recharge_order(
    db: Session,
    *,
    tenant: Tenant,
    payer_user_id: int,
    yuan_amount: Decimal | float | int | str,
    pay_channel: str,
) -> dict[str, Any]:
    if not is_credit_tenant(tenant):
        raise ValueError("当前企业为托管模式，无法在线充值")
    if not tenant.status:
        raise ValueError("企业服务已停服")

    channel = str(pay_channel or "").strip().lower()
    if channel not in {"wechat", "alipay"}:
        raise ValueError("请选择微信支付或支付宝")

    yuan = _normalize_yuan(yuan_amount)
    policy = merge_credit_policy(tenant.credit_policy_json)
    rate = Decimal(str(policy.get("credits_per_yuan") or 4.2))
    if rate <= 0:
        raise ValueError("企业汇率无效")
    credits = credits_from_yuan(tenant, yuan)
    if credits <= 0:
        raise ValueError("换算算力无效")

    amount_fen = int((yuan * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    out_trade_no = _gen_out_trade_no()
    subject = f"GEO算力充值-{tenant.name}"[:120]

    order = CreditRechargeOrder(
        out_trade_no=out_trade_no,
        tenant_id=tenant.id,
        payer_user_id=payer_user_id,
        yuan_amount=yuan,
        credits_amount=credits,
        credits_per_yuan_locked=rate,
        amount_fen=amount_fen,
        pay_channel=channel,
        status="pending",
        code_url=None,
    )
    db.add(order)
    db.flush()

    try:
        if channel == "wechat":
            code_url = create_native_code_url(
                out_trade_no=out_trade_no,
                amount_fen=amount_fen,
                description=subject,
            )
        else:
            code_url = create_precreate_qr_code(
                out_trade_no=out_trade_no,
                amount_fen=amount_fen,
                subject=subject,
            )
    except (WechatPayError, AlipayPayError) as exc:
        order.status = "closed"
        db.commit()
        raise ValueError(str(exc)) from exc

    order.code_url = code_url
    db.commit()
    db.refresh(order)

    payload = _order_status_payload(order, tenant)
    payload["dev_auto_paid"] = bool(
        (channel == "wechat" and settings.wechat_pay_dev_mode)
        or (channel == "alipay" and settings.alipay_dev_mode)
    )
    return payload


def get_credit_recharge_order_status(
    db: Session,
    *,
    out_trade_no: str,
    tenant_id: int,
) -> dict[str, Any]:
    order = db.scalar(
        select(CreditRechargeOrder).where(CreditRechargeOrder.out_trade_no == out_trade_no)
    )
    if order is None or order.tenant_id != tenant_id:
        raise ValueError("订单不存在")
    tenant = db.get(Tenant, tenant_id)
    return _order_status_payload(order, tenant)


def fulfill_credit_recharge_order_paid(
    db: Session,
    *,
    out_trade_no: str,
    transaction_id: str = "",
) -> dict[str, Any]:
    order = db.scalar(
        select(CreditRechargeOrder)
        .where(CreditRechargeOrder.out_trade_no == out_trade_no)
        .with_for_update()
    )
    if order is None:
        raise ValueError("订单不存在")

    tenant = db.scalar(select(Tenant).where(Tenant.id == order.tenant_id).with_for_update())
    if tenant is None:
        raise ValueError("企业不存在")

    if order.status == "paid" and order.ledger_id:
        return _order_status_payload(order, tenant)

    tx_id = str(transaction_id or "").strip()
    if tx_id:
        order.transaction_id = tx_id

    if order.status != "paid":
        row = recharge_credits(
            db,
            tenant,
            Decimal(str(order.credits_amount)),
            operator_user_id=order.payer_user_id,
            reason="在线充值",
            ref_type="online_pay",
            ref_id=order.out_trade_no,
            detail_json={
                "out_trade_no": order.out_trade_no,
                "pay_channel": order.pay_channel,
                "yuan_amount": float(order.yuan_amount),
                "credits_per_yuan": float(order.credits_per_yuan_locked),
                "transaction_id": tx_id or None,
            },
        )
        order.ledger_id = row.id
        order.status = "paid"
        order.paid_at = datetime.utcnow()

    db.commit()
    db.refresh(order)
    return _order_status_payload(order, tenant)


def mark_credit_recharge_order_paid_dev(db: Session, out_trade_no: str) -> dict[str, Any]:
    if not (settings.wechat_pay_dev_mode or settings.alipay_dev_mode):
        raise ValueError("仅开发模式可用")
    return fulfill_credit_recharge_order_paid(
        db,
        out_trade_no=out_trade_no,
        transaction_id=f"DEV-{out_trade_no}",
    )
