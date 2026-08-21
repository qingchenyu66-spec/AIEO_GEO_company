"""DeepSeek fallback for ambiguous monitor answer rank extraction."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from typing import Any

from app.core.config import settings
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.services.brand_service import BrandAsset, _is_industry_monitor_keyword, ranking_task_is_industry_scoped
from app.services.deepseek_client import DeepseekApiError, DeepseekClient
from app.services.monitor_service import (
    BrandRankResolution,
    _SECONDARY_MENTION_HEADING_RE,
    _answer_body_for_rank,
    _brand_appears_in_text,
    _name_matches_brand,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LlmBrandRankResult:
    rank: int | float | None
    mentioned: bool
    category: str | None
    rank_basis: str | None
    confidence: float
    evidence: str | None
    overall_rank: int | float | None = None
    category_ranks: list | None = None


def _parse_rank_number(raw: Any) -> int | float | None:
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value:  # NaN
        return None
    return int(value) if value.is_integer() else value


def _is_secondary_rank_category(name: str) -> bool:
    text = str(name or "")
    if _SECONDARY_MENTION_HEADING_RE.search(text):
        return True
    # 2026-08-21 - 人工纠偏样本：LLM 爱钻「特色视角/单科专项/小四门」次要段
    return bool(
        re.search(
            r"特色视角|差异化品牌|单科专项|小四门|专项资料|备选清单|补充热门|"
            r"轻奢颜值补充|高端进口备选|其他补充|拓展名单",
            text,
        )
    )


def _select_llm_matrix_rank(
    category_ranks: list[dict[str, Any]],
    *,
    preferred_category: str | None,
) -> tuple[int | float | None, str | None]:
    """主表有 rank 就用主表最靠前；主表没有再用补充名单。

    2026-08-19 - 禁止 min() 让「其他值得关注」盖掉主表
    2026-08-21 - preferred 若指向较差主表段，仍取主表最靠前（纠「全科第6盖掉分科第2」）
    """
    ranked = [row for row in category_ranks if row.get("rank") is not None]
    primary = [row for row in ranked if not _is_secondary_rank_category(str(row["category"]))]
    secondary = [row for row in ranked if _is_secondary_rank_category(str(row["category"]))]
    pool = primary or secondary
    if not pool:
        return None, preferred_category
    chosen = min(pool, key=lambda item: float(item["rank"]))
    if preferred_category:
        named = next((row for row in pool if row["category"] == preferred_category), None)
        # 同段或同名时保留 preferred 标签；位次一律取 pool 最靠前
        if named is not None and float(named["rank"]) == float(chosen["rank"]):
            return named["rank"], named["category"]
    return chosen["rank"], chosen["category"]


_ANSWER_START_MARKERS = (
    "现在开始组织回答",
    "现在开始整理回答",
    "下面给出正式回答",
    "以下是正式回答",
    "以下为正式回答",
)

# 2026-08-21 - 方案 C：DeepSeek 分享页「思考/搜索引用」里的品牌名会污染表序计位
_SEARCH_CHROME_RE = re.compile(
    r"(?:搜索到|Found)\s+\d+\s+(?:个网页|web pages).*?(?:查看全部|View All)",
    re.IGNORECASE | re.DOTALL,
)
_THOUGHT_HEADER_RE = re.compile(
    r"(?:已思考[（(][^）\n)]*[）)]|Thought for \d+ seconds?)\s*",
    re.IGNORECASE,
)


def strip_pre_answer_noise_for_rank(text: str) -> str:
    """计位用正文：去掉思考过程与搜索引用区，只留正式回答。

    2026-08-21 - 方案 C：浏览页标题里的竞品名会把表内第 3 误算成第 4
    """
    raw = str(text or "")
    if not raw.strip():
        return raw

    cut_at = -1
    for marker in _ANSWER_START_MARKERS:
        idx = raw.find(marker)
        if idx >= 0 and (cut_at < 0 or idx < cut_at):
            cut_at = idx + len(marker)
    if cut_at >= 0:
        raw = raw[cut_at:]
        raw = raw.lstrip("。．. \t\r\n")

    raw = _SEARCH_CHROME_RE.sub("\n", raw)
    raw = _THOUGHT_HEADER_RE.sub("\n", raw)
    return raw.strip()


def _parse_ordered_brands(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("ordered_brands") or payload.get("brand_list_prefix") or payload.get("list_preview")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        name = str(item or "").strip()
        if name:
            out.append(name)
    return out


def _rank_from_ordered_brands(ordered_brands: list[str], brand_terms: list[str]) -> int | None:
    if not ordered_brands or not brand_terms:
        return None
    for idx, name in enumerate(ordered_brands, start=1):
        if _name_matches_brand(name, brand_terms):
            return idx
    return None


def parse_llm_rank_payload(
    payload: dict[str, Any],
    *,
    brand_terms: list[str] | None = None,
) -> LlmBrandRankResult:
    """LLM JSON → 结果。矩阵用分类排；总排只作附录。

    2026-08-19 - 总排会叠全球段，不能当 mention_position
    2026-08-19 - 主表与补充名单都有时取主表，禁止 min 到补充名单
    2026-08-21 - 方案 C：有 ordered_brands 时以列表序校对 rank，纠正 LLM 口算偏差
    """
    mentioned = bool(payload.get("brand_mentioned"))
    overall = _parse_rank_number(payload.get("overall_rank"))
    category_ranks: list[dict[str, Any]] = []
    raw_cats = payload.get("category_ranks")
    if isinstance(raw_cats, list):
        for item in raw_cats:
            if not isinstance(item, dict):
                continue
            name = str(item.get("category") or item.get("name") or "").strip()
            if not name:
                continue
            category_ranks.append(
                {"category": name, "rank": _parse_rank_number(item.get("rank"))}
            )

    category = str(payload.get("category") or "").strip() or None
    category_rank = _parse_rank_number(payload.get("category_rank"))
    selected_rank, selected_category = _select_llm_matrix_rank(
        category_ranks,
        preferred_category=category,
    )
    if selected_rank is not None:
        category_rank = selected_rank
        if selected_category:
            category = selected_category
    elif category_rank is None and category:
        named = next(
            (row["rank"] for row in category_ranks if row["category"] == category),
            None,
        )
        if named is not None:
            category_rank = named
    if category_rank is None:
        category_rank = _parse_rank_number(payload.get("rank"))

    if not category and category_ranks:
        matched = next(
            (row["category"] for row in category_ranks if row.get("rank") == category_rank),
            None,
        )
        category = matched or str(category_ranks[0]["category"])

    confidence_raw = payload.get("confidence")
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    rank_basis = str(payload.get("rank_basis") or "").strip() or None
    ordered_brands = _parse_ordered_brands(payload)
    checked = _rank_from_ordered_brands(ordered_brands, brand_terms or [])
    if checked is not None:
        mentioned = True
        if category_rank is not None and int(checked) != int(category_rank):
            # 列表序与口算不一致时信列表，避免再出现「表第三却报第四」
            category_rank = checked
            rank_basis = "ordered_brands_check"
            confidence = max(confidence, 0.9)
        elif category_rank is None:
            category_rank = checked
            rank_basis = rank_basis or "ordered_brands_check"

    return LlmBrandRankResult(
        rank=category_rank if mentioned else None,
        mentioned=mentioned,
        category=category,
        rank_basis=rank_basis,
        confidence=confidence,
        evidence=str(payload.get("evidence") or "").strip() or None,
        overall_rank=overall if mentioned else None,
        category_ranks=category_ranks or None,
    )


def should_trigger_llm_fallback(
    resolution: BrandRankResolution,
    *,
    is_industry_task: bool,
) -> bool:
    """Only call LLM for ranking prompts where rules are low-confidence."""
    if resolution.source in {"manual", "llm", "exposure"}:
        return False
    if not resolution.mentioned:
        return False
    if resolution.rank is None:
        return True
    if is_industry_task and resolution.rank > 10:
        return True
    if resolution.source == "appearance":
        return True
    if is_industry_task and resolution.source == "api":
        return True
    return False


def _truncate_answer(text: str, limit: int) -> tuple[str, bool]:
    cleaned = (text or "").strip()
    if len(cleaned) <= limit:
        return cleaned, False
    return cleaned[:limit], True


def rank_engine_is_llm() -> bool:
    return str(getattr(settings, "rank_engine", "llm") or "llm").strip().lower() == "llm"


def extract_brand_rank_with_llm(
    *,
    brand_terms: list[str],
    monitor_keyword: str,
    prompt: str,
    answer_text: str,
    force: bool = False,
) -> LlmBrandRankResult | None:
    client = DeepseekClient()
    # 2026-08-19 - rank_engine=llm 时不看 fallback 开关，有 key 就抽分类排
    if not client.api_key:
        return None
    if not force and not rank_engine_is_llm() and not client.rank_fallback_enabled:
        return None

    # 2026-08-21 - 方案 C：送 LLM 前先裁思考/搜索区，再截断
    cleaned = strip_pre_answer_noise_for_rank(answer_text)
    body, truncated = _truncate_answer(cleaned, settings.deepseek_rank_parse_max_chars)
    if not body:
        return None

    try:
        payload = client.extract_brand_rank_from_answer(
            brand_terms=brand_terms,
            monitor_keyword=monitor_keyword,
            prompt=prompt,
            answer_text=body,
            truncated=truncated,
        )
    except DeepseekApiError as exc:
        logger.warning("[rank_llm] deepseek failed monitor_keyword=%r: %s", monitor_keyword, exc)
        return None

    return parse_llm_rank_payload(payload, brand_terms=brand_terms)


def apply_llm_rank_fallback(
    resolution: BrandRankResolution,
    llm_result: LlmBrandRankResult | None,
    *,
    min_confidence: float = 0.65,
) -> BrandRankResolution:
    """合并规则结果与 LLM：有多个位次时取最靠前（数字最小）。

    2026-07-29 - 任何情况取最优 - LLM 不再无条件覆盖 appearance；与规则比 min
    """
    if llm_result is None or llm_result.confidence < min_confidence:
        return resolution
    if not llm_result.mentioned:
        if resolution.rank is None:
            return replace(resolution, mentioned=False, source="none", confidence=llm_result.confidence)
        return resolution

    llm_resolution = BrandRankResolution(
        rank=llm_result.rank,
        mentioned=True,
        source="llm",
        confidence=llm_result.confidence,
        category=llm_result.category,
        rank_basis=llm_result.rank_basis,
        evidence=llm_result.evidence,
        overall_rank=llm_result.overall_rank,
        category_ranks=llm_result.category_ranks,
    )
    if resolution.rank is None:
        return llm_resolution

    # 两边都有位次：取更靠前的一条（与方案 X 规则池一致）
    try:
        rule_key = float(resolution.rank)
        llm_key = float(llm_result.rank) if llm_result.rank is not None else float("inf")
    except (TypeError, ValueError):
        return llm_resolution
    return resolution if rule_key <= llm_key else llm_resolution


def rank_resolution_to_json(resolution: BrandRankResolution) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source": resolution.source,
        "rank": resolution.rank,
        "mentioned": resolution.mentioned,
        "confidence": resolution.confidence,
    }
    if resolution.category:
        payload["category"] = resolution.category
    if resolution.rank_basis:
        payload["rank_basis"] = resolution.rank_basis
    if resolution.evidence:
        payload["evidence"] = resolution.evidence
    if resolution.overall_rank is not None:
        payload["overall_rank"] = resolution.overall_rank
    if resolution.category_ranks:
        payload["category_ranks"] = resolution.category_ranks
    return payload


def persist_rank_resolution(subtask: GeoMonitorSubtask, resolution: BrandRankResolution) -> None:
    from datetime import datetime

    raw = dict(subtask.raw_result_json or {})
    payload = rank_resolution_to_json(resolution)
    # 2026-08-14 - 落库权威元数据带解析时间，补跑/详情可审计
    payload["parsed_at"] = datetime.now().isoformat(timespec="seconds")
    raw["rank_resolution"] = payload
    subtask.raw_result_json = raw


def _llm_resolution_from_result(llm_result: LlmBrandRankResult) -> BrandRankResolution:
    return BrandRankResolution(
        rank=llm_result.rank,
        mentioned=True,
        source="llm",
        confidence=llm_result.confidence,
        category=llm_result.category,
        rank_basis=llm_result.rank_basis or "category_local",
        evidence=llm_result.evidence,
        overall_rank=llm_result.overall_rank,
        category_ranks=llm_result.category_ranks,
    )


def _keep_llm_result_if_evidence_off(
    result: LlmBrandRankResult | None,
    answer_text: str,
) -> LlmBrandRankResult | None:
    """evidence 对不上正文时仍保留位次。

    2026-08-19 - 模型给了 rank=1 但 evidence 少空格/漏 **，整条当 llm_miss
    """
    if result is None:
        return None
    evidence = result.evidence
    if not evidence or evidence in answer_text:
        return result
    logger.info("[rank_llm] evidence not in answer, keep rank=%s", result.rank)
    return replace(result, evidence=None)


def resolve_rank_with_optional_llm(
    *,
    subtask: GeoMonitorSubtask,
    task: GeoMonitorTask,
    resolution: BrandRankResolution,
    brand_terms: list[str],
    asset: BrandAsset | None,
) -> BrandRankResolution:
    monitor_keyword = str(task.monitor_keywords or "").strip()
    answer_text = _answer_body_for_rank(subtask)
    if not _brand_appears_in_text(answer_text, brand_terms):
        return resolution

    def _run_llm() -> LlmBrandRankResult | None:
        result = extract_brand_rank_with_llm(
            brand_terms=brand_terms,
            monitor_keyword=monitor_keyword,
            prompt=str(subtask.prompt or ""),
            answer_text=answer_text,
            force=rank_engine_is_llm(),
        )
        return _keep_llm_result_if_evidence_off(result, answer_text)

    # 2026-08-19 - 规则计位先停：矩阵只用 LLM 分类排，不再和规则取 min
    if rank_engine_is_llm():
        llm_result = _run_llm()
        if llm_result is None or not llm_result.mentioned or llm_result.rank is None:
            return BrandRankResolution(
                rank=None,
                mentioned=True,
                source="none",
                confidence=0.4,
                rank_basis="llm_miss",
            )
        if llm_result.confidence < 0.65:
            return BrandRankResolution(
                rank=None,
                mentioned=True,
                source="none",
                confidence=llm_result.confidence,
                rank_basis="llm_low_conf",
                category=llm_result.category,
                evidence=llm_result.evidence,
                overall_rank=llm_result.overall_rank,
                category_ranks=llm_result.category_ranks,
            )
        return _llm_resolution_from_result(llm_result)

    is_industry_task = ranking_task_is_industry_scoped(monitor_keyword, subtask.prompt, asset)
    if not should_trigger_llm_fallback(resolution, is_industry_task=is_industry_task):
        return resolution
    return apply_llm_rank_fallback(resolution, _run_llm())
