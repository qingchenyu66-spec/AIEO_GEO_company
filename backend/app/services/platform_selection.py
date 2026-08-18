"""Brand keyword-group platform selection: code + mode + screenshot."""

from __future__ import annotations

from typing import Any

from app.schemas.monitor import DEEP_MONITOR_MODE, FAST_MONITOR_MODE, MonitorMode, ScreenshotMode


def _coerce_mode(raw: Any) -> MonitorMode:
    mode = str(raw or "").strip().lower()
    # 2026-08-18 - 深度→reasoning_search（深度+联网）；快速仍 search
    if mode in {"reasoning", "reasoning_search"}:
        return DEEP_MONITOR_MODE
    if mode == "search":
        return "search"
    # standard / 空 / 非法 → 联网 search
    return FAST_MONITOR_MODE


def normalize_platform_selection(raw: Any) -> dict[str, Any] | None:
    """Accept legacy string, dict, or PlatformSelection-like object; return normalized dict or None."""
    # 2026-08-11 - 快速→search；reasoning* 原样；字符串平台默认 search
    # 2026-08-18 - 深度也走 _coerce_mode → reasoning_search
    if isinstance(raw, str):
        code = raw.strip().lower()
        if not code:
            return None
        return {"code": code, "mode": FAST_MONITOR_MODE, "screenshot": 1}
    if hasattr(raw, "model_dump") and callable(raw.model_dump):
        raw = raw.model_dump()
    elif hasattr(raw, "dict") and callable(raw.dict) and not isinstance(raw, dict):
        raw = raw.dict()
    elif not isinstance(raw, dict):
        code = getattr(raw, "code", None) or getattr(raw, "platform", None)
        if code is None:
            return None
        code = str(code).strip().lower()
        if not code:
            return None
        return {
            "code": code,
            "mode": _coerce_mode(getattr(raw, "mode", None)),
            "screenshot": 1,
        }
    code = str(raw.get("code") or raw.get("platform") or "").strip().lower()
    if not code:
        return None
    # ponytail: 产品强制截图作客户证据；UI 不再提供关闭入口，入口归一化恒为 1
    return {"code": code, "mode": _coerce_mode(raw.get("mode")), "screenshot": 1}


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
