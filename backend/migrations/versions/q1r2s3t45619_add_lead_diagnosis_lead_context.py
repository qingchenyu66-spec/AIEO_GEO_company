"""add geo_lead_diagnosis.lead_context_json for structured entry context

Revision ID: q1r2s3t45619
Revises: p0q1r2s34518
Create Date: 2026-08-13
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "q1r2s3t45619"
# 2026-08-20 - 与 competitor_daily_stat 并行头合并：接到 s3t4 之后，避免双 head
down_revision: Union[str, Sequence[str], None] = "s3t4u5v67821"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 2026-08-13 - 售前入口字段混入 contact_note - 独立 lead_context_json，旧行空对象
    op.add_column(
        "geo_lead_diagnosis",
        sa.Column(
            "lead_context_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("(JSON_OBJECT())"),
            comment="诊断上下文字典：website_url/industry/product_focus/purchase_scenario/source",
        ),
    )


def downgrade() -> None:
    op.drop_column("geo_lead_diagnosis", "lead_context_json")
