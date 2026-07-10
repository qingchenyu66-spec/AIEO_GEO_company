"""模力指数报告 HTML 片段：与参考模板 1:1 对齐的 markup。"""

from __future__ import annotations

import html
import re
from typing import Any

from app.services.report_molizhishu_theme import get_theme


def _esc(text: Any) -> str:
    return html.escape(str(text or ""), quote=False)


def rank_cell_bg(rank: Any) -> str | None:
    return get_theme().rank_cell_bg(rank)


def format_rank_display(rank: Any) -> str:
    if rank is None or rank == "":
        return "&nbsp;"
    try:
        value = float(rank)
    except (TypeError, ValueError):
        return _esc(rank)
    if value.is_integer():
        return _esc(str(int(value)))
    return _esc(f"{value:.1f}")


def render_matrix_cell(rank: Any) -> str:
    bg = rank_cell_bg(rank)
    if rank is None or rank == "":
        return "<td>&nbsp;</td>"
    style = f' style="background-color:{bg}"' if bg else ""
    return f"<td{style}>{format_rank_display(rank)}</td>"


def render_matrix_table(table_id: str, row_header: str, prompts: list[str], rows: list[dict[str, Any]]) -> str:
    if not prompts or not rows:
        return ""
    head = "".join(f"<th>{_esc(prompt)}</th>" for prompt in prompts)
    body_rows = []
    for row in rows:
        cells = "".join(render_matrix_cell(cell) for cell in row.get("cells") or [])
        body_rows.append(
            f'<tr style="text-align:center"><td>{_esc(row.get("label") or "")}</td>{cells}</tr>'
        )
    return (
        f'<table id="{_esc(table_id)}" class="RankTable">'
        f'<thead><tr><th width="20%">{_esc(row_header)}</th>{head}</tr></thead>'
        f"<tbody>{''.join(body_rows)}</tbody></table>"
    )


def _font_brand(text: str, *, brand: bool) -> str:
    if not brand:
        return _esc(text)
    return f'<span class="brand-cell-text">{_esc(text)}</span>'


def _font_type(text: str, *, muted: bool) -> str:
    if not muted:
        return _esc(text)
    return f'<span class="muted-cell-text">{_esc(text)}</span>'


