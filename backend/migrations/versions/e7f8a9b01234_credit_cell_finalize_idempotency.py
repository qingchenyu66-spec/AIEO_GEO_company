"""credit cell finalize idempotency table

Revision ID: e7f8a9b01234
Revises: c2fd1c465f20
Create Date: 2026-09-07

2026-09-07 - 按格结算上生产 - 幂等表避免扫 ledger JSON；同租户批次原格唯一
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b01234"
down_revision: Union[str, Sequence[str], None] = "c2fd1c465f20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geo_tenant_credit_cell_finalize",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("batch_ref", sa.String(length=64), nullable=False),
        sa.Column("origin_subtask_id", sa.String(length=64), nullable=False),
        sa.Column("entry_type", sa.String(length=20), nullable=False, comment="settle/release/skipped"),
        sa.Column("credits", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("ledger_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["sys_tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "batch_ref", "origin_subtask_id", name="uk_credit_cell_finalize"),
    )
    op.create_index("ix_geo_tenant_credit_cell_finalize_tenant_id", "geo_tenant_credit_cell_finalize", ["tenant_id"])
    op.create_index("ix_geo_tenant_credit_cell_finalize_batch_ref", "geo_tenant_credit_cell_finalize", ["batch_ref"])


def downgrade() -> None:
    op.drop_index("ix_geo_tenant_credit_cell_finalize_batch_ref", table_name="geo_tenant_credit_cell_finalize")
    op.drop_index("ix_geo_tenant_credit_cell_finalize_tenant_id", table_name="geo_tenant_credit_cell_finalize")
    op.drop_table("geo_tenant_credit_cell_finalize")
