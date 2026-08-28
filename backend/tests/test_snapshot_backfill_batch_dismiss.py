"""Batch dismiss helpers for snapshot backfill."""

from app.services.snapshot_backfill_service import (
    _collect_batch_dismiss_targets,
    _gap_dismiss_matrix_key,
    _slot_is_batch_dismissable,
)


def test_gap_dismiss_matrix_key():
    key = _gap_dismiss_matrix_key(
        platform="doubao",
        prompt="词A",
        day_text="2026-08-28",
        schedule_window_key="20260828-0930",
    )
    assert key == ("doubao", "词A", "2026-08-28", "20260828-0930")


def test_slot_batch_dismissable():
    assert _slot_is_batch_dismissable({"is_gap": True, "backfill_dismissed": False})
    assert _slot_is_batch_dismissable({"subtask_id": "st-1", "backfill_dismissed": False})
    assert not _slot_is_batch_dismissable({"backfill_dismissed": True, "is_gap": True})
    assert not _slot_is_batch_dismissable({"needs_backfill": True, "backfill_dismissed": False})


def test_collect_batch_dismiss_targets_todo_only():
    cells = [
        {
            "has_todo": True,
            "word": "词A",
            "platform": "doubao",
            "slots": [
                {"subtask_id": "s1", "backfill_dismissed": False, "mention_position": 1},
                {"subtask_id": "s2", "backfill_dismissed": False, "mention_position": 10},
                {"is_gap": True, "backfill_dismissed": False},
                {"subtask_id": "s3", "backfill_dismissed": True},
            ],
        },
        {
            "has_todo": False,
            "slots": [{"subtask_id": "s9", "backfill_dismissed": False}],
        },
    ]
    targets = _collect_batch_dismiss_targets(cells, todo_only=True)
    ids = {slot.get("subtask_id") or "gap" for _cell, slot in targets}
    assert ids == {"s1", "s2", "gap"}


def test_collect_batch_dismiss_targets_all():
    cells = [
        {
            "has_todo": False,
            "slots": [
                {"subtask_id": "s1", "backfill_dismissed": False},
                {"needs_backfill": True, "backfill_dismissed": False},
            ],
        },
    ]
    targets = _collect_batch_dismiss_targets(cells, todo_only=False)
    assert len(targets) == 1
    assert targets[0][1]["subtask_id"] == "s1"
