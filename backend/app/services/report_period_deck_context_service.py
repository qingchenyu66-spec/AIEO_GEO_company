"""周期监测报告 16:9 幻灯上下文：环比模块 → 监测母版页。

母版页型（0727 导图）：
- cover / section / dark / thanks：1/2/4/6
- light（模版3）：表与正文
- light-wide（模版5）：趋势图、矩阵等宽内容
"""

from __future__ import annotations

import html
import re
from datetime import date
from typing import Any

from app.services.report_period_comparison_service import (
    TYPE_LABELS,
    _RANK_TREND_TYPES,
    _delta_class,
    _fmt_pct,
    _fmt_rank,
    build_v2_conclusions,
    platform_display_name,
    render_action_plan_html,
    render_competitor_html,
    render_disclaimer_html,
    render_keyword_html,
    render_keyword_platform_matrix_html,
    render_preface_html,
    render_risk_strategy_html,
    render_source_influence_html,
    render_trend_html,
    render_weekly_focus_html,
)
from app.services.report_premium_font_service import build_font_face_css

# 2026-07-28 - 周期报迁监测幻灯 - 预览/导出指纹用，改版式时 bump
# 2026-07-29 - v12：PDF 截图降采样；v13：PDF 复用预览 HTML（外链资源+route）
# 2026-07-29 - v18：矩阵页标题只留主标题，避免蓝条挤爆
# 2026-07-29 - v19：平台中文名 / 季年轴补 0 / Y 轴整数 / 信源图满宽
# 2026-07-29 - v20：竞品趋势放大字号+裁空周；信源 1 标对 1 柱
# 2026-07-29 - v21：信源结论外置防压扁叠标
# 2026-07-29 - v22：信源 TOP 改 HTML 条形榜（全文+渐变柱）
PERIOD_DECK_PIPELINE = "monitor-deck-v22"


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=False)


def _strip_outer_section(fragment: str) -> str:
    """去掉环比 HTML 最外层 <section>…</section>，便于塞进幻灯 overlay。"""
    text = (fragment or "").strip()
    if not text:
        return ""
    return re.sub(
        r"^<section\b[^>]*>|</section>\s*$",
        "",
        text,
        flags=re.I | re.S,
    ).strip()


def _strip_h2(fragment: str) -> str:
    return re.sub(r"<h2\b[^>]*>.*?</h2>", "", fragment or "", count=1, flags=re.I | re.S).strip()


def _drop_echarts_src(fragment: str) -> str:
    """幻灯 head 已内联 echarts；去掉片段里的外链 script。"""
    return re.sub(
        r'<script\s+src=["\'][^"\']*["\']\s*>\s*</script>',
        "",
        fragment or "",
        flags=re.I,
    )


def _split_before_table(fragment: str) -> tuple[str, str]:
    """把正文拆成「表前块 / 表及后续」，便于 pack 分页（图与表、摘要与竞品表）。"""
    text = fragment or ""
    match = re.search(r"<table\b", text, flags=re.I)
    if not match:
        return text.strip(), ""
    return text[: match.start()].strip(), text[match.start() :].strip()


def _platform_chip_rows(codes: list[str], *, per_row: int = 4) -> list[list[str]]:
    # 2026-07-29 - 封面 5 枚/行+34px 易叠行；改 4 列并配合 CSS 行距
    names = [platform_display_name(code) for code in codes if code]
    if not names:
        names = ["DeepSeek"]
    return [names[i : i + per_row] for i in range(0, len(names), per_row)]


def _prev_period_scope(report_type: str) -> str:
    return {
        "weekly": "上周",
        "monthly": "上月",
        "quarterly": "上季度",
        "annual": "上年度",
    }.get(report_type, "上一周期")


