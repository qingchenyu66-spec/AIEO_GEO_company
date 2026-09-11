"""Guard against UnboundLocalError on schedule submit path."""

from app.services.monitor_service import submit_monitor_task


def test_submit_monitor_task_does_not_shadow_normalize_region_codes():
    # Local import inside submit_monitor_task would bind the name for the whole
    # function and break schedule submits (auto_commit=False skips that branch).
    assert "normalize_region_codes" not in submit_monitor_task.__code__.co_varnames
