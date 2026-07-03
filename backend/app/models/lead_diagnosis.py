from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.lead_diagnosis_config import DEFAULT_LEAD_SCHEDULE_TIMES, LEAD_SCHEDULE_DAYS

__all__ = ["DEFAULT_LEAD_SCHEDULE_TIMES", "LEAD_SCHEDULE_DAYS", "LeadDiagnosis", "LeadDiagnosisRun"]


class LeadDiagnosis(Base):
    """售前线索诊断：不绑定正式企业，连续三天各三时段共九次抓取后汇总。"""

    __tablename__ = "geo_lead_diagnosis"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="售前诊断ID")
    brand_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="品牌名称")
    contact_name: Mapped[str | None] = mapped_column(String(60), nullable=True, comment="联系人姓名")
    contact_phone: Mapped[str | None] = mapped_column(String(30), nullable=True, comment="联系电话")
    contact_note: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="销售备注")
    prompts_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="检测问题列表，最多5条")
    competitors_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="竞品名称列表")
    region_code: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="监测地区编码，空值代表全部区域")
    schedule_times_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="每日抓取时段")
    diagnosis_date: Mapped[date] = mapped_column(Date, index=True, nullable=False, comment="诊断日期")
    status: Mapped[str] = mapped_column(
        String(20),
        index=True,
        server_default="pending",
        nullable=False,
        comment="pending/collecting/ready/failed",
    )
    health_score: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="健康分0-100")
    diagnosis_result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="汇总诊断结果")
    converted_tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("sys_tenant.id"),
        index=True,
        nullable=True,
        comment="转化后的企业ID",
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("sys_user.id"),
        index=True,
        nullable=True,
        comment="创建人用户ID",
    )
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="逻辑删除")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
    )

    runs: Mapped[list["LeadDiagnosisRun"]] = relationship(back_populates="lead", cascade="all, delete-orphan")


class LeadDiagnosisRun(Base):
    """售前诊断单次时段抓取记录。"""

    __tablename__ = "geo_lead_diagnosis_run"
    __table_args__ = (UniqueConstraint("lead_diagnosis_id", "schedule_key", name="uk_lead_diag_schedule_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="抓取记录ID")
    lead_diagnosis_id: Mapped[int] = mapped_column(
        ForeignKey("geo_lead_diagnosis.id"),
        index=True,
        nullable=False,
        comment="所属售前诊断ID",
    )
    schedule_key: Mapped[str] = mapped_column(String(80), nullable=False, comment="时段唯一键")
    schedule_label: Mapped[str] = mapped_column(String(40), nullable=False, comment="时段展示名")
    task_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True, comment="模力指数主任务ID")
    status: Mapped[str] = mapped_column(
        String(32),
        index=True,
        nullable=False,
        comment="pending/submitted/completed/failed/skipped",
    )
    prompt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="提交问题数")
    platform_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="提交平台数")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="失败原因")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
    )

    lead: Mapped[LeadDiagnosis] = relationship(back_populates="runs")
