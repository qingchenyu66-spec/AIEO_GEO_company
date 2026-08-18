"""Tests for monitor daily stat aggregation."""

from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.brand import BrandAsset, BrandCompetitor
from app.models.lead_diagnosis import LeadDiagnosisRun
from app.models.monitor import (
    GeoMonitorCompetitorDailyStat,
    GeoMonitorDailyStat,
    GeoMonitorScheduleRun,
    GeoMonitorSubtask,
    GeoMonitorTask,
)
from app.services.monitor_stats_service import (
    _is_transient_daily_stat_conflict,
    _rebuild_daily_stat_for_platform_day,
    refresh_stats_for_task,
)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            GeoMonitorTask.__table__,
            GeoMonitorSubtask.__table__,
            GeoMonitorDailyStat.__table__,
            GeoMonitorCompetitorDailyStat.__table__,
            GeoMonitorScheduleRun.__table__,
            LeadDiagnosisRun.__table__,
            BrandAsset.__table__,
            BrandCompetitor.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _add_task_with_subtasks(
    db,
    *,
    task_id: str,
    tenant_id: int,
    platform: str,
    stat_day: datetime,
    mention_positions: list[int | None],
) -> None:
    # 2026-08-17 - 日表走 kpi_rank：需正文含品牌词，否则 mention_position 单独不计
    if db.scalar(select(BrandAsset).where(BrandAsset.tenant_id == tenant_id)) is None:
        db.add(
            BrandAsset(
                tenant_id=tenant_id,
                company_full_name="测试公司",
                brand_name="测试品牌",
                brand_short_name="测品",
                monitor_keywords_json=["测试品牌"],
                aliases_json=[],
                product_keywords_json=[],
                monitored_platforms_json=["doubao"],
                region_codes_json=[],
                schedule_times_json=["09:00"],
                schedule_weekdays_json=[],
                schedule_month_days_json=[],
            )
        )
    task = GeoMonitorTask(
        task_id=task_id,
        tenant_id=tenant_id,
        status="completed",
        total_items=len(mention_positions),
        completed_items=len(mention_positions),
        failed_items=0,
        monitor_keywords="测试品牌",
        prompts_json=["推荐测试品牌排名"],
        platforms_json=[{"platform": platform}],
        raw_request_json={},
        raw_response_json={},
        created_at=stat_day,
    )
    db.add(task)
    for index, mention_position in enumerate(mention_positions, start=1):
        db.add(
            GeoMonitorSubtask(
                subtask_id=f"{task_id}-{index}",
                task_id=task_id,
                platform=platform,
                mode="standard",
                prompt="推荐测试品牌哪个好",
                status="completed",
                mention_position=mention_position,
                answer_content="1. 测试品牌\n2. 其它" if mention_position is not None else "其它品牌",
                all_rankings_json=(
                    [{"name": "测试品牌", "rank": mention_position}]
                    if mention_position is not None
                    else []
                ),
                raw_result_json={},
                updated_at=stat_day,
            )
        )
    db.commit()


def test_refresh_stats_merges_multiple_tasks_for_same_day_platform(db_session) -> None:
    tenant_id = 1
    day = datetime(2026, 7, 3, 12, 0, 0)
    _add_task_with_subtasks(
        db_session,
        task_id="task-a",
        tenant_id=tenant_id,
        platform="doubao",
        stat_day=day,
        mention_positions=[1, None],
    )
    _add_task_with_subtasks(
        db_session,
        task_id="task-b",
        tenant_id=tenant_id,
        platform="doubao",
        stat_day=day,
        mention_positions=[2, 3, None],
    )

    refresh_stats_for_task(db_session, "task-a")
    db_session.commit()
    refresh_stats_for_task(db_session, "task-b")
    db_session.commit()

    row = db_session.scalar(
        select(GeoMonitorDailyStat).where(
            GeoMonitorDailyStat.tenant_id == tenant_id,
            GeoMonitorDailyStat.platform == "doubao",
        )
    )
    assert row is not None
    assert row.completed_count == 5
    assert row.mentioned_count == 3
    assert row.top3_count == 3  # positions 1,2,3

    from app.services.monitor_stats_service import workspace_metrics_from_stat_rows

    metrics = workspace_metrics_from_stat_rows([row])
    assert metrics["top3_rate"] == 60.0  # 3/5
    assert metrics["brand_mention_rate"] == 60.0


def test_is_transient_daily_stat_conflict_detects_deadlock() -> None:
    class FakeOrig(Exception):
        def __init__(self):
            super().__init__(1213, "Deadlock found when trying to get lock; try restarting transaction")

    err = OperationalError("INSERT", {}, FakeOrig())
    assert _is_transient_daily_stat_conflict(err) is True
    assert _is_transient_daily_stat_conflict(ValueError("nope")) is False


def test_rebuild_daily_stat_retries_on_deadlock(db_session) -> None:
    """自检：写段首次模拟 MySQL 1213，重试后应落库成功，不影响汇总口径。"""
    tenant_id = 119
    day = datetime(2026, 8, 8, 9, 32, 0)
    _add_task_with_subtasks(
        db_session,
        task_id="task-deadlock",
        tenant_id=tenant_id,
        platform="doubao",
        stat_day=day,
        mention_positions=[1, 2],
    )
    # detect_stat_date 优先 task.created_at
    task = db_session.scalar(select(GeoMonitorTask).where(GeoMonitorTask.task_id == "task-deadlock"))
    assert task is not None
    task.created_at = day
    db_session.commit()

    calls = {"n": 0}
    real_write = _write_daily_stat_row_ref()

    def flaky_write(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError(
                "INSERT",
                {},
                Exception(1213, "Deadlock found when trying to get lock; try restarting transaction"),
            )
        return real_write(*args, **kwargs)

    with patch("app.services.monitor_stats_service._write_daily_stat_row", side_effect=flaky_write):
        _rebuild_daily_stat_for_platform_day(
            db_session,
            tenant_id=tenant_id,
            stat_date=day.date(),
            platform="doubao",
        )

    row = db_session.scalar(
        select(GeoMonitorDailyStat).where(
            GeoMonitorDailyStat.tenant_id == tenant_id,
            GeoMonitorDailyStat.platform == "doubao",
            GeoMonitorDailyStat.stat_date == day.date(),
        )
    )
    assert calls["n"] == 2
    assert row is not None
    assert row.completed_count == 2
    assert row.mentioned_count == 2


def _write_daily_stat_row_ref():
    from app.services.monitor_stats_service import _write_daily_stat_row

    return _write_daily_stat_row
