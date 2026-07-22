"""模力指数风格售前诊断报告 HTML 上下文（1:1 参考模板）。"""

from __future__ import annotations

import base64
import time
from datetime import datetime
from typing import Any

from app.services.molizhishu_catalog_service import get_supported_platform_catalog
from app.services.report_premium_font_service import build_font_face_css
from app.services.report_competitor_visuals import build_competitor_analysis
from app.services.report_chart_service import build_entity_rank_trend_chart, build_rank_trend_chart
from app.services.report_molizhishu_fragments import (
    render_analysis_html,
    render_competitor_landscape_table,
    render_competitor_strategy,
    render_diagnosis_swot,
    render_executive_block,
    render_insight_paragraph,
    render_kpi_overview,
    render_matrix_table,
    render_mention_table,
    render_platform_stats_table,
    render_prompt_comment,
    render_prompt_platform_matrix,
    render_prompt_scorecard,
    render_ranking_table,
    render_sentiment_overview,
    render_tip_list,
)


def _b64_png(data: bytes | None) -> str | None:
    if not data:
        return None
    return f"data:image/png;base64,{base64.b64encode(data).decode('ascii')}"


def _format_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return moment.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return text[:19]


def _format_footer_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return f"{moment.year}/{moment.month}/{moment.day} {moment.strftime('%H:%M:%S')}"
    except ValueError:
        now = datetime.now()
        return f"{now.year}/{now.month}/{now.day} {now.strftime('%H:%M:%S')}"


def _platform_label(platform_stats: list[dict[str, Any]], platform_names: dict[str, str]) -> str:
    if not platform_stats:
        return "DeepSeek"
    count = len(platform_stats)
    top = max(platform_stats, key=lambda row: float(row.get("completed") or row.get("total") or 0))
    code = str(top.get("platform") or "")
    top_name = platform_names.get(code) or code or "DeepSeek"
    if count <= 1:
        return top_name
    return f"{top_name} 等 {count} 个平台"


def _period_range_label(period_label: str) -> str:
    text = str(period_label or "").strip()
    if "至" in text:
        head = text.split("·", 1)[0].strip()
        if "至" in head:
            return head
    if "起" in text:
        return text.split("起", 1)[0].strip()
    return text or "—"


def _competitor_label(competitors: list[Any]) -> str:
    cleaned = [str(item).strip() for item in competitors if str(item).strip()]
    return "、".join(cleaned) if cleaned else "未指定竞品"


def _comment_map(enrichment: dict[str, Any]) -> dict[str, str]:
    return {
        str(row.get("prompt") or ""): str(row.get("comment") or "").strip()
        for row in enrichment.get("prompt_commentaries") or []
        if str(row.get("prompt") or "").strip()
    }


_DECK_CHART_FIGSIZE = (16.5, 8.2)


def _chart_entity_names(
    *,
    brand: str,
    competitors: list[Any],
    tracked_entities: list[str],
) -> list[str]:
    names: list[str] = []
    for raw in [brand, *tracked_entities, *[str(item).strip() for item in competitors]]:
        name = str(raw or "").strip()
        if name and name not in names:
            names.append(name)
    return names[:8]


def _build_chart_slides(
    *,
    rank_trend: list[dict[str, Any]],
    prompt_analytics: list[dict[str, Any]],
    brand: str,
    competitors: list[Any],
    tracked_entities: list[str],
) -> list[dict[str, str]]:
    """一图一页：总趋势 + 各语义词趋势（含竞品折线）。"""
    entities = _chart_entity_names(
        brand=brand,
        competitors=competitors,
        tracked_entities=tracked_entities,
    )
    slides: list[dict[str, str]] = []
    overall = _b64_png(
        build_entity_rank_trend_chart(
            rank_trend,
            brand=brand,
            tracked_entities=entities,
            title="",
            subtitle=None,
            figsize=_DECK_CHART_FIGSIZE,
        )
        or build_rank_trend_chart(rank_trend)
    )
    if overall:
        slides.append(
            {
                "title": "平均排名趋势图",
                "subtitle": "品牌及竞品平均排名",
                "src": overall,
            }
        )
    for index, block in enumerate(prompt_analytics, start=1):
        prompt = str(block.get("prompt") or "").strip()
        src = _b64_png(
            build_entity_rank_trend_chart(
                block.get("round_trend") or [],
                brand=brand,
                tracked_entities=entities,
                title="",
                subtitle=None,
                figsize=_DECK_CHART_FIGSIZE,
            )
        )
        if src:
            slides.append(
                {
                    "title": f"问题{index}趋势图",
                    "subtitle": prompt,
                    "src": src,
                }
            )
    return slides


