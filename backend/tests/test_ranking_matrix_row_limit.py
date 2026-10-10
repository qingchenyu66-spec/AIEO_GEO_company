"""排名矩阵行数上限：月视图全平台不得砍掉月初。"""

from datetime import date
from unittest.mock import MagicMock

import app.services.monitor_service as monitor_service
from app.core.read_cache import ranking_matrix_cache_key
from app.services.monitor_service import _iter_hydrated_subtask_batches, _ranking_matrix_row_limit


def test_ranking_matrix_row_limit_expands_for_month_all_platforms() -> None:
    limit = _ranking_matrix_row_limit(
        requested_limit=120,
        range_start_day=date(2026, 7, 1),
        range_end_day=date(2026, 7, 23),
        all_platforms=True,
        purchased_platforms=["deepseek", "doubao", "yuanbao", "tongyi", "kimi", "quark", "baidu", "weibo"],
        keyword_group_count=1,
    )
    # 23 天 × 8 平台 = 184 > 120，必须抬高，否则会从新往旧裁掉月初
    assert limit >= 23 * 8
    assert limit == 184


def test_ranking_matrix_row_limit_keeps_requested_when_larger() -> None:
    limit = _ranking_matrix_row_limit(
        requested_limit=500,
        range_start_day=date(2026, 7, 1),
        range_end_day=date(2026, 7, 7),
        all_platforms=False,
        purchased_platforms=["deepseek"],
        keyword_group_count=1,
    )
    assert limit == 500


def test_ranking_matrix_raw_rows_are_hydrated_in_batches_without_total_cap(monkeypatch) -> None:
    pages = iter(([5, 4], [3, 2], [1]))
    monkeypatch.setattr(
        monitor_service,
        "_ordered_subtask_ids",
        lambda _db, _stmt: list(next(pages)),
    )
    monkeypatch.setattr(
        monitor_service,
        "_hydrate_subtasks_in_id_order",
        lambda _db, ids, *_options: ids,
    )

    batches = list(_iter_hydrated_subtask_batches(MagicMock(), MagicMock(), batch_size=2))

    assert batches == [[5, 4], [3, 2], [1]]


def test_ranking_matrix_cache_version_changes_after_full_history_fix() -> None:
    key = ranking_matrix_cache_key(
        "CUSTOMER",
        6,
        platform=None,
        start_date="2026-01-01",
        end_date="2026-10-10",
        keyword=None,
        monitor_group=None,
        keyword_group=None,
        monitor_keyword=None,
        exposure_term=None,
        limit_rows=8000,
    )
    assert key.startswith("monitor:ranking-matrix:v4:CUSTOMER:6:")
