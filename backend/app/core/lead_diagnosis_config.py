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


def clamp_lead_schedule_days(value: int | None) -> int:
    """新建诊断天数：默认 3；建议 3–7；硬限制 1–30。"""
    try:
        days = int(value) if value is not None else LEAD_SCHEDULE_DAYS
    except (TypeError, ValueError):
        days = LEAD_SCHEDULE_DAYS
    return max(LEAD_SCHEDULE_DAYS_MIN, min(LEAD_SCHEDULE_DAYS_MAX, days))
