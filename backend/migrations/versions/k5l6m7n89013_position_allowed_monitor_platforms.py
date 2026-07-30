"""add position allowed_monitor_platforms_json for per-platform scope

Revision ID: k5l6m7n89013
Revises: j4k5l6m79012
Create Date: 2026-07-30

有「平台范围」编辑权的职位回填当前目录全量码，保持原编辑能力；未授权职位保持空数组。
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "k5l6m7n89013"
down_revision: Union[str, Sequence[str], None] = "j4k5l6m79012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MODELS = "platform.audit.models"


def upgrade() -> None:
    # 2026-07-30 - 平台范围细到单端 - 职位存可配平台多选；空=全不能勾
    op.add_column(
        "sys_position",
        sa.Column(
            "allowed_monitor_platforms_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("(JSON_ARRAY())"),
            comment="可配置监测平台码；需配合 platform.audit.models 编辑权；空=不可勾任何端",
        ),
    )
    bind = op.get_bind()
    # 已有平台范围编辑权的职位：回填 geo_platform 可提交目录（无表则跳过，保持空）
    try:
        codes = [
            str(row[0])
            for row in bind.execute(
                sa.text(
                    """
                    SELECT platform_code FROM geo_platform
                    WHERE deleted = 0 AND status = 1
                    ORDER BY id
                    """
                )
            ).fetchall()
            if row and row[0]
        ]
    except Exception:
        codes = []
    if not codes:
        return
    import json

    payload = json.dumps(codes, ensure_ascii=False)
    bind.execute(
        sa.text(
            f"""
            UPDATE sys_position p
            INNER JOIN sys_position_menu pm ON pm.position_id = p.id
            INNER JOIN sys_menu m ON m.id = pm.menu_id AND m.menu_code = :menu_code AND m.deleted = 0
            SET p.allowed_monitor_platforms_json = CAST(:codes AS JSON)
            WHERE p.deleted = 0
              AND pm.can_update = 1
              AND (p.allowed_monitor_platforms_json IS NULL OR JSON_LENGTH(p.allowed_monitor_platforms_json) = 0)
            """
        ),
        {"menu_code": MODELS, "codes": payload},
    )


def downgrade() -> None:
    op.drop_column("sys_position", "allowed_monitor_platforms_json")
