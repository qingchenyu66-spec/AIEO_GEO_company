"""人工补录与同步覆盖防护。"""

from types import SimpleNamespace

from app.services.monitor_service import (
    is_manual_snapshot_subtask,
    subtask_inflight_blocks_snapshot_backfill,
)


def test_inflight_statuses_block_backfill():
    for status in ("pending", "processing", "running", "queued"):
        assert subtask_inflight_blocks_snapshot_backfill(SimpleNamespace(status=status)) is True


def test_terminal_statuses_allow_backfill():
    for status in ("completed", "partial_completed", "failed", "stopped"):
        assert subtask_inflight_blocks_snapshot_backfill(SimpleNamespace(status=status)) is False


def test_is_manual_snapshot_subtask():
    assert is_manual_snapshot_subtask(SimpleNamespace(raw_result_json={"source": "manual_snapshot"})) is True
    assert is_manual_snapshot_subtask(SimpleNamespace(raw_result_json={"source": "api"})) is False
    assert is_manual_snapshot_subtask(SimpleNamespace(raw_result_json=None)) is False
