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
    value = str(url or "").strip().split("#", 1)[0].split("?", 1)[0].rstrip("/")
    return value


def _url_lookup_aliases(url: str) -> list[str]:
    """同一文章常见变体：http/https、www 有无。"""
    base = _normalize_url(url)
    if not is_http_url(base):
        return []
    out: list[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        text = _normalize_url(value)
        if text and text not in seen:
            seen.add(text)
            out.append(text)

    _add(base)
    if base.startswith("https://"):
        _add("http://" + base[len("https://") :])
    elif base.startswith("http://"):
        _add("https://" + base[len("http://") :])

    expanded: list[str] = []
    for item in list(out):
        expanded.append(item)
        for scheme in ("https://", "http://"):
            if not item.startswith(scheme):
                continue
            rest = item[len(scheme) :]
            if rest.startswith("www."):
                expanded.append(scheme + rest[4:])
            else:
                expanded.append(scheme + "www." + rest)
    for item in expanded:
        _add(item)
    return out


def source_cache_key(url: str) -> str:
    digest = hashlib.sha1(_normalize_url(url).encode("utf-8")).hexdigest()
    return f"source_value:{_CACHE_VERSION}:{digest}"


def _disk_path(url: str) -> Path:
    digest = hashlib.sha1(_normalize_url(url).encode("utf-8")).hexdigest()
    return _CACHE_DIR / f"{_CACHE_VERSION}-{digest}.json"


def get_cached_source_value(url: str) -> str | None:
    for candidate in _url_lookup_aliases(url):
        cached = get_json_cache(source_cache_key(candidate))
        if isinstance(cached, dict):
            text = str(cached.get("value_analysis") or "").strip()
            if text:
                return text
        path = _disk_path(candidate)
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        text = str(payload.get("value_analysis") or "").strip()
        if text:
            return text
    return None


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
    # 2026-07-29 - 同标题多 URL 时按 title 映射会串链 - 优先行内 url / top_sources 同下标
    tops = list(top_sources or [])
    out: list[dict[str, Any]] = []
    for index, row in enumerate(rows[:8]):
        title = str(row.get("title") or "").strip()
        src = tops[index] if index < len(tops) else {}
        url = _normalize_url(str(row.get("url") or ""))
        if not is_http_url(url):
            url = _normalize_url(str((src or {}).get("url") or ""))
        if not is_http_url(url) and is_http_url(title):
            url = title
        platforms = row.get("platforms")
        if not platforms:
            platforms = (src or {}).get("platforms") or []
        out.append(
            {
                "title": title or str((src or {}).get("title") or url or ""),
                "url": url,
                "count": int(row.get("count") or (src or {}).get("count") or 0),
                "platforms": platforms,
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
    sync_fill_misses: bool = False,
) -> dict[str, Any]:
    """导出/组装时：套缓存；月季年可同步补 miss，周报仅异步预热。"""
    # 2026-07-29 - 渠道拆解仍大量同句 - 月季年 miss 同步深抓+LLM，避免只剩规则套话
    updated, misses = apply_cached_source_value_analyses(modules, top_sources=top_sources)
    if sync_fill_misses and misses:
        try:
            pregenerate_source_value_analyses(
                brand_name=brand_name,
                period_label=period_label,
                sources=misses,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("信源价值同步补齐失败：%s", exc)
        updated, misses = apply_cached_source_value_analyses(updated, top_sources=top_sources)
    if enqueue_misses and misses:
        enqueue_source_value_pregenerate(
            brand_name=brand_name,
            period_label=period_label,
            sources=misses,
        )
    return updated
