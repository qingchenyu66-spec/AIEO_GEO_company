"""模力指数风格售前诊断报告 HTML 上下文（1:1 参考模板）。"""

from __future__ import annotations

import base64
import re
import time
from datetime import datetime
from typing import Any

from app.services.molizhishu_catalog_service import get_supported_platform_catalog
from app.services.report_premium_font_service import build_font_face_css
from app.services.report_competitor_visuals import build_competitor_analysis
from app.services.report_chart_service import (
    build_day_entity_grouped_bar,
    build_entity_rank_trend_chart,
    build_merged_rank_trend_panels,
    build_prompt_day_grouped_bar,
    build_rank_trend_chart,
)
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


def _platform_chips(platform_stats: list[dict[str, Any]], platform_names: dict[str, str]) -> list[str]:
    """封面平台芯片：完整列出，不缩写。"""
    if not platform_stats:
        return ["DeepSeek"]
    names: list[str] = []
    for row in platform_stats:
        code = str(row.get("platform") or "").strip()
        label = str(platform_names.get(code) or code or "").strip()
        if label and label not in names:
            names.append(label)
    return names or ["DeepSeek"]


def _platform_chip_rows(chips: list[str], *, per_row: int = 5) -> list[list[str]]:
    """封面平台：每行约 5 个，超出换行。"""
    cleaned = [str(x).strip() for x in chips if str(x).strip()]
    if not cleaned:
        return [["DeepSeek"]]
    n = max(int(per_row), 1)
    return [cleaned[i : i + n] for i in range(0, len(cleaned), n)]


def _platform_label(platform_stats: list[dict[str, Any]], platform_names: dict[str, str]) -> str:
    """兼容旧调用：顿号拼接。"""
    return "、".join(_platform_chips(platform_stats, platform_names))


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


_DECK_CHART_FIGSIZE = (16.5, 7.2)


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


def _fmt_rank(value: Any) -> str:
    if value is None or value == "":
        return "—"
    try:
        return f"{float(value):.1f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def _prompt_chart_kpis(block: dict[str, Any]) -> list[dict[str, str]]:
    """方案 C：问题趋势图顶部 KPI 条（样本 / 提及率 / 均排 / 走势）。"""
    sample = int(block.get("sample_count") or 0)
    try:
        rate_text = f"{float(block.get('brand_mention_rate')):.1f}%"
    except (TypeError, ValueError):
        rate_text = "—"

    ranks: list[float] = []
    for point in block.get("round_trend") or []:
        raw = point.get("avg_rank")
        if raw is None:
            continue
        try:
            ranks.append(float(raw))
        except (TypeError, ValueError):
            continue
    span = f"{_fmt_rank(ranks[0])} → {_fmt_rank(ranks[-1])}" if ranks else "—"

    return [
        {"label": "监测样本", "value": str(sample) if sample else "—"},
        {"label": "品牌提及率", "value": rate_text},
        {"label": "平均排名", "value": _fmt_rank(block.get("brand_avg_rank"))},
        {"label": "均排走势", "value": span},
    ]


