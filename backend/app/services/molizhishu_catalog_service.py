"""Fetch supported Molizhishu platforms from official API documentation."""

from __future__ import annotations

import logging
import re
import threading
from datetime import datetime, timedelta
from typing import Any

from app.core.platform_order import sort_catalog_items, sort_platform_codes

import httpx

logger = logging.getLogger(__name__)

MOLIZHISHU_PLATFORM_DOC_URL = "https://doc.molizhishu.com/docs/api/submit-task"
MOLIZHISHU_PLATFORM_DOC_FALLBACK_URL = "https://doc.molizhishu.com/docs/intro"
CACHE_TTL = timedelta(hours=24)

_FALLBACK_CATALOG: list[dict[str, Any]] = sort_catalog_items([
    {"code": "doubao", "name": "豆包", "description": "字节跳动旗下的智能 AI 助手。", "channel": "web", "sort_order": 10},
    {"code": "doubao_mobile", "name": "豆包移动版", "description": "字节跳动豆包移动端版本。", "channel": "mobile", "sort_order": 11},
    {"code": "baiduai", "name": "百度 AI+", "description": "百度推出的 AI 搜索。", "channel": "web", "sort_order": 20},
    {"code": "deepseek", "name": "DeepSeek", "description": "领先的国产自研大模型，性能强劲。", "channel": "web", "sort_order": 30},
    {"code": "deepseek_mobile", "name": "DeepSeek 移动端", "description": "DeepSeek 移动端版本。", "channel": "mobile", "sort_order": 31},
    {"code": "weibo_zhisou", "name": "微博智搜", "description": "微博推出的 AI 搜索。", "channel": "web", "sort_order": 40},
    {"code": "yuanbao", "name": "元宝", "description": "腾讯出品的 AI 助手，连接微信生态。", "channel": "web", "sort_order": 50},
    {"code": "qianwen", "name": "通义千问", "description": "阿里巴巴自研大模型，功能全面。", "channel": "web", "sort_order": 60},
    {"code": "qianwen_mobile", "name": "通义千问移动端", "description": "通义千问移动端版本。", "channel": "mobile", "sort_order": 61},
    {"code": "quark", "name": "夸克", "description": "夸克浏览器内置 AI，主打搜索与学习。", "channel": "web", "sort_order": 70},
    {"code": "kimi", "name": "Kimi", "description": "月之暗面出品，支持长文本处理。", "channel": "web", "sort_order": 80},
    {"code": "antafu", "name": "蚂蚁阿福", "description": "蚂蚁集团推出的 AI 助手。", "channel": "web", "sort_order": 90},
])

_lock = threading.Lock()
_cache: dict[str, Any] = {
    "catalog": [dict(item) for item in _FALLBACK_CATALOG],
    # ponytail: None so first get_supported_platform_catalog() actually hits 官方文档，不把启动 fallback 当成已同步
    "fetched_at": None,
    "source": "fallback",
    "source_url": MOLIZHISHU_PLATFORM_DOC_URL,
}


def _channel_for_code(code: str, name: str) -> str:
    if code.endswith("_mobile") or "移动" in name:
        return "mobile"
    return "web"


def _parse_platform_rows(html: str) -> list[dict[str, Any]]:
    rows = re.findall(
        r"<code>([a-z][a-z0-9_]+)</code></td>\s*<td>([^<]+)</td>\s*<td>([^<]+)</td>",
        html,
        flags=re.IGNORECASE,
    )
    catalog: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, (code, name, description) in enumerate(rows):
        text = code.strip().lower()
        if not text or text in seen:
            continue
        seen.add(text)
        catalog.append({
            "code": text,
            "name": name.strip(),
            "description": description.strip(),
            "channel": _channel_for_code(text, name),
            "sort_order": (index + 1) * 10,
        })
    return catalog


def _fetch_doc_catalog(url: str) -> list[dict[str, Any]]:
    with httpx.Client(timeout=3.0, follow_redirects=True) as client:
        response = client.get(url, headers={"Accept": "text/html,application/json"})
        response.raise_for_status()
    catalog = _parse_platform_rows(response.text)
    if not catalog:
        raise ValueError(f"未能解析监测平台列表：{url}")
    return catalog


def refresh_platform_catalog(*, force: bool = False) -> dict[str, Any]:
    """Pull supported platforms from Molizhishu official docs."""
    with _lock:
        fetched_at = _cache.get("fetched_at")
        if (
            not force
            and fetched_at is not None
            and isinstance(fetched_at, datetime)
            and datetime.now() - fetched_at < CACHE_TTL
            and _cache.get("catalog")
            and _cache.get("source") != "fallback"
        ):
            return dict(_cache)

    last_error: Exception | None = None
    for url in (MOLIZHISHU_PLATFORM_DOC_URL, MOLIZHISHU_PLATFORM_DOC_FALLBACK_URL):
        try:
            catalog = _fetch_doc_catalog(url)
            snapshot = {
                "catalog": catalog,
                "fetched_at": datetime.now(),
                "source": "molizhishu_doc",
                "source_url": url,
            }
            with _lock:
                _cache.clear()
                _cache.update(snapshot)
            logger.info("[molizhishu] refreshed platform catalog from %s count=%s", url, len(catalog))
            return dict(snapshot)
        except Exception as exc:
            last_error = exc
            logger.warning("[molizhishu] platform catalog fetch failed url=%s error=%s", url, exc)

    if last_error is not None:
        logger.error("[molizhishu] platform catalog refresh failed, using cache/fallback: %s", last_error)
    with _lock:
        _cache.setdefault("catalog", [dict(item) for item in _FALLBACK_CATALOG])
        # 失败时保留上一次成功拉取时间；若从未成功则标记 fallback（下次仍应重试）
        if _cache.get("source") != "molizhishu_doc":
            _cache["fetched_at"] = None
            _cache["source"] = "fallback"
        _cache.setdefault("source_url", MOLIZHISHU_PLATFORM_DOC_URL)
        return dict(_cache)


def get_platform_catalog_meta() -> dict[str, Any]:
    snapshot = refresh_platform_catalog(force=False)
    fetched_at = snapshot.get("fetched_at")
    return {
        "source": snapshot.get("source") or "fallback",
        "source_url": snapshot.get("source_url") or MOLIZHISHU_PLATFORM_DOC_URL,
        "fetched_at": fetched_at.isoformat(timespec="seconds") if isinstance(fetched_at, datetime) else None,
    }


def get_supported_platform_catalog(*, force_refresh: bool = False) -> list[dict[str, Any]]:
    snapshot = refresh_platform_catalog(force=force_refresh)
    catalog = snapshot.get("catalog") or _FALLBACK_CATALOG
    return sort_catalog_items([dict(item) for item in catalog])


def supported_platform_codes(*, force_refresh: bool = False) -> frozenset[str]:
    return frozenset(item["code"] for item in get_supported_platform_catalog(force_refresh=force_refresh))


def filter_submittable_platforms(codes: list[str] | None, *, force_refresh: bool = False) -> list[str]:
    allowed = supported_platform_codes(force_refresh=force_refresh)
    result: list[str] = []
    seen: set[str] = set()
    for code in codes or []:
        text = str(code or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        if text in allowed:
            result.append(text)
    return sort_platform_codes(result)
