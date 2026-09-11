from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# settle_cell_credit_cap：同格（含自动重试）实扣算力上限（绝对值，默认 2），不是「2×单价」
# 2026-09-07 - 方案 A：词/场次/地区配额退役，默认策略只留汇率与结算封顶
DEFAULT_CREDIT_POLICY = {
    "credits_per_yuan": 4.2,
    "settle_cell_credit_cap": 2,
}


class Tenant(Base):
    __tablename__ = "sys_tenant"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="企业名称")
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False, comment="企业编码")
    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    owner_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sys_user.id"), index=True, nullable=True, comment="归属销售/创建人用户ID")
    service_start_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="服务开始日期")
    service_end_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="服务结束日期")
    stop_reason: Mapped[str | None] = mapped_column(String(30), nullable=True, comment="停服原因：manual人工停服、canceled未开始取消、expired到期")
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="停服时间")
    stopped_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("sys_user.id"), nullable=True, comment="停服操作人ID")
    logo_path: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="企业 Logo 相对路径")
    logo_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="企业 Logo 更新时间")
    # 2026-08-27 - 算力自助一期 - hosted 不扣客户算力；credit 走双闸
    billing_mode: Mapped[str] = mapped_column(
        String(20),
        default="hosted",
        server_default="hosted",
        index=True,
        nullable=False,
        comment="hosted 托管 | credit 算力自助",
    )
    credit_balance: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        default=Decimal("0"),
        server_default=text("0"),
        nullable=False,
        comment="可用算力余额",
    )
    credit_reserved: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        default=Decimal("0"),
        server_default=text("0"),
        nullable=False,
        comment="预扣锁定中",
    )
    credit_policy_json: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: dict(DEFAULT_CREDIT_POLICY),
        # 2026-09-08 - 方案 A：仅留汇率/结算封顶等；词数场次地区配额已退役
        comment="算力策略（汇率、单格封顶等；配额键已废弃）",
    )
    platform_whitelist_json: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default=text("(JSON_ARRAY())"),
        # 2026-09-08 - 方案 A：列保留兼容旧数据，业务一律当空，不可再写入非空
        comment="已废弃：历史平台白名单，现网恒为空",
    )
    # 2026-09-01 - 商品卡进门户一期 - 按企业开通，默认关；需日常词组含手机端才有数据
    goods_card_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("0"),
        nullable=False,
        comment="是否开通客户门户商品卡分析",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False, comment="逻辑删除")

    identities: Mapped[list["UserIdentity"]] = relationship(back_populates="tenant")


from app.models.user_identity import UserIdentity  # noqa: E402
