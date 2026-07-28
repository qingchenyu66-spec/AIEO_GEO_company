"""Brand analysis dashboard: DeepSeek sentiment/description + platform buckets."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, time, timedelta
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload, load_only
from sqlalchemy.orm.attributes import flag_modified

from app.api.dependencies import CurrentSession
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.services.brand_service import get_brand_asset, tenant_purchased_platforms
from app.services.deepseek_client import DeepseekApiError, DeepseekClient
from app.services.monitor_service import (
    _answer_excerpt,
    _normalize_sentiment_label,
    _resolve_workspace_brief_tenant_id,
    _subtask_answer_plaintext,
)
from app.services.molizhishu_catalog_service import get_supported_platform_catalog
from app.services.media_proxy_service import public_screenshot_url

logger = logging.getLogger(__name__)

# 2026-07-28 - 正负面：v2 过严正面归零；v3 适中口径，打开页会重判
BA_SENTIMENT_SOURCE = "deepseek-v3"
# 2026-07-27 - 一快照多要点：bump source，旧单句视为未抽，仪表盘会重抽
BA_DESC_SOURCE = "deepseek-v2"
BA_SENTIMENT_BATCH = 12
BA_SENTIMENT_MAX_PER_REQUEST = 24
BA_DESC_BATCH = 10
BA_DESC_MAX_PER_REQUEST = 24
SENTIMENT_KEYS = ("positive", "neutral", "negative")
# 软上限 8（prompt 引导）；确有更多独立要点可到硬上限 16
BA_DESC_SOFT_MAX = 8
BA_DESC_HARD_MAX = 16
# ponytail: SequenceMatcher on short CN text; 0.60 + LCS 门闩合并近义、少误并不同业务点。
# Ceiling: 仍可能漏并换词大的近义；upgrade path: embedding / DeepSeek cluster.
BA_DESC_SIMILARITY = 0.60
_DESC_PUNCT_RE = re.compile(r"[\s、。，；：！？\"'“”‘’（）()\[\]【】《》·\-—_/\\|＋+]+")


def _platform_name_map() -> dict[str, str]:
    return {
        str(item.get("code") or ""): str(item.get("name") or item.get("code") or "")
        for item in get_supported_platform_catalog()
    }


def _purchased_platforms_for_brand_words(db: Session, tenant_id: int) -> list[str]:
    """品牌分析平台口径：企业已购平台（监测词组汇总），不用品牌词组勾选冒充已购。"""
    asset = get_brand_asset(db, tenant_id)
    return tenant_purchased_platforms(db, tenant_id, asset) if asset else []


def _has_deepseek_sentiment(subtask: GeoMonitorSubtask) -> bool:
    raw = subtask.raw_result_json if isinstance(subtask.raw_result_json, dict) else {}
    return str(raw.get("_ba_sentiment_source") or "") == BA_SENTIMENT_SOURCE


def _mark_deepseek_sentiment(subtask: GeoMonitorSubtask, sentiment: str) -> None:
    raw = dict(subtask.raw_result_json) if isinstance(subtask.raw_result_json, dict) else {}
    raw["_ba_sentiment_source"] = BA_SENTIMENT_SOURCE
    raw["_ba_sentiment"] = sentiment
    subtask.raw_result_json = raw
    flag_modified(subtask, "raw_result_json")
    subtask.sentiment = sentiment


def _has_deepseek_description(subtask: GeoMonitorSubtask) -> bool:
    raw = subtask.raw_result_json if isinstance(subtask.raw_result_json, dict) else {}
    return str(raw.get("_ba_description_source") or "") == BA_DESC_SOURCE


def _normalize_description_list(items: list[Any] | None) -> list[str]:
    """清洗要点列表：去空、截断、去重；硬上限 BA_DESC_HARD_MAX。"""
    out: list[str] = []
    seen: set[str] = set()
    for item in items or []:
        text = re.sub(r"\s+", "", str(item or "").strip())
        if len(text) < 4:
            continue
        if len(text) > 60:
            text = text[:60]
        key = _normalize_description_key(text)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= BA_DESC_HARD_MAX:
            break
    return out


def _ba_descriptions(subtask: GeoMonitorSubtask) -> list[str]:
    """读多条要点；兼容旧字段单句 _ba_description。"""
    raw = subtask.raw_result_json if isinstance(subtask.raw_result_json, dict) else {}
    multi = raw.get("_ba_descriptions")
    if isinstance(multi, list):
        return _normalize_description_list(multi)
    single = str(raw.get("_ba_description") or "").strip()
    return _normalize_description_list([single] if single else [])


def _ba_description(subtask: GeoMonitorSubtask) -> str:
    rows = _ba_descriptions(subtask)
    return rows[0] if rows else ""


def _mark_deepseek_description(subtask: GeoMonitorSubtask, description: str) -> None:
    _mark_deepseek_descriptions(subtask, [description] if description else [])


def _mark_deepseek_descriptions(subtask: GeoMonitorSubtask, descriptions: list[str]) -> None:
    cleaned = _normalize_description_list(descriptions)
    raw = dict(subtask.raw_result_json) if isinstance(subtask.raw_result_json, dict) else {}
    raw["_ba_description_source"] = BA_DESC_SOURCE
    raw["_ba_descriptions"] = cleaned
    # 兼容旧读者：首条仍写单字段
    raw["_ba_description"] = cleaned[0] if cleaned else ""
    subtask.raw_result_json = raw
    flag_modified(subtask, "raw_result_json")


def _normalize_description_key(text: str) -> str:
    s = _DESC_PUNCT_RE.sub("", str(text or "").strip().lower())
    s = s.replace("全媒体", "全媒")
    return s


def _description_similarity(a: str, b: str) -> float:
    na = _normalize_description_key(a)
    nb = _normalize_description_key(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def _lcs_run_len(a: str, b: str) -> int:
    """最长连续公共子串长度（短中文要点够用）。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i, ca in enumerate(a, start=1):
        cur = [0] * (len(b) + 1)
        for j, cb in enumerate(b, start=1):
            if ca == cb:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def _descriptions_similar(a: str, b: str, *, threshold: float = BA_DESC_SIMILARITY) -> bool:
    """近义合并判定：全等/包含/高相似直接并；中段相似须 LCS≥6，避免不同业务点误并。"""
    na = _normalize_description_key(a)
    nb = _normalize_description_key(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    # 2026-07-28 - 「总部位于北京」vs「2008年成立总部位于北京」类包含句应合并
    if len(shorter) >= 6 and shorter in longer:
        return True
    ratio = SequenceMatcher(None, na, nb).ratio()
    if ratio >= 0.85:
        return True
    if ratio < threshold:
        return False
    # 2026-07-28 - 0.60~0.85 易把短视频/户外等不同要点并掉 - 加连续公共子串门闩
    return _lcs_run_len(na, nb) >= 6


def _dominant_sent_key(tally: dict[str, int]) -> str:
    if not tally:
        return "unknown"
    return max(tally.items(), key=lambda kv: (kv[1], kv[0] != "unknown"))[0]


def _sentiments_mergeable(a: str, b: str) -> bool:
    """正/负不互并；中性/未知可与任一侧合并。"""
    if a == b:
        return True
    hard = {"positive", "negative"}
    return a not in hard or b not in hard


def _merge_similar_description_buckets(
    buckets: list[dict[str, Any]],
    *,
    threshold: float = BA_DESC_SIMILARITY,
) -> list[dict[str, Any]]:
    if len(buckets) <= 1:
        return buckets
    parent = list(range(len(buckets)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(len(buckets)):
        for j in range(i + 1, len(buckets)):
            if not _sentiments_mergeable(
                _dominant_sent_key(buckets[i]["_sent_tally"]),
                _dominant_sent_key(buckets[j]["_sent_tally"]),
            ):
                continue
            if _descriptions_similar(
                buckets[i]["description"],
                buckets[j]["description"],
                threshold=threshold,
            ):
                union(i, j)

    merged: dict[int, dict[str, Any]] = {}
    for index, bucket in enumerate(buckets):
        root = find(index)
        target = merged.get(root)
        if target is None:
            merged[root] = {
                "description": bucket["description"],
                "answers": list(bucket["answers"]),
                "_sent_tally": dict(bucket["_sent_tally"]),
                "_platforms": set(bucket["_platforms"]),
            }
            continue
        # 近义组合并时按 subtask 去重，避免多样本要点并组后样本数虚高
        existing = {str(a.get("subtask_id") or "") for a in target["answers"]}
        for answer in bucket["answers"]:
            sid = str(answer.get("subtask_id") or "")
            if sid and sid in existing:
                continue
            target["answers"].append(answer)
            if sid:
                existing.add(sid)
            label = str(answer.get("sentiment") or "")
            sent_key = {
                "正面": "positive",
                "中性": "neutral",
                "负面": "negative",
            }.get(label, "unknown")
            # 上面跳过重复后才加 tally；用 answers 情感近似（与分组时一致）
            tally = target["_sent_tally"]
            tally[sent_key] = int(tally.get(sent_key, 0)) + 1
            code = str(answer.get("platform") or "").strip()
            if code:
                target["_platforms"].add(code)
        if len(str(bucket["description"])) > len(str(target["description"])):
            target["description"] = bucket["description"]
    return list(merged.values())


def preserve_brand_analysis_sentiment_on_upsert(
    subtask: GeoMonitorSubtask,
    incoming: dict[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    """同步远端时保留 DeepSeek 二次解析结果（情感 + AI 描述）。返回 (sentiment, raw_json)。"""
    prev = subtask.raw_result_json if isinstance(subtask.raw_result_json, dict) else {}
    keep = str(prev.get("_ba_sentiment_source") or "") == BA_SENTIMENT_SOURCE
    kept_value = str(prev.get("_ba_sentiment") or subtask.sentiment or "").strip().lower()
    raw = dict(incoming) if isinstance(incoming, dict) else {}
    remote_sentiment = incoming.get("sentiment") if isinstance(incoming, dict) else None
    if keep and kept_value in SENTIMENT_KEYS:
        raw["_ba_sentiment_source"] = BA_SENTIMENT_SOURCE
        raw["_ba_sentiment"] = kept_value
        sentiment_out: str | None = kept_value
    else:
        sentiment_out = str(remote_sentiment).strip() if remote_sentiment is not None else None
    if str(prev.get("_ba_description_source") or "") == BA_DESC_SOURCE:
        raw["_ba_description_source"] = BA_DESC_SOURCE
        raw["_ba_description"] = str(prev.get("_ba_description") or "").strip()
        prev_multi = prev.get("_ba_descriptions")
        if isinstance(prev_multi, list):
            raw["_ba_descriptions"] = _normalize_description_list(prev_multi)
        elif raw["_ba_description"]:
            raw["_ba_descriptions"] = [raw["_ba_description"]]
    return sentiment_out, raw


def parse_brand_word_sentiments_with_deepseek(
    db: Session,
    *,
    tenant_id: int,
    brand_name: str,
    subtasks: list[GeoMonitorSubtask],
    max_items: int = BA_SENTIMENT_MAX_PER_REQUEST,
) -> dict[str, Any]:
    """对尚未二次解析的品牌词回答调用 DeepSeek，写回 sentiment。"""
    client = DeepseekClient()
    # 品牌分析情感只依赖 API Key，不绑「情感关键词」功能开关
    if not client.api_key:
        return {"parsed": 0, "skipped": len(subtasks), "error": "未配置 DeepSeek API Key"}

    pending: list[GeoMonitorSubtask] = []
    for item in subtasks:
        if _has_deepseek_sentiment(item):
            continue
        if not _subtask_answer_plaintext(item).strip():
            continue
        pending.append(item)
        if len(pending) >= max_items:
            break

    parsed = 0
    errors: list[str] = []
    for offset in range(0, len(pending), BA_SENTIMENT_BATCH):
        batch = pending[offset:offset + BA_SENTIMENT_BATCH]
        payload = [
            {"id": item.subtask_id, "text": _subtask_answer_plaintext(item)[:1200]}
            for item in batch
        ]
        try:
            rows = client.classify_brand_answer_sentiments(brand_name=brand_name, items=payload)
        except DeepseekApiError as exc:
            logger.warning("brand analysis sentiment parse failed tenant=%s error=%s", tenant_id, exc)
            errors.append(str(exc))
            break
        by_id = {row["id"]: row["sentiment"] for row in rows}
        for item in batch:
            sentiment = by_id.get(item.subtask_id)
            if sentiment not in SENTIMENT_KEYS:
                continue
            _mark_deepseek_sentiment(item, sentiment)
            parsed += 1
    if parsed:
        db.commit()
    return {
        "parsed": parsed,
        "pending_left": max(0, len(pending) - parsed),
        "errors": errors,
    }


def parse_brand_word_descriptions_with_deepseek(
    db: Session,
    *,
    tenant_id: int,
    brand_name: str,
    subtasks: list[GeoMonitorSubtask],
    max_items: int = BA_DESC_MAX_PER_REQUEST,
) -> dict[str, Any]:
    """对尚未抽取 AI 描述的品牌词回答调用 DeepSeek，写回 raw_json。"""
    client = DeepseekClient()
    if not client.api_key:
        return {"parsed": 0, "skipped": len(subtasks), "error": "未配置 DeepSeek API Key"}

    pending: list[GeoMonitorSubtask] = []
    for item in subtasks:
        if _has_deepseek_description(item):
            continue
        if not _subtask_answer_plaintext(item).strip():
            continue
        pending.append(item)
        if len(pending) >= max_items:
            break

    parsed = 0
    errors: list[str] = []
    for offset in range(0, len(pending), BA_DESC_BATCH):
        batch = pending[offset:offset + BA_DESC_BATCH]
        payload = [
            {"id": item.subtask_id, "text": _subtask_answer_plaintext(item)[:1200]}
            for item in batch
        ]
        try:
            rows = client.extract_brand_answer_descriptions(brand_name=brand_name, items=payload)
        except (DeepseekApiError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("brand analysis description parse failed tenant=%s error=%s", tenant_id, exc)
            errors.append(str(exc))
            break
        by_id = {
            row["id"]: list(row.get("descriptions") or [])
            for row in rows
            if row.get("id")
        }
        for item in batch:
            if item.subtask_id not in by_id:
                continue
            _mark_deepseek_descriptions(item, by_id[item.subtask_id])
            parsed += 1
    if parsed:
        db.commit()
    return {
        "parsed": parsed,
        "pending_left": max(0, len(pending) - parsed),
        "errors": errors,
    }


def _group_ai_descriptions(
    subtasks: list[GeoMonitorSubtask],
    *,
    platform_names: dict[str, str],
) -> list[dict[str, Any]]:
    """相同/语义相近短描述归并；空描述跳过。一快照可贡献多条要点。点击卡片看组内全部快照。"""
    groups: dict[str, dict[str, Any]] = {}
    for item in subtasks:
        for desc in _ba_descriptions(item):
            key = _normalize_description_key(desc)
            if not key:
                continue
            code = str(item.platform or "").strip()
            label = _normalize_sentiment_label(item.sentiment)
            sent_key = {
                "正面": "positive",
                "中性": "neutral",
                "负面": "negative",
            }.get(label, "unknown")
            excerpt = _answer_excerpt(item.mention_context or _subtask_answer_plaintext(item), 160)
            answer = {
                "subtask_id": item.subtask_id,
                "task_id": item.task_id,
                "platform": code,
                "platform_name": platform_names.get(code) or code,
                "prompt": item.prompt,
                "excerpt": excerpt,
                "sentiment": label,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                "page_screenshot": public_screenshot_url(item.page_screenshot),
            }
            bucket = groups.get(key)
            if bucket is None:
                groups[key] = {
                    "description": desc,
                    "answers": [answer],
                    "_sent_tally": {sent_key: 1},
                    "_platforms": {code} if code else set(),
                }
                continue
            # 同一快照多要点归到同组时，answers 不去重：样本仍计一次语义出现
            if not any(a.get("subtask_id") == item.subtask_id for a in bucket["answers"]):
                bucket["answers"].append(answer)
                tally = bucket["_sent_tally"]
                tally[sent_key] = int(tally.get(sent_key, 0)) + 1
                if code:
                    bucket["_platforms"].add(code)
            if len(desc) > len(str(bucket.get("description") or "")):
                bucket["description"] = desc

    buckets = _merge_similar_description_buckets(list(groups.values()))

    label_of = {
        "positive": "正面",
        "neutral": "中性",
        "negative": "负面",
        "unknown": "未知",
    }
    rows: list[dict[str, Any]] = []
    for bucket in buckets:
        tally: dict[str, int] = bucket.pop("_sent_tally")
        platforms: set[str] = bucket.pop("_platforms")
        dominant = _dominant_sent_key(tally)
        answers = sorted(
            bucket["answers"],
            key=lambda row: str(row.get("updated_at") or ""),
            reverse=True,
        )
        rows.append({
            "description": bucket["description"],
            "sentiment": label_of.get(dominant, "未知"),
            "sample_count": len(answers),
            "platforms": [
                {"code": code, "name": platform_names.get(code) or code}
                for code in sorted(platforms, key=lambda c: platform_names.get(c) or c)
            ],
            "answers": answers,
        })
    rows.sort(key=lambda row: (-int(row["sample_count"]), str(row["description"])))
    return rows


def _load_brand_word_subtasks(
    db: Session,
    *,
    tenant_id: int,
    lookback_start: datetime,
    range_end: datetime,
    limit: int = 400,
) -> list[GeoMonitorSubtask]:
    stmt = (
        select(GeoMonitorSubtask)
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .options(
            joinedload(GeoMonitorSubtask.task).load_only(
                GeoMonitorTask.monitor_keywords,
                GeoMonitorTask.created_at,
                GeoMonitorTask.purpose,
            ),
            load_only(
                GeoMonitorSubtask.subtask_id,
                GeoMonitorSubtask.task_id,
                GeoMonitorSubtask.platform,
                GeoMonitorSubtask.prompt,
                GeoMonitorSubtask.status,
                GeoMonitorSubtask.answer_content,
                GeoMonitorSubtask.mention_context,
                GeoMonitorSubtask.page_screenshot,
                GeoMonitorSubtask.sentiment,
                GeoMonitorSubtask.raw_result_json,
                GeoMonitorSubtask.updated_at,
            ),
        )
        .where(
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.tenant_id == tenant_id,
            GeoMonitorTask.purpose == "brand_word",
            GeoMonitorSubtask.status.in_(("completed", "partial_completed")),
            or_(
                GeoMonitorSubtask.updated_at >= lookback_start,
                GeoMonitorTask.created_at >= lookback_start,
            ),
            GeoMonitorSubtask.updated_at <= range_end,
        )
        .order_by(GeoMonitorSubtask.updated_at.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).unique())


def build_brand_analysis_dashboard(
    db: Session,
    current: CurrentSession,
    *,
    tenant_id: int | None = None,
    parse_sentiments: bool = False,
) -> dict[str, Any]:
    """品牌分析专用：情感饼图 + 平台情感柱 + AI 描述归并。

    默认不在读路径调 DeepSeek；同步写路径 / 显式 parse=true 再补齐。
    """
    resolved = _resolve_workspace_brief_tenant_id(current, tenant_id)
    asset = get_brand_asset(db, resolved)
    brand_name = (
        (asset.company_full_name if asset else None)
        or (asset.brand_name if asset else None)
        or "监测品牌"
    )
    purchased = _purchased_platforms_for_brand_words(db, resolved)
    purchased_set = set(purchased)
    names = _platform_name_map()

    # 品牌分析实时口径：含今日，不套客户侧「截至昨日」
    now = datetime.now()
    range_end = now
    trend_start = datetime.combine(now.date() - timedelta(days=30), time.min)
    lookback_start = trend_start - timedelta(days=7)
    subtasks = _load_brand_word_subtasks(
        db,
        tenant_id=resolved,
        lookback_start=lookback_start,
        range_end=range_end,
    )
    if purchased_set:
        subtasks = [item for item in subtasks if item.platform in purchased_set]

    parse_meta: dict[str, Any] = {
        "parsed": 0,
        "pending_left": 0,
        "errors": [],
        "description_parsed": 0,
        "description_pending_left": 0,
        "description_errors": [],
    }
    if parse_sentiments and subtasks:
        # 2026-07-28 - parse=true 时 LLM/JSON 异常曾整接口 400，前端吞错一直停在旧单句
        try:
            sent_meta = parse_brand_word_sentiments_with_deepseek(
                db,
                tenant_id=resolved,
                brand_name=str(brand_name),
                subtasks=subtasks,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("brand analysis sentiment parse crashed tenant=%s", resolved)
            sent_meta = {"parsed": 0, "pending_left": len(subtasks), "errors": [str(exc)]}
        subtasks = _load_brand_word_subtasks(
            db,
            tenant_id=resolved,
            lookback_start=lookback_start,
            range_end=range_end,
        )
        if purchased_set:
            subtasks = [item for item in subtasks if item.platform in purchased_set]
        try:
            desc_meta = parse_brand_word_descriptions_with_deepseek(
                db,
                tenant_id=resolved,
                brand_name=str(brand_name),
                subtasks=subtasks,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("brand analysis description parse crashed tenant=%s", resolved)
            desc_meta = {"parsed": 0, "pending_left": len(subtasks), "errors": [str(exc)]}
        parse_meta = {
            "parsed": int(sent_meta.get("parsed") or 0),
            "pending_left": int(sent_meta.get("pending_left") or 0),
            "errors": list(sent_meta.get("errors") or []),
            "error": sent_meta.get("error") or desc_meta.get("error"),
            "description_parsed": int(desc_meta.get("parsed") or 0),
            "description_pending_left": int(desc_meta.get("pending_left") or 0),
            "description_errors": list(desc_meta.get("errors") or []),
        }
        subtasks = _load_brand_word_subtasks(
            db,
            tenant_id=resolved,
            lookback_start=lookback_start,
            range_end=range_end,
        )
        if purchased_set:
            subtasks = [item for item in subtasks if item.platform in purchased_set]
    elif subtasks:
        # 读路径默认不调 LLM，仍回报待解析量供前端决定是否二次请求
        parse_meta["pending_left"] = sum(1 for item in subtasks if not _has_deepseek_sentiment(item))
        parse_meta["description_pending_left"] = sum(
            1 for item in subtasks if not _has_deepseek_description(item)
        )

    sentiment_counts = {"正面": 0, "中性": 0, "负面": 0, "未知": 0}
    platform_counts: dict[str, int] = {code: 0 for code in purchased}
    buckets: dict[str, dict[str, list[dict[str, Any]]]] = {
        code: {"positive": [], "neutral": [], "negative": [], "unknown": []}
        for code in purchased
    }

    for item in subtasks:
        code = str(item.platform or "").strip()
        if purchased and code not in purchased_set:
            continue
        if code not in buckets:
            buckets[code] = {"positive": [], "neutral": [], "negative": [], "unknown": []}
            platform_counts[code] = 0
        label = _normalize_sentiment_label(item.sentiment)
        sentiment_counts[label] = sentiment_counts.get(label, 0) + 1
        platform_counts[code] = platform_counts.get(code, 0) + 1
        key = {
            "正面": "positive",
            "中性": "neutral",
            "负面": "negative",
        }.get(label, "unknown")
        excerpt = _answer_excerpt(item.mention_context or _subtask_answer_plaintext(item), 160)
        buckets[code][key].append({
            "subtask_id": item.subtask_id,
            "task_id": item.task_id,
            "prompt": item.prompt,
            "excerpt": excerpt,
            "sentiment": label,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            "page_screenshot": public_screenshot_url(item.page_screenshot),
        })

    # 列表只含有样本的已购平台；已购全集在 purchased_platforms
    platform_rows: list[dict[str, Any]] = []
    for code in purchased or sorted(buckets.keys()):
        count = platform_counts.get(code, 0)
        if count <= 0:
            continue
        platform_rows.append({
            "code": code,
            "name": names.get(code) or code,
            "sample_count": count,
            "positive": buckets.get(code, {}).get("positive") or [],
            "neutral": buckets.get(code, {}).get("neutral") or [],
            "negative": buckets.get(code, {}).get("negative") or [],
            "unknown": buckets.get(code, {}).get("unknown") or [],
        })

    base_pie = [
        {"name": "正面", "value": sentiment_counts["正面"]},
        {"name": "中性", "value": sentiment_counts["中性"]},
        {"name": "负面", "value": sentiment_counts["负面"]},
    ]
    if sentiment_counts["未知"]:
        base_pie.append({"name": "未知", "value": sentiment_counts["未知"]})

    platform_pie = [
        {
            "name": names.get(code) or code,
            "code": code,
            "value": platform_counts.get(code, 0),
        }
        for code in (purchased or list(platform_counts.keys()))
        if platform_counts.get(code, 0) > 0
    ]

    ai_descriptions = _group_ai_descriptions(subtasks, platform_names=names)

    period_label = f"{trend_start.date().isoformat()} ~ {range_end.date().isoformat()}"
    return {
        "tenant_id": resolved,
        "brand_name": brand_name,
        "company_name": asset.company_full_name if asset else brand_name,
        "period_label": period_label,
        "purchased_platforms": purchased,
        "sample_count": sum(platform_counts.values()),
        "sentiment_counts": sentiment_counts,
        "sentiment_pie": base_pie,
        "platform_pie": platform_pie,
        "platforms": platform_rows,
        "ai_descriptions": ai_descriptions,
        "parse": parse_meta,
        "generated_at": now.isoformat(timespec="seconds"),
    }


def parse_sentiments_after_brand_word_sync(db: Session, task: GeoMonitorTask) -> None:
    """品牌词任务同步完成后尽快二次解析情感与 AI 描述。"""
    if str(getattr(task, "purpose", "") or "") != "brand_word" or not task.tenant_id:
        return
    asset = get_brand_asset(db, task.tenant_id)
    brand_name = (asset.company_full_name if asset else None) or (asset.brand_name if asset else None) or "监测品牌"
    subtasks = list(
        db.scalars(
            select(GeoMonitorSubtask).where(
                GeoMonitorSubtask.task_id == task.task_id,
                GeoMonitorSubtask.status.in_(("completed", "partial_completed")),
            )
        )
    )
    if not subtasks:
        return
    parse_brand_word_sentiments_with_deepseek(
        db,
        tenant_id=task.tenant_id,
        brand_name=str(brand_name),
        subtasks=subtasks,
    )
    parse_brand_word_descriptions_with_deepseek(
        db,
        tenant_id=task.tenant_id,
        brand_name=str(brand_name),
        subtasks=subtasks,
    )
