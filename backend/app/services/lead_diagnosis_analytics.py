"""售前诊断扩展分析：对齐模力指数报告的语义词排名、提及率、信源与趋势。"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from app.models.lead_diagnosis import LeadDiagnosis, LeadDiagnosisRun
from app.models.monitor import GeoMonitorSubtask
from app.core.region_catalog import region_display_name
from app.services.monitor_service import TERMINAL_STATUSES
from app.services.ranking_parser import (
    normalize_structured_rankings,
    ranking_entry_explicit_rank,
    ranking_entry_name,
)


def _normalize_name_key(name: str | None) -> str:
    text = str(name or "").strip().lower()
    return re.sub(r"\s+", "", text)


def names_match(left: str | None, right: str | None) -> bool:
    a = _normalize_name_key(left)
    b = _normalize_name_key(right)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    if len(a) >= 2 and len(b) >= 2 and (a[:2] in b or b[:2] in a):
        return True
    return False


def _find_entity_rank(entries: list[dict[str, Any]], entity_name: str) -> float | None:
    for entry in entries:
        if names_match(ranking_entry_name(entry), entity_name):
            rank = ranking_entry_explicit_rank(entry)
            if rank is not None:
                return float(rank)
    return None


def _entity_mentioned(entries: list[dict[str, Any]], entity_name: str) -> bool:
    return any(names_match(ranking_entry_name(entry), entity_name) for entry in entries)


def _source_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc or urlparse(f"https://{url}").netloc
    except Exception:
        return ""
    return host.lower().removeprefix("www.")


def _round_rate(mention_count: int, sample_count: int) -> float:
    if not sample_count:
        return 0.0
    return round(mention_count / sample_count * 100, 1)


def _entity_flags(name: str, brand: str, competitors: list[str]) -> dict[str, bool]:
    return {
        "is_brand": names_match(name, brand),
        "is_competitor": any(names_match(name, item) for item in competitors),
    }


def _mention_row(
    name: str,
    *,
    brand: str,
    competitors: list[str],
    sample_count: int,
    mention_count: int,
    ranks: list[float],
) -> dict[str, Any]:
    flags = _entity_flags(name, brand, competitors)
    return {
        "name": name,
        **flags,
        "sample_count": sample_count,
        "mention_count": mention_count,
        "mention_rate": _round_rate(mention_count, sample_count),
        "avg_rank": round(sum(ranks) / len(ranks), 1) if ranks else None,
    }


def _build_prompt_mention_table(
    rows: list[GeoMonitorSubtask],
    *,
    brand: str,
    competitors: list[str],
) -> list[dict[str, Any]]:
    sample_count = len(rows)
    tracked = [brand, *competitors]
    stats: dict[str, dict[str, Any]] = {
        name: {"mention_count": 0, "ranks": []} for name in tracked
    }

    for item in rows:
        entries = normalize_structured_rankings(item.all_rankings_json or [])
        for name in tracked:
            mentioned = _entity_mentioned(entries, name)
            rank = _find_entity_rank(entries, name)
            if names_match(name, brand) and not mentioned and item.mention_position:
                mentioned = True
                rank = float(item.mention_position)
            if not mentioned:
                continue
            stats[name]["mention_count"] += 1
            if rank is not None:
                stats[name]["ranks"].append(rank)

    table = [
        _mention_row(
            name,
            brand=brand,
            competitors=competitors,
            sample_count=sample_count,
            mention_count=stats[name]["mention_count"],
            ranks=stats[name]["ranks"],
        )
        for name in tracked
    ]
    extra_names: Counter[str] = Counter()
    for item in rows:
        for entry in normalize_structured_rankings(item.all_rankings_json or []):
            entry_name = ranking_entry_name(entry)
            if not entry_name or any(names_match(entry_name, n) for n in tracked):
                continue
            extra_names[entry_name] += 1
    for entry_name, count in extra_names.most_common(8):
        ranks: list[float] = []
        mention_count = 0
        for item in rows:
            entries = normalize_structured_rankings(item.all_rankings_json or [])
            if _entity_mentioned(entries, entry_name):
                mention_count += 1
                rank = _find_entity_rank(entries, entry_name)
                if rank is not None:
                    ranks.append(rank)
        table.append(
            _mention_row(
                entry_name,
                brand=brand,
                competitors=competitors,
                sample_count=sample_count,
                mention_count=mention_count,
                ranks=ranks,
            )
        )
    table.sort(key=lambda row: (-row["mention_rate"], row["avg_rank"] or 999))
    return table


def _build_prompt_ranking_list(
    rows: list[GeoMonitorSubtask],
    *,
    brand: str,
    competitors: list[str],
) -> list[dict[str, Any]]:
    if not rows:
        return []
    latest_time = max((item.updated_at or datetime.min) for item in rows)
    latest_rows = [item for item in rows if item.updated_at == latest_time] or rows[-1:]
    aggregated: dict[tuple[str, str | None], dict[str, Any]] = {}
    for item in latest_rows:
        for entry in normalize_structured_rankings(item.all_rankings_json or []):
            name = ranking_entry_name(entry)
            if not name:
                continue
            category = entry.get("category")
            key = (name, category)
            rank = ranking_entry_explicit_rank(entry)
            bucket = aggregated.setdefault(
                key,
                {
                    "name": name,
                    "category": category or "默认分类",
                    "ranks": [],
                    **_entity_flags(name, brand, competitors),
                },
            )
            if rank is not None:
                bucket["ranks"].append(float(rank))
    result = []
    for bucket in aggregated.values():
        ranks = bucket["ranks"]
        result.append(
            {
                "name": bucket["name"],
                "category": bucket["category"],
                "rank": round(min(ranks), 1) if ranks else None,
                "is_brand": bucket["is_brand"],
                "is_competitor": bucket["is_competitor"],
            }
        )
    result.sort(key=lambda row: (row["rank"] is None, row["rank"] or 999))
    return result[:15]


def _avg_rank_for_entity_in_batch(
    batch: list[GeoMonitorSubtask],
    entity_name: str,
    *,
    is_brand: bool = False,
) -> float | None:
    ranks: list[float] = []
    for item in batch:
        entries = normalize_structured_rankings(item.all_rankings_json or [])
        mentioned = _entity_mentioned(entries, entity_name)
        rank = _find_entity_rank(entries, entity_name)
        if is_brand and not mentioned and item.mention_position:
            mentioned = True
            rank = float(item.mention_position)
        if mentioned and rank is not None:
            ranks.append(rank)
    return round(sum(ranks) / len(ranks), 1) if ranks else None


def _tracked_entities(brand: str, competitors: list[str], *, limit: int = 4) -> list[str]:
    names = [brand]
    for name in competitors:
        cleaned = str(name).strip()
        if cleaned and not any(names_match(cleaned, existing) for existing in names):
            names.append(cleaned)
        if len(names) >= limit:
            break
    return names


def _build_prompt_round_trend(
    rows: list[GeoMonitorSubtask],
    *,
    brand: str,
    task_run_map: dict[str, LeadDiagnosisRun],
    competitors: list[str] | None = None,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[GeoMonitorSubtask]] = {}
    for item in rows:
        run = task_run_map.get(item.task_id or "")
        if run is None:
            continue
        grouped.setdefault(run.schedule_key, []).append(item)

    tracked = _tracked_entities(brand, competitors or [])
    trend: list[dict[str, Any]] = []
    for run in sorted(task_run_map.values(), key=lambda row: row.schedule_key):
        batch = grouped.get(run.schedule_key) or []
        if not batch:
            continue
        mention_count = 0
        ranks: list[float] = []
        for item in batch:
            entries = normalize_structured_rankings(item.all_rankings_json or [])
            if _entity_mentioned(entries, brand) or item.mention_position:
                mention_count += 1
                rank = _find_entity_rank(entries, brand) or (
                    float(item.mention_position) if item.mention_position else None
                )
                if rank is not None:
                    ranks.append(rank)
        entities = {
            name: _avg_rank_for_entity_in_batch(batch, name, is_brand=names_match(name, brand))
            for name in tracked
        }
        brand_rank = entities.get(brand)
        trend.append(
            {
                "schedule_key": run.schedule_key,
                "schedule_label": run.schedule_label,
                "sample_count": len(batch),
                "mention_count": mention_count,
                "mention_rate": _round_rate(mention_count, len(batch)),
                "avg_rank": brand_rank if brand_rank is not None else (
                    round(sum(ranks) / len(ranks), 1) if ranks else None
                ),
                "entities": entities,
            }
        )
    return trend


def build_source_analysis(
    rows: list[GeoMonitorSubtask],
    *,
    brand: str,
) -> dict[str, Any]:
    domain_map: dict[str, dict[str, Any]] = {}
    brand_linked = 0
    total_refs = 0
    for item in rows:
        entries = normalize_structured_rankings(item.all_rankings_json or [])
        brand_mentioned = _entity_mentioned(entries, brand) or bool(item.mention_position)
        for source in item.reference_list_json or []:
            url = str(source.get("url") or source.get("site") or "").strip()
            if not url:
                continue
            total_refs += 1
            domain = _source_domain(url) or url
            bucket = domain_map.setdefault(
                domain,
                {"domain": domain, "count": 0, "brand_related_count": 0, "platforms": []},
            )
            bucket["count"] += 1
            if brand_mentioned:
                bucket["brand_related_count"] += 1
                brand_linked += 1
            if item.platform and item.platform not in bucket["platforms"]:
                bucket["platforms"].append(item.platform)

    domain_stats = sorted(domain_map.values(), key=lambda row: row["count"], reverse=True)[:15]
    coverage_note = (
        f"共采集 {len(rows)} 条有效回答、{total_refs} 条引用；"
        f"其中 {brand_linked} 条引用出现在品牌被提及的样本中。"
    )
    if not domain_stats:
        coverage_note = "当前样本中尚未形成可统计的引用网站分布，建议补充垂直行业内容部署。"
    return {
        "total_samples": len(rows),
        "total_references": total_refs,
        "brand_related_references": brand_linked,
        "coverage_note": coverage_note,
        "domain_stats": domain_stats,
    }


def build_rule_report_sections(
    *,
    brand: str,
    competitors: list[str],
    prompt_analytics: list[dict[str, Any]],
    source_analysis: dict[str, Any],
    kpis: dict[str, Any],
) -> dict[str, str]:
    competitor_text = "、".join(competitors) if competitors else "未配置竞品"
    visible_prompts = [row for row in prompt_analytics if row.get("brand_mention_rate", 0) > 0]
    invisible_prompts = [row for row in prompt_analytics if row.get("brand_mention_rate", 0) <= 0]

    industry = (
        f"监测覆盖 {len(prompt_analytics)} 个核心语义词，品牌为「{brand}」，竞品包括 {competitor_text}。"
        "用户意图集中在机构推荐、课程性价比与实操培训选择，AI 回答呈现头部品牌集中、长尾品牌分场景露出的特征。"
    )
    if visible_prompts:
        best = min(
            visible_prompts,
            key=lambda row: (row.get("brand_avg_rank") or 999, -row.get("brand_mention_rate", 0)),
        )
        ranking = (
            f"品牌在「{best['prompt']}」表现最好，平均排名 {best.get('brand_avg_rank') or '—'}，提及率 {best.get('brand_mention_rate')}%。"
            f"但在 {len(invisible_prompts)} 个语义词中未进入推荐列表，整体仍受头部机构挤压。"
        )
    else:
        ranking = "品牌在所有监测语义词中均未进入 AI 推荐前排，需优先补齐结构化内容与第三方引用。"

    mention = (
        f"整体品牌提及率 {kpis.get('mention_rate')}%，Top3 露出率 {kpis.get('top3_rate')}%。"
        "分语义词看，头部竞品提及率通常显著高于目标品牌，说明 AI 训练语料中的品牌关联仍不足。"
    )
    source = source_analysis.get("coverage_note") or "引用信源数据不足。"
    actions = (
        "1. 垂直行业站：围绕每个未上榜语义词发布对比评测与选购指南；"
        "2. 问答平台：用列表/表格结构回答「选哪家靠谱」「性价比推荐」类问题；"
        "3. 权威门户：输出可引用数据与案例，提高被 AI 采信概率；"
        "4. 视频内容：制作课程评测短视频，标题覆盖监测语义词。"
    )
    return {
        "industry_analysis": industry,
        "ranking_analysis": ranking,
        "mention_analysis": mention,
        "source_analysis": source,
        "action_recommendations": actions,
    }


def _subtask_region_code(
    subtask: GeoMonitorSubtask,
    *,
    task_region_map: dict[str, list[str] | None] | None,
    lead: LeadDiagnosis,
) -> str:
    codes = (task_region_map or {}).get(subtask.task_id or "")
    if codes:
        first = str(codes[0] or "").strip()
        if first:
            return first
    return str(lead.region_code or "").strip()


def _build_brand_city_rankings(
    lead: LeadDiagnosis,
    subtasks: list[GeoMonitorSubtask],
    *,
    task_region_map: dict[str, list[str] | None] | None = None,
) -> list[dict[str, Any]]:
    """按监测地区汇总品牌与竞品平均排名、提及率（对齐外部报告「品牌城市排名」）。"""
    completed = [
        item for item in subtasks
        if item.status in TERMINAL_STATUSES and item.answer_content
    ]
    if not completed:
        return []

    brand = lead.brand_name
    competitors = [str(item).strip() for item in (lead.competitors_json or []) if str(item).strip()]
    grouped: dict[str, list[GeoMonitorSubtask]] = {}
    for item in completed:
        region_code = _subtask_region_code(item, task_region_map=task_region_map, lead=lead)
        grouped.setdefault(region_code, []).append(item)

    blocks: list[dict[str, Any]] = []
    for region_code, rows in grouped.items():
        mention_table = _build_prompt_mention_table(rows, brand=brand, competitors=competitors)
        blocks.append({
            "region_code": region_code or None,
            "region_name": region_display_name(region_code),
            "sample_count": len(rows),
            "rows": mention_table,
        })
    blocks.sort(key=lambda block: (-block["sample_count"], block["region_name"]))
    return blocks


def build_lead_diagnosis_analytics(
    lead: LeadDiagnosis,
    subtasks: list[GeoMonitorSubtask],
    runs: list[LeadDiagnosisRun],
    *,
    task_region_map: dict[str, list[str] | None] | None = None,
) -> dict[str, Any]:
    completed = [item for item in subtasks if item.status in TERMINAL_STATUSES and item.answer_content]
    brand = lead.brand_name
    competitors = [str(item).strip() for item in (lead.competitors_json or []) if str(item).strip()]
    prompts = [str(item).strip() for item in (lead.prompts_json or []) if str(item).strip()]
    task_run_map = {run.task_id: run for run in (runs or []) if run.task_id}

    prompt_analytics: list[dict[str, Any]] = []
    for prompt in prompts:
        rows = [item for item in completed if item.prompt == prompt]
        mention_table = _build_prompt_mention_table(rows, brand=brand, competitors=competitors)
        brand_row = next((row for row in mention_table if row["is_brand"]), None)
        prompt_analytics.append(
            {
                "prompt": prompt,
                "sample_count": len(rows),
                "brand_mention_count": brand_row["mention_count"] if brand_row else 0,
                "brand_mention_rate": brand_row["mention_rate"] if brand_row else 0.0,
                "brand_avg_rank": brand_row["avg_rank"] if brand_row else None,
                "mention_table": mention_table,
                "ranking_list": _build_prompt_ranking_list(rows, brand=brand, competitors=competitors),
                "round_trend": _build_prompt_round_trend(
                    rows,
                    brand=brand,
                    competitors=competitors,
                    task_run_map=task_run_map,
                ),
            }
        )

    source_analysis = build_source_analysis(completed, brand=brand)
    rank_trend = _build_prompt_round_trend(
        completed,
        brand=brand,
        competitors=competitors,
        task_run_map=task_run_map,
    )
    tracked = _tracked_entities(brand, competitors)
    brand_city_rankings = _build_brand_city_rankings(
        lead,
        subtasks,
        task_region_map=task_region_map,
    )
    return {
        "prompt_analytics": prompt_analytics,
        "source_analysis": source_analysis,
        "rank_trend": rank_trend,
        "tracked_entities": tracked,
        "competitors": competitors,
        "brand_city_rankings": brand_city_rankings,
    }
