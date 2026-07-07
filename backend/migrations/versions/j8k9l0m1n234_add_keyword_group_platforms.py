"""add keyword group platforms and retire platform.audit.models menu

Revision ID: j8k9l0m1n234
Revises: i7j8k9l0m123
Create Date: 2026-07-07 09:05:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "j8k9l0m1n234"
down_revision: Union[str, Sequence[str], None] = "i7j8k9l0m123"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RETIRED_MENU = "platform.audit.models"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("geo_brand_keyword_group")}
    if "platforms_json" not in columns:
        op.add_column(
            "geo_brand_keyword_group",
            sa.Column(
                "platforms_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("(JSON_ARRAY())"),
                comment="监测平台编码JSON",
            ),
        )

    bind.execute(
        sa.text(
            """
            UPDATE geo_brand_keyword_group kg
            INNER JOIN geo_brand_asset ba ON ba.id = kg.brand_asset_id
            SET kg.platforms_json = ba.monitored_platforms_json
            WHERE kg.deleted = 0
              AND ba.deleted = 0
              AND (
                kg.platforms_json IS NULL
                OR JSON_LENGTH(kg.platforms_json) = 0
              )
              AND JSON_LENGTH(ba.monitored_platforms_json) > 0
            """
        )
    )

    bind.execute(
        sa.text(
            """
            UPDATE sys_menu
            SET is_visible = 0
            WHERE menu_code = :menu_code AND deleted = 0
            """
        ),
        {"menu_code": RETIRED_MENU},
    )
    bind.execute(
        sa.text(
            """
            UPDATE sys_menu_config
            SET is_visible = 0,
                remark = '已合并至监测词组配置'
            WHERE menu_code = :menu_code AND deleted = 0
            """
        ),
        {"menu_code": RETIRED_MENU},
    )
    bind.execute(
        sa.text(
            """
            DELETE pm FROM sys_position_menu pm
            INNER JOIN sys_menu m ON m.id = pm.menu_id
            WHERE m.menu_code = :menu_code AND m.deleted = 0
            """
        ),
        {"menu_code": RETIRED_MENU},
    )
    bind.execute(
        sa.text(
            """
            DELETE uim FROM sys_user_identity_menu uim
            INNER JOIN sys_menu m ON m.id = uim.menu_id
            WHERE m.menu_code = :menu_code AND m.deleted = 0
            """
        ),
        {"menu_code": RETIRED_MENU},
    )
    bind.execute(
        sa.text(
            """
            DELETE rm FROM sys_role_menu rm
            INNER JOIN sys_menu m ON m.id = rm.menu_id
            WHERE m.menu_code = :menu_code AND m.deleted = 0
            """
        ),
        {"menu_code": RETIRED_MENU},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE sys_menu
            SET is_visible = 1
            WHERE menu_code = :menu_code AND deleted = 0
            """
        ),
        {"menu_code": RETIRED_MENU},
    )
    bind.execute(
        sa.text(
            """
            UPDATE sys_menu_config
            SET is_visible = 1
            WHERE menu_code = :menu_code AND deleted = 0
            """
        ),
        {"menu_code": RETIRED_MENU},
    )
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("geo_brand_keyword_group")}
    if "platforms_json" in columns:
        op.drop_column("geo_brand_keyword_group", "platforms_json")
