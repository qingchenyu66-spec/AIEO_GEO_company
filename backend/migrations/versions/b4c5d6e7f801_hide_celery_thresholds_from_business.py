"""hide celery queue thresholds from business alert list

Revision ID: b4c5d6e7f801
Revises: a3b7c9d1e2f4
Create Date: 2026-07-01 14:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "b4c5d6e7f801"
down_revision: Union[str, Sequence[str], None] = "a3b7c9d1e2f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE geo_alert_threshold
        SET deleted = 1
        WHERE deleted = 0
          AND metric_type IN ('celery_queue_submit', 'celery_queue_sync')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE geo_alert_threshold
        SET deleted = 0
        WHERE metric_type IN ('celery_queue_submit', 'celery_queue_sync')
        """
    )
