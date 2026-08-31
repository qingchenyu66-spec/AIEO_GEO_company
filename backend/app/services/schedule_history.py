"""调度时段历史：改时段生效日前用旧表，之后用企业当前配置。

2026-08-29 00:00 批量切了 14 家客户；缺口矩阵若一律用当前配置，
会把新三点套到切表前的历史日，造出假「漏跑待补」。
"""

from __future__ import annotations

from datetime import date, time

from app.models.brand import BrandAsset
from app.services.schedule_service import schedule_times_for_asset

# 2026-08-31 - 缺口矩阵新旧时段混显 - 以改表日为界回放旧计划
SCHEDULE_CUTOVER_DATE = date(2026, 8, 29)

# old=改表前  new=目标新表（仅文档/脚本用；历史日缺口只回放 old）
TENANT_SCHEDULE_HISTORY: dict[int, dict[str, list[str]]] = {
    6: {"old": ["09:30", "13:30", "16:30"], "new": ["02:41", "08:37", "15:42"]},
    14: {"old": ["09:35", "12:25", "16:10"], "new": ["02:06", "08:51", "15:10"]},
    118: {"old": ["09:30", "14:30", "20:30"], "new": ["02:22", "08:32", "15:48"]},
    119: {"old": ["09:30", "14:30", "20:30"], "new": ["02:38", "08:44", "15:40"]},
    120: {"old": ["00:40", "08:40", "16:40"], "new": ["02:27", "08:04", "15:20"]},
    121: {"old": ["09:30", "14:30", "20:30"], "new": ["02:12", "08:54", "15:38"]},
    124: {"old": ["09:30", "14:30", "20:30"], "new": ["02:28", "08:13", "15:49"]},
    125: {"old": ["10:30", "12:00", "20:00"], "new": ["02:05", "08:12", "15:44"]},
    128: {"old": ["09:30", "13:30", "16:30"], "new": ["02:52", "08:55", "15:28"]},
    131: {"old": ["09:30", "14:30", "20:30"], "new": ["02:54", "08:21", "15:31"]},
    132: {"old": ["09:30", "14:30", "20:30"], "new": ["02:08", "08:53", "15:17"]},
    134: {"old": ["09:30", "14:30", "20:30"], "new": ["02:53", "08:37", "15:09"]},
    141: {"old": ["09:30", "14:30", "20:30"], "new": ["02:19", "08:22", "15:42"]},
    142: {"old": ["09:00", "14:00", "20:30"], "new": ["02:23", "08:08", "15:18"]},
}


def _parse_hhmm(value: str) -> time | None:
    try:
        hour_text, minute_text = value.strip().split(":", 1)
        return time(hour=int(hour_text), minute=int(minute_text))
    except (ValueError, TypeError):
        return None


def schedule_times_for_asset_on_day(asset: BrandAsset, day: date) -> list[time]:
    """按自然日回放应期望的监测时段；切表前有备案的用旧表，否则用当前配置。"""
    history = TENANT_SCHEDULE_HISTORY.get(int(asset.tenant_id))
    if history and day < SCHEDULE_CUTOVER_DATE:
        old_times = [_parse_hhmm(item) for item in (history.get("old") or [])]
        parsed = [item for item in old_times if item is not None]
        if parsed:
            return parsed
    return schedule_times_for_asset(asset)
