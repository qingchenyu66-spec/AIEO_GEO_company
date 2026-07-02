"""add platform and alert threshold tables

Revision ID: a3b7c9d1e2f4
Revises: e0f1a2b3c4d5
Create Date: 2026-07-01 10:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3b7c9d1e2f4"
down_revision: Union[str, Sequence[str], None] = "e0f1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_THRESHOLDS = [
    ("ranking_drop", "排名下滑预警", "3", "5", "位"),
    ("negative_rate", "负面占比预警", "20", "35", "%"),
    ("task_failure_rate", "任务失败率预警", "10", "25", "%"),
    ("molizhishu_balance", "模力账户余额预警", "500", "100", "元"),
    ("celery_queue_submit", "提交队列积压", "50", "150", "条"),
    ("celery_queue_sync", "同步队列积压", "100", "300", "条"),
]


def upgrade() -> None:
    op.create_table(
        "geo_platform",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="平台ID"),
        sa.Column("platform_code", sa.String(length=50), nullable=False, comment="平台编码"),
        sa.Column("platform_name", sa.String(length=100), nullable=False, comment="平台名称"),
        sa.Column("platform_icon", sa.String(length=255), nullable=True, comment="平台图标URL"),
        sa.Column("access_type", sa.String(length=30), server_default="api", nullable=False, comment="访问方式"),
        sa.Column("api_endpoint", sa.String(length=500), nullable=True, comment="API端点"),
        sa.Column("status", sa.Boolean(), server_default=sa.text("1"), nullable=False, comment="是否启用"),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False, comment="排序权重"),
        sa.Column("description", sa.String(length=500), nullable=True, comment="平台描述"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.Column("deleted", sa.Boolean(), server_default=sa.text("0"), nullable=False, comment="逻辑删除"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform_code"),
    )
    op.create_index("ix_geo_platform_platform_code", "geo_platform", ["platform_code"], unique=True)
    op.create_index("ix_geo_platform_deleted", "geo_platform", ["deleted"], unique=False)

    op.create_table(
        "geo_alert_threshold",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="阈值配置ID"),
        sa.Column("tenant_id", sa.Integer(), nullable=True, comment="所属企业ID，NULL表示全局默认"),
        sa.Column("metric_type", sa.String(length=50), nullable=False, comment="指标类型"),
        sa.Column("threshold_name", sa.String(length=100), nullable=False, comment="阈值名称"),
        sa.Column("warning_value", sa.String(length=50), nullable=False, comment="预警阈值"),
        sa.Column("critical_value", sa.String(length=50), nullable=False, comment="严重告警阈值"),
        sa.Column("unit", sa.String(length=20), server_default="", nullable=False, comment="单位"),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("1"), nullable=False, comment="是否启用"),
        sa.Column("updated_by", sa.String(length=80), nullable=True, comment="最后更新人"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.Column("deleted", sa.Boolean(), server_default=sa.text("0"), nullable=False, comment="逻辑删除"),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_geo_alert_threshold_tenant_id", "geo_alert_threshold", ["tenant_id"], unique=False)
    op.create_index("ix_geo_alert_threshold_metric_type", "geo_alert_threshold", ["metric_type"], unique=False)
    op.create_index("ix_geo_alert_threshold_deleted", "geo_alert_threshold", ["deleted"], unique=False)

    threshold_table = sa.table(
        "geo_alert_threshold",
        sa.column("tenant_id", sa.Integer()),
        sa.column("metric_type", sa.String()),
        sa.column("threshold_name", sa.String()),
        sa.column("warning_value", sa.String()),
        sa.column("critical_value", sa.String()),
        sa.column("unit", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("deleted", sa.Boolean()),
    )
    op.bulk_insert(
        threshold_table,
        [
            {
                "tenant_id": None,
                "metric_type": metric_type,
                "threshold_name": name,
                "warning_value": warning,
                "critical_value": critical,
                "unit": unit,
                "enabled": True,
                "deleted": False,
            }
            for metric_type, name, warning, critical, unit in DEFAULT_THRESHOLDS
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_geo_alert_threshold_deleted", table_name="geo_alert_threshold")
    op.drop_index("ix_geo_alert_threshold_metric_type", table_name="geo_alert_threshold")
    op.drop_index("ix_geo_alert_threshold_tenant_id", table_name="geo_alert_threshold")
    op.drop_table("geo_alert_threshold")
    op.drop_index("ix_geo_platform_deleted", table_name="geo_platform")
    op.drop_index("ix_geo_platform_platform_code", table_name="geo_platform")
    op.drop_table("geo_platform")
