from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

__all__ = ["H5DiagnosisOrder"]


class H5DiagnosisOrder(Base):
    """9.9 元 H5 付费售前诊断订单。"""

    __tablename__ = "geo_h5_diagnosis_order"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    out_trade_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    openid: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    wechat_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="用户填写的微信号，供销售跟进")
    contact_phone: Mapped[str] = mapped_column(String(30), nullable=False)
    brand_name: Mapped[str] = mapped_column(String(100), nullable=False)
    form_json: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("(JSON_OBJECT())"),
        comment="行业/产品/官网等扩展字段",
    )
    prompts_json: Mapped[list] = mapped_column(JSON, nullable=False)
    platforms_json: Mapped[list] = mapped_column(JSON, nullable=False)
    schedule_days: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default=text("3"))
    amount_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=990, server_default=text("990"))
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        server_default="pending",
        index=True,
        comment="pending/paid/failed/closed",
    )
    prepay_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    wx_transaction_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    lead_diagnosis_id: Mapped[int | None] = mapped_column(
        ForeignKey("geo_lead_diagnosis.id"),
        nullable=True,
        index=True,
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 2026-09-01 - H5 自助结果页短链鉴权 + ready 短信幂等
    result_access_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    result_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sms_ready_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sms_ready_last_error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
