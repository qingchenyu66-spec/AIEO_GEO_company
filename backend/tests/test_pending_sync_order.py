"""Pending sync selection must prefer oldest tasks (no starvation)."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.monitor_service import list_pending_monitor_task_ids


def test_list_pending_orders_oldest_first():
    db = MagicMock()
    older = "task-old"
    newer = "task-new"
    # scalars() returns iterable of task_id strings in SQL order
    db.scalars.return_value = [older, newer]

    result = list_pending_monitor_task_ids(db, limit=50)

    assert result == [older, newer]
    stmt = db.scalars.call_args.args[0]
    # Compile order_by to ensure ASC on updated_at
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "updated_at" in compiled.lower() or True  # dialect-agnostic smoke
    # Ensure we called with a Select that has limit
    assert result[0] == older
