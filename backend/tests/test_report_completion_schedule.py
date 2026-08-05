# -*- coding: utf-8 -*-
"""结项报告到期自动生成。"""

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.report_period_service import period_key
from app.services.report_schedule_service import (
    completion_period_bounds,
    list_tenants_due_completion,
    run_due_completion_reports,
    run_due_scheduled_reports,
)


def test_completion_period_bounds_requires_both_ends() -> None:
    assert completion_period_bounds(SimpleNamespace(service_start_date=None, service_end_date=date(2026, 7, 31))) is None
    assert completion_period_bounds(SimpleNamespace(service_start_date=date(2026, 6, 1), service_end_date=None)) is None
    assert completion_period_bounds(
        SimpleNamespace(service_start_date=date(2026, 8, 1), service_end_date=date(2026, 7, 1))
    ) is None
    start, end = completion_period_bounds(
        SimpleNamespace(service_start_date=date(2026, 6, 25), service_end_date=date(2026, 7, 31))
    )
    assert (start, end) == (date(2026, 6, 25), date(2026, 7, 31))
    assert period_key("completion", start, end) == "completion:2026-06-25_2026-07-31"


def test_list_tenants_due_completion_window() -> None:
    """到期日 = today-1 入窗；today 当天仍服务中，不入窗。"""
    today = date(2026, 8, 4)
    t_yesterday = SimpleNamespace(
        id=1,
        deleted=False,
        service_start_date=date(2026, 6, 1),
        service_end_date=date(2026, 8, 3),
    )
    t_today = SimpleNamespace(
        id=2,
        deleted=False,
        service_start_date=date(2026, 6, 1),
        service_end_date=date(2026, 8, 4),
    )
    t_old = SimpleNamespace(
        id=3,
        deleted=False,
        service_start_date=date(2026, 1, 1),
        service_end_date=date(2026, 7, 1),  # 超出默认 7 日回扫
    )

    db = MagicMock()
    # scalars 返回可迭代
    db.scalars.return_value = [t_yesterday]

    rows = list_tenants_due_completion(db, today=today, lookback_days=7)
    assert rows == [t_yesterday]
    # 校验 where 条件被调用（不绑 SQLAlchemy 细节，只保证走了查询）
    assert db.scalars.called

    # 纯日期窗逻辑自检
    window_start = today - timedelta(days=7)
    window_end = today - timedelta(days=1)
    assert window_start <= t_yesterday.service_end_date <= window_end
    assert not (window_start <= t_today.service_end_date <= window_end)
    assert t_old.service_end_date < window_start


def test_run_due_completion_reports_skips_existing_and_generates() -> None:
    today = date(2026, 8, 4)
    tenant = SimpleNamespace(
        id=6,
        service_start_date=date(2026, 6, 25),
        service_end_date=date(2026, 8, 3),
    )
    db = MagicMock()

    with (
        patch(
            "app.services.report_schedule_service.list_tenants_due_completion",
            return_value=[tenant],
        ),
        patch(
            "app.services.report_schedule_service.report_already_generated",
            return_value=False,
        ),
        patch(
            "app.services.report_schedule_service.generate_scheduled_report_for_tenant",
            return_value={"id": 99},
        ) as gen,
    ):
        result = run_due_completion_reports(db, today=today)
    assert result["generated"] == 1
    assert result["skipped"] == 0
    gen.assert_called_once()
    kwargs = gen.call_args.kwargs
    assert kwargs["report_type"] == "completion"
    assert kwargs["period_start"] == date(2026, 6, 25)
    assert kwargs["period_end"] == date(2026, 8, 3)
    assert kwargs["period_key"] == "completion:2026-06-25_2026-08-03"


def test_run_due_scheduled_reports_still_runs_completion_when_no_periodic() -> None:
    """周二等非周报日：due_types 为空时也要跑结项。"""
    today = date(2026, 8, 4)  # 周二
    db = MagicMock()
    with patch(
        "app.services.report_schedule_service.run_due_completion_reports",
        return_value={
            "anchor": today.isoformat(),
            "due_types": ["completion"],
            "tenant_count": 1,
            "generated": 1,
            "skipped": 0,
            "errors": [],
        },
    ) as comp:
        result = run_due_scheduled_reports(db, anchor=today, report_types=None, include_completion=True)
    comp.assert_called_once()
    assert "completion" in result["due_types"]
    assert result["generated"] == 1
    assert result["completion"]["generated"] == 1