def _kpi_cards_html(comparison: dict[str, Any]) -> str:
    kpis = comparison.get("kpis") or {}

    def card(title: str, metric: dict[str, Any], fmt_prev, fmt_cur) -> str:
        cls = _delta_class(str(metric.get("direction") or "flat"))
        return (
            '<article class="kpi-card">'
            f'<span class="kpi-label">{_esc(title)}</span>'
            f'<strong class="kpi-value">{fmt_cur(metric.get("current"))}</strong>'
            f'<span class="kpi-prev">上期 {fmt_prev(metric.get("previous"))}</span>'
            f'<span class="kpi-delta {cls}">{_esc(metric.get("text") or "")}</span>'
            "</article>"
        )

    parts = [
        card(
            "综合健康分",
            kpis.get("health_score") or {},
            lambda v: str(int(v)) if v is not None else "—",
            lambda v: str(int(v)) if v is not None else "—",
        ),
        card("品牌提及率", kpis.get("mention_rate") or {}, _fmt_pct, _fmt_pct),
        card("平均推荐排名", kpis.get("avg_rank") or {}, _fmt_rank, _fmt_rank),
        card("Top3 露出率", kpis.get("top3_rate") or {}, _fmt_pct, _fmt_pct),
    ]
    return f'<div class="kpi-grid">{"".join(parts)}</div>'


def _conclusions_html(
    comparison: dict[str, Any],
    keyword_analytics: dict[str, Any],
    competitor_analytics: dict[str, Any],
) -> str:
    lines = build_v2_conclusions(comparison, keyword_analytics, competitor_analytics)
    if not lines:
        lines = list(comparison.get("highlights") or [])[:6]
    if not lines:
        return ""
    items = "".join(f"<li>{_esc(line)}</li>" for line in lines)
    return f'<ul class="conclusion-list">{items}</ul>'


def _platform_table_html(comparison: dict[str, Any]) -> str:
    rows_html = []
    for row in comparison.get("platform_rows") or []:
        mr = row.get("mention_rate") or {}
        ar = row.get("avg_rank") or {}
        rows_html.append(
            "<tr>"
            f"<td>{_esc(row.get('name'))}</td>"
            f"<td>{_esc(_fmt_rank(ar.get('previous')))}</td>"
            f"<td>{_esc(_fmt_rank(ar.get('current')))}</td>"
            f"<td><span class='delta {_delta_class(str(ar.get('direction') or 'flat'))}'>"
            f"{_esc(ar.get('text') or '')}</span></td>"
            f"<td>{_esc(_fmt_pct(mr.get('previous')))}</td>"
            f"<td>{_esc(_fmt_pct(mr.get('current')))}</td>"
            f"<td><span class='delta {_delta_class(str(mr.get('direction') or 'flat'))}'>"
            f"{_esc(mr.get('text') or '')}</span></td>"
            f"<td>{int(row.get('completed') or 0)}</td>"
            "</tr>"
        )
    if not rows_html:
        return '<p class="hint">暂无分平台环比数据。</p>'
    return (
        '<table class="report-table period-table">'
        "<thead><tr>"
        "<th>平台</th><th>上期排名</th><th>本期排名</th><th>排名环比</th>"
        "<th>上期提及率</th><th>本期提及率</th><th>提及环比</th><th>样本</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody></table>"
    )


def _sample_meta_html(comparison: dict[str, Any], snapshot: dict[str, Any]) -> str:
    snap_kpis = snapshot.get("kpis") or {}
    completed = int(snap_kpis.get("completed_count") or snap_kpis.get("subtask_count") or 0)
    if completed <= 0:
        metric = (comparison.get("kpis") or {}).get("completed_count") or {}
        completed = int(metric.get("current") or 0) if isinstance(metric, dict) else int(metric or 0)
    prev = _esc(comparison.get("previous_period_label") or "")
    warn = str(comparison.get("sample_warn") or "").replace("子任务", "样本")
    parts = [
        f'<p class="note sample-meta">本期有效监测样本 {completed} 条 · 对比周期 {prev}</p>'
    ]
    if warn:
        parts.append(f'<p class="warn">{_esc(warn)}</p>')
    return "".join(parts)


