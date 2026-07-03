"""add lead diagnosis region_code

Revision ID: f3c4d5e6f708
Revises: f2b3c4d5e6f7
Create Date: 2026-07-03 09:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f3c4d5e6f708"
down_revision = "f2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "geo_lead_diagnosis",
        sa.Column("region_code", sa.String(length=20), nullable=True, comment="监测地区编码，空值代表全部区域"),
    )


def downgrade() -> None:
    op.drop_column("geo_lead_diagnosis", "region_code")
