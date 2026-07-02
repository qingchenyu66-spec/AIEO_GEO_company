"""报告 AI 增强——DeepSeek 撰写结论，失败时回退规则模板。"""

from __future__ import annotations

import logging
from typing import Any

from app.services.deepseek_client import DeepseekApiError, DeepseekClient

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
) -> tuple[list[str], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """返回 highlights、diagnosis 块、ai_insights 元数据、更新后的 kpis。"""
    kpis = dict(snapshot.get("kpis") or {})
    rule_highlights = list(snapshot.get("highlights") or [])
    names = [name for name in (competitor_names or []) if name]

    diagnosis_block: dict[str, Any] = {
        "health_score": (existing_diagnosis or {}).get("health_score") or kpis.get("health_score"),
        "sentiment_summary": (existing_diagnosis or {}).get("sentiment_summary"),
        "strength_points": (existing_diagnosis or {}).get("strength_points"),
        "weakness_points": (existing_diagnosis or {}).get("weakness_points"),
        "recommendation": (existing_diagnosis or {}).get("recommendation"),
        "diagnosis_title": (existing_diagnosis or {}).get("diagnosis_title"),
    }
    highlights = rule_highlights
    ai_insights: dict[str, Any] = {"source": "rule"}

    client = DeepseekClient()
    if not client.report_enabled:
        return highlights, diagnosis_block, ai_insights, kpis

    try:
        insights = client.generate_report_insights(
            brand_name=brand_name,
            company_name=company_name,
            report_type=report_type,
            period_label=period_label,
            kpis=kpis,
            platform_stats=list(snapshot.get("platform_stats") or []),
            sentiment_counts=dict(snapshot.get("sentiment_counts") or {}),
            top_sources=list(snapshot.get("top_sources") or []),
            competitor_names=names,
            rule_highlights=rule_highlights,
        )
    except DeepseekApiError as exc:
        logger.warning("DeepSeek 报告生成失败，回退规则模板：%s", exc)
        ai_insights["source"] = "rule"
        ai_insights["fallback_reason"] = str(exc)
        return highlights, diagnosis_block, ai_insights, kpis

    highlights = insights.get("highlights") or rule_highlights
    ai_insights = {
        "source": "deepseek",
        "model": client.model,
        "executive_summary": insights.get("executive_summary"),
    }

    for key in ("sentiment_summary", "strength_points", "weakness_points", "recommendation"):
        value = insights.get(key)
        if value:
            diagnosis_block[key] = value

    if diagnosis_block.get("health_score") is None and insights.get("health_score") is not None:
        diagnosis_block["health_score"] = insights["health_score"]
        kpis["health_score"] = insights["health_score"]

    return highlights, diagnosis_block, ai_insights, kpis