def build_molizhishu_report_context(payload: dict[str, Any], platform_names: dict[str, str] | None = None) -> dict[str, Any]:
    platform_names = platform_names or {
        str(item.get("code") or ""): str(item.get("name") or item.get("code") or "")
        for item in get_supported_platform_catalog()
    }
    brand = str(payload.get("brand_name") or payload.get("tenant_name") or "")
    competitors = payload.get("competitors") or []
    prompt_analytics = payload.get("prompt_analytics") or []
    platform_stats = payload.get("platform_stats") or []
    sections = payload.get("report_sections") or {}
    enrichment = payload.get("report_enrichment") or {}
    if not enrichment and prompt_analytics:
        from app.services.report_enrichment_service import build_report_enrichment

        enrichment = build_report_enrichment(
            brand=brand,
            competitors=[str(item).strip() for item in competitors if str(item).strip()],
            prompt_analytics=prompt_analytics,
            matrix_rows=payload.get("matrix_rows") or [],
            platform_stats=platform_stats,
            platform_names=platform_names,
            source_analysis=payload.get("source_analysis") or {},
            top_sources=payload.get("top_sources") or [],
            subtasks=[],
            sentiment_counts=payload.get("sentiment_counts") or {},
            positive_rate=payload.get("positive_rate") or 0,
        )
    diagnosis = payload.get("diagnosis") or {}
    sentiment_counts = enrichment.get("sentiment_counts") or payload.get("sentiment_counts") or {}
    generated_at = _format_timestamp(payload.get("generated_at"))
    platform_label = _platform_label(platform_stats, platform_names)
    period_range = _period_range_label(payload.get("period_label") or "")
    ts_suffix = str(int(time.time() * 1000))
    comments = _comment_map(enrichment)

    date_matrix = payload.get("brand_date_matrix") or {}
    city_matrix = payload.get("brand_city_matrix") or {}
    if not date_matrix.get("rows"):
        prompts = [str(row.get("prompt") or "") for row in prompt_analytics if row.get("prompt")]
        date_matrix = {"prompts": prompts, "rows": []}

    ranking_blocks = []
    for index, block in enumerate(prompt_analytics, start=1):
        prompt = str(block.get("prompt") or "")
        rows = block.get("molizhishu_ranking_rows") or []
        if not prompt:
            continue
        ranking_blocks.append(
            {
                "index": index,
                "prompt": prompt,
                "comment_html": render_prompt_comment(comments.get(prompt)),
                "table_id": f"rank-list-{prompt}",
                "table_html": render_ranking_table(f"rank-list-{prompt}", rows),
            }
        )

    mention_blocks = []
    for index, block in enumerate(prompt_analytics, start=1):
        prompt = str(block.get("prompt") or "")
        table = block.get("mention_table") or []
        if not prompt:
            continue
        mention_blocks.append(
            {
                "index": index,
                "prompt": prompt,
                "comment_html": render_prompt_comment(comments.get(prompt)),
                "table_id": f"report-list2-{prompt}",
                "table_html": render_mention_table(
                    f"report-list2-{prompt}",
                    [
                        {
                            "name": row.get("name"),
                            "sample_count": row.get("sample_count"),
                            "mention_count": row.get("mention_count"),
                            "mention_rate": row.get("mention_rate"),
                            "is_brand": row.get("is_brand"),
                        }
                        for row in sorted(table, key=lambda item: float(item.get("mention_rate") or 0), reverse=True)
                    ],
                ),
            }
        )

    source_analysis = payload.get("source_analysis") or {}
    top_sources = payload.get("top_sources") or []
    source_top_html = ""
    if top_sources:
        from app.services.report_text_sanitize import consolidate_top_sources

        rows = "".join(
            f"<tr><td>{idx}</td><td>{row.get('title') or '—'}</td><td>{row.get('count') or 0}</td></tr>"
            for idx, row in enumerate(consolidate_top_sources(top_sources, limit=20), start=1)
        )
        source_top_html = (
            '<table class="report-table"><thead><tr><th>#</th><th>信源标题</th><th>引用次数</th></tr></thead>'
            f"<tbody>{rows}</tbody></table>"
        )
    domain_stats = list(source_analysis.get("domain_stats") or [])
    domain_map_slides: list[dict[str, Any]] = []
    _DOMAIN_CHUNK = 14
    if domain_stats:
        chunks: list[list[Any]] = [
            domain_stats[start : start + _DOMAIN_CHUNK]
            for start in range(0, len(domain_stats), _DOMAIN_CHUNK)
        ]
        # 尾页过短（≤3 行）并回上一页，避免单独占一页
        if len(chunks) >= 2 and len(chunks[-1]) <= 3:
            chunks[-2].extend(chunks[-1])
            chunks.pop()
        page_total = len(chunks)
        for page_no, chunk in enumerate(chunks, start=1):
            rows = "".join(
                f"<tr><td>{row.get('domain') or '—'}</td>"
                f"<td>{row.get('count') or 0}</td>"
                f"<td>{row.get('brand_related_count') or 0}</td></tr>"
                for row in chunk
            )
            domain_map_slides.append(
                {
                    "title": (
                        "品牌平均排名与引用网站映射关系"
                        if page_total == 1
                        else f"品牌平均排名与引用网站映射关系 ({page_no}/{page_total})"
                    ),
                    "html": (
                        '<table class="report-table RankTable domain-map-table">'
                        "<thead><tr><th>域名</th><th>引用次数</th><th>品牌相关引用</th></tr></thead>"
                        f"<tbody>{rows}</tbody></table>"
                    ),
                }
            )

    highlights = payload.get("highlights") or []
    if not highlights:
        highlights = diagnosis.get("highlights") or []

    contact_label = str(payload.get("contact_phone") or payload.get("contact_name") or "").strip()
    competitor_rows = enrichment.get("competitor_landscape") or []
    competitor_analysis = build_competitor_analysis(
        brand_name=brand,
        rows=competitor_rows,
        platform_stats=[
            {
                **row,
                "name": platform_names.get(str(row.get("platform") or "")) or row.get("platform"),
            }
            for row in platform_stats
        ],
        prompt_analytics=prompt_analytics,
    )

    return {
        "page_title": f"AI搜索平台品牌分析报告_{brand}_{platform_label}_{ts_suffix}",
        "font_face_css": build_font_face_css(),
        "brand_name": brand,
        "competitor_text": _competitor_label(competitors),
        "contact_label": contact_label,
        "show_contact_meta": bool(contact_label),
        "platform_label": platform_label,
        "period_range": period_range,
        "generated_at": generated_at,
        "footer_generated_at": _format_footer_timestamp(payload.get("generated_at")),
        "overview_kpi_html": render_kpi_overview(
            health_score=payload.get("health_score"),
            mention_rate=payload.get("mention_rate"),
            avg_rank=payload.get("avg_rank"),
            top3_rate=payload.get("top3_rate"),
            positive_rate=enrichment.get("positive_rate") or payload.get("positive_rate"),
            completed_count=payload.get("completed_count"),
            source_count=payload.get("source_count"),
        ),
        "overview_executive_html": render_executive_block(
            executive_summary=payload.get("executive_summary"),
            highlights=highlights if isinstance(highlights, list) else [],
        ),
        "overview_sentiment_html": render_sentiment_overview(
            sentiment_counts if isinstance(sentiment_counts, dict) else {},
            positive_rate=enrichment.get("positive_rate") or payload.get("positive_rate") or 0,
        ),
        "overview_swot_html": render_diagnosis_swot(
            strength_points=diagnosis.get("strength_points"),
            weakness_points=diagnosis.get("weakness_points"),
            recommendation=diagnosis.get("recommendation"),
        ),
        "overview_platform_html": render_platform_stats_table(platform_stats, platform_names),
        "overview_platform_insight_html": render_insight_paragraph(enrichment.get("platform_insight")),
        "overview_prompt_html": render_prompt_scorecard(prompt_analytics),
        "overview_competitor_html": render_competitor_landscape_table(
            competitor_rows
        ),
        "overview_competitor_strategy_html": render_competitor_strategy(competitor_analysis),
        "overview_matrix_html": render_prompt_platform_matrix(
            enrichment.get("prompt_platform_matrix") or {}
        ),
        "chart_slides": _build_chart_slides(
            rank_trend=payload.get("rank_trend") or [],
            prompt_analytics=prompt_analytics,
            brand=brand,
            competitors=competitors if isinstance(competitors, list) else [],
            tracked_entities=[str(item) for item in (payload.get("tracked_entities") or []) if str(item).strip()],
        ),
        "brand_recent_table_html": render_matrix_table(
            "t_divBrandRecent",
            "日期",
            date_matrix.get("prompts") or [],
            date_matrix.get("rows") or [],
        ),
        "brand_city_table_html": render_matrix_table(
            "t_divBrandCityRank",
            "城市",
            city_matrix.get("prompts") or [],
            city_matrix.get("rows") or [],
        ),
        "show_city_table": bool(city_matrix.get("rows")),
        "ranking_blocks": ranking_blocks,
        "mention_blocks": mention_blocks,
        "source_top_html": source_top_html,
        "domain_map_slides": domain_map_slides,
        "source_action_tips_html": render_tip_list(enrichment.get("source_action_tips") or []),
        "analysis_html": render_analysis_html(
            sections,
            analysis_html=payload.get("analysis_html"),
            priority_actions=enrichment.get("priority_actions") or [],
            # 信源建议单独成页，避免分析页重复
            source_action_tips=None,
        ),
    }
