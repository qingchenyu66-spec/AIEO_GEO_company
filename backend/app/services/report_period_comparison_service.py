"""周期报告环比 HTML：桌面样例生成 + 正式导出共用渲染与数据组装。"""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.models.tenant import Tenant
from app.services.brand_service import (
    keyword_group_monitor_keywords,
    list_competitors,
    list_keyword_groups,
)
from app.services.competitor_analytics_service import aggregate_competitor_period_stats
from app.services.monitor_service import (
    TERMINAL_STATUSES,
    _matrix_group_monitor_label,
    _resolve_prompt_monitor_keyword,
)
from app.services.report_period_content_service import build_report_modules
from app.services.report_period_service import PERIOD_COMPARISON_REPORT_TYPES, period_bounds, period_label
from app.services.report_competitor_visuals import (
    build_competitor_analysis,
    classify_rank_risk,
    entity_visual_style,
)

TREND_META = {
    "weekly": {"title": "日趋势", "bucket": "day", "unit": "天"},
    "monthly": {"title": "周趋势", "bucket": "week", "unit": "周"},
    "quarterly": {"title": "月趋势", "bucket": "month", "unit": "月"},
    "annual": {"title": "季趋势", "bucket": "quarter", "unit": "季"},
}

OUT_DIR = Path.home() / "Desktop" / "周期报告样例_环比预览"
ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"
# 门户预览中间态：同源静态包；最终预览/导出/PDF 会再内联 bundle，避免 blob/Playwright 外链失败
ECHARTS_PORTAL_SRC = "/report-assets/echarts.min.js"
ECHARTS_STATIC_DIR = Path(__file__).resolve().parents[1] / "static" / "report_period"
_ECHARTS_SCRIPT_SRC_RE = re.compile(
    r'<script\b[^>]*\bsrc=["\'][^"\']*echarts[^"\']*["\'][^>]*>\s*</script>',
    re.IGNORECASE,
)
REPORT_TYPES = ("weekly", "monthly", "quarterly", "annual")
PERIOD_EXPORT_TYPES = PERIOD_COMPARISON_REPORT_TYPES
TYPE_LABELS = {
    "weekly": "GEO 监测周报",
    "monthly": "GEO 监测月报",
    "quarterly": "GEO 监测季报",
    "annual": "GEO 监测年报",
}
_RANK_TREND_TYPES = frozenset({"monthly", "quarterly", "annual"})
PLATFORM_LABELS = {
    "doubao": "豆包",
    "doubao_mobile": "豆包移动版",
    "deepseek": "DeepSeek",
    "deepseek_mobile": "DeepSeek移动端",
    "yuanbao": "元宝",
    "qianwen": "通义千问",
    "kimi": "Kimi",
    "quark": "夸克",
    "baiduai": "百度AI+",
    "weibo_zhisou": "微博智搜",
}

# 上一周期演示 KPI（库内无上期样本时 fallback，保证样例可预览环比 UI）
_DEMO_PREVIOUS_PROFILE: dict[str, dict[str, float]] = {
    "weekly": {"mention_rate": 55.2, "avg_rank": 3.1, "top3_rate": 40.5, "completed_count": 38, "health_score": 72},
    "monthly": {"mention_rate": 54.8, "avg_rank": 3.0, "top3_rate": 39.0, "completed_count": 152, "health_score": 73},
    "quarterly": {"mention_rate": 52.5, "avg_rank": 3.2, "top3_rate": 37.5, "completed_count": 420, "health_score": 71},
}
_DEMO_PREVIOUS_PLATFORMS: dict[str, dict[str, float]] = {
    "doubao": {"mention_rate": 58.0, "avg_rank": 2.5},
    "kimi": {"mention_rate": 52.0, "avg_rank": 2.9},
    "deepseek": {"mention_rate": 50.5, "avg_rank": 3.4},
    "yuanbao": {"mention_rate": 48.0, "avg_rank": 3.2},
    "qianwen": {"mention_rate": 46.5, "avg_rank": 3.5},
    "deepseek_mobile": {"mention_rate": 44.0, "avg_rank": 3.8},
}
_DEFAULT_DEMO_PLATFORMS = ["doubao", "kimi", "deepseek", "yuanbao", "qianwen", "deepseek_mobile"]
_ENRICH_NOTE = "本样例已对稀疏监测数据做演示增强，便于预览趋势、环比与监控词×平台表格效果。"
_DEMO_TREND_SERIES: dict[str, dict[str, list[float]]] = {
    "weekly": {
        "mention_rate": [51.2, 52.8, 54.1, 53.5, 55.9, 57.4, 58.6],
        "avg_rank": [3.5, 3.4, 3.3, 3.2, 3.1, 3.0, 2.9],
        "completed": [18, 22, 24, 23, 26, 28, 27],
    },
    "monthly": {
        "mention_rate": [52.0, 54.5, 55.8, 56.2, 58.1],
        "avg_rank": [3.4, 3.2, 3.1, 3.0, 2.8],
        "completed": [96, 112, 118, 124, 132],
    },
    "quarterly": {
        "mention_rate": [52.5, 55.8, 58.6],
        "avg_rank": [3.3, 3.0, 2.8],
        "completed": [560, 612, 644],
    },
}
_DEMO_SOURCES = [
    {"title": "知乎 - 行业选购与品牌推荐", "count": 28},
    {"title": "官方网站 - 品牌介绍与服务案例", "count": 22},
    {"title": "垂直行业媒体 - 深度评测", "count": 18},
    {"title": "百家号 - 场景化种草内容", "count": 15},
    {"title": "搜狐号 - 行业趋势解读", "count": 12},
    {"title": "今日头条 - 品牌对比问答", "count": 10},
    {"title": "微信搜一搜 - 官方公众号文章", "count": 9},
    {"title": "B站 - 场景测评短视频", "count": 7},
]


def _stable_unit(key: str) -> float:
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def _resolve_platform_codes(snapshot: dict[str, Any]) -> list[str]:
    codes = [str(item.get("platform") or "") for item in snapshot.get("platform_stats") or [] if item.get("platform")]
    if codes:
        return codes[:8]
    return list(_DEFAULT_DEMO_PLATFORMS)


def _period_totals(report_type: str) -> tuple[int, int]:
    """(本期样本总量, 上期样本总量)。"""
    mapping = {"weekly": (168, 154), "monthly": (672, 638), "quarterly": (2016, 1890)}
    return mapping.get(report_type, (168, 154))