def render_ranking_table(table_id: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    body = []
    for row in rows:
        brand = bool(row.get("is_brand"))
        muted = bool(row.get("type_muted"))
        if brand:
            body.append(
                "<tr>"
                f"<td>{_font_brand(str(row.get('name') or ''), brand=True)}</td>"
                f"<td>{_font_brand(str(row.get('type_label') or '最近'), brand=True)}</td>"
                f"<td>{_font_brand(str(row.get('category') or '默认分类'), brand=True)}</td>"
                f"<td>{_font_brand(str(row.get('rank_display') or '—'), brand=True)}</td>"
                f"<td>{_font_brand(str(row.get('collected_at') or '—'), brand=True)}</td>"
                "</tr>"
            )
        else:
            body.append(
                "<tr>"
                f"<td>{_esc(str(row.get('name') or ''))}</td>"
                f"<td>{_font_type(str(row.get('type_label') or '最近'), muted=muted)}</td>"
                f"<td>{_esc(str(row.get('category') or '默认分类'))}</td>"
                f"<td>{_esc(str(row.get('rank_display') or '—'))}</td>"
                f"<td>{_esc(str(row.get('collected_at') or '—'))}</td>"
                "</tr>"
            )
    return (
        f'<div id="{_esc(table_id)}"><tr"></tr">'
        f'<table id="{_esc(table_id)}" class="RankTable">'
        '<thead><tr>'
        '<th width="25%">品牌名称</th><th>类型</th><th width="30%">分类</th>'
        '<th width="10%">排名</th><th width="18%">采集时间</th>'
        "</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def render_progress_cell(rate: float, *, brand: bool) -> str:
    theme = get_theme()
    width = max(0.0, min(100.0, float(rate)))
    display = f"{width:.1f}%"
    fill = theme.mention_bar_fill(width)
    bar = (
        '<div class="progress-container">'
        f'<div class="progress-bar" style="width: {width}%; background: {fill};"></div>'
        f'<span class="progress-text">{display}</span></div>'
    )
    if brand:
        return f'<td><div class="brand-row-outline">{bar}</div></td>'
    return f"<td>{bar}</td>"


def render_mention_table(table_id: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    body = []
    for row in rows:
        brand = bool(row.get("is_brand"))
        rate = float(row.get("mention_rate") or 0)
        body.append(
            "<tr>"
            f"<td>{_font_brand(str(row.get('name') or ''), brand=brand)}</td>"
            f"<td>{_font_brand(str(row.get('sample_count') or 0), brand=brand)}</td>"
            f"<td>{_font_brand(str(row.get('mention_count') or 0), brand=brand)}</td>"
            f"{render_progress_cell(rate, brand=brand)}"
            "</tr>"
        )
    return (
        f'<div id="{_esc(table_id)}"><tr"></tr">'
        f'<table id="{_esc(table_id)}" class="RankTable">'
        '<thead><tr>'
        '<th width="25%">品牌名称</th><th width="10%">采集次数</th>'
        '<th width="10%">提及次数</th><th width="30%">提及率</th>'
        "</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _health_score_class(score: Any) -> str:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "kpi-neutral"
    if value >= 70:
        return "kpi-good"
    if value >= 50:
        return "kpi-warn"
    return "kpi-bad"


def _prompt_status_label(row: dict[str, Any]) -> tuple[str, str]:
    rate = float(row.get("brand_mention_rate") or 0)
    rank = row.get("brand_avg_rank")
    if rate <= 0:
        return "未露面", "status-bad"
    if rank is not None and float(rank) <= 3 and rate >= 40:
        return "优秀", "status-good"
    if rank is not None and float(rank) <= 5:
        return "良好", "status-ok"
    return "待优化", "status-warn"


def render_kpi_overview(
    *,
    health_score: Any,
    mention_rate: Any,
    avg_rank: Any,
    top3_rate: Any,
    positive_rate: Any,
    completed_count: Any,
    source_count: Any,
) -> str:
    cards = [
        ("健康分", health_score, _health_score_class(health_score), "" if health_score in (None, "") else "分"),
        ("品牌提及率", mention_rate, "kpi-primary", "%"),
        ("平均排名", avg_rank if avg_rank not in (None, "") else "—", "kpi-primary", "" if avg_rank in (None, "") else "位"),
        ("Top3 露出率", top3_rate, "kpi-primary", "%"),
        ("正面情绪占比", positive_rate, "kpi-good", "%"),
        ("有效样本", completed_count, "kpi-neutral", "条"),
        ("引用信源", source_count, "kpi-neutral", "个"),
    ]
    items = []
    for label, value, css, suffix in cards:
        display = _esc(value)
        if suffix and value not in (None, "", "—"):
            display = f"{display}{suffix}"
        items.append(
            f'<div class="kpi-card {css}"><div class="kpi-label">{_esc(label)}</div>'
            f'<div class="kpi-value">{display}</div></div>'
        )
    return f'<div class="kpi-grid">{"".join(items)}</div>'


def render_executive_block(*, executive_summary: str | None, highlights: list[str]) -> str:
    chunks: list[str] = []
    summary = str(executive_summary or "").strip()
    if summary:
        chunks.append(
            f'<p class="executive-summary">{summary if summary.startswith("<") else _esc(summary)}</p>'
        )
    cleaned = [str(item).strip() for item in highlights if str(item).strip()]
    if cleaned:
        items = "".join(f"<li>{item if item.startswith('<') else _esc(item)}</li>" for item in cleaned[:6])
        chunks.append(f'<ul class="highlight-list">{items}</ul>')
    return "".join(chunks)


def render_platform_stats_table(rows: list[dict[str, Any]], platform_names: dict[str, str]) -> str:
    if not rows:
        return ""
    sorted_rows = sorted(rows, key=lambda row: float(row.get("mention_rate") or 0), reverse=True)
    body = []
    for row in sorted_rows:
        code = str(row.get("platform") or "")
        name = platform_names.get(code) or code or "—"
        avg_rank = row.get("avg_rank")
        rank_text = "—" if avg_rank in (None, "") else f"{float(avg_rank):.1f}"
        body.append(
            "<tr>"
            f"<td>{_esc(name)}</td>"
            f"<td>{row.get('completed') or row.get('total') or 0}</td>"
            f"<td>{float(row.get('mention_rate') or 0):.1f}%</td>"
            f"<td>{_esc(rank_text)}</td>"
            "</tr>"
        )
    return (
        '<table class="report-table overview-table">'
        "<thead><tr><th>平台</th><th>样本数</th><th>提及率</th><th>平均排名</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def render_prompt_scorecard(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    body = []
    for index, row in enumerate(rows, start=1):
        prompt = str(row.get("prompt") or "")
        status, status_class = _prompt_status_label(row)
        avg_rank = row.get("brand_avg_rank")
        rank_text = "—" if avg_rank in (None, "") else f"{float(avg_rank):.1f}"
        body.append(
            "<tr>"
            f"<td>{index}</td>"
            f'<td class="prompt-cell">{_esc(prompt)}</td>'
            f"<td>{row.get('sample_count') or 0}</td>"
            f"<td>{float(row.get('brand_mention_rate') or 0):.1f}%</td>"
            f"<td>{_esc(rank_text)}</td>"
            f'<td><span class="status-tag {status_class}">{_esc(status)}</span></td>'
            "</tr>"
        )
    return (
        '<table class="report-table overview-table">'
        "<thead><tr><th>#</th><th>语义词</th><th>样本</th><th>提及率</th><th>平均排名</th><th>表现</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def render_sentiment_overview(sentiment_counts: dict[str, Any], *, positive_rate: Any) -> str:
    total = sum(int(v or 0) for v in sentiment_counts.values()) or 1
    labels = {
        "positive": "正面",
        "neutral": "中性",
        "negative": "负面",
        "unknown": "未知",
    }
    rows = []
    for key in ("positive", "neutral", "negative", "unknown"):
        count = int(sentiment_counts.get(key) or 0)
        if count <= 0 and key == "unknown":
            continue
        pct = round(count / total * 100, 1)
        rows.append(f"<tr><td>{labels.get(key, key)}</td><td>{count}</td><td>{pct}%</td></tr>")
    summary = f'<p class="insight-text">综合正面情绪占比 <strong>{_esc(positive_rate)}%</strong>（含中性）。</p>'
    table = (
        '<table class="report-table overview-table">'
        "<thead><tr><th>情绪</th><th>样本数</th><th>占比</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    return summary + table


def render_diagnosis_swot(
    *,
    strength_points: str | None,
    weakness_points: str | None,
    recommendation: str | None,
) -> str:
    blocks = []
    for title, content, css in (
        ("优势亮点", strength_points, "swot-good"),
        ("待改善项", weakness_points, "swot-warn"),
        ("优化建议", recommendation, "swot-tip"),
    ):
        text = str(content or "").strip()
        if not text:
            continue
        body = text if text.startswith("<") else f"<p>{_esc(text)}</p>"
        blocks.append(f'<div class="swot-card {css}"><h4>{_esc(title)}</h4>{body}</div>')
    if not blocks:
        return ""
    return f'<div class="swot-grid">{"".join(blocks)}</div>'


def render_competitor_landscape_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    body = []
    for row in rows:
        brand = bool(row.get("is_brand"))
        name_cell = _font_brand(str(row.get("name") or ""), brand=brand) if brand else _esc(row.get("name"))
        avg_rank = row.get("avg_rank")
        rank_text = "—" if avg_rank in (None, "") else f"{float(avg_rank):.1f}"
        body.append(
            "<tr>"
            f"<td>{name_cell}</td>"
            f"<td>{float(row.get('mention_rate') or 0):.1f}%</td>"
            f"<td>{_esc(rank_text)}</td>"
            "</tr>"
        )
    return (
        '<table class="report-table overview-table">'
        "<thead><tr><th>品牌/竞品</th><th>综合提及率</th><th>平均排名</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def render_prompt_platform_matrix(matrix: dict[str, Any]) -> str:
    platforms = matrix.get("platforms") or []
    rows = matrix.get("rows") or []
    if not platforms or not rows:
        return ""
    head = "".join(f"<th>{_esc(name)}</th>" for name in platforms)
    body = []
    for row in rows:
        prompt = str(row.get("prompt") or "")
        cells = []
        for cell in row.get("cells") or []:
            mention = cell.get("mention_rate")
            rank = cell.get("avg_rank")
            if mention in (None, "") and rank in (None, ""):
                cells.append("<td>—</td>")
            else:
                mention_text = "—" if mention in (None, "") else f"{float(mention):.0f}%"
                if rank in (None, ""):
                    rank_text = "—"
                else:
                    rank_value = float(rank)
                    rank_text = str(int(rank_value)) if rank_value.is_integer() else f"{rank_value:.1f}"
                cells.append(f"<td>{_esc(mention_text)} / {_esc(rank_text)}</td>")
        body.append(f"<tr><td class=\"prompt-cell\">{_esc(prompt)}</td>{''.join(cells)}</tr>")
    return (
        '<table class="report-table overview-table matrix-platform-table">'
        f"<thead><tr><th>语义词</th>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def render_insight_paragraph(text: str | None) -> str:
    content = str(text or "").strip()
    if not content:
        return ""
    if content.startswith("<"):
        return f'<div class="insight-text">{content}</div>'
    return f'<p class="insight-text">{_esc(content)}</p>'


def render_tip_list(tips: list[str]) -> str:
    cleaned = [str(item).strip() for item in tips if str(item).strip()]
    if not cleaned:
        return ""
    items = "".join(f"<li>{item if item.startswith('<') else _esc(item)}</li>" for item in cleaned)
    return f'<ul class="action-tip-list">{items}</ul>'


def render_answer_excerpts(excerpts: list[dict[str, Any]], platform_names: dict[str, str]) -> str:
    if not excerpts:
        return ""
    blocks = []
    for index, row in enumerate(excerpts, start=1):
        platform = platform_names.get(str(row.get("platform") or "")) or row.get("platform") or "—"
        blocks.append(
            '<div class="excerpt-card">'
            f'<div class="excerpt-meta">#{index} · {_esc(row.get("prompt") or "")} · '
            f'{_esc(platform)} · 排名 {_esc(row.get("rank") or "—")}</div>'
            f'<blockquote class="excerpt-quote">{_esc(row.get("excerpt") or "")}</blockquote>'
            "</div>"
        )
    return "".join(blocks)


def render_prompt_comment(text: str | None) -> str:
    content = str(text or "").strip()
    if not content:
        return ""
    if content.startswith("<"):
        return f'<div class="prompt-comment">{content}</div>'
    return f'<p class="prompt-comment">{_esc(content)}</p>'


def render_chart_block(title: str, src: str) -> str:
    return (
        '<div class="chart-container">'
        f'<div class="chart-title">{_esc(title)}</div>'
        '<div class="chart-image-wrapper">'
        f'<img src="{src}" alt="{_esc(title)}" class="chart-image" '
        'style="max-width: 1200px; max-height: 400px;" '
        "onload=\"this.style.opacity=1\" "
        "onerror=\"this.parentElement.innerHTML='<div style=\\'padding:40px;color:#666;\\'>图表加载失败</div>'\">"
        "</div></div>"
    )


_ANALYSIS_TITLES = {
    "industry_analysis": "1. 行业分析",
    "ranking_analysis": "2. 排名分析",
    "mention_analysis": "3. 提及率分析",
    "source_analysis": "4. 引用网站分析",
    "action_recommendations": "5. 采取措施建议",
}

_ANALYSIS_H2_ALIASES = {
    "行业与ai搜索意图分析": "1. 行业分析",
    "行业与 ai 搜索意图分析": "1. 行业分析",
    "分语义词排名与竞品对比": "2. 排名分析",
    "提及率与曝光分析": "3. 提及率分析",
    "引用网站与信源覆盖": "4. 引用网站分析",
    "数据分析与优化建议": "",
}


def _normalize_analysis_h2(html: str) -> str:
    def _repl(match: re.Match[str]) -> str:
        inner = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        key = inner.lower().replace(" ", "")
        for alias, title in _ANALYSIS_H2_ALIASES.items():
            if alias.replace(" ", "") in key or key in alias.replace(" ", ""):
                return f'<h2 class="analysis-h2">{title}</h2>' if title else ""
        if re.match(r"^\d+\.", inner):
            return f'<h2 class="analysis-h2">{inner}</h2>'
        return f'<h2 class="analysis-h2">{inner}</h2>'

    cleaned = re.sub(r"<h2[^>]*>(.*?)</h2>", _repl, html, flags=re.I | re.S)
    return re.sub(r"<h2[^>]*>\s*数据分析与优化建议\s*</h2>", "", cleaned, flags=re.I)


def _wrap_analysis_blocks(html: str) -> str:
    parts = re.split(r"(?=<h2\b)", html.strip())
    blocks: list[str] = []
    for part in parts:
        chunk = part.strip()
        if not chunk:
            continue
        blocks.append(f'<div class="analysis-block">{chunk}</div>')
    return "\n".join(blocks)


def render_priority_actions(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td><span class=\"priority-tag priority-{str(row.get('priority') or 'P2').lower()}\">"
            f"{_esc(row.get('priority') or 'P2')}</span></td>"
            f"<td>{_esc(row.get('title') or '')}</td>"
            f"<td>{_esc(row.get('timeline') or '—')}</td>"
            "</tr>"
        )
    return (
        '<div class="analysis-block analysis-priority-block">'
        '<h2 class="analysis-h2">6. 优先级行动清单</h2>'
        '<table class="report-table overview-table">'
        "<thead><tr><th>优先级</th><th>行动项</th><th>建议周期</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def render_analysis_html(
    sections: dict[str, Any],
    *,
    analysis_html: str | None = None,
    priority_actions: list[dict[str, Any]] | None = None,
    source_action_tips: list[str] | None = None,
) -> str:
    from app.services.report_text_sanitize import sanitize_analysis_html

    if analysis_html and str(analysis_html).strip():
        body = sanitize_analysis_html(str(analysis_html).strip())
        body = _normalize_analysis_h2(body)
        body = _wrap_analysis_blocks(body)
    else:
        chunks: list[str] = []
        for key, title in _ANALYSIS_TITLES.items():
            raw = str(sections.get(key) or "").strip()
            if not raw:
                continue
            section_parts = [f'<h2 class="analysis-h2">{title}</h2>']
            if raw.startswith("<"):
                section_parts.append(raw)
            else:
                for part in re.split(r"\n+", raw):
                    part = part.strip()
                    if part:
                        section_parts.append(f"<p>{_esc(part)}</p>")
            chunks.append(f'<div class="analysis-block">{"".join(section_parts)}</div>')
        body = "\n".join(chunks)

    extras: list[str] = []
    if priority_actions:
        extras.append(render_priority_actions(priority_actions))
    tips = [str(item).strip() for item in (source_action_tips or []) if str(item).strip()]
    if tips and "采取措施建议" not in body:
        items = "".join(f"<li>{_esc(item)}</li>" for item in tips[:5])
        extras.append(
            '<div class="analysis-block">'
            '<h2 class="analysis-h2">信源优化补充</h2>'
            f"<ul>{items}</ul></div>"
        )
    if extras:
        body = f"{body}\n{''.join(extras)}"
    return body
