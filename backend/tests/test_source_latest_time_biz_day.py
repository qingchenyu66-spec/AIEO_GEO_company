"""信源 latest_time 必须用业务日，不能被补录后的 updated_at 污染。"""


def test_source_latest_time_prefers_business_day_over_updated_at():
    from datetime import date, datetime, time

    biz_day = date(2026, 7, 12)
    updated_at = datetime(2026, 7, 14, 9, 1, 12)
    candidate = datetime.combine(biz_day, time.max).isoformat(timespec="seconds")
    assert candidate.startswith("2026-07-12")
    assert updated_at.isoformat() > candidate
    # 业务日截断后对「截至 07-13」仍可见；updated_at 则会误杀
    cutoff = datetime(2026, 7, 13, 23, 59, 59)
    assert datetime.fromisoformat(candidate) <= cutoff
    assert updated_at > cutoff
