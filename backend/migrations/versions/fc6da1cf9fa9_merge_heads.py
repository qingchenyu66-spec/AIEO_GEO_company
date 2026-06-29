"""merge_heads

Revision ID: fc6da1cf9fa9
Revises: a1b2c3d4e5f6, d5e6f7a8b901
Create Date: 2026-06-29 13:57:56.926056

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fc6da1cf9fa9'
down_revision: Union[str, Sequence[str], None] = ('a1b2c3d4e5f6', 'd5e6f7a8b901')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
