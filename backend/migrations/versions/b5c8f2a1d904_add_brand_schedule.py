"""add brand schedule

Revision ID: b5c8f2a1d904
Revises: a4f2c6d8e901
Create Date: 2026-06-23 15:10:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b5c8f2a1d904"
down_revision: Union[str, None] = "a4f2c6d8e901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("geo_brand_asset", sa.Column("schedule_type", sa.String(length=20), nullable=False, server_default="daily_times", comment="监测计划类型：daily_times每天几次，fixed_times指定时间，weekly每周，monthly每月"))
    op.add_column("geo_brand_asset", sa.Column("schedule_times_json", sa.JSON(), nullable=True, comment="指定执行时间JSON，例如['09:30','14:30']"))
    op.add_column("geo_brand_asset", sa.Column("schedule_frequency", sa.Integer(), nullable=False, server_default="3", comment="每天执行次数，仅daily_times类型使用"))
    op.add_column("geo_brand_asset", sa.Column("schedule_weekdays_json", sa.JSON(), nullable=True, comment="每周执行星期JSON，1-7代表周一到周日"))
    op.add_column("geo_brand_asset", sa.Column("schedule_month_days_json", sa.JSON(), nullable=True, comment="每月执行日期JSON，1-31"))
    op.execute("UPDATE geo_brand_asset SET schedule_times_json = JSON_ARRAY('09:30','14:30','20:30'), schedule_weekdays_json = JSON_ARRAY(), schedule_month_days_json = JSON_ARRAY()")
    op.alter_column("geo_brand_asset", "schedule_times_json", existing_type=sa.JSON(), nullable=False)
    op.alter_column("geo_brand_asset", "schedule_weekdays_json", existing_type=sa.JSON(), nullable=False)
    op.alter_column("geo_brand_asset", "schedule_month_days_json", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    op.drop_column("geo_brand_asset", "schedule_month_days_json")
    op.drop_column("geo_brand_asset", "schedule_weekdays_json")
    op.drop_column("geo_brand_asset", "schedule_frequency")
    op.drop_column("geo_brand_asset", "schedule_times_json")
    op.drop_column("geo_brand_asset", "schedule_type")
