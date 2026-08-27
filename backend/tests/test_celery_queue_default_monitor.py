"""default 队列纳入 Celery 监控。"""

from app.core.celery_queue_monitor import QUEUE_NAMES, QUEUE_METRIC_BY_NAME, _threshold


def test_default_queue_in_monitor_names() -> None:
    assert "default" in QUEUE_NAMES
    assert QUEUE_METRIC_BY_NAME["default"] == "celery_queue_default"


def test_default_queue_thresholds() -> None:
    assert _threshold("default", "warning") == 30
    assert _threshold("default", "critical") == 80
