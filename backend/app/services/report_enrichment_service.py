"""售前诊断报告内容 enrich：规则叙事、竞品汇总、摘录与实体归并。"""

from __future__ import annotations

import re
from typing import Any

from app.models.monitor import GeoMonitorSubtask
from app.services.monitor_service import TERMINAL_STATUSES

_EXCERPT_MAX = 220
_DOMAIN_TIPS: dict[str, str] = {
    "zhihu.com": "在知乎发布对比评测与选购指南类回答，覆盖监测语义词。",
    "baijiahao.baidu.com": "通过百家号发布行业榜单与场景化推荐文章。",
    "docin.com": "豆丁网：上传可引用的行业白皮书/研究报告 PDF。",
    "douban.com": "补充垂直社区中的品牌案例与口碑讨论。",
}


def _strict_entity_match(left: str | None, right: str | None) -> bool:
    a = re.sub(r"\s+", "", str(left or "").strip().lower())
    b = re.sub(r"\s+", "", str(right or "").strip().lower())
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return len(shorter) >= 3 and shorter in longer


def _names_match(left: str | None, right: str | None) -> bool:
    a = re.sub(r"\s+", "", str(left or "").strip().lower())
    b = re.sub(r"\s+", "", str(right or "").strip().lower())
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    if len(a) >= 2 and len(b) >= 2 and (a[:2] in b or b[:2] in a):
        return True
    return False


def canonical_ranking_name(name: str, brand: str, competitors: list[str]) -> str:
    if _names_match(name, brand):
        return brand
    for comp in competitors:
        if _strict_entity_match(name, comp):
            return comp
    return str(name or "").strip()


def build_competitor_landscape(
    prompt_analytics: list[dict[str, Any]],
    *,
    brand: str,
    competitors: list[str],
) -> list[dict[str, Any]]:
    tracked = [brand, *competitors]
    stats: dict[str, dict[str, Any]] = {
        name: {"name": name, "mention_total": 0, "sample_total": 0, "ranks": [], "is_brand": _names_match(name, brand)}
        for name in tracked
    }
    for block in prompt_analytics:
        sample_count = int(block.get("sample_count") or 0)
        for row in block.get("mention_table") or []:
            row_name = str(row.get("name") or "")
            target = None
            for name in tracked:
                if _names_match(row_name, name) or _strict_entity_match(row_name, name):
                    target = name
                    break
            if target is None:
                continue
            bucket = stats[target]
            bucket["mention_total"] += int(row.get("mention_count") or 0)
            bucket["sample_total"] += sample_count
            avg_rank = row.get("avg_rank")
            if avg_rank is not None:
                bucket["ranks"].append(float(avg_rank))
    rows = []
    for name in tracked:
        bucket = stats[name]
        sample_total = bucket["sample_total"] or 1
        ranks = bucket["ranks"]
        rows.append(
            {
                "name": name,
                "is_brand": bucket["is_brand"],
                "mention_rate": round(bucket["mention_total"] / sample_total * 100, 1),
                "avg_rank": round(sum(ranks) / len(ranks), 1) if ranks else None,
            }
        )
    rows.sort(key=lambda row: (-row["mention_rate"], row["avg_rank"] or 999))
    return rows


def build_prompt_platform_matrix(
    matrix_rows: list[dict[str, Any]],
    *,
    prompts: list[str],
    platform_names: dict[str, str],
) -> dict[str, Any]:
    platforms: list[str] = []
    for row in matrix_rows:
        code = str(row.get("platform") or "")
        if code and code not in platforms:
            platforms.append(code)
    cell_map: dict[tuple[str, str], dict[str, Any]] = {}
    for row in matrix_rows:
        prompt = str(row.get("prompt") or "")
        platform = str(row.get("platform") or "")
        if prompt and platform:
            cell_map[(prompt, platform)] = row
    matrix = []
    for prompt in prompts:
        cells = []
        for platform in platforms:
            cell = cell_map.get((prompt, platform)) or {}
            cells.append(
                {
                    "mention_rate": cell.get("mention_rate"),
                    "avg_rank": cell.get("avg_rank"),
                }
            )
        matrix.append({"prompt": prompt, "cells": cells})
    return {
        "prompts": prompts,
        "platforms": [platform_names.get(code) or code for code in platforms],
        "platform_codes": platforms,
        "rows": matrix,
    }


