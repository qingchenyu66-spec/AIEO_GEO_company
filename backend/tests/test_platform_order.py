from app.core.platform_order import ranking_matrix_row_sort_key


def test_ranking_matrix_row_sort_key_keeps_market_rank_within_day() -> None:
    day = "2026-07-06"
    rows = [
        {"day_key": day, "keyword_group": "", "platform": "kimi"},
        {"day_key": day, "keyword_group": "", "platform": "doubao_mobile"},
        {"day_key": day, "keyword_group": "", "platform": "baiduai"},
    ]
    ordered = sorted(
        rows,
        key=lambda row: ranking_matrix_row_sort_key(
            day_key=row["day_key"],
            keyword_group=row["keyword_group"],
            platform=row["platform"],
        ),
        reverse=True,
    )
    assert [row["platform"] for row in ordered] == ["doubao_mobile", "baiduai", "kimi"]


def test_ranking_matrix_row_sort_key_keeps_newer_day_first() -> None:
    rows = [
        {"day_key": "2026-07-05", "keyword_group": "", "platform": "doubao"},
        {"day_key": "2026-07-06", "keyword_group": "", "platform": "kimi"},
    ]
    ordered = sorted(
        rows,
        key=lambda row: ranking_matrix_row_sort_key(
            day_key=row["day_key"],
            keyword_group=row["keyword_group"],
            platform=row["platform"],
        ),
        reverse=True,
    )
    assert ordered[0]["day_key"] == "2026-07-06"
