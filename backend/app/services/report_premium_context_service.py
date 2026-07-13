"""Premium 深色简报 PDF 模板上下文构建（8 大模块）。"""

from __future__ import annotations

import base64
from datetime import date, datetime
from typing import Any

from app.services.molizhishu_catalog_service import get_supported_platform_catalog
from app.services.report_chart_service import (
    build_platform_mention_chart,
    build_rank_trend_chart,
    build_sentiment_pie_chart,
    build_source_bar_chart,
)
from app.services.report_period_content_service import (
    REPORT_MODULE_SCHEMA_VERSION,
    build_premium_content,
    build_report_modules,
    format_diagnosis_display_title,
    merge_report_sections,
    normalize_sentiment_counts,
    sentiment_summary_from_counts,
    _normalize_sentiment_layers,
    sanitize_report_modules_for_type,
)

REPORT_TYPE_LABELS = {
    "diagnosis": "企业诊断",
    "weekly": "监测周报",
    "monthly": "监测月报",
    "quarterly": "监测季报",
    "annual": "监测年报",
    "comparison": "对比报告",
}


def _format_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return moment.strftime("%Y年%m月%d日")
    except ValueError:
        return text[:10]


def _b64_png(data: bytes | None) -> str | None:
    if not data:
        return None
    return f"data:image/png;base64,{base64.b64encode(data).decode('ascii')}"


def _parse_iso_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _sentiment_dict(payload: dict[str, Any]) -> dict[str, int]:
    direct = payload.get("sentiment_counts")
    if isinstance(direct, dict) and direct:
        return normalize_sentiment_counts({str(k): int(v) for k, v in direct.items()})
    snapshot_sentiment = (payload.get("monitor_snapshot") or {}).get("sentiment_counts")
    if isinstance(snapshot_sentiment, dict):
        return normalize_sentiment_counts({str(k): int(v) for k, v in snapshot_sentiment.items()})
    return {}


def _refresh_sentiment_module(
    modules: dict[str, Any],
    *,
    payload: dict[str, Any],
    sentiment_counts: dict[str, int],
) -> dict[str, Any]:
    """导出时按统一中文键重算情绪模块，修复售前诊断英文键导致的左侧 0 条。"""
    if not sentiment_counts:
        return modules.get("sentiment") or {}
    diagnosis = payload.get("diagnosis") or {}
    kpis = payload.get("kpis") or {}
    completed = int(
        payload.get("completed_count")
        or kpis.get("completed_count")
        or sum(sentiment_counts.values())
        or 0
    )
    layers = _normalize_sentiment_layers(
        completed=completed,
        sentiment_counts=sentiment_counts,
        positive_rate=kpis.get("positive_rate") or payload.get("positive_rate"),
        diagnosis=diagnosis,
    )
    return {
        "total_samples": sum(sentiment_counts.values()) or completed,
        "layers": layers,
        "summary": sentiment_summary_from_counts(sentiment_counts, diagnosis=diagnosis),
    }


def _ensure_report_modules(payload: dict[str, Any]) -> dict[str, Any]:
    stored = payload.get("report_modules") or {}
    premium = payload.get("premium_content") or {}
    if stored.get("schema_version") == REPORT_MODULE_SCHEMA_VERSION:
        return stored
    if (premium.get("modules") or {}).get("schema_version") == REPORT_MODULE_SCHEMA_VERSION:
        return premium["modules"]

    diagnosis = payload.get("diagnosis") or {}
    return build_report_modules(
        brand_name=str(payload.get("brand_name") or ""),
        company_name=str(payload.get("company_name") or "") or None,
        report_type=str(payload.get("report_type") or "monthly"),
        period_label=str(payload.get("period_label") or ""),
        period_start=_parse_iso_date(payload.get("period_start")),
        period_end=_parse_iso_date(payload.get("period_end")),
        kpis={
            "mention_rate": payload.get("mention_rate"),
            "avg_rank": payload.get("avg_rank"),
            "top3_rate": payload.get("top3_rate"),
            "positive_rate": payload.get("positive_rate"),
            "completed_count": payload.get("completed_count"),
            "source_count": payload.get("source_count"),
            "health_score": payload.get("health_score"),
        },
        platform_stats=list(payload.get("platform_stats") or []),
        sentiment_counts=_sentiment_dict(payload),
        top_sources=list(payload.get("top_sources") or []),
        competitor_names=list(payload.get("competitors") or []),
        diagnosis=diagnosis,
        highlights=list(payload.get("highlights") or []),
    )