def enrich_snapshot(snapshot: dict[str, Any], *, report_type: str, platform_codes: list[str]) -> dict[str, Any]:
    enriched = dict(snapshot)
    kpis = dict(enriched.get("kpis") or {})
    cur_total, _prev_total = _period_totals(report_type)
    prev_demo = _DEMO_PREVIOUS_PROFILE[report_type]

    platform_stats: list[dict[str, Any]] = []
    mention_sum = 0.0
    rank_weight = 0.0
    rank_count = 0
    per_platform = max(8, cur_total // max(len(platform_codes), 1))
    for index, code in enumerate(platform_codes):
        unit = _stable_unit(f"{report_type}:{code}")
        mention = round(48 + unit * 28 - index * 1.2, 1)
        avg_rank = round(2.2 + (index * 0.35) + (1 - unit) * 1.1, 1)
        top3 = round(mention * 0.72, 1)
        platform_stats.append(
            {
                "platform": code,
                "total": per_platform,
                "completed": per_platform,
                "mention_rate": mention,
                "avg_rank": avg_rank,
            }
        )
        mention_sum += mention
        rank_weight += avg_rank
        rank_count += 1

    avg_mention = round(mention_sum / max(rank_count, 1), 1)
    avg_rank = round(rank_weight / max(rank_count, 1), 1)
    kpis.update(
        {
            "mention_rate": avg_mention,
            "avg_rank": avg_rank,
            "top3_rate": round(avg_mention * 0.74, 1),
            "positive_rate": 68.5,
            "completed_count": cur_total,
            "subtask_count": cur_total,
            "source_count": len(_DEMO_SOURCES),
            "health_score": _health_score({"mention_rate": avg_mention, "top3_rate": kpis.get("top3_rate"), "avg_rank": avg_rank}),
        }
    )
    enriched["kpis"] = kpis
    enriched["platform_stats"] = platform_stats
    enriched["platform_count"] = len(platform_stats)
    enriched["sentiment_counts"] = {"正面": int(cur_total * 0.68), "中性": int(cur_total * 0.22), "负面": int(cur_total * 0.10)}
    enriched["top_sources"] = [
        {**item, "url": f"https://example.com/source/{index + 1}", "platforms": platform_codes[:3]}
        for index, item in enumerate(_DEMO_SOURCES)
    ]
    enriched["highlights"] = [
        f"统计周期内共完成 {cur_total} 条监测子任务，品牌提及率 {avg_mention}%，平均推荐排名 {avg_rank}。",
        "豆包、Kimi 为核心优势渠道，DeepSeek 移动端仍有提升空间。",
        "监控词「电梯广告公司推荐」表现领先，部分场景词仍需加强内容布局。",
    ]
    enriched["demo_enriched"] = True
    return enriched


def enrich_previous_snapshot(snapshot: dict[str, Any], *, report_type: str, platform_codes: list[str]) -> dict[str, Any]:
    enriched = dict(snapshot)
    kpis = dict(enriched.get("kpis") or {})
    _cur_total, prev_total = _period_totals(report_type)
    prev_demo = _DEMO_PREVIOUS_PROFILE[report_type]
    per_platform = max(8, prev_total // max(len(platform_codes), 1))
    platform_stats: list[dict[str, Any]] = []
    for index, code in enumerate(platform_codes):
        base = _DEMO_PREVIOUS_PLATFORMS.get(code, {"mention_rate": 50.0, "avg_rank": 3.2})
        mention = round(float(base["mention_rate"]) - index * 0.8, 1)
        avg_rank = round(float(base["avg_rank"]) + index * 0.12, 1)
        platform_stats.append(
            {
                "platform": code,
                "total": per_platform,
                "completed": per_platform,
                "mention_rate": mention,
                "avg_rank": avg_rank,
            }
        )
    kpis.update(
        {
            "mention_rate": prev_demo["mention_rate"],
            "avg_rank": prev_demo["avg_rank"],
            "top3_rate": prev_demo["top3_rate"],
            "completed_count": prev_total,
            "health_score": int(prev_demo["health_score"]),
        }
    )
    enriched["kpis"] = kpis
    enriched["platform_stats"] = platform_stats
    enriched["demo_enriched"] = True
    return enriched


def enrich_trend(trend: dict[str, Any], *, report_type: str) -> dict[str, Any]:
    series = _DEMO_TREND_SERIES[report_type]
    points: list[dict[str, Any]] = []
    for index, slot in enumerate(trend.get("points") or []):
        mention = series["mention_rate"][index % len(series["mention_rate"])]
        avg_rank = series["avg_rank"][index % len(series["avg_rank"])]
        completed = series["completed"][index % len(series["completed"])]
        points.append({**slot, "mention_rate": mention, "avg_rank": avg_rank, "completed": completed, "top3_rate": round(mention * 0.72, 1)})
    if len(points) >= 2:
        summary = (
            f"{trend.get('title') or '趋势'}显示品牌提及率由 {points[0]['mention_rate']}% "
            f"升至 {points[-1]['mention_rate']}%，平均排名由 {points[0]['avg_rank']} "
            f"优化至 {points[-1]['avg_rank']}。"
        )
    return {**trend, "points": points, "summary": summary}


def _demo_keyword_metrics(keyword: str, platform_codes: list[str], *, report_type: str, keyword_index: int) -> dict[str, Any]:
    per_kw_total = {"weekly": 28, "monthly": 112, "quarterly": 336}[report_type]
    per_platform = max(4, per_kw_total // max(len(platform_codes), 1))
    breakdown: list[dict[str, Any]] = []
    mention_values: list[float] = []
    rank_values: list[float] = []
    for p_index, code in enumerate(platform_codes):
        unit = _stable_unit(f"{report_type}:{keyword}:{code}")
        mention = round(30 + unit * 48 - keyword_index * 2.5 - p_index * 1.8, 1)
        avg_rank = round(2.0 + p_index * 0.32 + (1 - unit) * 2.2 + keyword_index * 0.08, 1)
        breakdown.append(
            {
                "platform": code,
                "name": PLATFORM_LABELS.get(code, code),
                "completed": per_platform,
                "mention_rate": mention,
                "avg_rank": avg_rank,
                "top3_rate": round(mention * 0.7, 1),
            }
        )
        mention_values.append(mention)
        rank_values.append(avg_rank)

    cur_mention = round(sum(mention_values) / len(mention_values), 1)
    cur_rank = round(sum(rank_values) / len(rank_values), 1)
    prev_mention = round(cur_mention - 2.5 - keyword_index * 0.6, 1)
    prev_rank = round(cur_rank + 0.3 + keyword_index * 0.15, 1)
    status, status_class = _keyword_status(cur_mention, cur_rank)
    return {
        "keyword": keyword,
        "completed": per_kw_total,
        "mention_rate": _metric_delta(cur_mention, prev_mention),
        "avg_rank": _metric_delta(cur_rank, prev_rank, lower_is_better=True),
        "top3_rate": round(cur_mention * 0.72, 1),
        "status": status,
        "status_class": status_class,
        "weakest_platforms": _pick_weakest_platform_names(breakdown),
        "platform_breakdown": breakdown,
    }


def build_matrix_from_breakdown(
    weak_keywords: list[str],
    row_map: dict[str, dict[str, Any]],
    platform_codes: list[str],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for keyword in weak_keywords:
        breakdown = row_map.get(keyword, {}).get("platform_breakdown") or []
        stat_map = {str(item["platform"]): item for item in breakdown}
        row_stats = list(breakdown)
        cells: list[dict[str, Any]] = []
        for code in platform_codes:
            stat = stat_map.get(code)
            text, _, sparse = _format_platform_cell(stat)
            is_weak = _cell_is_weak(stat, row_stats) if stat else False
            cells.append({"text": text, "is_weak": is_weak, "sparse": sparse})
        rows.append({"keyword": keyword, "cells": cells})
    return {
        "platforms": [PLATFORM_LABELS.get(code, code) for code in platform_codes],
        "rows": rows,
    }


def enrich_keyword_analytics(
    analytics: dict[str, Any],
    *,
    keywords: list[str],
    platform_codes: list[str],
    report_type: str,
) -> dict[str, Any]:
    if not keywords:
        keywords = ["监控词A", "监控词B", "监控词C", "监控词D", "监控词E", "监控词F"]
    rows = [
        _demo_keyword_metrics(keyword, platform_codes, report_type=report_type, keyword_index=index)
        for index, keyword in enumerate(keywords)
    ]
    row_map = {str(row["keyword"]): row for row in rows}
    weak_top3 = sorted(
        rows,
        key=lambda row: (
            float(row["mention_rate"]["current"] or 0),
            -(float(row["avg_rank"]["current"]) if row["avg_rank"]["current"] is not None else -99),
        ),
    )[:3]
    highlights: list[str] = []
    for row in weak_top3:
        kw = row["keyword"]
        mr = row["mention_rate"]["current"]
        rk = row["avg_rank"]["current"]
        rd = row["avg_rank"]
        platform_hint = ""
        if row.get("weakest_platforms"):
            platform_hint = f"主要短板平台：{'、'.join(row['weakest_platforms'])}。"
        if rd["direction"] == "declined" and rd["delta"] is not None:
            highlights.append(
                f"监控词「{kw}」排名 {rk}，较上期 {rd['previous']} 回落 {abs(rd['delta'])} 位，优先补内容。{platform_hint}"
            )
        elif (mr or 0) <= 0:
            highlights.append(f"监控词「{kw}」本期未进入 AI 推荐列表，建议补充结构化问答与权威引用。{platform_hint}")
        else:
            highlights.append(f"监控词「{kw}」提及率 {mr}%、排名 {rk}，表现偏弱，建议针对性优化。{platform_hint}")
    weak_matrix = build_matrix_from_breakdown(
        [str(item["keyword"]) for item in weak_top3],
        row_map,
        platform_codes,
    )
    return {
        **analytics,
        "rows": rows,
        "weak_top3": weak_top3,
        "highlights": highlights,
        "weak_platform_matrix": weak_matrix,
        "demo_enriched": True,
    }


def _trend_axis_labels(points: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Chart uses short single-line labels; table/tooltip keep full range text."""
    short: list[str] = []
    full: list[str] = []
    for point in points:
        label = str(point.get("label") or "")
        sub = str(point.get("sub") or "").strip()
        if sub:
            short.append(label)
            full.append(f"{label} ({sub})")
        else:
            short.append(label)
            full.append(label)
    return short, full


def _finalize_competitor_analytics(
    *,
    brand_name: str,
    competitor_names: list[str],
    report_type: str,
    trend: dict[str, Any],
    rows: list[dict[str, Any]],
    rank_trend: dict[str, Any] | None = None,
    demo_enriched: bool = False,
) -> dict[str, Any]:
    if not rows:
        return {"rows": [], "highlights": [], "rank_trend": None, "analysis": build_competitor_analysis(brand_name=brand_name, rows=[])}

    brand_row = next((row for row in rows if row["is_brand"]), rows[0])
    brand_mr = float(brand_row["mention_rate"]["current"] or 0)
    brand_rank = brand_row["avg_rank"]["current"]
    for row in rows:
        cur_mr = float(row["mention_rate"]["current"] or 0)
        row["gap_mention_text"] = "—" if row["is_brand"] else f"{cur_mr - brand_mr:+.1f}pp"
        if row["is_brand"]:
            row["gap_rank_text"] = "—"
        elif brand_rank is not None and row["avg_rank"]["current"] is not None:
            row["gap_rank_text"] = f"{float(row['avg_rank']['current']) - float(brand_rank):+.1f} 位"
        else:
            row["gap_rank_text"] = "—"

    rows.sort(key=lambda row: (-float(row["mention_rate"]["current"] or 0), float(row["avg_rank"]["current"] or 99)))

    marker_symbols = {
        "o": "circle",
        "s": "rect",
        "^": "triangle",
        "D": "diamond",
        "v": "triangle",
        "p": "pin",
    }
    for row in rows:
        visual = entity_visual_style(row["name"], brand_name=brand_name)
        css_dash = visual.css_dash
        line_type: str | list[int]
        if css_dash == "none":
            line_type = "solid"
        else:
            line_type = [int(part) for part in css_dash.split()]
        risk = classify_rank_risk(row["avg_rank"]["current"])
        row["style"] = {
            "color": visual.color,
            "line_type": line_type,
            "symbol": marker_symbols.get(visual.marker, "circle"),
        }
        row["risk"] = {"level": risk.level, "label": risk.label, "color": risk.color}

    above = [row for row in rows if not row["is_brand"] and float(row["mention_rate"]["current"] or 0) > brand_mr]
    below = [row for row in rows if not row["is_brand"] and float(row["mention_rate"]["current"] or 0) <= brand_mr]
    highlights: list[str] = []
    if above:
        top = above[0]
        highlights.append(
            f"本品牌提及率 {brand_mr}%，低于 {top['name']}（{top['mention_rate']['current']}%），"
            f"提及率差距 {abs(float(top['mention_rate']['current']) - brand_mr):.1f} 个百分点。"
        )
    if below:
        highlights.append(
            f"本品牌提及率领先 {below[0]['name']}（{below[0]['mention_rate']['current']}%）"
            f"等 {len(below)} 家竞品，但排名仍需持续优化。"
        )
    if not highlights:
        highlights.append(
            f"本周期纳入 {len(competitor_names)} 家配置竞品对比，建议持续跟踪头部竞品提及率变化。"
        )

    if rank_trend is None and report_type in _RANK_TREND_TYPES and demo_enriched:
        points = trend.get("points") or []
        short_cats, full_cats = _trend_axis_labels(points)
        series: list[dict[str, Any]] = []
        for row in rows[:4]:
            base = float(row["avg_rank"]["current"] or 3.0)
            values = []
            for idx in range(len(short_cats)):
                wobble = (_stable_unit(f"comp-trend:{row['name']}:{idx}") - 0.5) * 0.5
                drift = -idx * 0.04 if row["is_brand"] else idx * 0.02
                values.append(round(max(1.2, base + wobble + drift), 1))
            series.append(
                {
                    "name": row["name"],
                    "is_brand": row["is_brand"],
                    "data": values,
                    "style": row["style"],
                }
            )
        rank_trend = {"categories": short_cats, "fullCategories": full_cats, "series": series}

    analysis = build_competitor_analysis(
        brand_name=brand_name,
        rows=[
            {
                "name": row["name"],
                "is_brand": row["is_brand"],
                "mention_rate": row["mention_rate"]["current"],
                "avg_rank": row["avg_rank"]["current"],
            }
            for row in rows
        ],
    )
    return {
        "rows": rows,
        "highlights": highlights,
        "rank_trend": rank_trend,
        "analysis": analysis,
        "demo_enriched": demo_enriched,
    }


def build_competitor_analytics_from_periods(
    db: Session,
    *,
    tenant_id: int,
    brand_name: str,
    competitor_names: list[str],
    report_type: str,
    trend: dict[str, Any],
    cur_start: date,
    cur_end: date,
    prev_start: date,
    prev_end: date,
) -> dict[str, Any]:
    current = aggregate_competitor_period_stats(db, tenant_id, start_date=cur_start, end_date=cur_end)
    previous = aggregate_competitor_period_stats(db, tenant_id, start_date=prev_start, end_date=prev_end)
    prev_by_name = {str(row["name"]): row for row in previous.get("rows") or []}
    rows: list[dict[str, Any]] = []
    for row in current.get("rows") or []:
        name = str(row.get("name") or "")
        prev_row = prev_by_name.get(name, {})
        rows.append(
            {
                "name": name,
                "is_brand": bool(row.get("is_brand")),
                "mention_rate": _metric_delta(row.get("mention_rate"), prev_row.get("mention_rate")),
                "avg_rank": _metric_delta(row.get("avg_rank"), prev_row.get("avg_rank"), lower_is_better=True),
            }
        )

    result = _finalize_competitor_analytics(
        brand_name=brand_name,
        competitor_names=competitor_names,
        report_type=report_type,
        trend=trend,
        rows=rows,
        demo_enriched=False,
    )
    if report_type in _RANK_TREND_TYPES and not result.get("rank_trend"):
        points = trend.get("points") or []
        if len(points) >= 2:
            short_cats, full_cats = _trend_axis_labels(points)
            brand_series_row = next((row for row in result["rows"] if row["is_brand"]), None)
            if brand_series_row:
                values = [
                    round(float(point["avg_rank"]), 1) if point.get("avg_rank") is not None else None
                    for point in points
                ]
                if any(value is not None for value in values):
                    result["rank_trend"] = {
                        "categories": short_cats,
                        "fullCategories": full_cats,
                        "series": [
                            {
                                "name": brand_series_row["name"],
                                "is_brand": True,
                                "data": values,
                                "style": brand_series_row.get("style") or {},
                            }
                        ],
                    }
    return result


def enrich_competitor_analytics(
    *,
    brand_name: str,
    competitor_names: list[str],
    report_type: str,
    trend: dict[str, Any],
    brand_mention_rate: float | None = None,
) -> dict[str, Any]:
    names = [str(item).strip() for item in competitor_names if str(item).strip()]
    if not names:
        names = ["竞品A", "竞品B", "竞品C", "竞品D", "竞品E"]
    tracked = [brand_name, *names[:5]]

    rows: list[dict[str, Any]] = []
    for index, name in enumerate(tracked):
        is_brand = index == 0
        unit = _stable_unit(f"comp:{report_type}:{name}")
        if is_brand and brand_mention_rate is not None:
            cur_mr = float(brand_mention_rate)
        else:
            cur_mr = round((58 if is_brand else 50) - index * 3.5 + unit * 12, 1)
        prev_mr = round(cur_mr - (1.8 if is_brand else 2.5) + (index % 2), 1)
        cur_rank = round((2.7 if is_brand else 3.0) + index * 0.32 + (1 - unit) * 0.8, 1)
        prev_rank = round(cur_rank + (0.15 if is_brand else 0.35), 1)
        rows.append(
            {
                "name": name,
                "is_brand": is_brand,
                "mention_rate": _metric_delta(cur_mr, prev_mr),
                "avg_rank": _metric_delta(cur_rank, prev_rank, lower_is_better=True),
            }
        )

    return _finalize_competitor_analytics(
        brand_name=brand_name,
        competitor_names=names,
        report_type=report_type,
        trend=trend,
        rows=rows,
        demo_enriched=True,
    )


def render_competitor_html(competitor: dict[str, Any], *, report_type: str, client: bool = False) -> str:
    esc = html.escape
    rows = competitor.get("rows") or []
    if not rows:
        return ""

    body = ""
    for row in rows:
        mr = row["mention_rate"]
        ar = row["avg_rank"]
        style = row.get("style") or {}
        risk = row.get("risk") or {}
        swatch = f'<span class="comp-swatch" style="background:{esc(str(style.get("color") or "#94a3b8"))};"></span>'
        name_text = f"<strong>{esc(row['name'])} ★</strong>" if row.get("is_brand") else esc(str(row["name"]))
        name_cell = swatch + name_text
        risk_badge = (
            f'<span class="comp-risk comp-risk-{esc(str(risk.get("level") or "neutral"))}">'
            f'{esc(str(risk.get("label") or "数据不足"))}</span>'
        )
        body += f"""
        <tr class="{'comp-brand-row' if row.get('is_brand') else ''}">
          <td>{name_cell}</td>
          <td>{esc(_fmt_pct(mr['current']))}</td>
          <td>{esc(_fmt_pct(mr['previous']))}</td>
          <td><span class="delta {_delta_class(mr['direction'])}">{esc(mr['text'])}</span></td>
          <td>{esc(_fmt_rank(ar['current']))} {risk_badge}</td>
          <td>{esc(_fmt_rank(ar['previous']))}</td>
          <td><span class="delta {_delta_class(ar['direction'])}">{esc(ar['text'])}</span></td>
          <td>{esc(str(row.get('gap_mention_text') or '—'))}</td>
          <td>{esc(str(row.get('gap_rank_text') or '—'))}</td>
        </tr>"""

    highlight_items = "".join(f"<li>{esc(line)}</li>" for line in competitor.get("highlights") or [])
    insight_html = f'<ul class="comp-insights">{highlight_items}</ul>' if highlight_items else ""
    analysis = competitor.get("analysis") or {}
    action_items = "".join(f"<li>{esc(str(item))}</li>" for item in analysis.get("actions") or [])
    strategy_html = f"""
      <div class="comp-strategy-grid">
        <div class="comp-strategy-card"><h3>竞争格局摘要</h3><p>{esc(str(analysis.get('management_summary') or '暂无可核验竞品结论'))}</p></div>
        <div class="comp-strategy-card comp-action-card"><h3>运营建议动作</h3><ol>{action_items}</ol></div>
      </div>
      <p class="comp-risk-legend"><strong>排名风险说明：</strong>前三名绿色达标；第4-5名黄色关注；第6-7名橙色警告；第8名以后红色高风险。</p>
    """

    trend_block = ""
    rank_trend = competitor.get("rank_trend")
    if rank_trend and report_type in _RANK_TREND_TYPES:
        trend_json = _embed_json(rank_trend)
        trend_block = f"""
        <div class="comp-trend-box">
          <h3>品牌 vs TOP3 竞品 · 平均排名趋势</h3>
          <div id="competitorRankTrendChart" class="echart-canvas echart-canvas-wide"></div>
        </div>
        <script>
        (function () {{
          const payload = {trend_json};
          const el = document.getElementById('competitorRankTrendChart');
          if (!el || !window.echarts) return;
          const chart = echarts.init(el);
          const xRotate = (payload.categories || []).length > 3 ? -34 : 0;
          const fullCats = payload.fullCategories || payload.categories || [];
          chart.setOption({{
            tooltip: {{
              trigger: 'axis',
              formatter: (items) => {{
                const p = items[0];
                const idx = p.dataIndex;
                const title = fullCats[idx] || p.axisValue;
                const lines = items.map(it => `${{it.marker}}${{it.seriesName}}：${{it.data}}`).join('<br/>');
                return `${{title}}<br/>${{lines}}`;
              }},
            }},
            legend: {{ top: 4, data: payload.series.map(s => s.name) }},
            grid: {{ left: 58, right: 36, top: 48, bottom: xRotate ? 92 : 56, containLabel: true }},
            xAxis: {{
              type: 'category',
              data: payload.categories,
              axisLabel: {{ interval: 0, rotate: xRotate, color: '#64748b', fontSize: 11, margin: 14 }},
            }},
            yAxis: {{
              type: 'value',
              name: '平均排名',
              nameLocation: 'end',
              nameGap: 8,
              inverse: true,
              min: 1,
              splitLine: {{ lineStyle: {{ type: 'dashed', color: '#e2e8f0' }} }},
              axisLabel: {{
                formatter: (v) => {{
                  const n = Number(v);
                  if (!Number.isFinite(n) || n <= 0 || n > 50) return '';
                  return String(Math.round(n * 10) / 10);
                }},
              }},
            }},
            series: payload.series.map((s, i) => ({{
              name: s.name,
              type: 'line',
              smooth: true,
              symbol: s.style.symbol,
              symbolSize: s.is_brand ? 9 : 7,
              lineStyle: {{ width: s.is_brand ? 3.5 : 2.2, type: s.style.line_type, color: s.style.color }},
              itemStyle: {{ color: s.style.color }},
              data: s.data,
            }})),
          }});
          window.addEventListener('resize', () => chart.resize());
        }})();
        </script>"""

    scope = {
        "weekly": "主要竞品",
        "monthly": "全部纳入竞品",
        "quarterly": "全部纳入竞品",
        "annual": "全部纳入竞品",
    }[report_type]
    if client:
        comp_note = (
            f"基于 AI 推荐结果中的品牌排名统计，对比周期内纳入监测的竞品品牌（{scope}）。"
            "★ 为本品牌；差距列为相对本品牌的提及率/排名差。"
        )
        comp_heading = "竞品对比分析 · 环比上一周期"
    else:
        comp_note = (
            f"基于监测样本中 AI 推荐排名结构化解析，仅统计资料库配置的竞品（{scope}）。"
            "★ 为本品牌；差距列为相对本品牌的提及率/排名差。"
        )
        comp_heading = "竞品格局 · 环比上一周期"
    return f"""
      <section class="competitor-section" id="competitors">
        <h2>{comp_heading}</h2>
        <p class="note">{esc(comp_note)}</p>
        {insight_html}
        {strategy_html}
        <table>
          <thead>
            <tr>
              <th>品牌/竞品</th>
              <th>提及率</th><th>上期</th><th>变化</th>
              <th>平均排名</th><th>上期</th><th>变化</th>
              <th>提及率差距</th><th>排名差距</th>
            </tr>
          </thead>
          <tbody>{body}</tbody>
        </table>
        {trend_block}
      </section>"""


_SENTIMENT_TOPIC_MARKERS = (
    "舆情",
    "负面舆情",
    "负面占比",
    "负面痛点",
    "情绪",
    "负向",
    "口碑优化",
    "舆情整改",
    "正向对冲",
    "负面清理",
)
_FALLBACK_PROBLEMS = (
    "信源结构偏集中：有效引用集中在少数渠道，跨平台佐证与背书链条仍待完善",
    "高权重渠道更新不足：知乎、行业媒体等决策参考渠道内容频次偏低，影响 AI 引用稳定性",
)
_PLAN_VISION_TITLE = {
    "weekly": "下一周品牌传播工作设想",
    "monthly": "下一月品牌传播工作设想",
    "quarterly": "下一季度品牌传播工作设想",
    "annual": "下一年度品牌传播工作设想",
}
_CLIENT_PLAN_TITLE = {
    "weekly": "下一周工作规划建议",
    "monthly": "下一月工作规划建议",
    "quarterly": "下一季度工作规划建议",
    "annual": "下一年度工作规划建议",
}
_CLIENT_PLAN_NOTE = "以下为下阶段工作方向与推进建议，不作为服务效果承诺。"
# ponytail: sample-only copy — effort/vision tone, no KPI guarantees
_VISION_ACTION_PLAN: dict[str, dict[str, list[str]]] = {
    "weekly": {
        "goals": [
            "持续巩固本周监测中表现较好的优势渠道",
            "稳步提升品牌在 AI 问答场景下的可见度与推荐表现",
            "针对短板平台推进一轮结构化内容补充与更新",
            "持续跟踪监控词表现，优先优化明显偏弱项",
        ],
        "actions": [
            "渠道分层：优势平台保持问答更新节奏，短板平台补充结构化内容",
            "高权重渠道：推进权威科普与选购指南类内容产出",
            "素材规范：梳理服务、价格等对外口径，便于各渠道统一引用",
            "监测复盘：结合周度数据回顾，动态调整下周内容与投放侧重",
        ],
    },
    "monthly": {
        "goals": [
            "朝着更高的品牌健康度持续优化内容与渠道布局",
            "努力提升品牌提及率，逐步缩小与行业标杆的差距",
            "推动各主流平台推荐表现整体向好、排位更靠前",
            "聚焦监控词短板，逐项推进内容与信源补强",
        ],
        "actions": [
            "渠道分层运营：资源向优势平台倾斜，同时补齐短板平台内容",
            "知乎长效运营：尝试建立行业指南类内容的月度更新机制",
            "素材储备：持续产出价格、服务相关的标准化宣传内容",
            "监测复盘：结合月报数据回顾，动态调整内容策略与投放侧重",
        ],
    },
    "quarterly": {
        "goals": [
            "围绕季度复盘结论，持续优化全域品牌传播布局",
            "努力提升品牌提及率与推荐排位，向行业领先水平靠拢",
            "推动各平台表现更均衡，缩小渠道之间的明显差距",
            "拓展高权重信源合作，丰富品牌权威背书来源",
        ],
        "actions": [
            "渠道专项：优势平台加大优质内容投入，短板平台推进专项内容补强",
            "信源建设：探索与垂直媒体合作深度评测、案例类内容",
            "高权重渠道：在知乎等决策参考渠道保持常态化内容更新",
            "季度复盘：对照监测数据回顾本季工作，拟定下季内容与投放侧重",
        ],
    },
    "annual": {
        "goals": [
            "基于年度监测复盘，持续优化全域品牌传播与内容布局",
            "稳步提升品牌提及率与推荐排位，缩小与行业标杆差距",
            "推动各平台表现更均衡，降低渠道间波动",
            "拓展高权重信源合作，沉淀可复用的权威背书资产",
        ],
        "actions": [
            "渠道专项：优势平台加大优质内容投入，短板平台推进专项补强",
            "信源建设：与垂直媒体探索年度深度评测与案例共创",
            "高权重渠道：在知乎等决策参考渠道保持常态化更新",
            "年度复盘：对照全年监测数据，拟定下一年内容与投放侧重",
        ],
    },
}


def apply_vision_action_plan(plan: dict[str, Any], *, report_type: str) -> dict[str, Any]:
    vision = _VISION_ACTION_PLAN.get(report_type, _VISION_ACTION_PLAN["monthly"])
    updated = dict(plan)
    updated["goals"] = list(vision["goals"])
    updated["actions"] = list(vision["actions"])
    if report_type in _PLAN_VISION_TITLE:
        updated["title"] = _PLAN_VISION_TITLE[report_type]
    return updated


def ensure_echarts_asset(out_dir: Path | None = None) -> str:
    """ponytail: download once for offline/PDF export; falls back to CDN if download fails."""
    assets = (out_dir or ECHARTS_STATIC_DIR) / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    target = assets / "echarts.min.js"
    if not target.exists() or target.stat().st_size < 1000:
        try:
            import urllib.request

            urllib.request.urlretrieve(ECHARTS_CDN, target)
        except Exception:
            return ECHARTS_CDN
    if out_dir is not None:
        return "assets/echarts.min.js"
    return target.resolve().as_uri()


def load_echarts_bundle_text() -> str:
    """读取本地 echarts 全文；缺失则尝试下载，再退化拉 CDN。"""
    local = ECHARTS_STATIC_DIR / "assets" / "echarts.min.js"
    ensure_echarts_asset()
    if local.exists() and local.stat().st_size > 1000:
        return local.read_text(encoding="utf-8")
    import urllib.request

    with urllib.request.urlopen(ECHARTS_CDN, timeout=60) as resp:
        text = resp.read().decode("utf-8")
    if len(text) < 1000 or "echarts" not in text.lower():
        raise RuntimeError("无法加载 echarts 资源")
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(text, encoding="utf-8")
    return text


def inline_echarts_scripts(html_text: str) -> str:
    """把 echarts 外链 script 换成内联，供 blob 预览与 Playwright set_content。"""
    if not _ECHARTS_SCRIPT_SRC_RE.search(html_text):
        return html_text
    code = load_echarts_bundle_text()
    safe = code.replace("</script", "<\\/script")
    # 必须用 callable 替换：echarts 源码含 \d 等，string repl 会被 re 当模板转义炸掉
    return _ECHARTS_SCRIPT_SRC_RE.sub(lambda _m: f"<script>{safe}</script>", html_text, count=1)


def build_v2_conclusions(
    comparison: dict[str, Any],
    keyword_analytics: dict[str, Any],
    competitor_analytics: dict[str, Any],
) -> list[str]:
    lines: list[str] = []
    comp_highlights = list(comparison.get("highlights") or [])
    if comp_highlights:
        kpi_line = next((item for item in comp_highlights if "提及率" in str(item)), comp_highlights[0])
        lines.append(str(kpi_line))
    kw_highlights = list(keyword_analytics.get("highlights") or [])
    if kw_highlights:
        lines.append(str(kw_highlights[0]))
    competitor_highlights = list(competitor_analytics.get("highlights") or [])
    if competitor_highlights:
        lines.append(str(competitor_highlights[0]))
    elif len(comp_highlights) > 1:
        lines.append(str(comp_highlights[1]))
    return lines[:3]


def polish_preface_for_client_v2(preface: dict[str, Any], *, brand_name: str) -> dict[str, Any]:
    updated = dict(preface)
    updated["monitor_tool"] = "GEO Monitor 品牌监测平台"
    lead = str(updated.get("sample_description") or "")
    for old, new in (
        ("监测子任务", "有效监测样本"),
        ("语义矩阵建模、", ""),
        ("多信源交叉校验机制，", "多源校验，"),
    ):
        lead = lead.replace(old, new)
    if "环比" not in lead:
        lead = lead.rstrip("。") + "；含与上一周期对比数据。"
    updated["sample_description"] = lead
    purpose = str(updated.get("purpose") or "")
    updated["purpose"] = (
        purpose.replace("市场口碑诊断、", "")
        .replace("市场口碑诊断", "品牌传播分析")
        .replace("营销内容布局决策参考", "内容布局决策参考")
    )
    updated["comparison_note"] = ""
    updated["trend_note"] = ""
    return updated


def polish_disclaimer_for_client_v2(
    disclaimer: dict[str, Any],
    *,
    brand_name: str,
    period_range: str,
    completed: int,
    platform_count: int,
) -> dict[str, Any]:
    _ = disclaimer
    count = platform_count or 7
    return {
        "notes": [
            f"本报告数据周期为 {period_range}，基于 {completed} 条有效监测样本，经系统化采集与多源校验生成",
            f"数据覆盖 {count} 大 AI 问答平台及知乎、垂直行业媒体、企业官网等渠道，不含短视频、线下等其他传播渠道",
            f"本报告由 GEO Monitor 基于监测数据生成，供 {brand_name} 品牌传播决策参考；未经授权，请勿向第三方传播",
            "指标释义：品牌提及率 = 监测记录中出现品牌名称的占比；平均排名 = AI 推荐列表平均位次；引用次数 = 外部渠道引用品牌相关内容频次",
            "排名数字越小表示推荐位置越靠前；箭头颜色表示相对上一周期的改善或回落",
        ],
    }


def polish_content_modules_for_client_v2(
    modules: dict[str, Any],
    *,
    brand_name: str,
    report_type: str,
    period_range: str,
    completed: int,
    platform_count: int,
) -> dict[str, Any]:
    polished = dict(modules)
    polished["disclaimer"] = polish_disclaimer_for_client_v2(
        polished.get("disclaimer") or {},
        brand_name=brand_name,
        period_range=period_range,
        completed=completed,
        platform_count=platform_count,
    )
    action_plan = polished.get("action_plan")
    if action_plan:
        plan = dict(action_plan)
        plan["title"] = _CLIENT_PLAN_TITLE.get(report_type, plan.get("title"))
        polished["action_plan"] = plan
    polished["toc"] = build_period_sample_toc(polished, v2=True, report_type=report_type, client=True)
    return polished


def _has_sentiment_topic(text: str) -> bool:
    blob = str(text or "")
    return any(marker in blob for marker in _SENTIMENT_TOPIC_MARKERS)


def _sanitize_module_text(text: str) -> str:
    cleaned = str(text or "")
    replacements = (
        ("若负面舆情集中于此，应作为整改与正向对冲的核心阵地。", "建议作为高权重内容持续运营与案例补强的核心阵地。"),
        ("负面清理&对冲：", "高权重内容补强："),
        ("针对服务响应、价格透明度痛点，", "针对用户决策关注的响应与报价透明问题，"),
        ("也可能是负面舆情高发渠道，机遇与风险并存。", "是提升跨平台一致露出与权威背书的关键渠道。"),
        ("既是品牌正向背书来源，", "是品牌正向背书与行业参考的重要来源，"),
        ("舆情与体验：", "体验与内容："),
        ("难以对冲负面舆论", "难以形成稳定的高权重内容矩阵"),
        ("知乎高权重渠道专项整改", "知乎高权重渠道专项运营"),
    )
    for old, new in replacements:
        cleaned = cleaned.replace(old, new)
    return cleaned


def build_period_sample_toc(
    modules: dict[str, Any],
    *,
    v2: bool = False,
    report_type: str = "monthly",
    client: bool = False,
) -> list[dict[str, str]]:
    plan = modules.get("action_plan") or {}
    plan_title = str(plan.get("title") or "下一周期品牌传播工作设想")
    kw_title = "核心监测词表现" if client else "监控词成绩单"
    comp_title = "竞品对比分析" if client else "竞品格局 · 环比对比"
    strategy_title = "分维度优化建议" if client else "风险诊断与分维度优化策略"
    weekly_focus_title = "本周关注与下周规划" if client else "本周关注与下周设想"
    toc: list[dict[str, str]] = [
        {"anchor": "preface", "title": "报告前言（监测范围与口径说明）"},
        {"anchor": "kpi", "title": "核心指标 · 环比上一周期"},
    ]
    if v2:
        toc.append({"anchor": "conclusions", "title": "核心结论"})
    toc.extend(
        [
            {"anchor": "trend", "title": "趋势分析"},
            {"anchor": "keywords", "title": kw_title},
            {"anchor": "competitors", "title": comp_title},
            {"anchor": "platform", "title": "分平台排名与提及率对比"},
        ]
    )
    if v2 and report_type == "weekly":
        toc.append({"anchor": "weekly-focus", "title": weekly_focus_title})
    else:
        toc.extend(
            [
                {"anchor": "sources", "title": "核心信源传播影响力分析"},
                {"anchor": "strategy", "title": strategy_title},
                {"anchor": "action-plan", "title": plan_title},
            ]
        )
    toc.append({"anchor": "disclaimer", "title": "报告备注说明"})
    return toc


def strip_sentiment_from_modules(modules: dict[str, Any], *, report_type: str) -> dict[str, Any]:
    cleaned = dict(modules)
    cleaned.pop("sentiment", None)

    preface = dict(cleaned.get("preface") or {})
    preface["core_dimensions"] = [
        item
        for item in (preface.get("core_dimensions") or [])
        if not _has_sentiment_topic(str(item))
    ]
    cleaned["preface"] = preface

    source_influence = dict(cleaned.get("source_influence") or {})
    rows: list[dict[str, Any]] = []
    for row in source_influence.get("rows") or []:
        item = dict(row)
        item["value_analysis"] = _sanitize_module_text(str(item.get("value_analysis") or ""))
        rows.append(item)
    source_influence["rows"] = rows
    conclusion = _sanitize_module_text(str(source_influence.get("conclusion") or ""))
    if _has_sentiment_topic(conclusion):
        top_title = rows[0]["title"] if rows else "高权重渠道"
        conclusion = (
            f"「{top_title}」为代表的高权重引用渠道，专业影响力突出，"
            "是品牌权威背书与跨平台一致露出的关键来源；建议保持内容更新与案例补强。"
        )
    source_influence["conclusion"] = conclusion
    cleaned["source_influence"] = source_influence

    risk = dict(cleaned.get("risk_and_strategy") or {})
    problems = [
        _sanitize_module_text(str(item))
        for item in (risk.get("problems") or [])
        if not _has_sentiment_topic(str(item))
    ]
    for fallback in _FALLBACK_PROBLEMS:
        if len(problems) >= 4:
            break
        if fallback not in problems:
            problems.append(fallback)
    risk["problems"] = problems[:4]

    dimensions: list[dict[str, Any]] = []
    for dim in risk.get("dimensions") or []:
        title = _sanitize_module_text(str(dim.get("title") or ""))
        if _has_sentiment_topic(title):
            continue
        actions = [
            _sanitize_module_text(str(item))
            for item in (dim.get("actions") or [])
            if not _has_sentiment_topic(str(item))
        ]
        if actions:
            dimensions.append({"title": title, "actions": actions})
    risk["dimensions"] = dimensions
    cleaned["risk_and_strategy"] = risk

    action_plan = cleaned.get("action_plan")
    if action_plan:
        cleaned["action_plan"] = apply_vision_action_plan(dict(action_plan), report_type=report_type)

    return cleaned


def build_sample_content_modules(
    *,
    brand_name: str,
    snapshot: dict[str, Any],
    report_type: str,
    period_lbl: str,
    period_start: date,
    period_end: date,
    competitor_names: list[str],
    v2: bool = False,
) -> dict[str, Any]:
    kpis = dict(snapshot.get("kpis") or {})
    if "health_score" not in kpis:
        kpis["health_score"] = _health_score(kpis)
    raw = build_report_modules(
        brand_name=brand_name,
        company_name=snapshot.get("company_name"),
        report_type=report_type,
        period_label=period_lbl,
        period_start=period_start,
        period_end=period_end,
        kpis=kpis,
        platform_stats=snapshot.get("platform_stats") or [],
        sentiment_counts=snapshot.get("sentiment_counts") or {},
        top_sources=snapshot.get("top_sources") or [],
        competitor_names=competitor_names,
        highlights=snapshot.get("highlights"),
    )
    cleaned = strip_sentiment_from_modules(raw, report_type=report_type)
    cleaned["toc"] = build_period_sample_toc(cleaned, v2=v2, report_type=report_type)
    return cleaned


def enrich_preface_from_modules(
    modules: dict[str, Any],
    *,
    report_type: str,
    previous_period_label: str,
    monitor_keywords: list[str] | None = None,
) -> dict[str, Any]:
    preface = dict(modules.get("preface") or {})
    preface["comparison_note"] = (
        f"本报告在常规监测指标基础上，增加与上一周期（{previous_period_label}）的"
        "平均推荐排名、品牌提及率及分平台表现环比对比，便于周/月/季复盘。"
    )
    trend_note = {
        "weekly": "趋势模块按自然日展示本周每日提及率与平均排名变化。",
        "monthly": "趋势模块按自然周展示本月每周提及率与平均排名变化。",
        "quarterly": "趋势模块按自然月展示本季度每月提及率与平均排名变化。",
        "annual": "趋势模块按自然季展示本年度每季提及率与平均排名变化。",
    }
    preface["trend_note"] = trend_note.get(report_type, "")
    keywords = [str(item).strip() for item in (monitor_keywords or []) if str(item).strip()]
    preface["monitor_keywords"] = format_monitor_keywords_text(keywords)
    preface["monitor_keyword_count"] = len(keywords)
    return preface


def render_toc_html(toc: list[dict[str, str]]) -> str:
    esc = html.escape
    items = "".join(
        f'<li><a href="#{esc(str(row.get("anchor") or ""))}">'
        f'<span>{esc(str(row.get("title") or ""))}</span></a></li>'
        for row in toc
    )
    return f"""
      <section class="toc-section" id="toc">
        <h2>报告目录</h2>
        <nav><ul class="toc-list">{items}</ul></nav>
      </section>"""


def render_source_influence_html(source_influence: dict[str, Any]) -> str:
    esc = html.escape
    rows = list(source_influence.get("rows") or [])[:8]
    if not rows:
        return ""

    body = ""
    chart_labels: list[str] = []
    chart_values: list[int] = []
    for row in rows:
        title = str(row.get("title") or "—")
        count = int(row.get("count") or 0)
        body += f"""
        <tr>
          <td>{int(row.get('index') or 0)}</td>
          <td>{esc(title)}</td>
          <td>{count}次</td>
          <td class="val-cell">{esc(str(row.get('value_analysis') or '—'))}</td>
        </tr>"""
        chart_labels.append(title)
        chart_values.append(count)

    chart_payload = _embed_json({"labels": chart_labels, "values": chart_values})
    conclusion = esc(str(source_influence.get("conclusion") or ""))
    return f"""
      <section class="source-section" id="sources">
        <h2>核心信源传播影响力分析</h2>
        <div class="source-grid">
          <div class="card-box source-table-box">
            <table>
              <thead>
                <tr><th>#</th><th>信源渠道</th><th>引用</th><th>渠道价值拆解</th></tr>
              </thead>
              <tbody>{body}</tbody>
            </table>
          </div>
          <div class="card-box">
            <h3>TOP 信源引用次数</h3>
            <div id="sourceBarChart" class="echart-canvas"></div>
            <p class="source-conclusion"><strong>核心判断：</strong>{conclusion}</p>
          </div>
        </div>
        <script>
        (function () {{
          const payload = {chart_payload};
          const el = document.getElementById('sourceBarChart');
          if (!el || !window.echarts) return;
          const chart = echarts.init(el);
          chart.setOption({{
            color: ['#1677ff'],
            tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'shadow' }} }},
            grid: {{ left: 120, right: 24, top: 12, bottom: 24 }},
            xAxis: {{ type: 'value', splitLine: {{ lineStyle: {{ type: 'dashed', color: '#e2e8f0' }} }} }},
            yAxis: {{
              type: 'category',
              data: [...payload.labels].reverse(),
              axisLabel: {{ width: 110, overflow: 'truncate', fontSize: 11, color: '#64748b' }},
            }},
            series: [{{
              type: 'bar',
              barMaxWidth: 18,
              label: {{ show: true, position: 'right', formatter: '{{c}}次' }},
              data: [...payload.values].reverse(),
            }}],
          }});
          window.addEventListener('resize', () => chart.resize());
        }})();
        </script>
      </section>"""


def render_risk_strategy_html(risk_and_strategy: dict[str, Any], *, client: bool = False) -> str:
    esc = html.escape
    problems = risk_and_strategy.get("problems") or []
    dimensions = risk_and_strategy.get("dimensions") or []
    if not problems and not dimensions:
        return ""

    problem_items = "".join(f"<li>{esc(str(item))}</li>" for item in problems)
    dim_cards = ""
    for dim in dimensions:
        actions = "".join(f"<li>{esc(str(item))}</li>" for item in (dim.get("actions") or []))
        dim_cards += f"""
        <div class="card-box">
          <h4>{esc(str(dim.get('title') or ''))}</h4>
          <ul>{actions}</ul>
        </div>"""
    heading = "分维度优化建议" if client else "风险诊断与分维度落地优化策略"
    problems_heading = "当前主要待改进方向" if client else "当前核心现存问题"
    return f"""
      <section class="strategy-section" id="strategy">
        <h2>{heading}</h2>
        <div class="card-box strategy-problems">
          <h3>{problems_heading}</h3>
          <ul>{problem_items}</ul>
        </div>
        <div class="strategy-grid">{dim_cards}</div>
      </section>"""


def render_action_plan_html(action_plan: dict[str, Any] | None, *, client: bool = False) -> str:
    if not action_plan or not action_plan.get("title"):
        return ""
    esc = html.escape
    goals = "".join(f"<li>{esc(str(item))}</li>" for item in (action_plan.get("goals") or []))
    actions = "".join(f"<li>{esc(str(item))}</li>" for item in (action_plan.get("actions") or []))
    period_label = esc(str(action_plan.get("period_label") or "下一周期"))
    plan_note = _CLIENT_PLAN_NOTE if client else "以下为工作设想与努力方向，供内部复盘参考，不构成效果或结果承诺。"
    goals_heading = "努力方向" if client else "愿景与努力方向"
    return f"""
      <section class="plan-section" id="action-plan">
        <h2>{esc(str(action_plan.get('title') or '下一周期品牌传播工作设想'))}</h2>
        <p class="note plan-note">{esc(plan_note)}</p>
        <div class="plan-grid">
          <div class="card-box">
            <h3>{goals_heading}（{period_label}）</h3>
            <ul>{goals}</ul>
          </div>
          <div class="card-box">
            <h3>重点推进事项</h3>
            <ul>{actions}</ul>
          </div>
        </div>
      </section>"""


def render_weekly_focus_html(content_modules: dict[str, Any], *, client: bool = False) -> str:
    esc = html.escape
    risk = content_modules.get("risk_and_strategy") or {}
    plan = content_modules.get("action_plan") or {}
    sources = list((content_modules.get("source_influence") or {}).get("rows") or [])[:3]
    problems = list(risk.get("problems") or [])[:3]
    problem_items = "".join(f"<li>{esc(str(item))}</li>" for item in problems)
    source_items = "".join(
        f"<li>{esc(str(row.get('title') or '—'))} · {int(row.get('count') or 0)}次</li>" for row in sources
    )
    focus_items = "".join(f"<li>{esc(str(item))}</li>" for item in (plan.get("goals") or [])[:2])
    focus_items += "".join(f"<li>{esc(str(item))}</li>" for item in (plan.get("actions") or [])[:2])
    heading = "本周关注与下周规划" if client else "本周关注与下周设想"
    plan_note = _CLIENT_PLAN_NOTE if client else "以下为工作关注与推进方向，供内部复盘参考，不构成效果或结果承诺。"
    next_heading = "下周规划建议" if client else "下周工作设想"
    return f"""
      <section class="weekly-focus-section" id="weekly-focus">
        <h2>{heading}</h2>
        <p class="note plan-note">{esc(plan_note)}</p>
        <div class="plan-grid">
          <div class="card-box">
            <h3>本周关注要点</h3>
            <ul>{problem_items or '<li>暂无</li>'}</ul>
            <h3 style="margin-top:14px">高频引用信源 TOP3</h3>
            <ul>{source_items or '<li>暂无</li>'}</ul>
          </div>
          <div class="card-box">
            <h3>{next_heading}</h3>
            <ul>{focus_items or '<li>暂无</li>'}</ul>
          </div>
        </div>
      </section>"""


def render_disclaimer_html(disclaimer: dict[str, Any]) -> str:
    esc = html.escape
    notes = disclaimer.get("notes") or []
    if not notes:
        return ""
    items = "".join(f"<li>{esc(str(item))}</li>" for item in notes)
    return f"""
      <section class="disclaimer-section" id="disclaimer">
        <h2>报告备注说明</h2>
        <ol>{items}</ol>
      </section>"""


def previous_period_bounds(report_type: str, start: date, end: date) -> tuple[date, date]:
    prev_end = start - timedelta(days=1)
    if report_type == "weekly":
        return prev_end - timedelta(days=6), prev_end
    if report_type == "monthly":
        return prev_end.replace(day=1), prev_end
    if report_type == "quarterly":
        quarter = (prev_end.month - 1) // 3
        start_month = quarter * 3 + 1
        prev_start = date(prev_end.year, start_month, 1)
        last_month = start_month + 2
        last_day = (date(prev_end.year, last_month + 1, 1) - timedelta(days=1)).day if last_month < 12 else 31
        if last_month == 12:
            prev_end = date(prev_end.year, 12, 31)
        else:
            prev_end = date(prev_end.year, last_month, last_day)
        return prev_start, prev_end
    if report_type == "annual":
        prev_year = prev_end.year
        return date(prev_year, 1, 1), date(prev_year, 12, 31)
    raise ValueError(report_type)


def schedule_trigger_for_sample(report_type: str, today: date) -> date:
    """模拟定时任务触发日：周报=最近周一，月/季=本月1号（若今天非1号则用上月/上季末后第一个1号逻辑）。"""
    if report_type == "weekly":
        return today - timedelta(days=today.weekday())
    if report_type == "monthly":
        return today.replace(day=1)
    if report_type == "quarterly":
        q_month = ((today.month - 1) // 3) * 3 + 1
        return date(today.year, q_month, 1)
    if report_type == "annual":
        return date(today.year, 1, 1)
    raise ValueError(report_type)


def _health_score(kpis: dict[str, Any]) -> int:
    mention = float(kpis.get("mention_rate") or 0)
    top3 = float(kpis.get("top3_rate") or 0)
    avg_rank = kpis.get("avg_rank")
    rank_score = max(0, min(100, 100 - ((float(avg_rank) if avg_rank is not None else 10) - 1) * 10))
    return round(mention * 0.45 + top3 * 0.25 + rank_score * 0.20 + min(mention, 100) * 0.10)


def _resolve_tenant_id(db, tenant_id: int | None, tenant_code: str | None) -> tuple[int, str]:
    if tenant_id is not None:
        row = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
        if row is None:
            raise ValueError(f"tenant_id={tenant_id} 不存在")
        return row.id, row.name
    if tenant_code:
        row = db.scalar(select(Tenant).where(Tenant.code == tenant_code, Tenant.deleted.is_(False)))
        if row:
            return row.id, row.name
    row = db.scalar(
        select(Tenant.id, Tenant.name)
        .join(GeoMonitorTask, GeoMonitorTask.tenant_id == Tenant.id)
        .where(Tenant.deleted.is_(False), GeoMonitorTask.deleted.is_(False))
        .group_by(Tenant.id, Tenant.name)
        .order_by(desc(func.max(GeoMonitorSubtask.updated_at)))
        .limit(1)
    )
    if row:
        return row[0], row[1]
    fallback = db.scalar(select(Tenant).where(Tenant.deleted.is_(False)).order_by(Tenant.id).limit(1))
    if fallback is None:
        raise RuntimeError("数据库无可用企业")
    return fallback.id, fallback.name


def _metric_delta(current: float | None, previous: float | None, *, lower_is_better: bool = False) -> dict[str, Any]:
    if current is None or previous is None:
        return {"current": current, "previous": previous, "delta": None, "direction": "na", "text": "—"}
    delta = round(current - previous, 1)
    if lower_is_better:
        if delta < 0:
            direction = "improved"
            text = f"↑{abs(delta):g} 位"
        elif delta > 0:
            direction = "declined"
            text = f"↓{abs(delta):g} 位"
        else:
            direction = "unchanged"
            text = "持平"
    else:
        if delta > 0:
            direction = "improved"
            text = f"+{delta:g}"
        elif delta < 0:
            direction = "declined"
            text = f"{delta:g}"
        else:
            direction = "unchanged"
            text = "持平"
    return {"current": current, "previous": previous, "delta": delta, "direction": direction, "text": text}


def build_comparison(
    report_type: str,
    current: dict[str, Any],
    previous: dict[str, Any] | None,
    prev_label: str,
    *,
    used_demo_previous: bool,
    allow_demo_fallback: bool = True,
) -> dict[str, Any]:
    ck = current.get("kpis") or {}
    pk = (previous or {}).get("kpis") or {}
    if int(pk.get("completed_count") or 0) <= 0:
        if allow_demo_fallback:
            demo = _DEMO_PREVIOUS_PROFILE[report_type]
            pk = {**demo, "source_count": ck.get("source_count")}
            used_demo_previous = True
        else:
            pk = {}
            used_demo_previous = False

    cur_health = _health_score(ck)
    prev_health = int(pk.get("health_score") or _health_score(pk))

    cur_platforms = {str(r["platform"]): r for r in current.get("platform_stats") or []}
    prev_platforms = {str(r["platform"]): r for r in (previous or {}).get("platform_stats") or []}
    platform_rows = []
    for code, row in cur_platforms.items():
        prev_row = prev_platforms.get(code) or {}
        if not prev_row and used_demo_previous and allow_demo_fallback and code in _DEMO_PREVIOUS_PLATFORMS:
            prev_row = _DEMO_PREVIOUS_PLATFORMS[code]
        platform_rows.append(
            {
                "platform": code,
                "name": PLATFORM_LABELS.get(code, code),
                "mention_rate": _metric_delta(row.get("mention_rate"), prev_row.get("mention_rate")),
                "avg_rank": _metric_delta(row.get("avg_rank"), prev_row.get("avg_rank"), lower_is_better=True),
                "completed": int(row.get("completed") or 0),
            }
        )
    platform_rows.sort(key=lambda r: float(r["mention_rate"]["current"] or 0), reverse=True)

    sample_warn = ""
    cur_n = int(ck.get("completed_count") or 0)
    prev_n = int(pk.get("completed_count") or 0)
    if prev_n and cur_n and abs(cur_n - prev_n) / max(prev_n, 1) > 0.3:
        sample_warn = "两期样本量差异较大，环比仅供参考。"

    return {
        "available": True,
        "previous_period_label": prev_label,
        "used_demo_previous": used_demo_previous,
        "sample_warn": sample_warn,
        "kpis": {
            "health_score": _metric_delta(cur_health, prev_health),
            "mention_rate": _metric_delta(ck.get("mention_rate"), pk.get("mention_rate")),
            "avg_rank": _metric_delta(ck.get("avg_rank"), pk.get("avg_rank"), lower_is_better=True),
            "top3_rate": _metric_delta(ck.get("top3_rate"), pk.get("top3_rate")),
            "completed_count": _metric_delta(float(cur_n), float(prev_n)),
        },
        "platform_rows": platform_rows,
        "highlights": _comparison_highlights(report_type, ck, pk, cur_health, prev_health),
    }


def _comparison_highlights(
    report_type: str,
    ck: dict[str, Any],
    pk: dict[str, Any],
    cur_health: int,
    prev_health: int,
) -> list[str]:
    scope, prev_scope = {
        "weekly": ("本周", "上周"),
        "monthly": ("本月", "上月"),
        "quarterly": ("本季度", "上季度"),
        "annual": ("本年度", "上年度"),
    }[report_type]
    lines: list[str] = []
    cur_rank = ck.get("avg_rank")
    prev_rank = pk.get("avg_rank")
    if cur_rank is not None and prev_rank is not None:
        d = round(float(cur_rank) - float(prev_rank), 1)
        if d < 0:
            lines.append(f"{scope}平均推荐排名 {cur_rank}，较{prev_scope} {prev_rank} 提升 {abs(d)} 位。")
        elif d > 0:
            lines.append(f"{scope}平均推荐排名 {cur_rank}，较{prev_scope} {prev_rank} 回落 {d} 位，需关注短板平台。")
        else:
            lines.append(f"{scope}平均推荐排名 {cur_rank}，与{prev_scope}持平。")
    cur_mr = ck.get("mention_rate")
    prev_mr = pk.get("mention_rate")
    if cur_mr is not None and prev_mr is not None:
        d = round(float(cur_mr) - float(prev_mr), 1)
        verb = "上升" if d > 0 else ("下降" if d < 0 else "持平")
        lines.append(f"品牌提及率 {cur_mr}%（{prev_scope} {prev_mr}%），环比{verb} {abs(d) if d else 0} 个百分点。")
    hd = cur_health - prev_health
    if hd > 0:
        lines.append(f"综合健康分 {cur_health} 分，较{prev_scope}提升 {hd} 分。")
    elif hd < 0:
        lines.append(f"综合健康分 {cur_health} 分，较{prev_scope}下降 {abs(hd)} 分。")
    return lines[:4]


def _fmt_rank(v: Any) -> str:
    if v is None:
        return "—"
    return str(v)


def _fmt_pct(v: Any) -> str:
    if v is None:
        return "—"
    return f"{v}%"


def _delta_class(direction: str) -> str:
    return {"improved": "up", "declined": "down", "unchanged": "flat"}.get(direction, "na")


def collect_tenant_monitor_keywords(db, tenant_id: int) -> list[str]:
    """汇总企业全部启用词组下的监控词（去重、保序）。"""
    seen: set[str] = set()
    result: list[str] = []
    for group in _active_keyword_group_rows(db, tenant_id):
        for keyword in keyword_group_monitor_keywords(group):
            text = str(keyword or "").strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
    return result


def format_monitor_keywords_text(keywords: list[str], *, max_show: int = 10) -> str:
    cleaned = [str(item).strip() for item in keywords if str(item).strip()]
    if not cleaned:
        return "未配置监控词"
    shown = cleaned[:max_show]
    text = "、".join(shown)
    if len(cleaned) > max_show:
        text += f"等{len(cleaned)}个监控词"
    return text


def build_preface(
    *,
    modules: dict[str, Any],
    report_type: str,
    previous_period_label: str,
    monitor_keywords: list[str] | None = None,
) -> dict[str, Any]:
    return enrich_preface_from_modules(
        modules,
        report_type=report_type,
        previous_period_label=previous_period_label,
        monitor_keywords=monitor_keywords,
    )


def _month_week_ranges(year: int, month: int) -> list[tuple[int, date, date]]:
    """自然月内按周一切分（首尾周可能不足 7 天）。"""
    first = date(year, month, 1)
    last = date(year, month, 1)
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    ranges: list[tuple[int, date, date]] = []
    cursor = first
    idx = 1
    while cursor <= last:
        week_end = min(cursor + timedelta(days=(6 - cursor.weekday())), last)
        ranges.append((idx, cursor, week_end))
        cursor = week_end + timedelta(days=1)
        idx += 1
    return ranges


def _trend_bucket_slots(report_type: str, start: date, end: date) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    if report_type == "weekly":
        cursor = start
        while cursor <= end:
            slots.append({"key": cursor.isoformat(), "label": cursor.strftime("%m-%d"), "start": cursor, "end": cursor})
            cursor += timedelta(days=1)
        return slots
    if report_type == "monthly":
        for idx, w_start, w_end in _month_week_ranges(start.year, start.month):
            slots.append(
                {
                    "key": f"week-{idx}",
                    "label": f"第{idx}周",
                    "sub": f"{w_start:%m-%d}~{w_end:%m-%d}",
                    "start": w_start,
                    "end": w_end,
                }
            )
        return slots
    if report_type == "quarterly":
        cursor = date(start.year, start.month, 1)
        while cursor <= end:
            if cursor.month == 12:
                month_end = date(cursor.year, 12, 31)
            else:
                month_end = date(cursor.year, cursor.month + 1, 1) - timedelta(days=1)
            month_end = min(month_end, end)
            slots.append(
                {
                    "key": f"{cursor.year}-{cursor.month:02d}",
                    "label": f"{cursor.month}月",
                    "sub": f"{max(cursor, start):%m-%d}~{month_end:%m-%d}",
                    "start": max(cursor, start),
                    "end": month_end,
                }
            )
            if cursor.month == 12:
                cursor = date(cursor.year + 1, 1, 1)
            else:
                cursor = date(cursor.year, cursor.month + 1, 1)
        return slots
    if report_type == "annual":
        for quarter in range(1, 5):
            start_month = (quarter - 1) * 3 + 1
            q_start = date(start.year, start_month, 1)
            if start_month == 10:
                q_end = date(start.year, 12, 31)
            else:
                q_end = date(start.year, start_month + 3, 1) - timedelta(days=1)
            q_start = max(q_start, start)
            q_end = min(q_end, end)
            slots.append(
                {
                    "key": f"{start.year}-Q{quarter}",
                    "label": f"Q{quarter}",
                    "sub": f"{q_start:%m-%d}~{q_end:%m-%d}",
                    "start": q_start,
                    "end": q_end,
                }
            )
        return slots
    raise ValueError(report_type)


def _load_completed_subtasks(
    db,
    tenant_id: int,
    start: date,
    end: date,
) -> tuple[list[GeoMonitorSubtask], dict[int, date]]:
    """按业务检测日拉取区间子任务（禁止裸用 updated_at 当分日/周期键）。"""
    from app.services.monitor_stats_service import load_subtasks_for_business_date_range

    rows, _tasks, day_by_id = load_subtasks_for_business_date_range(
        db,
        tenant_id,
        start_date=start,
        end_date=end,
    )
    return rows, day_by_id


def _aggregate_bucket(rows: list[GeoMonitorSubtask]) -> dict[str, Any]:
    total = len(rows)
    mentioned = [r for r in rows if r.mention_position is not None]
    ranks = [float(r.mention_position) for r in mentioned]
    top3 = [r for r in mentioned if r.mention_position is not None and r.mention_position <= 3]
    return {
        "completed": total,
        "mention_rate": round(len(mentioned) / total * 100, 1) if total else None,
        "avg_rank": round(sum(ranks) / len(ranks), 1) if ranks else None,
        "top3_rate": round(len(top3) / total * 100, 1) if total else None,
    }


def _trend_slot_key(report_type: str, day: date, slots: list[dict[str, Any]]) -> str | None:
    if report_type == "weekly":
        return day.isoformat()
    if report_type == "monthly":
        return next((s["key"] for s in slots if s["start"] <= day <= s["end"]), None)
    if report_type == "annual":
        quarter = (day.month - 1) // 3 + 1
        return f"{day.year}-Q{quarter}"
    return f"{day.year}-{day.month:02d}"


def build_period_trend(db, tenant_id: int, report_type: str, start: date, end: date) -> dict[str, Any]:
    meta = TREND_META[report_type]
    slots = _trend_bucket_slots(report_type, start, end)
    points: list[dict[str, Any]] = []

    from app.services.monitor_stats_service import (
        has_daily_stats,
        list_daily_stats_for_tenant,
        period_bucket_from_stat_rows,
    )

    if has_daily_stats(db, [tenant_id]):
        # 与工作台一致：Top3/提及率/均排走日表，避免明细扫描与采样口径漂移
        bucket_stats: dict[str, list] = defaultdict(list)
        for row in list_daily_stats_for_tenant(db, tenant_id, since=start, until=end):
            key = _trend_slot_key(report_type, row.stat_date, slots)
            if key is None:
                continue
            bucket_stats[key].append(row)
        for slot in slots:
            agg = period_bucket_from_stat_rows(bucket_stats.get(slot["key"], []))
            points.append({**slot, **agg})
    else:
        rows, day_by_id = _load_completed_subtasks(db, tenant_id, start, end)
        bucket_rows: dict[str, list[GeoMonitorSubtask]] = defaultdict(list)
        for row in rows:
            day = day_by_id.get(row.id)
            if day is None:
                continue
            key = _trend_slot_key(report_type, day, slots)
            if key is None:
                continue
            bucket_rows[key].append(row)
        for slot in slots:
            agg = _aggregate_bucket(bucket_rows.get(slot["key"], []))
            points.append({**slot, **agg})

    valid_mr = [p["mention_rate"] for p in points if p["mention_rate"] is not None]
    valid_rank = [p["avg_rank"] for p in points if p["avg_rank"] is not None]
    summary = ""
    if len(valid_mr) >= 2:
        if valid_mr[-1] > valid_mr[0]:
            summary = f"{meta['title']}显示品牌提及率整体走高（{valid_mr[0]}% → {valid_mr[-1]}%）。"
        elif valid_mr[-1] < valid_mr[0]:
            summary = f"{meta['title']}显示品牌提及率整体回落（{valid_mr[0]}% → {valid_mr[-1]}%），需关注末段表现。"
    if len(valid_rank) >= 2:
        d = round(valid_rank[-1] - valid_rank[0], 1)
        if d < 0:
            summary += f" 平均排名由 {valid_rank[0]} 改善至 {valid_rank[-1]}。"
        elif d > 0:
            summary += f" 平均排名由 {valid_rank[0]} 退步至 {valid_rank[-1]}。"

    return {"title": meta["title"], "unit": meta["unit"], "points": points, "summary": summary.strip()}


def _active_keyword_group_rows(db, tenant_id: int) -> list:
    return [
        item
        for item in list_keyword_groups(db, tenant_id)
        if item.status and not item.deleted and keyword_group_monitor_keywords(item)
    ]


def _keyword_key(row: GeoMonitorSubtask, groups: list) -> str:
    label = _resolve_prompt_monitor_keyword(row.prompt or "", groups)
    if label:
        return label
    prompt = (row.prompt or "").strip()
    if len(prompt) > 36:
        return prompt[:35] + "…"
    return prompt or "未归类"


def _keyword_status(mention_rate: float | None, avg_rank: float | None) -> tuple[str, str]:
    rate = float(mention_rate or 0)
    if rate <= 0:
        return "未露面", "status-bad"
    if avg_rank is not None and float(avg_rank) <= 3 and rate >= 40:
        return "优秀", "status-good"
    if avg_rank is not None and float(avg_rank) <= 5:
        return "良好", "status-ok"
    return "待优化", "status-warn"


def _platform_stats_for_subtasks(rows: list[GeoMonitorSubtask]) -> list[dict[str, Any]]:
    bucket: dict[str, list[GeoMonitorSubtask]] = defaultdict(list)
    for row in rows:
        bucket[str(row.platform or "")].append(row)
    stats: list[dict[str, Any]] = []
    for platform, items in bucket.items():
        if not platform:
            continue
        agg = _aggregate_bucket(items)
        stats.append(
            {
                "platform": platform,
                "name": PLATFORM_LABELS.get(platform, platform),
                **agg,
            }
        )
    stats.sort(key=lambda item: (-int(item.get("completed") or 0), str(item.get("name") or "")))
    return stats


def _pick_weakest_platform_names(stats: list[dict[str, Any]], *, top_n: int = 2) -> list[str]:
    eligible = [item for item in stats if int(item.get("completed") or 0) > 0]
    if not eligible:
        return []
    ordered = sorted(
        eligible,
        key=lambda item: (
            float(item.get("mention_rate") or 0),
            -(float(item.get("avg_rank")) if item.get("avg_rank") is not None else 99),
        ),
    )
    return [str(item["name"]) for item in ordered[:top_n]]


def _cell_is_weak(stat: dict[str, Any], row_stats: list[dict[str, Any]]) -> bool:
    if int(stat.get("completed") or 0) <= 0:
        return False
    rates = [float(item.get("mention_rate") or 0) for item in row_stats if int(item.get("completed") or 0) > 0]
    if not rates:
        return False
    return float(stat.get("mention_rate") or 0) <= min(rates) + 0.01


def _format_platform_cell(stat: dict[str, Any] | None) -> tuple[str, bool, bool]:
    """返回 (展示文案, 是否短板格, 是否样本不足)。"""
    if stat is None or int(stat.get("completed") or 0) <= 0:
        return "—", False, False
    completed = int(stat.get("completed") or 0)
    mention = stat.get("mention_rate")
    rank = stat.get("avg_rank")
    rank_text = _fmt_rank(rank) if rank is not None else "—"
    text = f"{mention}% · {rank_text}" if mention is not None else rank_text
    if completed < 3:
        return f"{text}*", False, True
    return text, False, False


def build_weak_keyword_platform_matrix(
    weak_keywords: list[str],
    cur_map: dict[str, list[GeoMonitorSubtask]],
) -> dict[str, Any]:
    platform_codes: list[str] = []
    for keyword in weak_keywords:
        for stat in _platform_stats_for_subtasks(cur_map.get(keyword, [])):
            code = str(stat.get("platform") or "")
            if code and code not in platform_codes:
                platform_codes.append(code)

    rows: list[dict[str, Any]] = []
    for keyword in weak_keywords:
        row_stats = _platform_stats_for_subtasks(cur_map.get(keyword, []))
        stat_map = {str(item["platform"]): item for item in row_stats}
        cells: list[dict[str, Any]] = []
        for code in platform_codes:
            stat = stat_map.get(code)
            text, _, sparse = _format_platform_cell(stat)
            is_weak = _cell_is_weak(stat, row_stats) if stat else False
            cells.append({"text": text, "is_weak": is_weak, "sparse": sparse})
        rows.append({"keyword": keyword, "cells": cells})

    return {
        "platforms": [PLATFORM_LABELS.get(code, code) for code in platform_codes],
        "rows": rows,
    }


def build_keyword_analytics(
    db,
    tenant_id: int,
    *,
    start: date,
    end: date,
    prev_start: date,
    prev_end: date,
) -> dict[str, Any]:
    groups = _active_keyword_group_rows(db, tenant_id)
    cur_rows, _cur_days = _load_completed_subtasks(db, tenant_id, start, end)
    prev_rows, _prev_days = _load_completed_subtasks(db, tenant_id, prev_start, prev_end)

    cur_map: dict[str, list[GeoMonitorSubtask]] = defaultdict(list)
    prev_map: dict[str, list[GeoMonitorSubtask]] = defaultdict(list)
    for row in cur_rows:
        cur_map[_keyword_key(row, groups)].append(row)
    for row in prev_rows:
        prev_map[_keyword_key(row, groups)].append(row)

    ordered_keys = collect_tenant_monitor_keywords(db, tenant_id)
    seen_keys = set(ordered_keys)
    for key in sorted(cur_map.keys()):
        if key not in seen_keys:
            ordered_keys.append(key)
            seen_keys.add(key)

    rows: list[dict[str, Any]] = []
    for key in ordered_keys:
        cur_agg = _aggregate_bucket(cur_map.get(key, []))
        prev_agg = _aggregate_bucket(prev_map.get(key, []))
        mention = _metric_delta(cur_agg.get("mention_rate"), prev_agg.get("mention_rate"))
        rank = _metric_delta(cur_agg.get("avg_rank"), prev_agg.get("avg_rank"), lower_is_better=True)
        status, status_class = _keyword_status(cur_agg.get("mention_rate"), cur_agg.get("avg_rank"))
        kw_rows = cur_map.get(key, [])
        platform_stats = _platform_stats_for_subtasks(kw_rows)
        weakest_platforms = _pick_weakest_platform_names(platform_stats)
        rows.append(
            {
                "keyword": key,
                "completed": int(cur_agg.get("completed") or 0),
                "mention_rate": mention,
                "avg_rank": rank,
                "top3_rate": cur_agg.get("top3_rate"),
                "status": status,
                "status_class": status_class,
                "weakest_platforms": weakest_platforms,
            }
        )

    sampled = [row for row in rows if row["completed"] > 0]
    weak_top3 = sorted(
        sampled,
        key=lambda row: (
            float(row["mention_rate"]["current"] or 0),
            -(float(row["avg_rank"]["current"]) if row["avg_rank"]["current"] is not None else -99),
        ),
    )[:3]

    highlights: list[str] = []
    for row in weak_top3:
        kw = row["keyword"]
        mr = row["mention_rate"]["current"]
        rk = row["avg_rank"]["current"]
        rd = row["avg_rank"]
        platform_hint = ""
        weak_platforms = row.get("weakest_platforms") or []
        if weak_platforms:
            platform_hint = f"主要短板平台：{'、'.join(weak_platforms)}。"
        if rd["direction"] == "declined" and rd["delta"] is not None:
            highlights.append(
                f"监控词「{kw}」排名 {rk}，较上期 {rd['previous']} 回落 {abs(rd['delta'])} 位，优先补内容。{platform_hint}"
            )
        elif (mr or 0) <= 0:
            highlights.append(
                f"监控词「{kw}」本期未进入 AI 推荐列表，建议补充结构化问答与权威引用。{platform_hint}"
            )
        else:
            highlights.append(
                f"监控词「{kw}」提及率 {mr}%、排名 {rk}，表现偏弱，建议针对性优化。{platform_hint}"
            )

    weak_matrix = build_weak_keyword_platform_matrix(
        [str(item["keyword"]) for item in weak_top3],
        cur_map,
    )

    configured = collect_tenant_monitor_keywords(db, tenant_id)

    return {
        "rows": rows,
        "weak_top3": weak_top3,
        "highlights": highlights,
        "configured_labels": configured,
        "group_count": len(configured) or len(rows),
        "weak_platform_matrix": weak_matrix,
    }


def render_preface_html(preface: dict[str, Any], *, client: bool = False) -> str:
    esc = html.escape
    dims = "".join(f"<li>{esc(str(item))}</li>" for item in preface.get("core_dimensions") or [])
    side_blocks = [
        ("核心监测维度", dims, "ul", "preface-dims"),
        ("报告用途", str(preface.get("purpose") or ""), "p", ""),
    ]
    if not client:
        side_blocks.extend(
            [
                ("环比说明", str(preface.get("comparison_note") or ""), "p", ""),
                ("趋势说明", str(preface.get("trend_note") or ""), "p", ""),
            ]
        )
    side_html = ""
    for title, content, tag, cls in side_blocks:
        if not str(content).strip():
            continue
        if tag == "ul":
            side_html += f"<h3>{esc(title)}</h3><ul class=\"{cls}\">{content}</ul>"
        else:
            side_html += f"<h3>{esc(title)}</h3><{tag}>{esc(content)}</{tag}>"
    return f"""
      <section class="preface" id="preface">
        <h2>报告前言</h2>
        <p class="preface-lead">{esc(str(preface.get('sample_description') or ''))}</p>
        <div class="preface-grid">
          <dl>
            <dt>报告名称</dt><dd>{esc(str(preface.get('report_title') or '—'))}</dd>
            <dt>发布主体</dt><dd>{esc(str(preface.get('publisher') or '—'))}</dd>
            <dt>监测工具</dt><dd>{esc(str(preface.get('monitor_tool') or '—'))}</dd>
            <dt>统计周期</dt><dd>{esc(str(preface.get('period_range') or '—'))}</dd>
            <dt>监测词组</dt><dd>{esc(str(preface.get('monitor_keywords') or '—'))}</dd>
            <dt>纳入竞品</dt><dd>{esc(str(preface.get('competitors') or '—'))}</dd>
          </dl>
          <div class="preface-side">
            {side_html}
          </div>
        </div>
      </section>"""


def render_keyword_platform_matrix_html(matrix: dict[str, Any]) -> str:
    esc = html.escape
    platforms = matrix.get("platforms") or []
    rows = matrix.get("rows") or []
    if not platforms or not rows:
        return ""

    head = "".join(f"<th>{esc(name)}</th>" for name in platforms)
    body = ""
    for row in rows:
        cells = ""
        for cell in row.get("cells") or []:
            cls = "matrix-weak" if cell.get("is_weak") else ("matrix-sparse" if cell.get("sparse") else "")
            cells += f'<td class="{cls}">{esc(str(cell.get("text") or "—"))}</td>'
        body += f"<tr><td class=\"kw-cell\">{esc(str(row.get('keyword') or ''))}</td>{cells}</tr>"

    return f"""
      <div class="kw-matrix">
        <h3>短板监控词 × 平台表现</h3>
        <p class="note">仅展示本期表现最弱的 TOP3 监控词；单元格为「提及率 · 平均排名」，* 表示样本不足 3 条，橙色为同词最弱平台。</p>
        <table class="matrix-table">
          <thead><tr><th>监控词</th>{head}</tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>"""


def render_keyword_html(keyword_analytics: dict[str, Any], *, report_type: str, client: bool = False) -> str:
    esc = html.escape
    rows = keyword_analytics.get("rows") or []
    if not rows:
        return ""

    show_weakest_col = report_type == "weekly"
    matrix_html = ""
    if report_type in _RANK_TREND_TYPES:
        matrix_html = render_keyword_platform_matrix_html(keyword_analytics.get("weak_platform_matrix") or {})

    table_rows = ""
    for index, row in enumerate(rows, 1):
        mr = row["mention_rate"]
        ar = row["avg_rank"]
        weakest = "、".join(row.get("weakest_platforms") or []) or "—"
        weakest_col = f"<td>{esc(weakest)}</td>" if show_weakest_col else ""
        table_rows += f"""
        <tr>
          <td>{index}</td>
          <td class="kw-cell">{esc(str(row['keyword']))}</td>
          <td>{row['completed']}</td>
          <td>{esc(_fmt_pct(mr['current']))}</td>
          <td>{esc(_fmt_pct(mr['previous']))}</td>
          <td><span class="delta {_delta_class(mr['direction'])}">{esc(mr['text'])}</span></td>
          <td>{esc(_fmt_rank(ar['current']))}</td>
          <td>{esc(_fmt_rank(ar['previous']))}</td>
          <td><span class="delta {_delta_class(ar['direction'])}">{esc(ar['text'])}</span></td>
          <td>{esc(_fmt_pct(row.get('top3_rate')))}</td>
          {weakest_col}
          <td><span class="status-tag {esc(row['status_class'])}">{esc(row['status'])}</span></td>
        </tr>"""

    weak_items = "".join(f"<li>{esc(line)}</li>" for line in keyword_analytics.get("highlights") or [])
    weak_html = ""
    if weak_items:
        weak_html = f"""
        <div class="kw-weak">
          <h3>短板监控词 TOP3</h3>
          <ul>{weak_items}</ul>
        </div>"""

    if client:
        kw_heading = "核心监测词表现 · 环比上一周期"
        if show_weakest_col:
            kw_note = "按本周期监测关键词配置聚合统计；排名数字越小越靠前；另列各关键词的最弱平台。"
        else:
            kw_note = "按本周期监测关键词配置聚合统计；排名数字越小越靠前；下方附短板词跨平台明细。"
    else:
        kw_heading = "监控词成绩单 · 环比上一周期"
        kw_note = (
            f"按资料库配置的监控词组聚合统计；监测问题通过语义匹配归组，排名数字越小越靠前。"
            f"{'周报额外标注各监控词的最弱平台。' if show_weakest_col else '月报/季报在下方展示短板词的跨平台明细。'}"
        )
    weakest_head = "<th>最弱平台</th>" if show_weakest_col else ""
    return f"""
      <section class="keyword-section" id="keywords">
        <h2>{kw_heading}</h2>
        <p class="note">{esc(kw_note)}</p>
        {weak_html}
        <table>
          <thead>
            <tr>
              <th>#</th><th>监控词</th><th>样本</th>
              <th>提及率</th><th>上期提及率</th><th>提及率变化</th>
              <th>平均排名</th><th>上期排名</th><th>排名变化</th>
              <th>Top3率</th>{weakest_head}<th>表现</th>
            </tr>
          </thead>
          <tbody>{table_rows}</tbody>
        </table>
        {matrix_html}
      </section>"""


def _embed_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def render_trend_html(trend: dict[str, Any], *, echarts_src: str = ECHARTS_CDN) -> str:
    esc = html.escape
    points = trend.get("points") or []
    if not points:
        return ""

    short_categories, full_categories = _trend_axis_labels(points)
    need_slant = len(points) > 3
    chart_data = {
        "categories": short_categories,
        "fullCategories": full_categories,
        "mention": [point.get("mention_rate") for point in points],
        "rank": [point.get("avg_rank") for point in points],
        "completed": [int(point.get("completed") or 0) for point in points],
        "top3": [point.get("top3_rate") for point in points],
        "sparse": len(points) <= 4,
        "label_rotate": -34 if need_slant else 0,
        "grid_bottom": 92 if need_slant else 56,
    }
    chart_json = _embed_json(chart_data)

    table_rows = ""
    for point in points:
        sub = point.get("sub")
        label = point["label"] if not sub else f"{point['label']} ({sub})"
        table_rows += f"""
        <tr>
          <td>{esc(str(label))}</td>
          <td>{int(point.get('completed') or 0)}</td>
          <td>{esc(_fmt_pct(point.get('mention_rate')))}</td>
          <td>{esc(_fmt_rank(point.get('avg_rank')))}</td>
          <td>{esc(_fmt_pct(point.get('top3_rate')))}</td>
        </tr>"""

    summary = trend.get("summary") or ""
    summary_html = f'<p class="trend-summary">{esc(summary)}</p>' if summary else ""
    total_completed = sum(int(point.get("completed") or 0) for point in points)
    empty_note = (
        '<p class="note trend-empty-note">本周期各时间桶监测样本均为 0，暂无趋势可画。'
        "请确认报告周期与实际监测日期是否重合（例如 2025 年报在仅有 2026 年监测数据时会整表为空）。</p>"
        if total_completed <= 0
        else ""
    )
    sparse_note = (
        '<p class="note trend-sparse-note">本周期趋势时间点较少，图表采用柱状对比展示；明细见下方数据表。</p>'
        if chart_data["sparse"] and total_completed > 0
        else ""
    )
    chart_kind_hint = "柱状对比" if chart_data["sparse"] else "折线趋势"

    return f"""
      <section class="trend-section" id="trend">
        <h2>{esc(str(trend.get('title') or '趋势'))} · 品牌提及率与平均排名</h2>
        {summary_html}
        {empty_note}
        {sparse_note}
        <div class="trend-charts">
          <div class="trend-chart-box">
            <h3>品牌提及率（%）· {chart_kind_hint}</h3>
            <div id="trendMentionChart" class="echart-canvas"></div>
          </div>
          <div class="trend-chart-box">
            <h3>平均推荐排名（越小越靠前）· {chart_kind_hint}</h3>
            <div id="trendRankChart" class="echart-canvas"></div>
          </div>
        </div>
        <table>
          <thead>
            <tr><th>时间</th><th>样本数</th><th>提及率</th><th>平均排名</th><th>Top3率</th></tr>
          </thead>
          <tbody>{table_rows}</tbody>
        </table>
      </section>
      <script src="{html.escape(echarts_src, quote=True)}"></script>
      <script>
      (function () {{
        const data = {chart_json};
        const mentionEl = document.getElementById('trendMentionChart');
        const rankEl = document.getElementById('trendRankChart');
        if (!mentionEl || !rankEl) return;

        function failTip() {{
          const tip = '<p class="note">图表库未加载，请检查网络或刷新后重试；下方数据表仍可查阅。</p>';
          mentionEl.innerHTML = tip;
          rankEl.innerHTML = tip;
        }}

        function paint() {{
          if (!window.echarts) {{
            failTip();
            return;
          }}

        const mentionChart = echarts.init(mentionEl);
        const sparse = !!data.sparse;
        const mentionVals = data.mention.filter(v => v != null && Number.isFinite(Number(v))).map(Number);
        // ponytail: 全 null 时 Math.min(...[])=Infinity 会让坐标轴炸掉、柱子不画
        let minM = 0;
        let maxM = 100;
        if (mentionVals.length) {{
          minM = Math.max(0, Math.min(...mentionVals) - 8);
          maxM = Math.min(100, Math.max(...mentionVals) + (sparse ? 8 : 6));
          if (minM >= maxM) {{ maxM = Math.min(100, minM + 10); }}
        }}
        const xRotate = data.label_rotate || 0;
        const gridBottom = data.grid_bottom || 56;
        const fullCats = data.fullCategories || data.categories || [];
        const axisTitle = (idx) => fullCats[idx] || (data.categories[idx] || '');
        const xAxisLabel = {{
          interval: 0,
          rotate: xRotate,
          color: '#64748b',
          fontSize: 11,
          margin: xRotate ? 14 : 8,
        }};
        const mentionSeries = {{
          name: '提及率',
          type: sparse ? 'bar' : 'line',
          data: data.mention,
          label: {{ show: true, formatter: sparse ? '{{c}}%' : '{{c}}%', color: '#1677ff', fontWeight: 600 }},
        }};
        if (sparse) {{
          mentionSeries.barMaxWidth = 56;
          mentionSeries.itemStyle = {{ borderRadius: [8, 8, 0, 0], color: '#1677ff' }};
        }} else {{
          mentionSeries.smooth = true;
          mentionSeries.symbol = 'circle';
          mentionSeries.symbolSize = 8;
          mentionSeries.lineStyle = {{ width: 3 }};
          mentionSeries.areaStyle = {{
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              {{ offset: 0, color: 'rgba(22,119,255,0.35)' }},
              {{ offset: 1, color: 'rgba(22,119,255,0.04)' }},
            ]),
          }};
        }}
        mentionChart.setOption({{
          color: ['#1677ff'],
          tooltip: {{
            trigger: 'axis',
            formatter: params => {{
              const p = params[0];
              const idx = p.dataIndex;
              return `${{axisTitle(idx)}}<br/>提及率：<b>${{p.data}}%</b><br/>样本：${{data.completed[idx]}} 条`;
            }},
          }},
          grid: {{ left: 58, right: 36, top: 42, bottom: gridBottom, containLabel: true }},
          xAxis: {{
            type: 'category',
            data: data.categories,
            axisLabel: xAxisLabel,
            axisLine: {{ lineStyle: {{ color: '#cbd5e1' }} }},
          }},
          yAxis: {{
            type: 'value',
            name: '提及率 %',
            min: minM,
            max: maxM,
            splitLine: {{ lineStyle: {{ type: 'dashed', color: '#e2e8f0' }} }},
            axisLabel: {{ color: '#64748b' }},
          }},
          series: [mentionSeries],
        }});

        const rankChart = echarts.init(rankEl);
        const ranks = data.rank.filter(v => v != null && Number.isFinite(Number(v))).map(Number);
        let minR = 1;
        let maxR = 10;
        if (ranks.length) {{
          minR = Math.max(1, Math.min(...ranks) - 0.45);
          maxR = Math.max(...ranks) + 0.45;
          if (minR >= maxR) {{ maxR = minR + 1; }}
        }}
        const rankInverse = !sparse;
        const rankAxisLabel = {{
          color: '#64748b',
          formatter: (v) => {{
            const n = Number(v);
            if (!Number.isFinite(n) || n <= 0 || n > 50) return '';
            // ponytail: inverse+bar 会生成轴外垃圾刻度（如 #999997），按可视区间滤掉
            if (n < minR - 0.15 || n > maxR + 0.15) return '';
            const text = (Math.round(n * 10) / 10).toString();
            return text;
          }},
        }};
        const rankSeries = {{
          name: '平均排名',
          type: sparse ? 'bar' : 'line',
          data: data.rank,
          label: {{
            show: true,
            position: sparse ? 'top' : 'top',
            formatter: (p) => String(p.data),
            color: '#0e7490',
            fontWeight: 600,
          }},
        }};
        if (sparse) {{
          rankSeries.barMaxWidth = 56;
          rankSeries.itemStyle = {{ borderRadius: [8, 8, 0, 0], color: '#15b8c8' }};
        }} else {{
          rankSeries.smooth = true;
          rankSeries.symbol = 'circle';
          rankSeries.symbolSize = 8;
          rankSeries.lineStyle = {{ width: 3 }};
          rankSeries.label.position = 'top';
          rankSeries.label.distance = 10;
        }}
        rankChart.setOption({{
          color: ['#15b8c8'],
          tooltip: {{
            trigger: 'axis',
            formatter: params => {{
              const p = params[0];
              const idx = p.dataIndex;
              return `${{axisTitle(idx)}}<br/>平均排名：<b>${{p.data}}</b><br/>Top3率：${{data.top3[idx] ?? '—'}}%`;
            }},
          }},
          grid: {{ left: 58, right: 36, top: 42, bottom: gridBottom, containLabel: true }},
          xAxis: {{
            type: 'category',
            data: data.categories,
            axisLabel: xAxisLabel,
            axisLine: {{ lineStyle: {{ color: '#cbd5e1' }} }},
          }},
          yAxis: {{
            type: 'value',
            name: sparse ? '排名（越低越好）' : '排名',
            nameLocation: 'end',
            nameGap: 8,
            min: minR,
            max: maxR,
            inverse: rankInverse,
            splitNumber: sparse ? Math.min(4, ranks.length + 1) : 5,
            splitLine: {{ lineStyle: {{ type: 'dashed', color: '#e2e8f0' }} }},
            axisLabel: rankAxisLabel,
          }},
          series: [rankSeries],
        }});

        window.addEventListener('resize', () => {{
          mentionChart.resize();
          rankChart.resize();
        }});
        }}

        if (window.echarts) {{
          paint();
          return;
        }}
        // script src 失败/慢时：同源包或内联注入后仍可能晚到，短轮询再放弃
        let tries = 0;
        const timer = setInterval(() => {{
          tries += 1;
          if (window.echarts) {{
            clearInterval(timer);
            paint();
          }} else if (tries >= 40) {{
            clearInterval(timer);
            failTip();
          }}
        }}, 50);
      }})();
      </script>"""


def _render_report_tail_sections(
    *,
    v2: bool,
    report_type: str,
    content_modules: dict[str, Any],
    client: bool = False,
) -> str:
    if v2 and report_type == "weekly":
        return render_weekly_focus_html(content_modules, client=client) + render_disclaimer_html(
            content_modules.get("disclaimer") or {}
        )
    return (
        render_source_influence_html(content_modules.get("source_influence") or {})
        + render_risk_strategy_html(content_modules.get("risk_and_strategy") or {}, client=client)
        + render_action_plan_html(content_modules.get("action_plan"), client=client)
        + render_disclaimer_html(content_modules.get("disclaimer") or {})
    )


def render_html(
    *,
    brand_name: str,
    report_type: str,
    period_lbl: str,
    comparison: dict[str, Any],
    snapshot: dict[str, Any],
    preface: dict[str, Any],
    content_modules: dict[str, Any],
    trend: dict[str, Any],
    keyword_analytics: dict[str, Any],
    competitor_analytics: dict[str, Any],
    generated: date,
    v2: bool = False,
    echarts_src: str = ECHARTS_CDN,
) -> str:
    type_label = TYPE_LABELS[report_type]
    kpis = comparison["kpis"]
    esc = html.escape

    def kpi_card(title: str, metric: dict[str, Any], fmt_prev, fmt_cur, invert: bool = False) -> str:
        d = metric
        cls = _delta_class(d["direction"])
        cur = fmt_cur(d["current"])
        prev = fmt_prev(d["previous"])
        delta = esc(d["text"])
        return f"""
        <article class="kpi-card">
          <span class="kpi-label">{esc(title)}</span>
          <strong class="kpi-value">{cur}</strong>
          <span class="kpi-prev">上期 {prev}</span>
          <span class="kpi-delta {cls}">{delta}</span>
        </article>"""

    kpi_html = "".join(
        [
            kpi_card("综合健康分", kpis["health_score"], str, lambda v: str(int(v)) if v is not None else "—"),
            kpi_card("品牌提及率", kpis["mention_rate"], _fmt_pct, _fmt_pct),
            kpi_card("平均推荐排名", kpis["avg_rank"], _fmt_rank, _fmt_rank),
            kpi_card("Top3 露出率", kpis["top3_rate"], _fmt_pct, _fmt_pct),
        ]
    )

    platform_rows = ""
    for row in comparison["platform_rows"]:
        mr = row["mention_rate"]
        ar = row["avg_rank"]
        platform_rows += f"""
        <tr>
          <td>{esc(row['name'])}</td>
          <td>{esc(_fmt_rank(ar['previous']))}</td>
          <td>{esc(_fmt_rank(ar['current']))}</td>
          <td><span class="delta {_delta_class(ar['direction'])}">{esc(ar['text'])}</span></td>
          <td>{esc(_fmt_pct(mr['previous']))}</td>
          <td>{esc(_fmt_pct(mr['current']))}</td>
          <td><span class="delta {_delta_class(mr['direction'])}">{esc(mr['text'])}</span></td>
          <td>{row['completed']}</td>
        </tr>"""

    if v2:
        conclusion_lines = build_v2_conclusions(comparison, keyword_analytics, competitor_analytics)
    else:
        conclusion_lines = list(comparison.get("highlights") or []) + list(competitor_analytics.get("highlights") or [])[:2]
    highlight_items = "".join(f"<li>{esc(line)}</li>" for line in conclusion_lines)

    demo_note = ""
    if not v2:
        demo_note = f"<p class='warn'>⚠ {esc(_ENRICH_NOTE)}</p>"
        if comparison.get("used_demo_previous"):
            demo_note += f"<p class='warn'>⚠ 上一周期（{esc(comparison['previous_period_label'])}）库内样本较少，环比基准部分采用演示数据。</p>"
    sample_warn = comparison.get("sample_warn") or ""
    if v2 and sample_warn:
        sample_warn = sample_warn.replace("子任务", "样本")
    snap_kpis = snapshot.get("kpis") or {}
    completed = int(snap_kpis.get("completed_count") or snap_kpis.get("subtask_count") or 0)
    if completed <= 0:
        # comparison.kpis.*.current 是环比卡片；兜底避免 snapshot 缺 kpis 时正文写「0 条」
        completed_metric = (comparison.get("kpis") or {}).get("completed_count") or {}
        if isinstance(completed_metric, dict):
            completed = int(completed_metric.get("current") or 0)
        else:
            completed = int(completed_metric or 0)
    sample_meta = (
        f'<p class="note sample-meta">本期有效监测样本 {completed} 条 · 对比周期 {esc(comparison["previous_period_label"])}</p>'
        if v2
        else ""
    )
    hero_tag = "GEO 监测报告" if v2 else "样例预览 · 演示增强数据 · 未接入正式代码"
    title_suffix = "监测报告" if v2 else "环比样例"
    foot_note = "" if v2 else (
        "说明：本文件为桌面预览样例。正式接入后，环比数据将从上一自然周/月/季度的真实监测子任务自动计算；排名数字越小表示越靠前。"
    )
    foot_brand = "GEO Monitor · 周期监测报告" if v2 else "GEO Monitor · 周期报告环比预览样例"
    tail_sections = _render_report_tail_sections(
        v2=v2, report_type=report_type, content_modules=content_modules, client=v2
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{esc(brand_name)} · {esc(type_label)} · {esc(title_suffix)}</title>
  <style>
    :root {{
      --primary: #1677ff;
      --accent: #15b8c8;
      --text: #1f2937;
      --muted: #64748b;
      --border: #e2e8f0;
      --bg: #f5f7fb;
      --up: #16a34a;
      --down: #dc2626;
      --flat: #64748b;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--text); font-family: "Microsoft YaHei", "PingFang SC", sans-serif; line-height: 1.6; }}
    .page {{ max-width: 1080px; margin: 24px auto 48px; background: #fff; border-radius: 16px; box-shadow: 0 12px 40px rgba(22,119,255,.08); overflow: hidden; }}
    .hero {{ padding: 40px 48px 32px; background: linear-gradient(135deg, var(--primary), var(--accent)); color: #fff; }}
    .hero .tag {{ display: inline-block; background: rgba(255,255,255,.18); border-radius: 999px; padding: 4px 12px; font-size: 12px; margin-bottom: 12px; }}
    .hero h1 {{ margin: 0 0 8px; font-size: 28px; font-weight: 700; }}
    .hero p {{ margin: 4px 0; opacity: .92; font-size: 14px; }}
    .content {{ padding: 32px 48px 40px; }}
    h2 {{ margin: 28px 0 12px; font-size: 18px; color: var(--primary); border-left: 4px solid var(--accent); padding-left: 10px; }}
    .kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }}
    .kpi-card {{ border: 1px solid var(--border); border-radius: 12px; padding: 16px; background: #fafcff; }}
    .kpi-label {{ display: block; font-size: 12px; color: var(--muted); margin-bottom: 6px; }}
    .kpi-value {{ display: block; font-size: 26px; font-weight: 800; color: var(--primary); line-height: 1.2; }}
    .kpi-prev {{ display: block; font-size: 12px; color: var(--muted); margin-top: 6px; }}
    .kpi-delta {{ display: inline-block; margin-top: 8px; font-size: 13px; font-weight: 600; padding: 2px 8px; border-radius: 6px; }}
    .kpi-delta.up, .delta.up {{ color: var(--up); background: #ecfdf3; }}
    .kpi-delta.down, .delta.down {{ color: var(--down); background: #fef2f2; }}
    .kpi-delta.flat, .delta.flat {{ color: var(--flat); background: #f1f5f9; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th {{ background: #f0f6ff; color: var(--primary); text-align: left; padding: 10px 8px; border-bottom: 2px solid var(--border); }}
    td {{ padding: 10px 8px; border-bottom: 1px solid var(--border); vertical-align: middle; }}
    ul {{ margin: 0; padding-left: 20px; }}
    li {{ margin-bottom: 8px; }}
    .note, .warn {{ font-size: 13px; color: var(--muted); background: #f8fafc; border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }}
    .warn {{ background: #fffbeb; border-color: #fde68a; color: #92400e; }}
    .preface {{ margin-bottom: 8px; }}
    .preface-lead {{ margin: 0 0 16px; font-size: 14px; line-height: 1.75; color: var(--text); }}
    .preface-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; border: 1px solid var(--border); border-radius: 12px; padding: 20px 22px; background: #fafcff; }}
    .preface dl {{ margin: 0; }}
    .preface dt {{ font-size: 12px; color: var(--muted); margin-top: 10px; }}
    .preface dt:first-child {{ margin-top: 0; }}
    .preface dd {{ margin: 4px 0 0; font-size: 14px; font-weight: 600; color: var(--text); }}
    .preface-side h3 {{ margin: 0 0 8px; font-size: 13px; color: var(--primary); }}
    .preface-side h3:not(:first-child) {{ margin-top: 16px; }}
    .preface-side p {{ margin: 0; font-size: 13px; color: var(--text); line-height: 1.7; }}
    .preface-dims {{ margin: 0; padding-left: 18px; font-size: 13px; }}
    .preface-dims li {{ margin-bottom: 4px; }}
    .trend-section {{ margin-top: 8px; }}
    .trend-charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 8px; }}
    .trend-chart-box {{ border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px 8px; background: #fff; min-width: 0; overflow: hidden; }}
    .trend-chart-box h3 {{ margin: 0 0 8px; font-size: 13px; color: var(--muted); font-weight: 600; }}
    .echart-canvas {{ width: 100%; max-width: 100%; height: 280px; box-sizing: border-box; }}
    .trend-summary {{ margin: 0 0 12px; font-size: 13px; color: var(--text); background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 8px; padding: 10px 12px; }}
    .trend-sparse-note {{ margin: 0 0 12px; }}
    .keyword-section {{ margin-top: 8px; }}
    .kw-cell {{ max-width: 220px; font-weight: 600; }}
    .kw-weak {{ margin: 0 0 14px; padding: 12px 14px; background: #fff7ed; border: 1px solid #fed7aa; border-radius: 8px; }}
    .kw-weak h3 {{ margin: 0 0 8px; font-size: 14px; color: #c2410c; }}
    .kw-weak ul {{ margin: 0; padding-left: 18px; font-size: 13px; }}
    .status-tag {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: 600; }}
    .status-good {{ background: #ecfdf3; color: #15803d; }}
    .status-ok {{ background: #eff6ff; color: #1d4ed8; }}
    .status-warn {{ background: #fff7ed; color: #c2410c; }}
    .status-bad {{ background: #fef2f2; color: #b91c1c; }}
    .kw-matrix {{ margin-top: 18px; }}
    .kw-matrix h3 {{ margin: 0 0 8px; font-size: 15px; color: var(--primary); }}
    .matrix-table td, .matrix-table th {{ text-align: center; font-size: 12px; }}
    .matrix-table .kw-cell {{ text-align: left; }}
    .matrix-weak {{ background: #fff7ed; color: #c2410c; font-weight: 600; }}
    .matrix-sparse {{ color: var(--muted); }}
    .competitor-section {{ margin-top: 8px; }}
    .comp-insights {{ margin: 0 0 12px; padding-left: 18px; font-size: 13px; }}
    .comp-insights li {{ margin-bottom: 6px; }}
    .comp-brand-row td:first-child {{ color: var(--primary); }}
    .comp-swatch {{ display: inline-block; width: 10px; height: 10px; margin-right: 7px; border-radius: 50%; border: 1px solid rgba(15,23,42,.2); vertical-align: 0; }}
    .comp-risk {{ display: inline-block; margin-left: 4px; padding: 1px 6px; border-radius: 999px; font-size: 10px; font-weight: 700; white-space: nowrap; }}
    .comp-risk-good {{ color: #166534; background: #dcfce7; }}
    .comp-risk-watch {{ color: #92400e; background: #fef3c7; }}
    .comp-risk-warning {{ color: #c2410c; background: #ffedd5; }}
    .comp-risk-danger {{ color: #b91c1c; background: #fee2e2; }}
    .comp-risk-neutral {{ color: #4b5563; background: #e5e7eb; }}
    .comp-strategy-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin: 0 0 12px; }}
    .comp-strategy-card {{ border: 1px solid #bfdbfe; border-left: 4px solid #1677ff; border-radius: 10px; padding: 12px 14px; background: #f8fbff; }}
    .comp-action-card {{ border-color: #fed7aa; border-left-color: #f28e2b; background: #fffaf3; }}
    .comp-strategy-card h3 {{ margin: 0 0 7px; font-size: 14px; color: var(--primary); }}
    .comp-strategy-card p, .comp-strategy-card ol {{ margin: 0; font-size: 12px; line-height: 1.7; }}
    .comp-strategy-card ol {{ padding-left: 18px; }}
    .comp-risk-legend {{ margin: 0 0 12px; padding: 9px 12px; border: 1px dashed #cbd5e1; border-radius: 8px; font-size: 12px; color: var(--muted); }}
    .comp-trend-box {{ margin-top: 16px; border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px 4px; background: #fff; min-width: 0; overflow: hidden; }}
    .comp-trend-box h3 {{ margin: 0 0 8px; font-size: 14px; color: var(--primary); }}
    .echart-canvas-wide {{ width: 100%; max-width: 100%; height: 320px; box-sizing: border-box; }}
    .toc-section {{ margin-bottom: 8px; }}
    .toc-list {{ list-style: none; margin: 0; padding: 0; }}
    .toc-list li {{ margin-bottom: 8px; }}
    .toc-list a {{ display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; border: 1px solid var(--border); border-radius: 8px; text-decoration: none; color: var(--text); background: #fafcff; font-size: 13px; }}
    .toc-list a:hover {{ background: #eff6ff; border-color: #bfdbfe; }}
    .source-section, .strategy-section, .plan-section, .disclaimer-section {{ margin-top: 8px; }}
    .source-grid, .plan-grid, .strategy-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    .card-box {{ border: 1px solid var(--border); border-radius: 12px; padding: 16px; background: #fafcff; }}
    .card-box h3, .card-box h4 {{ margin: 0 0 10px; font-size: 14px; color: var(--primary); }}
    .card-box ul {{ margin: 0; padding-left: 18px; font-size: 13px; }}
    .strategy-problems {{ margin-bottom: 16px; }}
    .val-cell {{ font-size: 12px; color: var(--muted); line-height: 1.55; max-width: 280px; }}
    .source-conclusion {{ margin: 12px 0 0; font-size: 13px; line-height: 1.7; color: var(--text); }}
    .plan-note {{ margin: 0 0 14px; }}
    .read-guide, .sample-meta {{ margin: 0 0 14px; }}
    .disclaimer-section ol {{ margin: 0; padding-left: 20px; font-size: 13px; color: var(--muted); line-height: 1.75; }}
    .disclaimer-section li {{ margin-bottom: 8px; }}
    @media (max-width: 900px) {{
      .source-grid, .plan-grid, .strategy-grid, .trend-charts, .preface-grid, .kpi-grid, .comp-strategy-grid {{ grid-template-columns: 1fr; }}
    }}
    .foot {{ margin-top: 24px; font-size: 12px; color: var(--muted); }}
    @media print {{
      body {{ background: #fff; }}
      .page {{ box-shadow: none; margin: 0; max-width: none; border-radius: 0; overflow: visible; }}
      .content {{ padding: 20px 24px; }}
      .kpi-grid {{ grid-template-columns: repeat(4, 1fr) !important; }}
      h2, h3, h4 {{ break-after: avoid; page-break-after: avoid; }}
      section#platform, section#kpi, section#conclusions, section#preface, section#toc,
      section#disclaimer, .print-keep-section, .kw-weak, .kw-matrix, .comp-insights,
      .trend-summary, .note, .warn, .card-box, .preface-grid {{
        break-inside: avoid; page-break-inside: avoid;
      }}
      .comp-strategy-grid, .comp-strategy-card, .comp-risk-legend {{ break-inside: avoid; page-break-inside: avoid; }}
      section#platform table, .trend-section > table, .competitor-section > table,
      .kw-matrix table, .matrix-table, .source-table-box table {{
        break-inside: avoid; page-break-inside: avoid;
      }}
      section#keywords > table {{ break-inside: auto; page-break-inside: auto; }}
      thead {{ display: table-header-group; }}
      tr {{ break-inside: avoid; page-break-inside: avoid; }}
      .trend-charts {{ grid-template-columns: 1fr !important; gap: 12px; break-inside: avoid; }}
      .preface-grid, .plan-grid, .strategy-grid {{ grid-template-columns: 1fr 1fr !important; }}
      .trend-chart-box, .comp-trend-box {{ min-width: 0; overflow: hidden; width: 100%; break-inside: avoid; page-break-inside: avoid; }}
      .echart-canvas, .echart-canvas-wide {{ width: 100% !important; max-width: 100% !important; box-sizing: border-box; break-inside: avoid; page-break-inside: avoid; }}
      .echart-canvas {{ height: 260px; min-height: 260px; }}
      .echart-canvas-wide {{ height: 300px; min-height: 300px; }}
      .source-grid {{ grid-template-columns: 1fr !important; gap: 20px; }}
      .source-table-box table {{ table-layout: fixed; width: 100%; }}
      .source-table-box th:nth-child(1), .source-table-box td:nth-child(1) {{ width: 5%; }}
      .source-table-box th:nth-child(2), .source-table-box td:nth-child(2) {{ width: 22%; }}
      .source-table-box th:nth-child(3), .source-table-box td:nth-child(3) {{ width: 8%; white-space: nowrap; }}
      .source-table-box th:nth-child(4), .source-table-box td:nth-child(4) {{ width: 65%; }}
      .val-cell {{ max-width: none; white-space: normal; word-break: break-word; }}
      .trend-chart-box, .comp-trend-box, .source-table-box {{ break-inside: avoid; page-break-inside: avoid; }}
      .echart-canvas {{ break-inside: avoid; page-break-inside: avoid; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <header class="hero">
      <span class="tag">{esc(hero_tag)}</span>
      <h1>{esc(brand_name)}</h1>
      <p>{esc(type_label)}</p>
      <p>统计周期：{esc(period_lbl)}</p>
      <p>对比基准：{esc(comparison['previous_period_label'])} · 生成日期 {generated:%Y-%m-%d}</p>
    </header>
    <main class="content">
      {render_preface_html(preface, client=v2)}
      {render_toc_html(content_modules.get("toc") or [])}
      {demo_note}
      <section id="kpi">
      <h2>核心指标 · 环比上一周期</h2>
      {sample_meta}
      <div class="kpi-grid">{kpi_html}</div>
      {'<p class="warn">' + esc(sample_warn) + '</p>' if sample_warn else ''}
      </section>

      <section id="conclusions">
      <h2>核心结论</h2>
      <ul>{highlight_items or '<li>暂无环比结论</li>'}</ul>
      </section>

      {render_trend_html(trend, echarts_src=echarts_src)}

      {render_keyword_html(keyword_analytics, report_type=report_type, client=v2)}

      {render_competitor_html(competitor_analytics, report_type=report_type, client=v2)}

      <section id="platform">
      <h2>分平台排名与提及率对比</h2>
      <table>
        <thead>
          <tr>
            <th>平台</th><th>上期排名</th><th>本期排名</th><th>排名变化</th>
            <th>上期提及率</th><th>本期提及率</th><th>提及率变化</th><th>本期样本</th>
          </tr>
        </thead>
        <tbody>{platform_rows or '<tr><td colspan="8">暂无分平台数据</td></tr>'}</tbody>
      </table>
      </section>

      {tail_sections}

      {'<p class="note">' + esc(foot_note) + '</p>' if foot_note else ''}
      <p class="foot">{esc(foot_brand)}</p>
    </main>
  </div>
</body>
</html>"""


