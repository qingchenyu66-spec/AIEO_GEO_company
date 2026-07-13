"""周期报告时间窗口——生成日凌晨统计上一自然周/月/季/年。"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

AUTO_REPORT_TYPES = frozenset({"weekly", "monthly", "quarterly", "annual"})
PERIOD_COMPARISON_REPORT_TYPES = frozenset({"weekly", "monthly", "quarterly", "annual"})
HTML_TEMPLATE_REPORT_TYPES = PERIOD_COMPARISON_REPORT_TYPES | frozenset({"diagnosis"})
MANUAL_REPORT_TYPES = frozenset({"diagnosis"})


def last_day_of_month(value: date) -> date:
    return value.replace(day=calendar.monthrange(value.year, value.month)[1])


def weekly_period(anchor: date) -> tuple[date, date]:
    """生成日为周一：统计上一自然周（周一至周日）。"""
    end = anchor - timedelta(days=1)
    start = end - timedelta(days=6)
    return start, end


def monthly_period(anchor: date) -> tuple[date, date]:
    """生成日为当月 1 号：统计上一自然月。"""
    end = anchor - timedelta(days=1)
    start = end.replace(day=1)
    return start, end


def quarterly_period(anchor: date) -> tuple[date, date]:
    """生成日为季度首月 1 号（1/4/7/10 月）：统计上一自然季度。"""
    end = anchor - timedelta(days=1)
    quarter = (end.month - 1) // 3
    start_month = quarter * 3 + 1
    start = date(end.year, start_month, 1)
    end = last_day_of_month(date(end.year, start_month + 2, 1))
    return start, end


def annual_period(anchor: date) -> tuple[date, date]:
    """生成日为 1 月 1 号：统计上一自然年。"""
    year = anchor.year - 1
    return date(year, 1, 1), date(year, 12, 31)


def period_bounds(report_type: str, anchor: date) -> tuple[date, date]:
    """anchor 为自动生成任务触发日，返回该次报告应覆盖的数据统计区间。"""
    if report_type == "weekly":
        return weekly_period(anchor)
    if report_type == "monthly":
        return monthly_period(anchor)
    if report_type == "quarterly":
        return quarterly_period(anchor)
    if report_type == "annual":
        return annual_period(anchor)
    raise ValueError(f"不支持的周期报告类型: {report_type}")


def period_key(report_type: str, start: date, end: date) -> str:
    if report_type == "weekly":
        return f"weekly:{start.isoformat()}_{end.isoformat()}"
    if report_type == "monthly":
        return f"monthly:{start.year}-{start.month:02d}"
    if report_type == "quarterly":
        quarter = (start.month - 1) // 3 + 1
        return f"quarterly:{start.year}-Q{quarter}"
    if report_type == "annual":
        return f"annual:{start.year}"
    raise ValueError(f"不支持的周期报告类型: {report_type}")


def period_label(report_type: str, start: date, end: date) -> str:
    if report_type == "weekly":
        return f"{start.strftime('%Y-%m-%d')} 至 {end.strftime('%Y-%m-%d')}"
    if report_type == "monthly":
        return start.strftime("%Y年%m月")
    if report_type == "quarterly":
        quarter = (start.month - 1) // 3 + 1
        return f"{start.year} 年第{quarter}季度"
    if report_type == "annual":
        return f"{start.year} 年度"
    return f"截至 {end.strftime('%Y-%m-%d')}"


def default_report_title(report_type: str, brand_name: str, start: date, end: date) -> str:
    del brand_name
    label = {
        "weekly": "GEO 监测周报",
        "monthly": "GEO 监测月报",
        "quarterly": "GEO 监测季报",
        "annual": "GEO 监测年报",
    }.get(report_type, "GEO 监测报告")
    return f"{label}（{period_label(report_type, start, end)}）"


def bounds_from_period_key(report_type: str, key: str) -> tuple[date, date] | None:
    """由 period_key 反推统计起止日。"""
    if not key or ":" not in key:
        return None
    _, payload = key.split(":", 1)
    try:
        if report_type == "weekly":
            start_text, end_text = payload.split("_", 1)
            return date.fromisoformat(start_text), date.fromisoformat(end_text)
        if report_type == "monthly":
            year_text, month_text = payload.split("-", 1)
            start = date(int(year_text), int(month_text), 1)
            return start, last_day_of_month(start)
        if report_type == "quarterly":
            year_text, quarter_text = payload.split("-Q", 1)
            quarter = int(quarter_text)
            start_month = (quarter - 1) * 3 + 1
            start = date(int(year_text), start_month, 1)
            end = last_day_of_month(date(int(year_text), start_month + 2, 1))
            return start, end
        if report_type == "annual":
            year = int(payload)
            return date(year, 1, 1), date(year, 12, 31)
    except (TypeError, ValueError):
        return None
    return None


def due_scheduled_report_types(today: date) -> list[str]:
    """判断某日应触发的自动报告类型（凌晨任务触发日）。"""
    due: list[str] = []
    if today.weekday() == 0:
        due.append("weekly")
    if today.day == 1:
        due.append("monthly")
        if today.month in {1, 4, 7, 10}:
            due.append("quarterly")
        if today.month == 1:
            due.append("annual")
    return due