def build_period_deck_context(
    bundle: dict[str, Any],
    *,
    echarts_inline: str = "",
    echarts_src: str = "",
) -> dict[str, Any]:
    report_type = str(bundle.get("report_type") or "")
    brand = str(bundle.get("brand_name") or "品牌")
    period_lbl = str(bundle.get("period_lbl") or "")
    generated: date = bundle.get("generated") or date.today()
    comparison = bundle.get("comparison") or {}
    snapshot = bundle.get("snapshot") or {}
    preface = bundle.get("preface") or {}
    content_modules = bundle.get("content_modules") or {}
    trend = bundle.get("trend") or {}
    keyword_analytics = bundle.get("keyword_analytics") or {}
    competitor_analytics = bundle.get("competitor_analytics") or {}
    competitors = [str(x) for x in (bundle.get("competitors") or []) if str(x).strip()]
    platform_codes = list(bundle.get("platform_codes") or [])

    type_label = TYPE_LABELS.get(report_type, "GEO 监测报告")
    generated_at = generated.strftime("%Y-%m-%d")
    prev_scope = _prev_period_scope(report_type)
    # 2026-07-29 - 条目8：KPI/词/竞品/平台副标题按周月季年换「上周/上月…」
    kpi_slide_title = f"核心指标 · 环比{prev_scope}"
    ring_subtitle = f"环比{prev_scope}"

    trend_raw = (
        render_trend_html(trend, echarts_src="", presentation=True) if (trend.get("points")) else ""
    )
    trend_body = _drop_echarts_src(_strip_h2(_strip_outer_section(trend_raw)))
    # 2026-07-28 - 折线与表同块太挤且难分页 - 拆成两 pack-item
    trend_head_html, trend_table_html = _split_before_table(trend_body)
    # 趋势摘要留在正文；图表标题槽用固定小标题
    trend_subtitle = str(trend.get("title") or "品牌提及率与平均排名")

    keyword_raw = _drop_echarts_src(
        _strip_h2(
            _strip_outer_section(render_keyword_html(keyword_analytics, report_type=report_type, client=True))
        )
    )
    # 成绩单页用模版3；矩阵单独走模版5，避免与 keyword HTML 内嵌矩阵重复
    keyword_body = re.sub(r'<div class="kw-matrix">.*?</div>\s*', "", keyword_raw, flags=re.I | re.S)
    matrix = keyword_analytics.get("weak_platform_matrix") or {}
    # 与旧 A4 一致：矩阵仅月/季/年报
    matrix_html = (
        render_keyword_platform_matrix_html(matrix)
        if report_type in _RANK_TREND_TYPES
        and isinstance(matrix, dict)
        and (matrix.get("rows") and matrix.get("platforms"))
        else ""
    )
    # 小标题进母版槽后，正文不再重复 h3
    if matrix_html:
        matrix_html = re.sub(r"<h3\b[^>]*>.*?</h3>", "", matrix_html, count=1, flags=re.I | re.S)

    competitor_body = _drop_echarts_src(
        _strip_h2(
            _strip_outer_section(
                render_competitor_html(
                    competitor_analytics, report_type=report_type, client=True, presentation=True
                )
            )
        )
    )
    # 2026-07-28 - 竞品摘要占满页后表头孤儿 - 表前/表后拆开，对齐诊断分页
    competitor_head_html, competitor_table_html = _split_before_table(competitor_body)
    # 摘要+7条建议仍会 softShrink 压字：建议动作单独一块，优先拆页不压到看不见
    competitor_actions_html = ""
    m_action = re.search(
        r'(<div class="comp-strategy-card comp-action-card">[\s\S]*?</div>\s*)'
        r'(<p class="comp-risk-legend">[\s\S]*?</p>)?',
        competitor_head_html,
        flags=re.I,
    )
    if m_action:
        competitor_actions_html = (m_action.group(0) or "").strip()
        competitor_head_html = (
            competitor_head_html[: m_action.start()] + competitor_head_html[m_action.end() :]
        ).strip()
    preface_body = _strip_h2(_strip_outer_section(render_preface_html(preface, client=True)))
    # 2026-07-28 - 拆成 lead/meta/side 会出「半空白 2/3 页」难看 - 已弃用；改回整块双栏，装不下再 softShrink/peel
    preface_lead_html = ""
    preface_meta_html = ""
    preface_side_html = ""
    preface_grid_html = preface_body

    # 2026-07-29 - 条目2：tail 拆多 pack-item，避免整块超高被 overflow 裁切
    tail_parts: list[str] = []
    if report_type == "weekly":
        weekly_html = _drop_echarts_src(
            _strip_h2(_strip_outer_section(render_weekly_focus_html(content_modules, client=True)))
        )
        weekly_html = re.sub(r'<p\s+class="note plan-note">.*?</p>\s*', "", weekly_html, flags=re.I | re.S)
        weekly_html = weekly_html.replace("<ul>", "<ol>").replace("</ul>", "</ol>")
        if weekly_html.strip():
            tail_parts.append(weekly_html)
        tail_title = "本周关注"
    else:
        for frag in (
            render_source_influence_html(
                content_modules.get("source_influence") or {}, presentation=True
            ),
            render_risk_strategy_html(content_modules.get("risk_and_strategy") or {}, client=True),
            render_action_plan_html(content_modules.get("action_plan"), client=True),
        ):
            cleaned = _drop_echarts_src(_strip_h2(_strip_outer_section(frag)))
            # 2026-08-03 - 幻灯 CSS 隐藏 plan-note 但仍被 pack 单独分页 → 空页；与周报一致 strip
            cleaned = re.sub(r'<p\s+class="note plan-note">.*?</p>\s*', "", cleaned, flags=re.I | re.S)
            if cleaned.strip():
                tail_parts.append(cleaned)
        tail_title = "信源与优化建议"
    tail_html = "".join(tail_parts)

    disclaimer_html = _strip_h2(
        _strip_outer_section(render_disclaimer_html(content_modules.get("disclaimer") or {}))
    )

    return {
        "page_title": f"{brand} · {type_label}",
        "font_face_css": build_font_face_css(),
        "pipeline": PERIOD_DECK_PIPELINE,
        "brand_name": brand,
        "type_label": type_label,
        "period_range": str(preface.get("period_range") or period_lbl),
        "generated_at": generated_at,
        "competitor_text": "、".join(competitors) if competitors else "—",
        "platform_chip_rows": _platform_chip_rows(platform_codes),
        "section_title": "监测分析",
        "kpi_slide_title": kpi_slide_title,
        "kpi_html": _kpi_cards_html(comparison),
        "conclusions_html": _conclusions_html(comparison, keyword_analytics, competitor_analytics),
        "sample_meta_html": _sample_meta_html(comparison, snapshot),
        "preface_html": preface_body,
        "preface_lead_html": preface_lead_html,
        "preface_meta_html": preface_meta_html,
        "preface_side_html": preface_side_html,
        "preface_grid_html": preface_grid_html,
        "preface_subtitle": "监测范围与口径说明",
        "trend_html": trend_body,
        "trend_head_html": trend_head_html,
        "trend_table_html": trend_table_html,
        "trend_subtitle": trend_subtitle,
        "echarts_inline": echarts_inline,
        "echarts_src": echarts_src,
        "has_trend": bool(trend.get("points")),
        "keyword_html": keyword_body,
        # 2026-07-29 - 「· 监控词成绩单」与主标题重复啰嗦 - 副标题只留环比口径
        "keyword_subtitle": ring_subtitle,
        "matrix_html": matrix_html,
        # 2026-07-29 - 条目5：勿叠双×；副标题仍会长到挤蓝条 - 清空，说明留正文 note
        "matrix_subtitle": "",
        "has_matrix": bool(matrix_html),
        "competitor_html": competitor_body,
        "competitor_head_html": competitor_head_html,
        "competitor_actions_html": competitor_actions_html,
        "competitor_table_html": competitor_table_html,
        "competitor_subtitle": ring_subtitle,
        "platform_html": _platform_table_html(comparison),
        "platform_subtitle": ring_subtitle,
        "tail_title": tail_title,
        "tail_subtitle": "落地建议",
        "tail_html": tail_html,
        "tail_parts": tail_parts,
        "has_tail": bool(tail_parts),
        "disclaimer_html": disclaimer_html,
        "disclaimer_subtitle": "数据口径说明",
        "has_disclaimer": bool(disclaimer_html.strip()),
    }
