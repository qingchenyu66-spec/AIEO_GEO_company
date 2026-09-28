"""GEO 选词历史任务与范例库(运营工作台)."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class GeoKeywordMinerJob(Base):
    """平台运营 GEO 选词任务历史, 落 GEO 主库 MySQL."""

    __tablename__ = "geo_keyword_miner_job"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True, comment="选词服务任务 ID")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", index=True, comment="queued/running/done/error"
    )
    company: Mapped[str] = mapped_column(String(200), nullable=False, default="", comment="企业名")
    product: Mapped[str] = mapped_column(String(200), nullable=False, default="", comment="产品名")
    error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="失败原因")
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="提交参数")
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="挖掘结果 JSON")
    edited_result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="人工修订后的结果 JSON")
    edit_notes_json: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="修订备注/改因列表")
    selection_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expansion_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    task: Mapped[str] = mapped_column(String(40), nullable=False, default="", comment="both/select/expand")
    platforms_json: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="目标平台列表")
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="", comment="demo/llm 等")
    model: Mapped[str] = mapped_column(String(80), nullable=False, default="", comment="模型名")
    top_words_json: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="Top 关键词")
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"), nullable=True, index=True)
    created_by_identity_id: Mapped[int | None] = mapped_column(
        ForeignKey("sys_user_identity.id"), nullable=True, index=True
    )
    job_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="任务创建时间")
    job_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True, comment="任务最近更新时间"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GeoKeywordMinerExample(Base):
    """GEO 选词范例库: 全局按行业复用, 生成时 Top K 注入."""

    __tablename__ = "geo_keyword_miner_example"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True, comment="select/expand")
    industry: Mapped[str] = mapped_column(String(80), nullable=False, default="", index=True, comment="行业标签")
    product_tags: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="产品标签")
    stage: Mapped[str] = mapped_column(String(40), nullable=False, default="", comment="拓词阶段或选词类目")
    word: Mapped[str] = mapped_column(String(255), nullable=False, comment="关键词/问法")
    answer: Mapped[str | None] = mapped_column(Text, nullable=True, comment="拓词答案要点")
    intent: Mapped[str | None] = mapped_column(String(40), nullable=True, comment="选词意图")
    heat: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="拓词热度")
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="说明")
    edit_reason: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="改因备注")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True, comment="active/disabled")
    source_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True, comment="来源任务")
    source_company: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="来源企业")
    source_product: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="来源产品")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, comment="去重哈希")
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="注入引用次数")
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"), nullable=True)
    created_by_identity_id: Mapped[int | None] = mapped_column(ForeignKey("sys_user_identity.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