def wrap_period_html_for_word(html: str) -> bytes:
    """ponytail: Word 可直接打开的 HTML 包装，保留环比模板样式与表格。"""
    if "<head>" in html:
        enriched = html.replace(
            "<head>",
            "<head><meta name=\"ProgId\" content=\"Word.Document\">"
            "<meta name=\"Generator\" content=\"GEO Monitor\">",
            1,
        )
    else:
        enriched = html
    return enriched.encode("utf-8")


def _parse_report_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def compose_period_report_html(
    db: Session,
    *,
    tenant_id: int,
    report_type: str,
    period_start: date,
    period_end: date,
    generated: date | None = None,
    echarts_src: str | None = None,
) -> str:
    """正式导出：V2 环比模板，仅使用真实监测数据（不注入演示增强）。"""
    from app.services.report_service import build_tenant_monitor_snapshot

    if report_type not in PERIOD_EXPORT_TYPES:
        raise ValueError(f"unsupported report type: {report_type}")

    prev_start, prev_end = previous_period_bounds(report_type, period_start, period_end)
    lbl = period_label(report_type, period_start, period_end)
    prev_lbl = period_label(report_type, prev_start, prev_end)

    current = build_tenant_monitor_snapshot(db, tenant_id, start_date=period_start, end_date=period_end)
    brand_name = str(current.get("brand_name") or "")
    previous = build_tenant_monitor_snapshot(db, tenant_id, start_date=prev_start, end_date=prev_end)
    all_keywords = collect_tenant_monitor_keywords(db, tenant_id)
    platform_codes = _resolve_platform_codes(current)

    comparison = build_comparison(
        report_type,
        current,
        previous,
        prev_lbl,
        used_demo_previous=False,
        allow_demo_fallback=False,
    )
    competitors = [item.name for item in list_competitors(db, tenant_id) if item.name]
    keyword_analytics = build_keyword_analytics(
        db,
        tenant_id,
        start=period_start,
        end=period_end,
        prev_start=prev_start,
        prev_end=prev_end,
    )
    content_modules = build_sample_content_modules(
        brand_name=brand_name,
        snapshot=current,
        report_type=report_type,
        period_lbl=lbl,
        period_start=period_start,
        period_end=period_end,
        competitor_names=competitors,
        v2=True,
    )
    preface = polish_preface_for_client_v2(
        build_preface(
            modules=content_modules,
            report_type=report_type,
            previous_period_label=prev_lbl,
            monitor_keywords=all_keywords,
        ),
        brand_name=brand_name,
    )
    content_modules = polish_content_modules_for_client_v2(
        content_modules,
        brand_name=brand_name,
        report_type=report_type,
        period_range=str(preface.get("period_range") or lbl),
        completed=int((current.get("kpis") or {}).get("completed_count") or 0),
        platform_count=int(current.get("platform_count") or len(platform_codes)),
    )
    trend = build_period_trend(db, tenant_id, report_type, period_start, period_end)
    competitor_analytics = build_competitor_analytics_from_periods(
        db,
        tenant_id=tenant_id,
        brand_name=brand_name,
        competitor_names=competitors,
        report_type=report_type,
        trend=trend,
        cur_start=period_start,
        cur_end=period_end,
        prev_start=prev_start,
        prev_end=prev_end,
    )

    return render_html(
        brand_name=brand_name,
        report_type=report_type,
        period_lbl=lbl,
        comparison=comparison,
        snapshot=current,
        preface=preface,
        content_modules=content_modules,
        trend=trend,
        keyword_analytics=keyword_analytics,
        competitor_analytics=competitor_analytics,
        generated=generated or date.today(),
        v2=True,
        echarts_src=echarts_src or ECHARTS_PORTAL_SRC,
    )


