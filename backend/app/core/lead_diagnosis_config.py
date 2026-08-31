"""售前诊断调度常量（与前端 useLeadDiagnosis.ts 保持一致）。"""

from __future__ import annotations

LEAD_SCHEDULE_DAYS = 3
# 建议区间（产品口径）；硬限制另见 MIN/MAX
LEAD_SCHEDULE_DAYS_SUGGEST_MIN = 3
LEAD_SCHEDULE_DAYS_SUGGEST_MAX = 7
# 2026-08-04 - 天数「建议 3–7」非必须 - 硬限制放宽，避免误拦业务
LEAD_SCHEDULE_DAYS_MIN = 1
LEAD_SCHEDULE_DAYS_MAX = 30
DEFAULT_LEAD_SCHEDULE_TIMES = ["09:30", "14:30", "20:30"]
LEAD_DIAGNOSIS_CREATE_COOLDOWN_DAYS = 7
# 2026-08-31 - H5 按「监测次数」配置：每天最多 3 档，允许任意 1–90，不必整除 3
H5_SCHEDULE_RUNS_MIN = 1
H5_SCHEDULE_RUNS_MAX = 90
H5_SCHEDULE_SLOTS_PER_DAY = len(DEFAULT_LEAD_SCHEDULE_TIMES)


def clamp_lead_schedule_days(value: int | None) -> int:
    """新建诊断天数：默认 3；建议 3–7；硬限制 1–30。"""
    try:
        days = int(value) if value is not None else LEAD_SCHEDULE_DAYS
    except (TypeError, ValueError):
        days = LEAD_SCHEDULE_DAYS
    return max(LEAD_SCHEDULE_DAYS_MIN, min(LEAD_SCHEDULE_DAYS_MAX, days))


def clamp_h5_schedule_runs(value: int | None) -> int:
    try:
        runs = int(value) if value is not None else H5_SCHEDULE_SLOTS_PER_DAY * LEAD_SCHEDULE_DAYS
    except (TypeError, ValueError):
        runs = H5_SCHEDULE_SLOTS_PER_DAY * LEAD_SCHEDULE_DAYS
    return max(H5_SCHEDULE_RUNS_MIN, min(H5_SCHEDULE_RUNS_MAX, runs))


def h5_runs_to_schedule_days(runs: int) -> int:
    """次数换日历跨度：ceil(runs/每天档数)，供 schedule_days 字段兼容。"""
    n = clamp_h5_schedule_runs(runs)
    return max(LEAD_SCHEDULE_DAYS_MIN, (n + H5_SCHEDULE_SLOTS_PER_DAY - 1) // H5_SCHEDULE_SLOTS_PER_DAY)
