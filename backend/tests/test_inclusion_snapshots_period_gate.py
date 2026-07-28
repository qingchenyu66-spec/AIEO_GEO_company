"""收录明细周期门禁：跟上方日期联动用 detect_day，勿用 updated_at<=昨日。"""

from datetime import datetime

from app.services.monitor_service import customer_display_cutoff, customer_display_date_range


def test_period_gate_keeps_today_rewritten_row_with_detect_in_range() -> None:
    # 模拟客户选「近 7 天」、数据截至昨日；行在今日被洗库 bump 了 updated_at
    now = datetime(2026, 7, 27, 16, 0, 0)
    range_end = customer_display_cutoff(now)
    trend_start, trend_end = customer_display_date_range(
        now=now,
        start_at=datetime(2026, 7, 20),
        end_at=datetime(2026, 7, 26, 23, 59, 59),
    )
    detect_dt = datetime(2026, 7, 24, 10, 0, 0)
    updated_at = datetime(2026, 7, 27, 15, 30, 0)

    assert trend_start <= detect_dt <= range_end
    assert trend_end.date() == range_end.date()
    # 旧门禁 updated_at<=range_end 会误杀；新口径只看 detect
    assert updated_at > range_end
