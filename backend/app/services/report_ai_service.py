"""报告 AI 增强——DeepSeek 撰写结论，失败时回退规则模板。"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.services.deepseek_client import DeepseekApiError, DeepseekClient
from app.services.report_period_content_service import (
    ALL_RICH_REPORT_TYPES,
    build_periodic_report_sections,
    build_premium_content,
    build_report_modules,
    enrich_source_influence_with_llm,
    merge_report_modules,
    merge_report_sections,
)

logger = logging.getLogger(__name__)


def enrich_report_narrative(
    *,
    brand_name: str,
    company_name: str | None,
    report_type: str,
    period_label: str,
    snapshot: dict[str, Any],
    competitor_names: list[str] | None = None,
    existing_diagnosis: dict[str, Any] | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> tuple[list[str], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str], dict[str, Any], dict[str, Any] | None]:
    """返回 highlights、diagnosis、ai_insights、kpis、report_sections、premium_content、report_modules。"""
    kpis = dict(snapshot.get("kpis") or {})
    rule_highlights = list(snapshot.get("highlights") or [])
    names = [name for name in (competitor_names or []) if name]
    platform_stats = list(snapshot.get("platform_stats") or [])
    sentiment_counts = dict(snapshot.get("sentiment_counts") or {})
    top_sources = list(snapshot.get("top_sources") or [])

    diagnosis_block: dict[str, Any] = {
        "health_score": (existing_diagnosis or {}).get("health_score") or kpis.get("health_score"),
        "sentiment_summary": (existing_diagnosis or {}).get("sentiment_summary"),
        "strength_points": (existing_diagnosis or {}).get("strength_points"),
        "weakness_points": (existing_diagnosis or {}).get("weakness_points"),
        "recommendation": (existing_diagnosis or {}).get("recommendation"),
        "diagnosis_title": (existing_diagnosis or {}).get("diagnosis_title"),
    }
    highlights = rule_highlights
    ai_insights: dict[str, Any] = {}
    ai_report_sections: dict[str, str] | None = None
    ai_report_modules: dict[str, Any] | None = None
    report_modules: dict[str, Any] | None = None

    if report_type in ALL_RICH_REPORT_TYPES:
        report_modules = build_report_modules(
            brand_name=brand_name,
            company_name=company_name,
            report_type=report_type,
            period_label=period_label,
            period_start=period_start,
            period_end=period_end,
            kpis=kpis,
            platform_stats=platform_stats,
            sentiment_counts=sentiment_counts,
            top_sources=top_sources,
            competitor_names=names,
            diagnosis=diagnosis_block,
            highlights=rule_highlights,
        )

    rule_sections: dict[str, str] = {}
    if report_modules:
        rule_sections = dict(report_modules.get("legacy_sections") or {})
    elif report_type in ALL_RICH_REPORT_TYPES:
        rule_sections = build_periodic_report_sections(
            brand_name=brand_name,
            company_name=company_name,
            report_type=report_type,
            period_label=period_label,
            kpis=kpis,
            platform_stats=platform_stats,
            sentiment_counts=sentiment_counts,
            top_sources=top_sources,
            competitor_names=names,
        )

    client = DeepseekClient()
    if client.report_enabled:
        try:
            insights = client.generate_report_insights(
                brand_name=brand_name,
                company_name=company_name,
                report_type=report_type,
                period_label=period_label,
                kpis=kpis,
                platform_stats=platform_stats,
                sentiment_counts=sentiment_counts,
                top_sources=top_sources,
                competitor_names=names,
                rule_highlights=rule_highlights,
            )
        except DeepseekApiError as exc:
            logger.warning("报告智能撰写失败，回退规则模板：%s", exc)
        else:
            highlights = insights.get("highlights") or rule_highlights
            ai_insights = {
                "executive_summary": insights.get("executive_summary"),
                "highlights": highlights,
            }
            ai_report_sections = insights.get("report_sections")
            ai_report_modules = insights.get("report_modules")

            for key in ("sentiment_summary", "strength_points", "weakness_points", "recommendation"):
                value = insights.get(key)
                if value:
                    diagnosis_block[key] = value

            if diagnosis_block.get("health_score") is None and insights.get("health_score") is not None:
                diagnosis_block["health_score"] = insights["health_score"]
                kpis["health_score"] = insights["health_score"]

    if report_modules and ai_report_modules:
        report_modules = merge_report_modules(rule_modules=report_modules, ai_modules=ai_report_modules)

    if report_modules:
        # 2026-07-29 - 渠道价值拆解敷衍 - Premium/诊断路径同样用 LLM 覆盖拆解列
        report_modules = enrich_source_influence_with_llm(
            report_modules,
            brand_name=brand_name,
            period_label=period_label,
            top_sources=top_sources,
        )

    report_sections = merge_report_sections(ai_sections=ai_report_sections, rule_sections=rule_sections)
    if report_modules:
        report_modules = dict(report_modules)
        report_modules["legacy_sections"] = report_sections

    premium_content = build_premium_content(
        brand_name=brand_name,
        company_name=company_name,
        report_type=report_type,
        period_label=period_label,
        kpis=kpis,
        platform_stats=platform_stats,
        diagnosis=diagnosis_block,
        report_sections=report_sections,
        executive_summary=ai_insights.get("executive_summary"),
        highlights=highlights,
        report_modules=report_modules,
        sentiment_counts=sentiment_counts,
        top_sources=top_sources,
        competitor_names=names,
        period_start=period_start,
        period_end=period_end,
    )

    return highlights, diagnosis_block, ai_insights, kpis, report_sections, premium_content, report_modules