def build_rule_prompt_comments(
    prompt_analytics: list[dict[str, Any]],
    *,
    brand: str,
    competitors: list[str],
    matrix_rows: list[dict[str, Any]],
) -> list[dict[str, str]]:
    comments: list[dict[str, str]] = []
    for block in prompt_analytics:
        prompt = str(block.get("prompt") or "")
        rate = float(block.get("brand_mention_rate") or 0)
        rank = block.get("brand_avg_rank")
        rank_text = f"{float(rank):.1f}" if rank is not None else "—"
        prompt_matrix = [row for row in matrix_rows if row.get("prompt") == prompt]
        best_platform = None
        worst_platform = None
        if prompt_matrix:
            mentioned = [row for row in prompt_matrix if float(row.get("mention_rate") or 0) > 0]
            if mentioned:
                best_platform = max(mentioned, key=lambda row: float(row.get("mention_rate") or 0))
                worst_platform = min(mentioned, key=lambda row: float(row.get("mention_rate") or 0))
        top_competitor = None
        for row in block.get("mention_table") or []:
            if row.get("is_brand") or row.get("is_competitor"):
                if not row.get("is_brand"):
                    top_competitor = row
                    break
        parts = [f"「{prompt}」提及率 {rate:.1f}%，平均排名 {rank_text}"]
        if rate <= 0:
            parts.append("品牌尚未进入 AI 推荐列表，需优先补齐该场景内容")
        elif rank is not None and float(rank) <= 3:
            parts.append("排名靠前，建议维持更新频率巩固优势")
        else:
            parts.append("排名仍有提升空间，建议对标头部竞品优化表述")
        if top_competitor:
            parts.append(
                f"竞品「{top_competitor.get('name')}」提及率 {float(top_competitor.get('mention_rate') or 0):.1f}%"
            )
        if best_platform and worst_platform and best_platform.get("platform") != worst_platform.get("platform"):
            parts.append(
                f"平台差异：{best_platform.get('platform')} 提及率较高，"
                f"{worst_platform.get('platform')} 偏低"
            )
        comments.append({"prompt": prompt, "comment": "；".join(parts) + "。"})
    return comments


def build_rule_platform_insight(
    platform_stats: list[dict[str, Any]],
    platform_names: dict[str, str],
) -> str:
    if not platform_stats:
        return "暂无分平台样本，无法解读平台差异。"
    sorted_rows = sorted(platform_stats, key=lambda row: float(row.get("mention_rate") or 0), reverse=True)
    top = sorted_rows[0]
    bottom = sorted_rows[-1]
    top_name = platform_names.get(str(top.get("platform") or "")) or top.get("platform")
    bottom_name = platform_names.get(str(bottom.get("platform") or "")) or bottom.get("platform")
    spread = float(top.get("mention_rate") or 0) - float(bottom.get("mention_rate") or 0)
    return (
        f"分平台提及率差距 {spread:.1f} 个百分点：{top_name} 最高（{float(top.get('mention_rate') or 0):.1f}%），"
        f"{bottom_name} 最低（{float(bottom.get('mention_rate') or 0):.1f}%）。"
        "建议在低提及平台补充结构化榜单内容与权威引用，缩小平台间曝光差异。"
    )


def build_rule_source_tips(
    source_analysis: dict[str, Any],
    top_sources: list[dict[str, Any]],
) -> list[str]:
    tips: list[str] = []
    for row in (source_analysis.get("domain_stats") or [])[:5]:
        domain = str(row.get("domain") or "").lower().removeprefix("www.")
        for key, tip in _DOMAIN_TIPS.items():
            if key in domain and tip not in tips:
                tips.append(tip)
        if len(tips) >= 4:
            break
    if not tips and top_sources:
        tips.append("高频信源以资讯与聚合站为主，建议发布可被 AI 引用的榜单、报告与问答内容。")
    if source_analysis.get("brand_related_references", 0) == 0:
        tips.append("品牌相关引用偏少，优先在垂直行业站建立可验证的品牌资料页。")
    return tips[:5]


