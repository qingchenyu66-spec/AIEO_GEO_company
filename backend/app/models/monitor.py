from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class GeoMonitorTask(Base):
    """本地监控主任务，保存模力指数主任务和我方业务归属。"""

    __tablename__ = "geo_monitor_task"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="本地主任务ID")
    task_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False, comment="模力指数主任务ID")
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("sys_tenant.id"), index=True, nullable=True, comment="所属企业ID")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"), index=True, nullable=True, comment="创建人用户ID")
    monitor_keywords: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="监控品牌或关键词")
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, comment="主任务状态")
    total_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="子任务总数")
    completed_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="已完成子任务数")
    failed_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="失败子任务数")
    prompts_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="提交的问题列表JSON")
    platforms_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="提交的平台配置JSON")
    region_code_json: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="提交的地区编码JSON")
    callback_url: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="本次任务回调地址")
    poll_url: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="远端轮询地址")
    remote_created_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="远端创建时间毫秒时间戳")
    remote_completed_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="远端完成时间毫秒时间戳")
    raw_request_json: Mapped[dict] = mapped_column(JSON, nullable=False, comment="提交给模力指数的原始请求JSON")
    raw_response_json: Mapped[dict] = mapped_column(JSON, nullable=False, comment="模力指数提交任务原始响应JSON")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="最近一次同步或提交错误")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False, comment="逻辑删除")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="本地创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, comment="本地更新时间")

    subtasks: Mapped[list["GeoMonitorSubtask"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class GeoMonitorSubtask(Base):
    """本地监控子任务，保存每个平台每个问题的完整回答结果。"""

    __tablename__ = "geo_monitor_subtask"
    __table_args__ = (UniqueConstraint("subtask_id", name="uk_geo_monitor_subtask_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="本地子任务ID")
    subtask_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="模力指数子任务ID")
    task_id: Mapped[str] = mapped_column(ForeignKey("geo_monitor_task.task_id"), index=True, nullable=False, comment="模力指数主任务ID")
    platform: Mapped[str] = mapped_column(String(50), index=True, nullable=False, comment="AI平台编码")
    mode: Mapped[str] = mapped_column(String(50), nullable=False, comment="监控模式")
    prompt: Mapped[str] = mapped_column(Text, nullable=False, comment="检测问题")
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, comment="子任务状态")
    remote_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="远端完成时间毫秒时间戳")
    page_screenshot: Mapped[str | None] = mapped_column(String(1000), nullable=True, comment="网页快照或截图URL")
    answer_content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="AI回答原文")
    reference_list_json: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="全部引用来源JSON")
    citation_list_json: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="真实引用来源JSON")
    reasoning_process_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="推理过程JSON")
    recommended_questions_json: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="推荐追问JSON")
    media_content_json: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="媒体内容JSON")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="子任务失败原因")
    proxy_ip: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="执行代理IP")
    amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True, comment="本子任务扣费金额")
    mention_position: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="监控词提及位置")
    mention_context: Mapped[str | None] = mapped_column(Text, nullable=True, comment="监控词提及上下文")
    sentiment: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="情感倾向")
    competitor_rankings_json: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="竞品排名JSON")
    all_rankings_json: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="全部品牌排名JSON")
    raw_result_json: Mapped[dict] = mapped_column(JSON, nullable=False, comment="子任务原始结果JSON")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, comment="本地更新时间")

    task: Mapped[GeoMonitorTask] = relationship(back_populates="subtasks")


class GeoMonitorDailyStat(Base):
    """企业 × 日期 × 平台的监测预聚合统计。"""

    __tablename__ = "geo_monitor_daily_stat"
    __table_args__ = (
        UniqueConstraint("tenant_id", "stat_date", "platform", name="uk_geo_monitor_daily_stat"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("sys_tenant.id"), index=True, nullable=False)
    stat_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    completed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mentioned_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    top3_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rank_sum: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rank_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    citation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class GeoMonitorCallbackEvent(Base):
    """模力指数回调事件，做幂等和问题追踪。"""

    __tablename__ = "geo_monitor_callback_event"
    __table_args__ = (UniqueConstraint("payload_hash", name="uk_geo_callback_payload_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="回调事件ID")
    task_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False, comment="模力指数主任务ID")
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False, comment="回调内容SHA256哈希")
    process_status: Mapped[str] = mapped_column(String(32), default="processed", nullable=False, comment="处理状态")
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, comment="回调原始JSON")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="处理失败原因")
    received_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="接收时间")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="处理完成时间")


class GeoMonitorScheduleRun(Base):
    """企业定时监测执行记录，用唯一调度键避免同一时间窗口重复提交任务。"""

    __tablename__ = "geo_monitor_schedule_run"
    __table_args__ = (UniqueConstraint("tenant_id", "schedule_key", name="uk_geo_schedule_tenant_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="调度执行记录ID")
    tenant_id: Mapped[int] = mapped_column(ForeignKey("sys_tenant.id"), index=True, nullable=False, comment="所属企业ID")
    schedule_key: Mapped[str] = mapped_column(String(80), nullable=False, comment="调度窗口唯一键，例如20260624-0930")
    task_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True, comment="提交成功后的模力指数主任务ID")
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, comment="调度状态：submitted、skipped、failed")
    prompt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="本次提交问题数量")
    platform_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="本次提交平台数量")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="提交失败原因")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"), index=True, nullable=True, comment="触发调度的用户ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="调度创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, comment="调度更新时间")
