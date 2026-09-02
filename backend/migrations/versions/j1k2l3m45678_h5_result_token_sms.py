"""add H5 diagnosis result access token and SMS fields

Revision ID: j1k2l3m45678
Revises: i0j1k2l34567
Create Date: 2026-09-01 10:05:00.000000

2026-09-01 - H5 用户自助看报告：结果页 token + ready 短信发送状态
（只挂 H5 菜单线，勿 merge credit head，避免本地半套 credit 库卡 upgrade）
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "j1k2l3m45678"
down_revision: Union[str, Sequence[str], None] = "i0j1k2l34567"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "geo_h5_diagnosis_order",
        sa.Column("result_access_token", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "geo_h5_diagnosis_order",
        sa.Column("result_token_expires_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "geo_h5_diagnosis_order",
        sa.Column("sms_ready_sent_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "geo_h5_diagnosis_order",
        sa.Column("sms_ready_last_error", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_geo_h5_diagnosis_order_result_access_token",
        "geo_h5_diagnosis_order",
        ["result_access_token"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_geo_h5_diagnosis_order_result_access_token", table_name="geo_h5_diagnosis_order")
    op.drop_column("geo_h5_diagnosis_order", "sms_ready_last_error")
    op.drop_column("geo_h5_diagnosis_order", "sms_ready_sent_at")
    op.drop_column("geo_h5_diagnosis_order", "result_token_expires_at")
    op.drop_column("geo_h5_diagnosis_order", "result_access_token")
