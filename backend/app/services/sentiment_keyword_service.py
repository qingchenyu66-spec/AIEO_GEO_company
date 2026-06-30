"""Extract positive/negative keyword phrases from monitor answers for word cloud."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.api.dependencies import CurrentSession
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.services.brand_service import get_brand_asset
from app.services.competitor_analytics_service import (
    _entity_mentioned_in_entries,
    _normalize_sentiment_label,
    _parse_platform_filters,
    _resolve_tenant_id,
)
from app.services.deepseek_client import DeepseekApiError, DeepseekClient
from app.services.ranking_parser import normalize_structured_rankings

logger = logging.getLogger(__name__)

_LLM_BATCH_SIZE = 8
_LLM_MAX_SUBTASKS = 32

_STOP_WORDS = set(
    "的 了 在 是 我 有 和 就 不 人 都 一 个 上 也 很 到 说 要 去 你 会 着 没有 看 好 自己 这 他 她 它 们 那 什么 怎么 哪 为什么 可以 因为 所以 但是 如果 虽然 而且 还是 只是 已经 比较 非常 一起 需要 可能 应该 或者 然后 不过 其实 目前 根据 方面 通过 进行 使用 以及 一些 更加 相关 存在 包括 不同 主要 关于 其中 对于 同时 问题 情况 内容 结果 信息 用户 数据 功能 服务 产品 公司 企业 品牌 提供 是否 如何 这样 那样 之后 以前 以后 之前 之中 之外 之内 回答 推荐 选择 适合 适合谁 适合您 基于 最新 市场 行业 头部 代表 公司 传媒 广告 电梯 媒体 投放 覆盖 全国 区域 本地 中小 品牌 客户 目标 受众 预算 规模 属性 分类 整理 对比 速览 主流 核心 优势 地位 数据 特点 定位 一句话 表格 公司类型 适合 谁 如下 以下 第一 第二 第三 第四 第五".split()
)

_CITATION_RE = re.compile(r"\[\s*citation\s*:\s*\d+\s*\]", re.I)
_MARKDOWN_RE = re.compile(r"\*\*|__|`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_CLAUSE_SPLIT = re.compile(r"[。！？；\n\r|]+")
_PHRASE_SPLIT = re.compile(r"[；;，,、：:]+")
_NOISE_RE = re.compile(r"^[#\->\s|·•\d.]+$")


def _clean_text(text: str) -> str:
    cleaned = _CITATION_RE.sub("", text)
    cleaned = _LINK_RE.sub(r"\1", cleaned)
    cleaned = _MARKDOWN_RE.sub("", cleaned)
    cleaned = re.sub(r"^[*\-\s]+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"[#\->\|]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _is_valid_phrase(phrase: str) -> bool:
    text = phrase.strip()
    if not text or _NOISE_RE.match(text):
        return False
    if len(text) < 4 or len(text) > 28:
        return False
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
    if len(chinese_chars) < 2:
        return False
    if text in _STOP_WORDS:
        return False
    if re.fullmatch(r"[\d\sWw%+]+", text):
        return False
    return True


def _extract_phrases(text: str | None) -> set[str]:
    if not text:
        return set()
    cleaned = _clean_text(text)
    if not cleaned:
        return set()

    phrases: set[str] = set()
    for clause in _CLAUSE_SPLIT.split(cleaned):
        clause = clause.strip()
        if _is_valid_phrase(clause):
            phrases.add(clause)
        for part in _PHRASE_SPLIT.split(clause):
            part = part.strip()
            if _is_valid_phrase(part):
                phrases.add(part)

    for word in re.findall(r"[\u4e00-\u9fff]{4,12}", cleaned):
        if word not in _STOP_WORDS:
            phrases.add(word)
    return phrases


def _brand_names(asset) -> set[str]:
    names: set[str] = set()
    if asset is None:
        return names
    for value in (asset.brand_name, asset.brand_short_name, asset.company_full_name):
        text = str(value or "").strip()
        if text:
            names.add(text)
    return names


def _brand_mentioned(item: GeoMonitorSubtask, brand_names: set[str]) -> bool:
    if item.mention_position is not None:
        return True
    if not brand_names:
        return True
    entries = normalize_structured_rankings(item.all_rankings_json or [])
    return any(_entity_mentioned_in_entries(entries, name) for name in brand_names)


def _snippet_for_subtask(item: GeoMonitorSubtask) -> str:
    context = _clean_text(item.mention_context or "")
    if context:
        return context[:420]
    answer = _clean_text(item.answer_content or "")
    return answer[:720]


def _aggregate_rule_based(
    items: list[GeoMonitorSubtask],
    brand_names: set[str],
) -> dict[str, dict[str, Any]]:
    bucket: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "subtask_ids": [], "task_ids": []})
    for item in items:
        phrases = _extract_phrases(item.mention_context)
        phrases.update(_extract_phrases(item.answer_content))
        for phrase in phrases:
            if brand_names and phrase in brand_names:
                continue
            entry = bucket[phrase]
            entry["count"] += 1
            entry["subtask_ids"].append(item.subtask_id)
            entry["task_ids"].append(item.task_id)
    return bucket


def _aggregate_with_deepseek(
    *,
    brand_display: str,
    polarity: str,
    items: list[GeoMonitorSubtask],
    brand_names: set[str],
) -> dict[str, dict[str, Any]] | None:
    client = DeepseekClient()
    if not client.enabled or not items:
        return None

    bucket: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "subtask_ids": [], "task_ids": []})
    sampled = items[:_LLM_MAX_SUBTASKS]
    excerpts = [
        {
            "subtask_id": item.subtask_id,
            "task_id": item.task_id,
            "text": _snippet_for_subtask(item),
        }
        for item in sampled
        if _snippet_for_subtask(item)
    ]
    if not excerpts:
        return None

    extracted_total = 0
    for start in range(0, len(excerpts), _LLM_BATCH_SIZE):
        batch = excerpts[start:start + _LLM_BATCH_SIZE]
        try:
            phrases = client.extract_sentiment_phrases(
                brand_name=brand_display,
                polarity=polarity,
                excerpts=batch,
            )
        except DeepseekApiError as exc:
            logger.warning("DeepSeek 情绪词提取失败：%s", exc)
            return None
        for row in phrases:
            text = row["text"]
            if brand_names and text in brand_names:
                continue
            entry = bucket[text]
            entry["count"] += 1
            entry["subtask_ids"].append(row["subtask_id"])
            entry["task_ids"].append(row["task_id"])
            extracted_total += 1

    if extracted_total == 0:
        return None
    return bucket


def build_sentiment_keywords(
    db: Session,
    current: CurrentSession,
    *,
    tenant_id: int | None = None,
    platform: str | None = None,
    platforms: str | None = None,
    days: int = 30,
    prompt: str | None = None,
    limit: int = 80,
) -> dict[str, Any]:
    resolved_tenant_id = _resolve_tenant_id(current, tenant_id)
    empty = {
        "positive": [],
        "negative": [],
        "positive_sample": 0,
        "negative_sample": 0,
        "source": "rule",
    }
    if resolved_tenant_id is None:
        return empty

    asset = get_brand_asset(db, resolved_tenant_id)
    brand_names = _brand_names(asset)
    range_end = datetime.now()
    range_start = range_end - timedelta(days=max(1, min(days, 365)))
    platform_filters = _parse_platform_filters(platform, platforms)
    prompt_filter = str(prompt or "").strip()

    stmt = (
        select(GeoMonitorSubtask)
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .options(
            load_only(
                GeoMonitorSubtask.subtask_id,
                GeoMonitorSubtask.task_id,
                GeoMonitorSubtask.platform,
                GeoMonitorSubtask.prompt,
                GeoMonitorSubtask.mention_position,
                GeoMonitorSubtask.all_rankings_json,
                GeoMonitorSubtask.sentiment,
                GeoMonitorSubtask.answer_content,
                GeoMonitorSubtask.mention_context,
                GeoMonitorSubtask.updated_at,
            )
        )
        .where(
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.tenant_id == resolved_tenant_id,
            GeoMonitorSubtask.updated_at >= range_start,
            GeoMonitorSubtask.updated_at <= range_end,
            GeoMonitorSubtask.status.in_(("completed", "partial_completed")),
            GeoMonitorSubtask.sentiment.isnot(None),
        )
    )
    if platform_filters:
        stmt = stmt.where(GeoMonitorSubtask.platform.in_(platform_filters))
    if prompt_filter:
        stmt = stmt.where(GeoMonitorSubtask.prompt == prompt_filter)

    subtasks = list(db.scalars(stmt.limit(5000)))
    brand_display = (asset.brand_name if asset else None) or "本品牌"
    grouped: dict[str, list[GeoMonitorSubtask]] = {"positive": [], "negative": []}
    sample_counts = {"positive": 0, "negative": 0}

    for item in subtasks:
        polarity = _normalize_sentiment_label(item.sentiment)
        if polarity not in ("positive", "negative"):
            continue
        if not _brand_mentioned(item, brand_names):
            continue
        sample_counts[polarity] += 1
        grouped[polarity].append(item)

    buckets: dict[str, dict[str, dict[str, Any]]] = {"positive": {}, "negative": {}}
    used_llm = False
    for polarity in ("positive", "negative"):
        llm_bucket = _aggregate_with_deepseek(
            brand_display=brand_display,
            polarity=polarity,
            items=grouped[polarity],
            brand_names=brand_names,
        )
        if llm_bucket:
            buckets[polarity] = llm_bucket
            used_llm = True
        else:
            buckets[polarity] = _aggregate_rule_based(grouped[polarity], brand_names)

    def finalize(polarity: str) -> list[dict[str, Any]]:
        rows = []
        for text, stats in buckets[polarity].items():
            rows.append({
                "text": text,
                "count": int(stats["count"]),
                "subtask_id": stats["subtask_ids"][0],
                "task_id": stats["task_ids"][0],
                "subtask_ids": stats["subtask_ids"][:5],
            })
        rows.sort(key=lambda row: (-row["count"], row["text"]))
        return rows[: max(1, min(limit, 120))]

    return {
        "positive": finalize("positive"),
        "negative": finalize("negative"),
        "positive_sample": sample_counts["positive"],
        "negative_sample": sample_counts["negative"],
        "source": "deepseek" if used_llm else "rule",
    }
