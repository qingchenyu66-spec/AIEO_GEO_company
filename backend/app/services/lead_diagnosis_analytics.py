"""售前诊断扩展分析：对齐模力指数报告的语义词排名、提及率、信源与趋势。"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from app.models.lead_diagnosis import LeadDiagnosis, LeadDiagnosisRun
from app.models.monitor import GeoMonitorSubtask
from app.core.region_catalog import region_display_name, normalize_region_codes
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


def _strict_entity_match(left: str | None, right: str | None) -> bool:
    """报告展示用：仅完整名或较长子串匹配，避免前两字误判。"""
    a = _normalize_name_key(left)
    b = _normalize_name_key(right)
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return len(shorter) >= 3 and shorter in longer


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


def _is_tracked_entity(name: str, brand: str, competitors: list[str]) -> bool:
    if names_match(name, brand):
        return True
    return any(_strict_entity_match(name, item) for item in competitors)


def canonical_ranking_name(name: str, brand: str, competitors: list[str]) -> str:
    if names_match(name, brand):
        return brand
    for comp in competitors:
        if _strict_entity_match(name, comp):
            return comp
    return str(name or "").strip()


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
            if not name or not _is_tracked_entity(name, brand, competitors):
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


def _format_collect_time(value: datetime | None) -> str:
    if not value:
        return "—"
    return value.strftime("%y-%m-%d %H:%M")


def _day_key_from_run(run: LeadDiagnosisRun) -> str:
    label = str(run.schedule_label or "").strip()
    if len(label) >= 10 and label[4:5] == "-" and label[7:8] == "-":
        return label[:10]
    key = str(run.schedule_key or "").strip()
    if len(key) >= 8 and key[:8].isdigit():
        return f"{key[:4]}-{key[4:6]}-{key[6:8]}"
    return label or key


def _format_day_label(day_key: str) -> str:
    text = str(day_key or "").strip()
    if len(text) >= 10 and text[4:5] == "-":
        return f"{text[2:4]}{text[4:]}"
    return text


def _group_rows_by_day(
    rows: list[GeoMonitorSubtask],
    task_run_map: dict[str, LeadDiagnosisRun],
) -> dict[str, list[GeoMonitorSubtask]]:
    grouped: dict[str, list[GeoMonitorSubtask]] = {}
    for item in rows:
        run = task_run_map.get(item.task_id or "")
        if run is None:
            continue
        grouped.setdefault(_day_key_from_run(run), []).append(item)
    return grouped


def _build_molizhishu_ranking_rows(
    rows: list[GeoMonitorSubtask],
    *,
    brand: str,
    competitors: list[str],
    task_run_map: dict[str, LeadDiagnosisRun],
) -> list[dict[str, Any]]:
    """最近 / 最优 / 最差 三批次排名明细，对齐模力报告 RankTable。"""
    if not rows or not task_run_map:
        return []

    by_day = _group_rows_by_day(rows, task_run_map)
    day_keys = sorted(by_day.keys())
    if not day_keys:
        return []

    day_brand_rank: dict[str, float] = {}
    for day in day_keys:
        avg = _avg_rank_for_entity_in_batch(by_day[day], brand, is_brand=True)
        if avg is not None:
            day_brand_rank[day] = avg

    latest_day = day_keys[-1]
    best_day = min(day_brand_rank, key=day_brand_rank.get) if day_brand_rank else latest_day
    worst_day = max(day_brand_rank, key=day_brand_rank.get) if day_brand_rank else latest_day

    export_plan = [
        (latest_day, "最近", False),
        (best_day, "最优", best_day != latest_day),
        (worst_day, "最差", worst_day not in {latest_day, best_day}),
    ]

    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for day, label, muted in export_plan:
        batch = by_day.get(day) or []
        aggregated: dict[tuple[str, str], list[float]] = {}
        for item in batch:
            for entry in normalize_structured_rankings(item.all_rankings_json or []):
                name = ranking_entry_name(entry)
                if not name or not _is_tracked_entity(name, brand, competitors):
                    continue
                rank = ranking_entry_explicit_rank(entry)
                if rank is None:
                    continue
                category = str(entry.get("category") or "默认分类")
                canonical = canonical_ranking_name(name, brand, competitors)
                aggregated.setdefault((canonical, category), []).append(float(rank))
        collected_at = _format_day_label(day)
        for (name, category), ranks in sorted(aggregated.items(), key=lambda row: min(row[1])):
            rank_value = round(sum(ranks) / len(ranks), 1)
            dedupe = (label, name, category, rank_value, collected_at)
            if dedupe in seen:
                continue
            seen.add(dedupe)
            flags = _entity_flags(name, brand, competitors)
            rank_display = str(int(rank_value)) if float(rank_value).is_integer() else str(rank_value)
            result.append(
                {
                    "name": name,
                    "type_label": label,
                    "type_muted": muted,
                    "category": category,
                    "rank_display": rank_display,
                    **flags,
                    "collected_at": collected_at,
                }
            )
    return result


def _build_date_prompt_matrix(prompt_analytics: list[dict[str, Any]]) -> dict[str, Any]:
    prompts = [str(row.get("prompt") or "") for row in prompt_analytics if row.get("prompt")]
    date_map: dict[str, dict[str, Any]] = {}
    for prompt, block in zip(prompts, prompt_analytics):
        for point in block.get("round_trend") or []:
            date_key = str(point.get("schedule_label") or point.get("schedule_key") or "")[:10]
            if not date_key:
                continue
            date_map.setdefault(date_key, {})[prompt] = point.get("avg_rank")
    rows = [{"label": date_key, "cells": [date_map[date_key].get(prompt) for prompt in prompts]} for date_key in sorted(date_map)]
    return {"prompts": prompts, "rows": rows}


def _build_city_prompt_matrix(
    lead: LeadDiagnosis,
    subtasks: list[GeoMonitorSubtask],
    prompts: list[str],
    *,
    brand: str,
    task_region_map: dict[str, list[str] | None] | None = None,
) -> dict[str, Any]:
    completed = [item for item in subtasks if item.status in TERMINAL_STATUSES and item.answer_content]
    grouped: dict[str, dict[str, list[GeoMonitorSubtask]]] = {}
    for item in completed:
        region = region_display_name(_subtask_region_code(item, task_region_map=task_region_map, lead=lead)) or "全部区域"
        grouped.setdefault(region, {}).setdefault(item.prompt, []).append(item)
    rows = []
    for region in sorted(grouped):
        cells = []
        for prompt in prompts:
            batch = grouped[region].get(prompt) or []
            cells.append(_avg_rank_for_entity_in_batch(batch, brand, is_brand=True) if batch else None)
        rows.append({"label": region, "cells": cells})
    return {"prompts": prompts, "rows": rows}


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
    grouped = _group_rows_by_day(rows, task_run_map)

    tracked = _tracked_entities(brand, competitors or [])
    trend: list[dict[str, Any]] = []
    for day_key in sorted(grouped.keys()):
        batch = grouped[day_key]
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
                "schedule_key": day_key,
                "schedule_label": day_key,
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
        f"整体提及率 {kpis.get('mention_rate')}%，平均排名 {kpis.get('avg_rank') or '—'}，"
        "AI 回答呈现头部品牌集中、分场景露出差异明显的特征。"
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
        "<p style=\"color:#ffcc00;font-weight:bold;\">针对不同引用网站类型的优化建议：</p>"
        "<ul>"
        "<li><strong style=\"color:#ff6666;\">垂直行业/报告类网站：</strong>"
        "发布可被 AI 引用的行业榜单、白皮书与场景选购指南。</li>"
        "<li><strong style=\"color:#ff6666;\">问答/自媒体平台：</strong>"
        "用列表/表格结构回答「哪家好」「推荐」类问题，覆盖监测语义词。</li>"
        "<li><strong style=\"color:#ff6666;\">门户/资讯站：</strong>"
        "发布品牌案例与权威数据，强化第三方背书。</li>"
        "<li><strong style=\"color:#ff6666;\">视频/内容平台：</strong>"
        "制作场景化评测短视频，标题对齐核心语义词。</li>"
        "</ul>"
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
    fallback_codes = normalize_region_codes(lead.region_codes_json or [])
    if len(fallback_codes) == 1:
        return fallback_codes[0]
    return ""


def _build_brand_city_rankings(
    lead: LeadDiagnosis,
    subtasks: list[GeoMonitorSubtask],
    *,
    competitors: list[str] | None = None,
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
    competitor_names = competitors or [
        str(item).strip() for item in (lead.competitors_json or []) if str(item).strip()
    ]
    grouped: dict[str, list[GeoMonitorSubtask]] = {}
    for item in completed:
        region_code = _subtask_region_code(item, task_region_map=task_region_map, lead=lead)
        grouped.setdefault(region_code, []).append(item)

    blocks: list[dict[str, Any]] = []
    for region_code, rows in grouped.items():
        mention_table = _build_prompt_mention_table(rows, brand=brand, competitors=competitor_names)
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
    competitors: list[str] | None = None,
    task_region_map: dict[str, list[str] | None] | None = None,
) -> dict[str, Any]:
    completed = [item for item in subtasks if item.status in TERMINAL_STATUSES and item.answer_content]
    brand = lead.brand_name
    competitors = competitors or [
        str(item).strip() for item in (lead.competitors_json or []) if str(item).strip()
    ]
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
                "molizhishu_ranking_rows": _build_molizhishu_ranking_rows(
                    rows,
                    brand=brand,
                    competitors=competitors,
                    task_run_map=task_run_map,
                ),
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
        competitors=competitors,
        task_region_map=task_region_map,
    )
    brand_date_matrix = _build_date_prompt_matrix(prompt_analytics)
    brand_city_matrix = _build_city_prompt_matrix(
        lead,
        subtasks,
        prompts,
        brand=brand,
        task_region_map=task_region_map,
    )
    return {
        "prompt_analytics": prompt_analytics,
        "source_analysis": source_analysis,
        "rank_trend": rank_trend,
        "tracked_entities": tracked,
        "competitors": competitors,
        "brand_city_rankings": brand_city_rankings,
        "brand_date_matrix": brand_date_matrix,
        "brand_city_matrix": brand_city_matrix,
    }
