"""算力 Celery beat 注册（预估与 stale 扫描；模式切换不挂空跑 beat）。"""

from app.celery_app import celery_app


def test_credit_beat_entries_registered():
    # 2026-09-09 - A甲：next_window 提交落地，apply-scheduled-billing-mode-changes 退出 beat
    beat = celery_app.conf.beat_schedule or {}
    assert beat["scan-stale-credit-reserves"]["task"] == "app.tasks.monitor.scan_stale_credit_reserves"
    assert beat["refresh-credit-window-estimate"]["task"] == "app.tasks.monitor.refresh_credit_window_estimate"
    assert "apply-scheduled-billing-mode-changes" not in beat
    assert "scan-credit-terms-reminders" not in beat
    assert beat["scan-credit-three-day-shortfall"]["task"] == (
        "app.tasks.monitor.scan_credit_three_day_shortfall"
    )


def test_credit_tasks_callable_sync():
    from app.tasks.monitor import (
        apply_scheduled_billing_mode_changes,
        refresh_credit_window_estimate,
        scan_credit_three_day_shortfall,
        scan_stale_credit_reserves,
    )

    assert scan_stale_credit_reserves()["status"] in {"ok", "disabled"}
    assert refresh_credit_window_estimate()["status"] in {"ok", "disabled"}
    mode_result = apply_scheduled_billing_mode_changes()
    assert mode_result["status"] in {"ok", "disabled"}
    # 任务仍可手工调用，但明确 deferred + 已撤 beat
    if mode_result["status"] == "ok":
        assert mode_result.get("deferred_to_submit") is True
        assert mode_result.get("applied") == 0
        assert mode_result.get("beat_removed") is True
    assert scan_credit_three_day_shortfall()["status"] in {"ok", "disabled"}
