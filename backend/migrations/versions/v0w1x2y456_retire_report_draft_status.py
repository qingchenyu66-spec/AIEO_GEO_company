"""retire report draft status — publish existing drafts

Revision ID: v0w1x2y456
Revises: u9v0w1x345
Create Date: 2026-07-15 10:25:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v0w1x2y456"
down_revision: Union[str, Sequence[str], None] = "u9v0w1x345"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 产品已取消草稿概念；客户端可见性仍由 report_type 白名单控制（诊断不会进客户端）
    op.execute(
        sa.text(
            """
            UPDATE geo_report
            SET status = 'published'
            WHERE deleted = 0 AND status = 'draft'
            """
        )
    )


def downgrade() -> None:
    # 无法可靠还原哪些曾为草稿；保留 published
    pass
