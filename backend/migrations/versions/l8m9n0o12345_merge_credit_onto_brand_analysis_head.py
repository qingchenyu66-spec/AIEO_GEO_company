"""merge credit self-service head onto main brand_analysis menu head

Revision ID: l8m9n0o12345
Revises: e7f8a9b01234, z4a5b6c890
Create Date: 2026-09-09

2026-09-08 - 算力自助迁移链并入 main 品牌分析头，避免双 head
2026-09-09 - 原误用 g8h9i0j12345 与 H5 订单迁移撞 ID，改为 l8m9n0o12345
"""

from typing import Sequence, Union

revision: str = "l8m9n0o12345"
down_revision: Union[str, Sequence[str], None] = ("e7f8a9b01234", "z4a5b6c890")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
