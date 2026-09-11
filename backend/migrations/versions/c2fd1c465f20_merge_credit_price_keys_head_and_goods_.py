"""merge credit price keys head and goods_card head

Revision ID: c2fd1c465f20
Revises: f6a7b89014, k2l3m4n56789
Create Date: 2026-09-04 14:39:08.112846

2026-09-04 - 本地双 head（算力价键 f6 / 货卡 k2）- 空 merge 收口；库已两边 schema 时 stamp 本 rev，勿盲 upgrade 重跑建表
"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "c2fd1c465f20"
down_revision: Union[str, Sequence[str], None] = ("f6a7b89014", "k2l3m4n56789")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 空 merge：两支线 DDL 已各自落地；仅统一 alembic head
    pass


def downgrade() -> None:
    pass

