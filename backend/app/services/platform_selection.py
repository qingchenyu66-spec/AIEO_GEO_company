"""Brand keyword-group platform selection: code + mode + screenshot."""

from __future__ import annotations

from typing import Any

from app.schemas.monitor import FAST_MONITOR_MODE, MonitorMode, ScreenshotMode

VALID_MODES = frozenset({"standard", "reasoning", "search", "reasoning_search"})


def normalize_platform_selection(raw: Any) -> dict[str, Any] | None:
    """Accept legacy string or {code, mode, screenshot}; return normalized dict or None."""
    if isinstance(raw, str):
        code = raw.strip().lower()
        if not code:
            return None
        return {"code": code, "mode": FAST_MONITOR_MODE, "screenshot": 1}
    if not isinstance(raw, dict):
        return None
    code = str(raw.get("code") or raw.get("platform") or "").strip().lower()
    if not code:
        return None
    mode = str(raw.get("mode") or FAST_MONITOR_MODE).strip().lower()
    if mode not in VALID_MODES:
        mode = FAST_MONITOR_MODE
    try:
        screenshot = int(raw.get("screenshot", 1))
    except (TypeError, ValueError):
        screenshot = 1
    if screenshot not in (0, 1, 2):
        screenshot = 1
    return {"code": code, "mode": mode, "screenshot": screenshot}


def normalize_platform_selections(raw_list: list[Any] | None) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in raw_list or []:
        entry = normalize_platform_selection(item)
        if entry is None or entry["code"] in seen:
            continue
        seen.add(entry["code"])
        result.append(entry)
    return result


def selection_codes(raw_list: list[Any] | None) -> list[str]:
    return [item["code"] for item in normalize_platform_selections(raw_list)]


def to_platform_configs(raw_list: list[Any] | None) -> list[tuple[str, MonitorMode, ScreenshotMode]]:
    rows: list[tuple[str, MonitorMode, ScreenshotMode]] = []
    for item in normalize_platform_selections(raw_list):
        rows.append((item["code"], item["mode"], item["screenshot"]))  # type: ignore[arg-type]
    return rows