def _build_chart_slides(
    *,
    rank_trend: list[dict[str, Any]],
    prompt_analytics: list[dict[str, Any]],
    brand: str,
    competitors: list[Any],
    tracked_entities: list[str],
) -> list[dict[str, str]]:
    """图表两版：①时段折线（总趋势+各问题）；②三日柱状（竞品缺数标 0）。"""
    entities = _chart_entity_names(
        brand=brand,
        competitors=competitors,
        tracked_entities=tracked_entities,
    )
    slides: list[dict[str, str]] = []

    # —— 第一版：时段折线（全部 schedule 点，不做日均折叠）——
    overall_line = _b64_png(
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
    if overall_line:
        slides.append(
            {
                "title": "平均排名趋势图",
                "subtitle": "品牌及竞品平均排名（按抓取时段全量展示）",
                "src": overall_line,
            }
        )

    for index, block in enumerate(prompt_analytics, start=1):
        rows = list(block.get("round_trend") or [])
        if not rows:
            continue
        prompt = str(block.get("prompt") or "").strip() or f"问题{index}"
        png = _b64_png(
            build_entity_rank_trend_chart(
                rows,
                brand=brand,
                tracked_entities=entities,
                title="",
                subtitle=None,
                figsize=_DECK_CHART_FIGSIZE,
            )
        )
        if not png:
            continue
        slides.append(
            {
                "title": f"问题{index}趋势图",
                "prompt": prompt,
                "kpis": _prompt_chart_kpis(block),
                "src": png,
            }
        )

    # —— 第二版：三日柱状（昨晚版；缺竞品均位画 0）——
    overall_bar = _b64_png(
        build_day_entity_grouped_bar(
            rank_trend,
            brand=brand,
            tracked_entities=entities,
            title="三日品牌/竞品均位对照",
            figsize=_DECK_CHART_FIGSIZE,
        )
    )
    if overall_bar:
        from app.services.report_chart_service import aggregate_trend_by_day, _short_schedule_label

        day_caps = [
            _short_schedule_label(row.get("schedule_label") or row.get("schedule_key"))
            for row in aggregate_trend_by_day(rank_trend)
        ]
        day_caps = [d for d in day_caps if d]
        slides.append(
            {
                "title": "三日均位对照",
                "subtitle": "按自然日汇总 · 品牌与竞品均位（无数据系列显示为 0）",
                "src": overall_bar,
                "caption": ("监测日期：" + "  ·  ".join(day_caps)) if day_caps else "",
            }
        )

    prompt_bar = _b64_png(
        build_prompt_day_grouped_bar(
            prompt_analytics,
            brand=brand,
            title="分语义词三日品牌均位",
            figsize=_DECK_CHART_FIGSIZE,
        )
    )
    if prompt_bar:
        slides.append(
            {
                "title": "语义词三日对照",
                "subtitle": "五个语义词 × 三天本品牌均位（无数据日期显示为 0）",
                "src": prompt_bar,
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
    # 方案2：品牌 official_url + 竞品 website_url → 站名豁免（2b 用简称）
    official_site_labels = payload.get("official_site_labels")
    if not isinstance(official_site_labels, dict):
        from app.services.report_source_label_service import load_official_site_labels_for_brand

        official_site_labels = load_official_site_labels_for_brand(brand)
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
    # 旧诊断包 tips 偏少/过短：导出时用规则引擎补到约 10 条；LLM 长句优先，短句扩写后保留
    from app.services.report_enrichment_service import build_rule_source_tips

    _MIN_TIP_LEN = 55
    raw_tips = [str(x).strip() for x in (enrichment.get("source_action_tips") or []) if str(x).strip()]
    cleaned: list[str] = []
    for tip in raw_tips:
        tip = re.sub(r"^针对\s*", "", tip)
        tip = re.sub(r"^【(?:深度|广度|维度|策略)】\s*", "", tip)
        tip = re.sub(r"验收口径[:：]?\s*", "", tip)
        if not tip or "验收口径" in tip:
            continue
        if len(tip) < _MIN_TIP_LEN:
            tip = tip.rstrip("。；; ") + "；落地时写清场景词、品牌全称与可核验证据，便于模型直接摘录。"
        if tip not in cleaned:
            cleaned.append(tip)
    rule_tips = build_rule_source_tips(payload.get("source_analysis") or {}, payload.get("top_sources") or [])
    for tip in rule_tips:
        tip = re.sub(r"^针对\s*", "", tip)
        if tip and tip not in cleaned:
            cleaned.append(tip)
        if len(cleaned) >= 10:
            break
    enrichment["source_action_tips"] = cleaned[:10]
    enrichment.pop("analysis_action_tips", None)

    # 7B：页顶行动项规则凑满 8~10（LLM 条目优先，短板规则补齐）
    from app.services.report_enrichment_service import build_priority_actions, merge_priority_actions

    enrichment["priority_actions"] = merge_priority_actions(
        build_priority_actions(
            prompt_analytics,
            platform_stats,
            platform_names=platform_names,
            source_analysis=payload.get("source_analysis") or {},
        ),
        enrichment.get("priority_actions"),
        min_count=8,
        max_count=10,
    )

    generated_at = _format_timestamp(payload.get("generated_at"))
    platform_label = _platform_label(platform_stats, platform_names)
    platform_chips = _platform_chips(platform_stats, platform_names)
    platform_chip_rows = _platform_chip_rows(platform_chips, per_row=5)
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
        from app.services.lead_diagnosis_analytics import compact_ranking_rows_for_deck

        # R1：分类强制默认，按 (类型, 品牌) 聚合；保留最近/最优/最差
        rows = compact_ranking_rows_for_deck(rows, only_recent=False)
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
    source_overview_slides: list[dict[str, Any]] = []
    if top_sources:
        from html import escape as _esc

        from app.services.report_source_label_service import enrich_domain_rows
        from app.services.report_text_sanitize import consolidate_top_sources

        enriched_sources = enrich_domain_rows(
            list(consolidate_top_sources(top_sources, limit=20)),
            brand=brand,
            use_llm=True,
            official_site_labels=official_site_labels,
        )
        # 横版一页可稳妥放下约 14 行；旧值 7 会把 8~14 条硬拆成两页留白
        _SOURCE_CHUNK = 14
        chunks: list[list[Any]] = [
            enriched_sources[start : start + _SOURCE_CHUNK]
            for start in range(0, len(enriched_sources), _SOURCE_CHUNK)
        ]
        # 尾页能并回上一页就并（避免「半页空白」）
        while (
            len(chunks) >= 2
            and len(chunks[-2]) + len(chunks[-1]) <= _SOURCE_CHUNK
        ):
            chunks[-2].extend(chunks[-1])
            chunks.pop()
        page_total = len(chunks)
        for page_no, chunk in enumerate(chunks, start=1):
            rows = []
            for row in chunk:
                rows.append(
                    "<tr>"
                    f"<td>{_esc(str(row.get('site_cn') or '—'))}</td>"
                    f"<td>{_esc(str(row.get('category_label') or '其他'))}</td>"
                    f"<td>{_esc(str(row.get('title') or '—'))}</td>"
                    f"<td>{int(row.get('count') or 0)}</td>"
                    "</tr>"
                )
            source_overview_slides.append(
                {
                    "title": (
                        "采信网站概览"
                        if page_total == 1
                        else f"采信网站概览 ({page_no}/{page_total})"
                    ),
                    "html": (
                        '<table class="report-table source-overview-table">'
                        "<thead><tr><th>网站</th><th>类别</th>"
                        "<th>信源标题 / 域名</th><th>引用次数</th></tr></thead>"
                        f"<tbody>{''.join(rows)}</tbody></table>"
                    ),
                }
            )
    domain_stats = list(source_analysis.get("domain_stats") or [])
    domain_map_slides: list[dict[str, Any]] = []
    _DOMAIN_CHUNK = 14
    if domain_stats:
        from html import escape as _esc

        from app.services.report_source_label_service import enrich_domain_rows

        enriched_domains = enrich_domain_rows(
            list(domain_stats),
            brand=brand,
            use_llm=True,
            official_site_labels=official_site_labels,
        )
        chunks: list[list[Any]] = [
            enriched_domains[start : start + _DOMAIN_CHUNK]
            for start in range(0, len(enriched_domains), _DOMAIN_CHUNK)
        ]
        # 尾页过短并回上一页（合并后 ≤18，与 deck_pack domain 口径对齐）
        if len(chunks) >= 2 and len(chunks[-1]) <= 3 and len(chunks[-2]) + len(chunks[-1]) <= 18:
            chunks[-2].extend(chunks[-1])
            chunks.pop()
        page_total = len(chunks)
        for page_no, chunk in enumerate(chunks, start=1):
            rows = "".join(
                "<tr>"
                f"<td>{_esc(str(row.get('domain') or '—'))}</td>"
                f"<td>{_esc(str(row.get('site_cn') or '—'))}</td>"
                f"<td>{int(row.get('count') or 0)}</td>"
                f"<td>{int(row.get('brand_related_count') or 0)}</td>"
                "</tr>"
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
                        "<thead><tr><th>域名</th><th>网站</th><th>总引用次数</th><th>品牌相关引用</th></tr></thead>"
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
        "page_title": f"GEO优化平台品牌分析报告_{brand}_{platform_label}_{ts_suffix}",
        "font_face_css": build_font_face_css(),
        "brand_name": brand,
        "competitor_text": _competitor_label(competitors),
        "contact_label": contact_label,
        "show_contact_meta": bool(contact_label),
        "platform_label": platform_label,
        "platform_chips": platform_chips,
        "platform_chip_rows": platform_chip_rows,
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
        # 2026-08-10 - 售前诊断常仅「全部区域」一行，城市表无信息量；不下发
        "show_city_table": False,
        "ranking_blocks": ranking_blocks,
        "mention_blocks": mention_blocks,
        "source_overview_slides": source_overview_slides,
        "domain_map_slides": domain_map_slides,
        "source_action_tips_html": render_tip_list(enrichment.get("source_action_tips") or []),
        "analysis_html": render_analysis_html(
            sections,
            analysis_html=payload.get("analysis_html"),
            priority_actions=enrichment.get("priority_actions") or [],
            # tips 用于第5节凑满 8~10；独立「信源优化建议」页仍用 source_action_tips_html
            source_action_tips=enrichment.get("source_action_tips") or [],
        ),
    }
