"""Brand keyword-group platform selection: code + mode + screenshot."""

from __future__ import annotations

from typing import Any

from app.schemas.monitor import (
    DEEPSEEK_SEARCH_MODE,
    MonitorMode,
    ScreenshotMode,
    default_monitor_mode,
)

VALID_MODES = frozenset({"standard", "reasoning", "search", "reasoning_search"})


def normalize_platform_selection(raw: Any) -> dict[str, Any] | None:
    """Accept legacy string, dict, or PlatformSelection-like object; return normalized dict or None."""
    if isinstance(raw, str):
        code = raw.strip().lower()
        if not code:
            return None
        return {"code": code, "mode": default_monitor_mode(code), "screenshot": 1}
    if hasattr(raw, "model_dump") and callable(raw.model_dump):
        raw = raw.model_dump()
    elif hasattr(raw, "dict") and callable(raw.dict) and not isinstance(raw, dict):
        raw = raw.dict()
    elif not isinstance(raw, dict):
        code = getattr(raw, "code", None) or getattr(raw, "platform", None)
        if code is None:
            return None
        code_text = str(code).strip().lower()
        raw = {
            "code": code_text,
            "mode": getattr(raw, "mode", default_monitor_mode(code_text)),
            "screenshot": getattr(raw, "screenshot", 1),
        }
    code = str(raw.get("code") or raw.get("platform") or "").strip().lower()
    if not code:
        return None
    # 桌面 DeepSeek：强制 search（存量 standard 配置也走联网，拿信源；同价）
    if code == "deepseek":
        return {"code": code, "mode": DEEPSEEK_SEARCH_MODE, "screenshot": 1}
    mode = str(raw.get("mode") or default_monitor_mode(code)).strip().lower()
    if mode not in VALID_MODES:
        mode = default_monitor_mode(code)
    # ponytail: 产品强制截图作客户证据；UI 不再提供关闭入口，入口归一化恒为 1
    return {"code": code, "mode": mode, "screenshot": 1}


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
