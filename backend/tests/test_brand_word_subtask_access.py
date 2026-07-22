"""brand_word 子任务详情：客户可见，不受 GEO 昨日闸门挡住。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.api.dependencies import CurrentSession
from app.services.monitor_service import get_monitor_subtask


def _customer(tenant_id: int = 6) -> CurrentSession:
    return CurrentSession(
        user=SimpleNamespace(id=1, username="c"),
        identity=SimpleNamespace(id=1, identity_type="CUSTOMER", tenant_id=tenant_id, user_id=1),
    )


def test_customer_can_open_today_brand_word_subtask(monkeypatch):
    task = SimpleNamespace(
        task_id="t-bw",
        tenant_id=6,
        purpose="brand_word",
        deleted=False,
    )
    subtask = SimpleNamespace(
        subtask_id="s-bw",
        task_id="t-bw",
        task=task,
    )
    db = MagicMock()
    db.scalar.return_value = subtask

    monkeypatch.setattr(
        "app.services.monitor_service.assert_monitor_task_access",
        lambda *_a, **_k: None,
    )

    def _should_not_call(*_a, **_k):
        raise AssertionError("GEO cutoff must not run for brand_word")

    monkeypatch.setattr("app.services.monitor_service.customer_subtask_visible", _should_not_call)

    got = get_monitor_subtask(db, "s-bw", _customer())
    assert got is subtask


def test_customer_geo_subtask_still_checks_cutoff(monkeypatch):
    task = SimpleNamespace(
        task_id="t-geo",
        tenant_id=6,
        purpose="geo",
        deleted=False,
    )
    subtask = SimpleNamespace(
        subtask_id="s-geo",
        task_id="t-geo",
        task=task,
    )
    db = MagicMock()
    db.scalar.return_value = subtask

    monkeypatch.setattr(
        "app.services.monitor_service.assert_monitor_task_access",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "app.services.monitor_service.get_brand_asset",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "app.services.monitor_service.schedule_runs_for_tasks",
        lambda *_a, **_k: {},
    )
    monkeypatch.setattr(
        "app.services.monitor_service.lead_diagnosis_runs_for_tasks",
        lambda *_a, **_k: {},
    )
    monkeypatch.setattr(
        "app.services.monitor_service._resolve_subtask_schedule_context",
        lambda *_a, **_k: {},
    )
    monkeypatch.setattr(
        "app.services.monitor_service.customer_subtask_visible",
        lambda *_a, **_k: False,
    )

    try:
        get_monitor_subtask(db, "s-geo", _customer())
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "子任务不存在或无权访问" in str(exc)
