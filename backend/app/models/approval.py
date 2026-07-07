from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OperationApproval(Base):
    """销售等受限身份提交的待审批操作。"""

    __tablename__ = "sys_operation_approval"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="审批单ID")
    operation_key: Mapped[str] = mapped_column(String(80), index=True, nullable=False, comment="操作编码")
    module: Mapped[str] = mapped_column(String(40), nullable=False, comment="业务模块")
    action: Mapped[str] = mapped_column(String(20), nullable=False, comment="动作类型")
    summary: Mapped[str] = mapped_column(String(255), nullable=False, comment="摘要")
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("sys_tenant.id"), index=True, nullable=True, comment="关联企业ID")
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="目标资源ID")
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, comment="请求参数JSON")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True, nullable=False, comment="pending/approved/rejected")
    requester_user_id: Mapped[int] = mapped_column(ForeignKey("sys_user.id"), index=True, nullable=False, comment="申请人用户ID")
    requester_identity_id: Mapped[int] = mapped_column(ForeignKey("sys_user_identity.id"), index=True, nullable=False, comment="申请人身份ID")
    reviewer_user_id: Mapped[int | None] = mapped_column(ForeignKey("sys_user.id"), nullable=True, comment="审批人用户ID")
    reviewer_identity_id: Mapped[int | None] = mapped_column(ForeignKey("sys_user_identity.id"), nullable=True, comment="审批人身份ID")
    review_comment: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="审批意见")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="审批时间")
    executed_result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="执行结果JSON")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
    )
    deleted: Mapped[bool] = mapped_column(default=False, index=True, nullable=False, comment="逻辑删除")