def build_period_report_html_for_export(
    db: Session,
    report: dict[str, Any],
    *,
    tenant_id: int,
) -> str:
    report_type = str(report.get("report_type") or "")
    period_start = _parse_report_date(report.get("period_start"))
    period_end = _parse_report_date(report.get("period_end"))
    if period_start is None or period_end is None:
        raise ValueError("period report missing period_start/period_end")
    generated = _parse_report_date(report.get("generated_at")) or date.today()
    html_text = compose_period_report_html(
        db,
        tenant_id=tenant_id,
        report_type=report_type,
        period_start=period_start,
        period_end=period_end,
        generated=generated,
    )
    # 预览(blob)/下载 HTML/PDF 共用：内联 echarts，不再依赖外链
    return inline_echarts_scripts(html_text)


def generate_one(db, tenant_id: int, brand_name: str, report_type: str, today: date, *, v2: bool = False) -> Path:
    from app.services.report_service import build_tenant_monitor_snapshot

    trigger = schedule_trigger_for_sample(report_type, today)
    start, end = period_bounds(report_type, trigger)
    prev_start, prev_end = previous_period_bounds(report_type, start, end)
    lbl = period_label(report_type, start, end)
    prev_lbl = period_label(report_type, prev_start, prev_end)

    current = build_tenant_monitor_snapshot(db, tenant_id, start_date=start, end_date=end)
    brand_name = current.get("brand_name") or brand_name
    previous = build_tenant_monitor_snapshot(db, tenant_id, start_date=prev_start, end_date=prev_end)
    all_keywords = collect_tenant_monitor_keywords(db, tenant_id)
    platform_codes = _resolve_platform_codes(current)

    current = enrich_snapshot(current, report_type=report_type, platform_codes=platform_codes)
    previous = enrich_previous_snapshot(previous, report_type=report_type, platform_codes=platform_codes)
    comparison = build_comparison(report_type, current, previous, prev_lbl, used_demo_previous=False)
    competitors = [item.name for item in list_competitors(db, tenant_id) if item.name]
    keyword_analytics = enrich_keyword_analytics(
        build_keyword_analytics(
            db,
            tenant_id,
            start=start,
            end=end,
            prev_start=prev_start,
            prev_end=prev_end,
        ),
        keywords=all_keywords,
        platform_codes=platform_codes,
        report_type=report_type,
    )
    content_modules = build_sample_content_modules(
        brand_name=brand_name,
        snapshot=current,
        report_type=report_type,
        period_lbl=lbl,
        period_start=start,
        period_end=end,
        competitor_names=competitors,
        v2=v2,
    )
    preface = build_preface(
        modules=content_modules,
        report_type=report_type,
        previous_period_label=prev_lbl,
        monitor_keywords=all_keywords,
    )
    if v2:
        preface = polish_preface_for_client_v2(preface, brand_name=brand_name)
        content_modules = polish_content_modules_for_client_v2(
            content_modules,
            brand_name=brand_name,
            report_type=report_type,
            period_range=str(preface.get("period_range") or lbl),
            completed=int((current.get("kpis") or {}).get("completed_count") or 0),
            platform_count=int(current.get("platform_count") or len(platform_codes)),
        )
    trend = enrich_trend(
        build_period_trend(db, tenant_id, report_type, start, end),
        report_type=report_type,
    )
    brand_mr = float((current.get("kpis") or {}).get("mention_rate") or 0)
    competitor_analytics = enrich_competitor_analytics(
        brand_name=brand_name,
        competitor_names=competitors,
        report_type=report_type,
        trend=trend,
        brand_mention_rate=brand_mr,
    )

    prefix = {"weekly": "周报", "monthly": "月报", "quarterly": "季报", "annual": "年报"}[report_type]
    safe_brand = "".join(c if c.isalnum() or c in "._-" else "_" for c in brand_name)[:40]
    suffix = "_V2" if v2 else ""
    out = OUT_DIR / f"{safe_brand}_{prefix}_环比样例_{start:%Y%m%d}{suffix}.html"
    echarts_src = ensure_echarts_asset(OUT_DIR) if v2 else ECHARTS_CDN
    out.write_text(
        render_html(
            brand_name=brand_name,
            report_type=report_type,
            period_lbl=lbl,
            comparison=comparison,
            snapshot=current,
            preface=preface,
            content_modules=content_modules,
            trend=trend,
            keyword_analytics=keyword_analytics,
            competitor_analytics=competitor_analytics,
            generated=today,
            v2=v2,
            echarts_src=echarts_src,
        ),
        encoding="utf-8",
    )
    return out
