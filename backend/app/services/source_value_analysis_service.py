"""渠道价值拆解：Playwright 读正文 → LLM 评价；导出只读缓存，异步预生成。"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.redis_client import get_json_cache, redis_lock, set_json_cache
from app.services.source_article_fetch_service import fetch_source_articles_batch, is_http_url

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).resolve().parents[2] / "storage" / "source_value_cache"
_CACHE_TTL_SECONDS = 7 * 24 * 3600
_CACHE_VERSION = "v1"
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="source-value")
_inflight: set[str] = set()
_inflight_lock = threading.Lock()


def _normalize_url(url: str) -> str:
    return str(url or "").strip().split("#", 1)[0]


def source_cache_key(url: str) -> str:
    digest = hashlib.sha1(_normalize_url(url).encode("utf-8")).hexdigest()
    return f"source_value:{_CACHE_VERSION}:{digest}"


def _disk_path(url: str) -> Path:
    digest = hashlib.sha1(_normalize_url(url).encode("utf-8")).hexdigest()
    return _CACHE_DIR / f"{_CACHE_VERSION}-{digest}.json"


def get_cached_source_value(url: str) -> str | None:
    value = _normalize_url(url)
    if not is_http_url(value):
        return None
    cached = get_json_cache(source_cache_key(value))
    if isinstance(cached, dict):
        text = str(cached.get("value_analysis") or "").strip()
        if text:
            return text
    path = _disk_path(value)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    text = str(payload.get("value_analysis") or "").strip()
    return text or None


def set_cached_source_value(
    url: str,
    *,
    value_analysis: str,
    title: str = "",
    brand_name: str = "",
    excerpt_len: int = 0,
) -> None:
    value = _normalize_url(url)
    text = str(value_analysis or "").strip()
    if not is_http_url(value) or not text:
        return
    payload = {
        "url": value,
        "title": title,
        "brand_name": brand_name,
        "value_analysis": text,
        "excerpt_len": int(excerpt_len or 0),
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    set_json_cache(source_cache_key(value), payload, ttl_seconds=_CACHE_TTL_SECONDS)
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _disk_path(value).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        logger.warning("信源价值缓存落盘失败 url=%s err=%s", value[:120], exc)


def _sources_payload(
    rows: list[dict[str, Any]],
    top_sources: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    url_by_title: dict[str, str] = {}
    platforms_by_title: dict[str, Any] = {}
    for item in top_sources or []:
        title = str(item.get("title") or item.get("url") or "").strip()
        if not title:
            continue
        url_by_title[title] = _normalize_url(str(item.get("url") or ""))
        platforms_by_title[title] = item.get("platforms") or []

    out: list[dict[str, Any]] = []
    for row in rows[:8]:
        title = str(row.get("title") or "").strip()
        url = url_by_title.get(title) or _normalize_url(str(row.get("url") or ""))
        if not url and is_http_url(title):
            url = title
        out.append(
            {
                "title": title,
                "url": url,
                "count": int(row.get("count") or 0),
                "platforms": row.get("platforms") or platforms_by_title.get(title) or [],
            }
        )
    return out


def apply_cached_source_value_analyses(
    modules: dict[str, Any],
    *,
    top_sources: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """用缓存覆盖 value_analysis；返回 (modules, 未命中且可抓取的信源列表)。"""
    influence = dict((modules or {}).get("source_influence") or {})
    rows = list(influence.get("rows") or [])
    if not rows:
        return modules, []

    payload = _sources_payload(rows, top_sources)
    updated: list[dict[str, Any]] = []
    misses: list[dict[str, Any]] = []
    for row, item in zip(rows, payload):
        next_row = dict(row)
        cached = get_cached_source_value(item["url"]) if item.get("url") else None
        if cached:
            next_row["value_analysis"] = cached
        elif is_http_url(str(item.get("url") or "")):
            misses.append(item)
        updated.append(next_row)

    if len(rows) > len(payload):
        updated.extend(dict(r) for r in rows[len(payload) :])

    out = dict(modules)
    out["source_influence"] = {**influence, "rows": updated}
    return out, misses


def pregenerate_source_value_analyses(
    *,
    brand_name: str,
    period_label: str = "",
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """Playwright 抓正文 + LLM 写拆解并写入缓存。供 Celery/后台线程调用。"""
    # 2026-07-29 - 方案 B：深抓正文异步预生成，导出链路只读缓存不阻塞
    cleaned: list[dict[str, Any]] = []
    for raw in sources[:8]:
        url = _normalize_url(str((raw or {}).get("url") or ""))
        if not is_http_url(url):
            continue
        if get_cached_source_value(url):
            continue
        cleaned.append(
            {
                "title": str((raw or {}).get("title") or url)[:180],
                "url": url,
                "count": int((raw or {}).get("count") or 0),
                "platforms": (raw or {}).get("platforms") or [],
            }
        )
    if not cleaned:
        return {"status": "ok", "fetched": 0, "analyzed": 0, "skipped": "all_cached_or_empty"}

    lock_token = hashlib.sha1("|".join(sorted(r["url"] for r in cleaned)).encode("utf-8")).hexdigest()[:16]
    with redis_lock(f"source_value_pregen:{lock_token}", ttl_seconds=900) as acquired:
        if not acquired:
            return {"status": "skipped", "reason": "lock_held"}

        # 二次过滤：拿锁期间可能已被其他 worker 写完
        cleaned = [row for row in cleaned if not get_cached_source_value(row["url"])]
        if not cleaned:
            return {"status": "ok", "fetched": 0, "analyzed": 0, "skipped": "filled_while_waiting"}

        bodies = fetch_source_articles_batch([row["url"] for row in cleaned])
        with_body: list[dict[str, Any]] = []
        for row in cleaned:
            excerpt = bodies.get(row["url"]) or ""
            if not excerpt:
                logger.info("信源正文未取到，跳过 LLM url=%s", row["url"][:160])
                continue
            with_body.append({**row, "excerpt": excerpt})

        if not with_body:
            return {"status": "ok", "fetched": 0, "analyzed": 0, "skipped": "no_body"}

        from app.services.deepseek_client import DeepseekApiError, DeepseekClient

        client = DeepseekClient()
        if not client.report_enabled:
            return {"status": "skipped", "reason": "report_llm_disabled", "fetched": len(with_body)}

        try:
            analyses = client.generate_source_value_analyses(
                brand_name=brand_name,
                period_label=period_label,
                sources=with_body,
            )
        except DeepseekApiError as exc:
            logger.warning("信源价值 LLM 失败：%s", exc)
            return {"status": "failed", "error": str(exc), "fetched": len(with_body)}

        stored = 0
        for row, analysis in zip(with_body, analyses):
            set_cached_source_value(
                row["url"],
                value_analysis=analysis,
                title=row.get("title") or "",
                brand_name=brand_name,
                excerpt_len=len(str(row.get("excerpt") or "")),
            )
            stored += 1
        return {"status": "ok", "fetched": len(with_body), "analyzed": stored}


def enqueue_source_value_pregenerate(
    *,
    brand_name: str,
    period_label: str = "",
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """入队异步预生成；无有效 URL 则 no-op。"""
    pending = []
    for raw in sources[:8]:
        url = _normalize_url(str((raw or {}).get("url") or ""))
        if not is_http_url(url):
            continue
        if get_cached_source_value(url):
            continue
        pending.append(
            {
                "title": str((raw or {}).get("title") or url),
                "url": url,
                "count": int((raw or {}).get("count") or 0),
                "platforms": (raw or {}).get("platforms") or [],
            }
        )
    if not pending:
        return {"queued": False, "reason": "nothing_to_do"}

    batch_key = hashlib.sha1(
        f"{brand_name}|{period_label}|{'|'.join(sorted(p['url'] for p in pending))}".encode("utf-8")
    ).hexdigest()[:20]
    with _inflight_lock:
        if batch_key in _inflight:
            return {"queued": False, "reason": "inflight"}
        _inflight.add(batch_key)

    def _run() -> None:
        try:
            pregenerate_source_value_analyses(
                brand_name=brand_name,
                period_label=period_label,
                sources=pending,
            )
        finally:
            with _inflight_lock:
                _inflight.discard(batch_key)

    if settings.celery_enabled:
        try:
            from app.tasks.report_source_value import pregenerate_source_value_task

            pregenerate_source_value_task.delay(
                brand_name=brand_name,
                period_label=period_label,
                sources=pending,
            )
            with _inflight_lock:
                _inflight.discard(batch_key)
            return {"queued": True, "via": "celery", "count": len(pending)}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Celery 入队失败，回退线程池：%s", exc)

    _executor.submit(_run)
    return {"queued": True, "via": "thread", "count": len(pending)}


def enrich_source_influence_with_cached_llm(
    modules: dict[str, Any],
    *,
    brand_name: str,
    period_label: str = "",
    top_sources: list[dict[str, Any]] | None = None,
    enqueue_misses: bool = True,
) -> dict[str, Any]:
    """导出/组装时：只套缓存；未命中保留规则文案并异步预生成。"""
    # 2026-07-29 - 渠道拆解敷衍 + 勿同步深抓 - 读缓存；miss 入队 Playwright+LLM
    updated, misses = apply_cached_source_value_analyses(modules, top_sources=top_sources)
    if enqueue_misses and misses:
        enqueue_source_value_pregenerate(
            brand_name=brand_name,
            period_label=period_label,
            sources=misses,
        )
    return updated
