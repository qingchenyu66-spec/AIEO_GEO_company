"""支付回调守卫（第一阶段）。

契约要点：
- 微信：原始 body + Wechatpay-* 头验平台签名，再用 APIv3 密钥解密
- 支付宝：RSA2 + out_trade_no/total_amount/seller_id/app_id
- 业务对账：金额、渠道、交易号；已支付订单按交易号幂等/拒异/空号兼容
- H5 渠道以 form_json.pay_channel 为准，不得仅按入口推断

残余风险（必须在 PR 标明）：
应用层两表查重无法彻底消除并发双写；跨表也无法靠两张表各自唯一键保证全局唯一。
强保证需要统一支付交易绑定表或经批准的全局互斥，不在本阶段范围。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.credit_recharge_order import CreditRechargeOrder
from app.models.h5_diagnosis_order import H5DiagnosisOrder
from app.services.alipay_pay_service import verify_notify_signature
from app.services.credit_recharge_service import (
    fulfill_credit_recharge_order_paid,
    is_credit_recharge_out_trade_no,
)
from app.services.h5_diagnosis_service import fulfill_h5_order_paid
from app.services.wechat_pay_service import (
    WechatPayError,
    decrypt_notify_resource,
    verify_wechat_platform_notify,
)

logger = logging.getLogger(__name__)

PayChannel = Literal["wechat", "alipay"]
OrderKind = Literal["credit", "h5"]


class PaymentNotifyReject(Exception):
    """回调校验失败：调用方映射为渠道要求的失败响应。"""

    def __init__(self, reason: str, *, security_event: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.security_event = security_event


@dataclass(frozen=True)
class NotifyFulfillResult:
    kind: OrderKind
    out_trade_no: str
    status: str
    payload: dict[str, Any] | None = None


def _log_security(event: str, *, channel: PayChannel, out_trade_no: str = "", detail: str = "") -> None:
    # 禁止记录签名、密钥、完整请求、手机号等个人信息
    logger.warning(
        "payment_notify_security event=%s channel=%s out_trade_no=%s detail=%s",
        event,
        channel,
        out_trade_no or "-",
        (detail or "-")[:120],
    )


def _yuan_to_fen(total_amount: str) -> int:
    text = str(total_amount or "").strip()
    if not text:
        raise PaymentNotifyReject("缺少 total_amount")
    try:
        # 支付宝金额为元，两位小数
        fen = int(round(float(text) * 100))
    except ValueError as exc:
        raise PaymentNotifyReject("total_amount 非法") from exc
    if fen < 0:
        raise PaymentNotifyReject("total_amount 非法")
    return fen


def resolve_order_kind(out_trade_no: str) -> OrderKind:
    return "credit" if is_credit_recharge_out_trade_no(out_trade_no) else "h5"


def load_order_for_update(db: Session, *, kind: OrderKind, out_trade_no: str):
    if kind == "credit":
        order = db.scalar(
            select(CreditRechargeOrder)
            .where(CreditRechargeOrder.out_trade_no == out_trade_no)
            .with_for_update()
        )
    else:
        order = db.scalar(
            select(H5DiagnosisOrder).where(H5DiagnosisOrder.out_trade_no == out_trade_no).with_for_update()
        )
    if order is None:
        raise PaymentNotifyReject("订单不存在")
    return order


def order_pay_channel(order: CreditRechargeOrder | H5DiagnosisOrder) -> str:
    if isinstance(order, CreditRechargeOrder):
        return str(order.pay_channel or "").strip().lower()
    if isinstance(order, H5DiagnosisOrder):
        form = order.form_json if isinstance(order.form_json, dict) else {}
        return str(form.get("pay_channel") or "").strip().lower()
    if hasattr(order, "form_json"):
        form = order.form_json if isinstance(order.form_json, dict) else {}
        return str(form.get("pay_channel") or "").strip().lower()
    return str(getattr(order, "pay_channel", "") or "").strip().lower()


def order_amount_fen(order: CreditRechargeOrder | H5DiagnosisOrder) -> int:
    return int(order.amount_fen or 0)


def order_stored_transaction_id(order: CreditRechargeOrder | H5DiagnosisOrder) -> str:
    if isinstance(order, CreditRechargeOrder):
        return str(order.transaction_id or "").strip()
    if isinstance(order, H5DiagnosisOrder):
        return str(order.wx_transaction_id or "").strip()
    if hasattr(order, "wx_transaction_id"):
        return str(getattr(order, "wx_transaction_id", "") or "").strip()
    return str(getattr(order, "transaction_id", "") or "").strip()


def order_is_paid(order: CreditRechargeOrder | H5DiagnosisOrder) -> bool:
    if isinstance(order, CreditRechargeOrder):
        return order.status == "paid" and bool(order.ledger_id)
    if isinstance(order, H5DiagnosisOrder):
        return order.status == "paid" and bool(order.lead_diagnosis_id)
    if hasattr(order, "ledger_id"):
        return order.status == "paid" and bool(order.ledger_id)
    return order.status == "paid" and bool(getattr(order, "lead_diagnosis_id", None))


def assert_channel_match(*, order: CreditRechargeOrder | H5DiagnosisOrder, entry_channel: PayChannel) -> None:
    expected = order_pay_channel(order)
    if not expected:
        raise PaymentNotifyReject("订单缺少 pay_channel")
    if expected != entry_channel:
        _log_security("channel_mismatch", channel=entry_channel, out_trade_no=order.out_trade_no, detail=expected)
        raise PaymentNotifyReject("支付渠道与订单不一致", security_event="channel_mismatch")


def assert_transaction_not_occupied(
    db: Session,
    *,
    channel: PayChannel,
    transaction_id: str,
    out_trade_no: str,
) -> None:
    """应用层占用检查。残余风险：无法消除并发双写；跨表亦无 DB 强唯一。"""
    tx = str(transaction_id or "").strip()
    if not tx:
        raise PaymentNotifyReject("交易号为空")

    credit_hit = db.scalar(
        select(CreditRechargeOrder).where(
            CreditRechargeOrder.transaction_id == tx,
            CreditRechargeOrder.out_trade_no != out_trade_no,
        )
    )
    if credit_hit is not None:
        # 渠道语义：积分单本身带 pay_channel；跨表冲突一律拒绝
        _log_security(
            "transaction_occupied",
            channel=channel,
            out_trade_no=out_trade_no,
            detail="credit",
        )
        raise PaymentNotifyReject("第三方交易号已绑定其他订单", security_event="transaction_occupied")

    h5_hit = db.scalar(
        select(H5DiagnosisOrder).where(
            H5DiagnosisOrder.wx_transaction_id == tx,
            H5DiagnosisOrder.out_trade_no != out_trade_no,
        )
    )
    if h5_hit is not None:
        _log_security(
            "transaction_occupied",
            channel=channel,
            out_trade_no=out_trade_no,
            detail="h5",
        )
        raise PaymentNotifyReject("第三方交易号已绑定其他订单", security_event="transaction_occupied")


def evaluate_paid_order_transaction(
    *,
    order: CreditRechargeOrder | H5DiagnosisOrder,
    transaction_id: str,
    channel: PayChannel,
) -> Literal["idempotent", "bind_empty", "proceed"]:
    """已支付订单交易号规则：同号幂等；异号拒绝；空号兼容绑定。"""
    if not order_is_paid(order):
        return "proceed"
    stored = order_stored_transaction_id(order)
    tx = str(transaction_id or "").strip()
    if stored and stored == tx:
        return "idempotent"
    if stored and stored != tx:
        _log_security(
            "paid_tx_mismatch",
            channel=channel,
            out_trade_no=order.out_trade_no,
            detail="mismatch",
        )
        raise PaymentNotifyReject("已支付订单交易号不一致", security_event="paid_tx_mismatch")
    # stored empty
    if not tx:
        raise PaymentNotifyReject("已支付订单缺少可绑定交易号")
    return "bind_empty"


def _fulfill(
    db: Session,
    *,
    kind: OrderKind,
    out_trade_no: str,
    transaction_id: str,
) -> dict[str, Any]:
    if kind == "credit":
        return fulfill_credit_recharge_order_paid(db, out_trade_no=out_trade_no, transaction_id=transaction_id)
    return fulfill_h5_order_paid(db, out_trade_no=out_trade_no, transaction_id=transaction_id)


def process_wechat_pay_notify(db: Session, *, body: bytes, headers: Any) -> NotifyFulfillResult | None:
    """处理微信回调。返回 None 表示可忽略（非 SUCCESS），不履约。"""
    if settings.wechat_pay_dev_mode:
        # 本地联调跳过平台签；生产必须关闭 DEV 并配置平台证书/公钥
        pass
    else:
        try:
            verify_wechat_platform_notify(headers=headers, body=body)
        except WechatPayError as exc:
            _log_security("wechat_signature_failed", channel="wechat", detail=str(exc))
            raise PaymentNotifyReject(str(exc), security_event="wechat_signature_failed") from exc

    try:
        payload = json.loads(body.decode("utf-8"))
        resource = payload.get("resource") or {}
        plain = decrypt_notify_resource(resource if isinstance(resource, dict) else {})
    except Exception as exc:
        raise PaymentNotifyReject("invalid notify") from exc

    if str(plain.get("trade_state") or "").strip() != "SUCCESS":
        return None

    out_trade_no = str(plain.get("out_trade_no") or "").strip()
    transaction_id = str(plain.get("transaction_id") or "").strip()
    if not out_trade_no:
        raise PaymentNotifyReject("missing out_trade_no")
    if not transaction_id:
        raise PaymentNotifyReject("交易号为空")

    amount = plain.get("amount") if isinstance(plain.get("amount"), dict) else {}
    try:
        paid_fen = int(amount.get("total"))
    except (TypeError, ValueError) as exc:
        raise PaymentNotifyReject("amount.total 非法") from exc
    currency = str(amount.get("currency") or "").strip().upper()
    if currency != "CNY":
        raise PaymentNotifyReject("amount.currency 必须为 CNY")
    appid = str(plain.get("appid") or "").strip()
    mchid = str(plain.get("mchid") or "").strip()
    if appid != str(settings.wechat_pay_app_id or "").strip():
        raise PaymentNotifyReject("appid 不匹配")
    if mchid != str(settings.wechat_pay_mch_id or "").strip():
        raise PaymentNotifyReject("mchid 不匹配")

    kind = resolve_order_kind(out_trade_no)
    order = load_order_for_update(db, kind=kind, out_trade_no=out_trade_no)
    assert_channel_match(order=order, entry_channel="wechat")
    if paid_fen != order_amount_fen(order):
        _log_security("amount_mismatch", channel="wechat", out_trade_no=out_trade_no)
        raise PaymentNotifyReject("实付金额与订单不一致", security_event="amount_mismatch")

    paid_action = evaluate_paid_order_transaction(order=order, transaction_id=transaction_id, channel="wechat")
    assert_transaction_not_occupied(
        db, channel="wechat", transaction_id=transaction_id, out_trade_no=out_trade_no
    )
    payload = _fulfill(db, kind=kind, out_trade_no=out_trade_no, transaction_id=transaction_id)
    return NotifyFulfillResult(kind=kind, out_trade_no=out_trade_no, status=paid_action, payload=payload)


def process_alipay_notify(db: Session, *, params: dict[str, Any]) -> NotifyFulfillResult | None:
    """处理支付宝异步通知。返回 None 表示可忽略（非成功状态）。"""
    if not verify_notify_signature(params):
        _log_security("alipay_signature_failed", channel="alipay")
        raise PaymentNotifyReject("支付宝签名校验失败", security_event="alipay_signature_failed")

    trade_status = str(params.get("trade_status") or "").strip()
    if trade_status not in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
        return None

    out_trade_no = str(params.get("out_trade_no") or "").strip()
    trade_no = str(params.get("trade_no") or "").strip()
    if not out_trade_no:
        raise PaymentNotifyReject("missing out_trade_no")
    if not trade_no:
        raise PaymentNotifyReject("交易号为空")

    app_id = str(params.get("app_id") or "").strip()
    seller_id = str(params.get("seller_id") or "").strip()
    expected_app = str(settings.alipay_app_id or "").strip()
    expected_seller = str(settings.alipay_seller_id or "").strip()
    if not expected_seller:
        raise PaymentNotifyReject("未配置 ALIPAY_SELLER_ID")
    if app_id != expected_app:
        raise PaymentNotifyReject("app_id 不匹配")
    if seller_id != expected_seller:
        raise PaymentNotifyReject("seller_id 不匹配")

    paid_fen = _yuan_to_fen(str(params.get("total_amount") or ""))
    kind = resolve_order_kind(out_trade_no)
    order = load_order_for_update(db, kind=kind, out_trade_no=out_trade_no)
    assert_channel_match(order=order, entry_channel="alipay")
    if paid_fen != order_amount_fen(order):
        _log_security("amount_mismatch", channel="alipay", out_trade_no=out_trade_no)
        raise PaymentNotifyReject("实付金额与订单不一致", security_event="amount_mismatch")

    # 通知里的 out_trade_no 已用于查单；再显式核对字段存在
    if str(params.get("out_trade_no") or "").strip() != order.out_trade_no:
        raise PaymentNotifyReject("out_trade_no 不匹配")

    paid_action = evaluate_paid_order_transaction(order=order, transaction_id=trade_no, channel="alipay")
    assert_transaction_not_occupied(db, channel="alipay", transaction_id=trade_no, out_trade_no=out_trade_no)
    payload = _fulfill(db, kind=kind, out_trade_no=out_trade_no, transaction_id=trade_no)
    return NotifyFulfillResult(kind=kind, out_trade_no=out_trade_no, status=paid_action, payload=payload)
