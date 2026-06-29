from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BrandDiagnosis(Base):
    __table_args__ = {"extend_existing": True}
    __tablename__ = "geo_brand_diagnosis"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="诊断ID")
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="被诊断企业ID")
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="诊断人用户ID")
    diagnosis_title: Mapped[str] = mapped_column(String(120), nullable=False, comment="诊断标题")
    health_score: Mapped[int] = mapped_column(Integer, nullable=False, comment="健康分0-100")
    sentiment_summary: Mapped[str | None] = mapped_column(String(300), nullable=True, comment="口碑情绪总结")
    strength_points: Mapped[str | None] = mapped_column(Text, nullable=True, comment="优势点")
    weakness_points: Mapped[str | None] = mapped_column(Text, nullable=True, comment="劣势和改善点")
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True, comment="诊断建议")
    diagnosis_platforms_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="诊断涉及平台列表")
    diagnosis_keywords_json: Mapped[list] = mapped_column(JSON, nullable=True, comment="诊断关键词")
    reference_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="引用来源数量")
    monitor_data_summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="监测数据摘要")
    report_url: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="报告导出链接")
    status: Mapped[str] = mapped_column(String(20), server_default="draft", nullable=False, comment="状态")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="逻辑删除")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间")