def build_premium_report_context(payload: dict[str, Any]) -> dict[str, Any]:
    report_type = str(payload.get("report_type") or "")
    diagnosis = payload.get("diagnosis") or {}
    modules = sanitize_report_modules_for_type(_ensure_report_modules(payload), report_type)
    type_label = payload.get("type_label") or REPORT_TYPE_LABELS.get(report_type, "监测报告")
    health_score = payload.get("health_score") or diagnosis.get("health_score")

    sentiment_counts = _sentiment_dict(payload)
    modules = dict(modules)
    modules["sentiment"] = _refresh_sentiment_module(
        modules,
        payload=payload,
        sentiment_counts=sentiment_counts,
    )
    rank_chart = _b64_png(build_rank_trend_chart(list(payload.get("rank_trend") or [])))
    platform_chart = _b64_png(build_platform_mention_chart(list(payload.get("platform_stats") or [])))
    sentiment_chart = _b64_png(build_sentiment_pie_chart(sentiment_counts or {
        layer["label"]: layer["count"] for layer in modules.get("sentiment", {}).get("layers", [])
    }))
    source_chart = _b64_png(build_source_bar_chart(list(payload.get("top_sources") or [])))

    executive = (
        payload.get("executive_summary")
        or modules.get("overview", {}).get("interpretations", [{}])[0].get("body")
        or ""
    )

    title = payload.get("title") or modules.get("preface", {}).get("report_title") or "GEO 监测报告"
    if report_type == "diagnosis":
        title = format_diagnosis_display_title(title)

    return {
        "title": title,
        "type_label": type_label,
        "report_type": report_type,
        "brand_name": payload.get("brand_name") or "",
        "company_name": payload.get("company_name") or payload.get("brand_name") or "",
        "period_label": payload.get("period_label") or "",
        "generated_at": _format_timestamp(payload.get("generated_at")),
        "summary": payload.get("summary") or "",
        "health_score": health_score,
        "completed_count": payload.get("completed_count"),
        "positive_rate": payload.get("positive_rate"),
        "executive_summary": executive,
        "highlights": list(payload.get("highlights") or modules.get("highlights") or [])[:6],
        "modules": modules,
        "preface": modules.get("preface") or {},
        "overview": modules.get("overview") or {},
        "sentiment": modules.get("sentiment") or {},
        "platform_benchmark": modules.get("platform_benchmark") or {},
        "competitor_analysis": modules.get("competitor_analysis") or {},
        "source_influence": modules.get("source_influence") or {},
        "risk_and_strategy": modules.get("risk_and_strategy") or {},
        "action_plan": modules.get("action_plan") or {},
        "disclaimer": modules.get("disclaimer") or {},
        "toc": modules.get("toc") or [],
        "charts": {
            "rank_trend": rank_chart,
            "platform_mention": platform_chart,
            "sentiment_pie": sentiment_chart,
            "source_bar": source_chart,
        },
        "footer_note": "本报告由 GEO Monitor 监测引擎输出，数据来源于多平台 AI 回答抓取与交叉验证。",
    }


def enrich_export_payload_for_premium(payload: dict[str, Any], *, report_type: str | None = None) -> dict[str, Any]:
    enriched = dict(payload)
    if report_type:
        enriched["report_type"] = report_type
    modules = _ensure_report_modules(enriched)
    enriched["report_modules"] = modules
    enriched["report_sections"] = merge_report_sections(
        ai_sections=enriched.get("report_sections"),
        rule_sections=modules.get("legacy_sections") or {},
    )
    enriched["premium_content"] = build_premium_content(
        brand_name=str(enriched.get("brand_name") or ""),
        company_name=str(enriched.get("company_name") or "") or None,
        report_type=str(enriched.get("report_type") or "monthly"),
        period_label=str(enriched.get("period_label") or ""),
        kpis={
            "mention_rate": enriched.get("mention_rate"),
            "avg_rank": enriched.get("avg_rank"),
            "top3_rate": enriched.get("top3_rate"),
            "positive_rate": enriched.get("positive_rate"),
            "completed_count": enriched.get("completed_count"),
            "health_score": enriched.get("health_score"),
        },
        platform_stats=list(enriched.get("platform_stats") or []),
        diagnosis=enriched.get("diagnosis") or {},
        report_sections=enriched["report_sections"],
        executive_summary=enriched.get("executive_summary"),
        highlights=list(enriched.get("highlights") or []),
        report_modules=modules,
        period_start=_parse_iso_date(enriched.get("period_start")),
        period_end=_parse_iso_date(enriched.get("period_end")),
        sentiment_counts=_sentiment_dict(enriched),
        top_sources=list(enriched.get("top_sources") or []),
    )
    if not enriched.get("executive_summary"):
        enriched["executive_summary"] = enriched["premium_content"].get("visibility_summary")
    return enriched
