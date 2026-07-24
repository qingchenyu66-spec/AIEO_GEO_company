"""排名矩阵行数上限：月视图全平台不得砍掉月初。"""

from datetime import date

from app.services.monitor_service import _ranking_matrix_row_limit


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
