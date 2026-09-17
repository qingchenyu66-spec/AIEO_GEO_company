from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

__all__ = ["CreditRechargeOrder"]


class CreditRechargeOrder(Base):
    """客户算力中心在线充值订单（微信 Native / 支付宝当面付）。"""

    __tablename__ = "geo_credit_recharge_order"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    out_trade_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("sys_tenant.id"), index=True, nullable=False)
    payer_user_id: Mapped[int] = mapped_column(ForeignKey("sys_user.id"), index=True, nullable=False)
    yuan_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    credits_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    credits_per_yuan_locked: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    amount_fen: Mapped[int] = mapped_column(Integer, nullable=False)
    pay_channel: Mapped[str] = mapped_column(String(20), nullable=False, comment="wechat/alipay")
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        server_default="pending",
        index=True,
        comment="pending/paid/closed",
    )
    code_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ledger_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
