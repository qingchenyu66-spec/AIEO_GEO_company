"""Tests for schedule failure retry semantics."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.monitor import GeoMonitorScheduleRun
from app.services.schedule_service import (
    get_schedule_run,
    persist_schedule_group_failure,
    schedule_run_blocks_due,
)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine, tables=[GeoMonitorScheduleRun.__table__])
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_schedule_run_blocks_due_submitted(db_session) -> None:
    run = GeoMonitorScheduleRun(
        tenant_id=1,
        schedule_key="20260706-0930-kw1",
        status="submitted",
        prompt_count=3,
        platform_count=1,
    )
    db_session.add(run)
    db_session.commit()
    assert schedule_run_blocks_due(run) is True


def test_schedule_run_allows_failed_retry(db_session) -> None:
    run = GeoMonitorScheduleRun(
        tenant_id=1,
        schedule_key="20260706-0930-kw1",
        status="failed",
        prompt_count=3,
        platform_count=1,
        error_message="network",
    )
    db_session.add(run)
    db_session.commit()
    assert schedule_run_blocks_due(run) is False


def test_schedule_run_blocks_fresh_running(db_session) -> None:
    run = GeoMonitorScheduleRun(
        tenant_id=1,
        schedule_key="20260706-0930-kw1",
        status="running",
        prompt_count=3,
        platform_count=1,
    )
    db_session.add(run)
    db_session.flush()
    now = datetime.now()
    run.created_at = now
    run.updated_at = now
    db_session.commit()
    assert schedule_run_blocks_due(run, now=now) is True


def test_schedule_run_allows_stale_running(db_session) -> None:
    run = GeoMonitorScheduleRun(
        tenant_id=1,
        schedule_key="20260706-0930-kw1",
        status="running",
        prompt_count=3,
        platform_count=1,
    )
    db_session.add(run)
    db_session.flush()
    run.updated_at = datetime.now() - timedelta(minutes=15)
    db_session.commit()
    assert schedule_run_blocks_due(run, now=datetime.now()) is False


def test_persist_schedule_group_failure_updates_existing(db_session) -> None:
    run = GeoMonitorScheduleRun(
        tenant_id=2,
        schedule_key="20260706-0950-kw2",
        status="failed",
        prompt_count=1,
        platform_count=1,
        error_message="old",
    )
    db_session.add(run)
    db_session.commit()

    persist_schedule_group_failure(
        db_session,
        tenant_id=2,
        group_key="20260706-0950-kw2",
        error_message="new error",
        prompt_count=5,
        platform_count=2,
    )
    updated = get_schedule_run(db_session, 2, "20260706-0950-kw2")
    assert updated is not None
    assert updated.status == "failed"
    assert updated.error_message == "new error"
    assert updated.prompt_count == 5
    assert updated.platform_count == 2