def pick_answer_excerpts(
    subtasks: list[GeoMonitorSubtask],
    *,
    brand: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    completed = [
        item for item in subtasks
        if item.status in TERMINAL_STATUSES and item.answer_content and item.mention_position
    ]
    completed.sort(key=lambda row: (row.mention_position or 999, -(len(row.answer_content or ""))))
    excerpts: list[dict[str, Any]] = []
    seen_prompts: set[str] = set()
    for item in completed:
        prompt = str(item.prompt or "")
        if prompt in seen_prompts:
            continue
        text = re.sub(r"\s+", " ", str(item.answer_content or "")).strip()
        if not text:
            continue
        snippet = text[:_EXCERPT_MAX] + ("…" if len(text) > _EXCERPT_MAX else "")
        excerpts.append(
            {
                "prompt": prompt,
                "platform": item.platform,
                "rank": item.mention_position,
                "excerpt": snippet,
            }
        )
        seen_prompts.add(prompt)
        if len(excerpts) >= limit:
            break
    return excerpts


def merge_prompt_commentaries(
    rule_comments: list[dict[str, str]],
    ai_comments: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    ai_map = {
        str(row.get("prompt") or ""): str(row.get("comment") or "").strip()
        for row in (ai_comments or [])
        if str(row.get("prompt") or "").strip() and str(row.get("comment") or "").strip()
    }
    merged: list[dict[str, str]] = []
    for row in rule_comments:
        prompt = row["prompt"]
        merged.append({"prompt": prompt, "comment": ai_map.get(prompt) or row["comment"]})
    return merged


def merge_priority_actions(
    rule_actions: list[dict[str, Any]],
    ai_actions: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """优先采用 DeepSeek 生成的行动清单，空则回退规则引擎。"""
    if not ai_actions:
        return rule_actions
    normalized: list[dict[str, Any]] = []
    for item in ai_actions:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        priority = str(item.get("priority") or "P2").upper()
        if priority not in {"P0", "P1", "P2"}:
            priority = "P2"
        normalized.append(
            {
                "priority": priority,
                "title": title,
                "timeline": str(item.get("timeline") or "90天").strip(),
            }
        )
    return normalized[:5] if normalized else rule_actions


def build_priority_actions(
    prompt_analytics: list[dict[str, Any]],
    platform_stats: list[dict[str, Any]],
    *,
    platform_names: dict[str, str],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if prompt_analytics:
        worst = min(
            prompt_analytics,
            key=lambda row: (float(row.get("brand_mention_rate") or 0), float(row.get("brand_avg_rank") or 999)),
        )
        prompt = str(worst.get("prompt") or "")
        if prompt and float(worst.get("brand_mention_rate") or 0) < 30:
            actions.append(
                {
                    "priority": "P0",
                    "title": f"补齐语义词「{prompt[:24]}」的内容与引用布局",
                    "timeline": "30天",
                }
            )
    if platform_stats:
        low = sorted(platform_stats, key=lambda row: float(row.get("mention_rate") or 0))[:2]
        for row in low:
            if float(row.get("mention_rate") or 0) < 20:
                code = str(row.get("platform") or "")
                name = platform_names.get(code) or code
                actions.append(
                    {
                        "priority": "P1",
                        "title": f"提升 {name} 平台品牌内容覆盖",
                        "timeline": "60天",
                    }
                )
    actions.append(
        {
            "priority": "P2",
            "title": "在垂直行业站/问答平台发布榜单与案例，增加可引用信源",
            "timeline": "90天",
        }
    )
    return actions[:5]


def build_report_enrichment(
    *,
    brand: str,
    competitors: list[str],
    prompt_analytics: list[dict[str, Any]],
    matrix_rows: list[dict[str, Any]],
    platform_stats: list[dict[str, Any]],
    platform_names: dict[str, str],
    source_analysis: dict[str, Any],
    top_sources: list[dict[str, Any]],
    subtasks: list[GeoMonitorSubtask],
    sentiment_counts: dict[str, int],
    positive_rate: float,
) -> dict[str, Any]:
    prompts = [str(row.get("prompt") or "") for row in prompt_analytics if row.get("prompt")]
    return {
        "competitor_landscape": build_competitor_landscape(
            prompt_analytics, brand=brand, competitors=competitors
        ),
        "prompt_platform_matrix": build_prompt_platform_matrix(
            matrix_rows, prompts=prompts, platform_names=platform_names
        ),
        "prompt_commentaries": build_rule_prompt_comments(
            prompt_analytics,
            brand=brand,
            competitors=competitors,
            matrix_rows=matrix_rows,
        ),
        "platform_insight": build_rule_platform_insight(platform_stats, platform_names),
        "source_action_tips": build_rule_source_tips(source_analysis, top_sources),
        "answer_excerpts": pick_answer_excerpts(subtasks, brand=brand),
        "sentiment_counts": sentiment_counts,
        "positive_rate": positive_rate,
        "priority_actions": build_priority_actions(
            prompt_analytics,
            platform_stats,
            platform_names=platform_names,
        ),
    }
