"""未配齐监测词/平台时调度应 skipped，不落 failed。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.monitor import GeoMonitorScheduleRun
from app.services.schedule_service import (
    DueScheduleGroup,
    _downgrade_config_failed_schedule_run,
    is_schedule_group_submittable,
    submit_schedule_group,
)


@pytest.fixture()
def schedule_run_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine, tables=[GeoMonitorScheduleRun.__table__])
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_is_schedule_group_submittable_false_when_no_keyword_group(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.schedule_service.resolve_schedule_keyword_group",
        lambda *_args, **_kwargs: None,
    )
    item = DueScheduleGroup(
        tenant_id=1,
        schedule_key="20260831-0930",
        group_key="20260831-0930-kw0",
        max_prompts=50,
        keyword="测试",
    )
    assert is_schedule_group_submittable(MagicMock(), SimpleNamespace(), item) is False


def test_is_schedule_group_submittable_false_when_build_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.schedule_service.resolve_schedule_keyword_group",
        lambda *_args, **_kwargs: {"id": 1, "monitor_keyword": "词"},
    )

    def _raise(*_args, **_kwargs):
        raise ValueError("企业未配置已购买或允许监测的模型平台")

    monkeypatch.setattr("app.services.schedule_service.build_scheduled_payload", _raise)
    item = DueScheduleGroup(
        tenant_id=1,
        schedule_key="20260831-0930",
        group_key="20260831-0930-kw0",
        max_prompts=50,
        keyword="测试",
    )
    assert is_schedule_group_submittable(MagicMock(), SimpleNamespace(), item) is False


def test_downgrade_config_failed_schedule_run(schedule_run_db) -> None:
    run = GeoMonitorScheduleRun(
        tenant_id=132,
        schedule_key="20260831-0853-kw0",
        status="failed",
        prompt_count=1,
        platform_count=0,
        error_message="企业未配置已购买或允许监测的模型平台",
    )
    schedule_run_db.add(run)
    schedule_run_db.commit()

    _downgrade_config_failed_schedule_run(
        schedule_run_db,
        tenant_id=132,
        group_key="20260831-0853-kw0",
    )
    schedule_run_db.refresh(run)
    assert run.status == "skipped"
    assert run.error_message is None


def test_submit_schedule_group_skips_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    db = MagicMock()
    asset = SimpleNamespace(tenant_id=132, deleted=False, status=True)
    tenant = SimpleNamespace(id=132, deleted=False)
    db.scalar.side_effect = [asset, tenant]

    monkeypatch.setattr("app.services.tenant_account_service.molizhishu_submit_skip_message", lambda *_a, **_k: None)
    monkeypatch.setattr("app.services.schedule_service.is_schedule_group_submittable", lambda *_a, **_k: False)
    monkeypatch.setattr("app.services.schedule_service.mark_schedule_group_skipped", lambda *_a, **_k: None)

    item = DueScheduleGroup(
        tenant_id=132,
        schedule_key="20260831-0853",
        group_key="20260831-0853-kw0",
        max_prompts=50,
        keyword="载望升学",
    )
    current = SimpleNamespace(user=SimpleNamespace(id=1))
    result = submit_schedule_group(db, current, item)
    assert result["status"] == "skipped"
    assert result["message"] == "监测未配置完整"
