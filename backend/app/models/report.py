from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class GeoReport(Base):
    """报告中心——存储生成的品牌诊断报告和周期性报告。"""

    __tablename__ = "geo_report"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="报告ID")
    tenant_id: Mapped[int] = mapped_column(ForeignKey("sys_tenant.id"), index=True, nullable=False, comment="所属企业ID")
    report_title: Mapped[str] = mapped_column(String(200), nullable=False, comment="报告标题")
    report_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True, comment="报告类型: diagnosis/weekly/monthly/quarterly/annual/completion")
    status: Mapped[str] = mapped_column(String(20), default="published", nullable=False, comment="状态: published/archived（历史 draft 已退役）")
    period_key: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True, comment="周期报告幂等键，如 monthly:2026-07")
    data_summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="数据摘要")
    report_content_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="报告正文JSON")
    report_url: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="报告导出链接")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"), index=True, nullable=True, comment="创建人用户ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False, comment="逻辑删除")
