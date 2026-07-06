"""Tests for monitor daily stat aggregation."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.brand import BrandAsset
from app.models.lead_diagnosis import LeadDiagnosisRun
from app.models.monitor import GeoMonitorDailyStat, GeoMonitorScheduleRun, GeoMonitorSubtask, GeoMonitorTask
from app.services.monitor_stats_service import refresh_stats_for_task


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            GeoMonitorTask.__table__,
            GeoMonitorSubtask.__table__,
            GeoMonitorDailyStat.__table__,
            GeoMonitorScheduleRun.__table__,
            LeadDiagnosisRun.__table__,
            BrandAsset.__table__,
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
    task = GeoMonitorTask(
        task_id=task_id,
        tenant_id=tenant_id,
        status="completed",
        total_items=len(mention_positions),
        completed_items=len(mention_positions),
        failed_items=0,
        prompts_json=["q"],
        platforms_json=[{"platform": platform}],
        raw_request_json={},
        raw_response_json={},
    )
    db.add(task)
    for index, mention_position in enumerate(mention_positions, start=1):
        db.add(
            GeoMonitorSubtask(
                subtask_id=f"{task_id}-{index}",
                task_id=task_id,
                platform=platform,
                mode="standard",
                prompt=f"prompt-{index}",
                status="completed",
                mention_position=mention_position,
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

    from sqlalchemy import select

    row = db_session.scalar(
        select(GeoMonitorDailyStat).where(
            GeoMonitorDailyStat.tenant_id == tenant_id,
            GeoMonitorDailyStat.platform == "doubao",
        )
    )
    assert row is not None
    assert row.completed_count == 5
    assert row.mentioned_count == 3
