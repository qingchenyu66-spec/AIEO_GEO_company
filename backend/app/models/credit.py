from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# 2026-08-27 - 算力自助一期 - 账本/单价/block/terms 与 billing_mode 切换留痕


# 2026-08-28 - MySQL UNIQUE 对 NULL 无效 - 归一键供唯一约束
CREDIT_PRICE_DEFAULT_PLATFORM_KEY = "__default__"
CREDIT_PRICE_GLOBAL_TENANT_KEY = 0


class TenantCreditCellFinalize(Base):
    """按格 settle/release 幂等表（同租户+批次+原格只落一次）。"""

    __tablename__ = "geo_tenant_credit_cell_finalize"
    __table_args__ = (
        UniqueConstraint("tenant_id", "batch_ref", "origin_subtask_id", name="uk_credit_cell_finalize"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("sys_tenant.id"), index=True, nullable=False)
    batch_ref: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    origin_subtask_id: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="settle/release/skipped")
    credits: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    ledger_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class TenantCreditLedger(Base):
    """企业算力流水（只追加）。"""

    __tablename__ = "geo_tenant_credit_ledger"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("sys_tenant.id"), index=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, comment="正=入账/释放，负=扣减/预扣")
    balance_after: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, comment="本条事后可用余额")
    entry_type: Mapped[str] = mapped_column(String(20), index=True, nullable=False, comment="recharge/adjust/reserve/settle/release")
    ref_type: Mapped[str | None] = mapped_column(String(40), nullable=True, comment="subtask/batch/manual/reserve_batch")
    ref_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    platform_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    keyword: Mapped[str | None] = mapped_column(String(200), nullable=True)
    window_key: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    region_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    operator_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sys_user.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reserve_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="预扣过期时间，TTL 自动 release")
    detail_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="按格 settle 明细等")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class CreditPriceRule(Base):
    """算力单价：global/tenant × 平台（空=默认）。"""

    __tablename__ = "geo_credit_price_rule"
    __table_args__ = (
        UniqueConstraint("scope", "tenant_key", "platform_key", name="uk_credit_price_rule_scope"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, comment="global | tenant")
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("sys_tenant.id"), index=True, nullable=True)
    tenant_key: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=CREDIT_PRICE_GLOBAL_TENANT_KEY,
        server_default="0",
        comment="global=0；tenant=tenant_id",
    )
    platform_code: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="空=默认价；deep_think_addon/chatgpt 等")
    platform_key: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=CREDIT_PRICE_DEFAULT_PLATFORM_KEY,
        server_default=CREDIT_PRICE_DEFAULT_PLATFORM_KEY,
        comment="空平台归一为 __default__，供唯一约束",
    )
    credits_per_subtask: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class CreditSubmitBlock(Base):
    """监测窗口未提交记录（客户算力不足或平台真金不足）。"""

    __tablename__ = "geo_credit_submit_block"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("sys_tenant.id"), index=True, nullable=False)
    window_key: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    block_reason: Mapped[str] = mapped_column(String(30), index=True, nullable=False, comment="tenant_credit | platform_balance")
    required_credits: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    available_credits: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    platform_balance_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    platform_required_estimate: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    tenant_notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ops_notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class BillingModeChangeLog(Base):
    """托管 ↔ 算力自助切换审计。"""

    __tablename__ = "geo_billing_mode_change_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("sys_tenant.id"), index=True, nullable=False)
    from_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    to_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    contract_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    operator_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("sys_user.id"), nullable=False)
    effective_policy: Mapped[str] = mapped_column(String(20), default="next_window", nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    credit_balance_action: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="none/freeze/zero_adjust")
    opening_credit_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    daily_estimate_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class CreditTermsVersion(Base):
    """算力/计费规则声明版本。"""

    __tablename__ = "geo_credit_terms_version"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    version_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content_html: Mapped[str] = mapped_column(Text, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    notice_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, comment="draft | published")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class CreditTermsAck(Base):
    """企业管理员确认规则声明。"""

    __tablename__ = "geo_tenant_credit_terms_ack"
    __table_args__ = (UniqueConstraint("tenant_id", "terms_version_id", name="uk_tenant_credit_terms_ack"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("sys_tenant.id"), index=True, nullable=False)
    terms_version_id: Mapped[int] = mapped_column(ForeignKey("geo_credit_terms_version.id"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("sys_user.id"), nullable=False)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
