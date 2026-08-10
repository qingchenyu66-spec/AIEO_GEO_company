"""模力指数报告 HTML 片段：与参考模板 1:1 对齐的 markup。"""

from __future__ import annotations

import html
import re
from typing import Any

from app.services.report_competitor_visuals import entity_visual_style
from app.services.report_molizhishu_theme import get_theme


def _esc(text: Any) -> str:
    return html.escape(str(text or ""), quote=False)


def _paragraph_html(text: str, *, short: bool | None = None) -> str:
    """短句/单行不缩进；较长段落才首行缩进。"""
    content = str(text or "").strip()
    if not content:
        return ""
    if content.startswith("<"):
        return content
    # 短句/单行不缩进；多句且较长才首行缩进
    if short is not None:
        is_short = short
    else:
        sentence_breaks = content.count("。") + content.count("！") + content.count("？")
        is_short = len(content) <= 48 or sentence_breaks <= 1
    cls = "para--short" if is_short else "para--indent"
    return f'<p class="{cls}">{_esc(content)}</p>'


def _split_sentence_paragraphs(text: str) -> str:
    """按句号/分号拆成多行，便于摘要与 SWOT 逐条阅读。"""
    content = str(text or "").strip()
    if not content:
        return ""
    if content.startswith("<"):
        return content
    parts = [p.strip() for p in re.split(r"(?<=[。！？；;])", content) if p and p.strip()]
    # 去掉仅剩标点的残段
    parts = [p for p in parts if p.strip("。！？；;，,、 ")]
    if len(parts) <= 1:
        return _paragraph_html(content, short=True)
    return "".join(_paragraph_html(part, short=True) for part in parts)


def _numbered_list_html(text: str) -> str | None:
    """把「1. xxx 2. xxx」收成 ol；识别不到则返回 None。"""
    content = str(text or "").strip()
    if not content or content.startswith("<"):
        return None
    parts = re.split(r"(?:(?<=^)|(?<=\s)|(?<=[。；;]))\d+[\.、．]\s*", content)
    items = [p.strip(" ；;，,") for p in parts if p and p.strip(" ；;，,")]
    # split 可能留下无编号前缀的首段；要求至少 2 条编号项
    numbered = re.findall(r"\d+[\.、．]\s*", content)
    if len(numbered) < 2 or len(items) < 2:
        return None
    # 若首段不是编号项（split 产生空前缀），丢掉空段后取后段
    if not re.match(r"^\d+[\.、．]", content.strip()):
        # parts[0] 可能是空或前导废话
        items = [p for p in items if p]
    if len(items) < 2:
        return None
    lis = "".join(f"<li>{_esc(item)}</li>" for item in items[:12])
    return f'<ol class="action-tip-list tip-list--dense">{lis}</ol>'


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


def _short_monitor_date(raw: str | None) -> str:
    """B：监测日期短格式 MM-DD（保留可解析的年月日）。"""
    text = str(raw or "").strip()
    if not text or text == "—":
        return "—"
    # 2026-07-02 / 2026-07-02 13:40 / 26-07-09 13:40
    m = re.search(r"(?:\d{2,4}-)?(\d{1,2})-(\d{1,2})", text)
    if m:
        return f"{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return text


def _rank_type_tag(label: str, *, muted: bool = False) -> str:
    """A：最近/最优/最差 → 小标签。"""
    text = str(label or "最近").strip() or "最近"
    if "最优" in text:
        kind = "best"
    elif "最差" in text:
        kind = "worst"
    else:
        kind = "recent"
    muted_cls = " rank-type-tag--muted" if muted else ""
    return f'<span class="rank-type-tag rank-type-tag--{kind}{muted_cls}">{_esc(text)}</span>'


def render_ranking_table(table_id: str, rows: list[dict[str, Any]]) -> str:
    """排名明细：A+B 去分类列 / 类型标签 / 本品牌高亮 / 日期短格式。"""
    if not rows:
        return ""
    body = []
    for row in rows:
        brand = bool(row.get("is_brand"))
        muted = bool(row.get("type_muted"))
        type_html = _rank_type_tag(str(row.get("type_label") or "最近"), muted=muted)
        name_html = _font_brand(str(row.get("name") or ""), brand=True) if brand else _esc(str(row.get("name") or ""))
        rank_html = (
            _font_brand(str(row.get("rank_display") or "—"), brand=True)
            if brand
            else _esc(str(row.get("rank_display") or "—"))
        )
        date_html = _esc(_short_monitor_date(row.get("collected_at")))
        if brand:
            date_html = f'<span class="brand-cell-text">{date_html}</span>'
        row_cls = ' class="rank-row--brand"' if brand else ""
        body.append(
            f"<tr{row_cls}>"
            f"<td>{name_html}</td>"
            f"<td>{type_html}</td>"
            f'<td class="rank-col">{rank_html}</td>'
            f'<td class="date-col">{date_html}</td>'
            "</tr>"
        )
    return (
        f'<div id="{_esc(table_id)}" class="ranking-detail-wrap">'
        f'<table id="{_esc(table_id)}" class="RankTable ranking-detail-table">'
        "<thead><tr>"
        '<th class="name-col">品牌名称</th>'
        '<th class="type-col">类型</th>'
        '<th class="rank-col">排名</th>'
        '<th class="date-col">监测日期</th>'
        "</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def render_progress_cell(
    rate: float,
    *,
    brand: bool,
    entity_name: str,
    brand_name: str | None,
) -> str:
    width = max(0.0, min(100.0, float(rate)))
    display = f"{width:.1f}%"
    fill = entity_visual_style(entity_name, brand_name=brand_name).color
    bar = (
        f'<div class="progress-container" style="--entity-color: {fill};">'
        f'<div class="progress-bar" style="width: {width}%; background: var(--entity-color);"></div>'
        f'<span class="progress-text">{display}</span></div>'
    )
    if brand:
        return f'<td><div class="brand-row-outline">{bar}</div></td>'
    return f"<td>{bar}</td>"


def render_mention_table(table_id: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    body = []
    brand_name = next((str(row.get("name") or "") for row in rows if row.get("is_brand")), None)
    for row in rows:
        brand = bool(row.get("is_brand"))
        entity_name = str(row.get("name") or "")
        rate = float(row.get("mention_rate") or 0)
        row_cls = ' class="rank-row--brand"' if brand else ""
        body.append(
            f"<tr{row_cls}>"
            f"<td>{_font_brand(str(row.get('name') or ''), brand=brand)}</td>"
            f"<td>{_font_brand(str(row.get('sample_count') or 0), brand=brand)}</td>"
            f"<td>{_font_brand(str(row.get('mention_count') or 0), brand=brand)}</td>"
            f"{render_progress_cell(rate, brand=brand, entity_name=entity_name, brand_name=brand_name)}"
            "</tr>"
        )
    return (
        f'<div id="{_esc(table_id)}">'
        f'<table id="{_esc(table_id)}" class="RankTable">'
        "<thead><tr>"
        '<th width="25%">品牌名称</th><th width="12%">监测样本数</th>'
        '<th width="12%">品牌提及次数</th><th width="30%">提及占比</th>'
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
        # 核心结论段落首行缩进 2 字；下方 highlight 列表不缩进
        if summary.startswith("<"):
            body = summary
        else:
            parts = [p.strip() for p in re.split(r"(?<=[。！？；;])", summary) if p and p.strip()]
            parts = [p for p in parts if p.strip("。！？；;，,、 ")]
            if len(parts) <= 1:
                body = _paragraph_html(summary, short=False)
            else:
                body = "".join(_paragraph_html(part, short=False) for part in parts)
        chunks.append(f'<div class="executive-summary">{body}</div>')
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
    meta = (
        ("positive", "正面", "is-positive"),
        ("neutral", "中性", "is-neutral"),
        ("negative", "负面", "is-negative"),
        ("unknown", "未知", "is-unknown"),
    )
    cards = []
    for key, label, css in meta:
        count = int(sentiment_counts.get(key) or 0)
        if count <= 0 and key == "unknown":
            continue
        pct = round(count / total * 100, 1)
        cards.append(
            f'<div class="sentiment-kpi-item {css}">'
            f'<div class="sentiment-kpi-label">{label}</div>'
            f'<div class="sentiment-kpi-value">{count}</div>'
            f'<div class="sentiment-kpi-pct">{pct}%</div>'
            f"</div>"
        )
    summary = (
        f'<p class="insight-text sentiment-kpi-summary">'
        f'综合正面情绪占比 <strong>{_esc(positive_rate)}%</strong>（含中性）。'
        f"</p>"
    )
    return summary + f'<div class="sentiment-kpi">{"".join(cards)}</div>'


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
        if text.startswith("<"):
            body = text
        else:
            numbered = _numbered_list_html(text)
            if numbered:
                body = numbered
            else:
                # 优势/待改善常以分号串联多条，统一按句/分号拆行
                body = _split_sentence_paragraphs(text)
        blocks.append(f'<div class="swot-card {css}"><h4>{_esc(title)}</h4>{body}</div>')
    if not blocks:
        return ""
    return f'<div class="swot-stack">{"".join(blocks)}</div>'


def render_competitor_landscape_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    body = []
    brand_name = next((str(row.get("name") or "") for row in rows if row.get("is_brand")), None)
    for row in rows:
        brand = bool(row.get("is_brand"))
        entity_name = str(row.get("name") or "")
        style = entity_visual_style(entity_name, brand_name=brand_name)
        name_text = _font_brand(entity_name, brand=brand) if brand else _esc(entity_name)
        role = "本品牌" if brand else "竞品"
        name_cell = (
            f'<span class="entity-swatch" style="--entity-color: {style.color};"></span>'
            f'{name_text}<span class="entity-role">{role}</span>'
        )
        avg_rank = row.get("avg_rank")
        rank_text = "—" if avg_rank in (None, "") else f"{float(avg_rank):.1f}"
        body.append(
            f'<tr data-entity-color="{style.color}" style="--entity-color: {style.color};">'
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


def render_competitor_strategy(analysis: dict[str, Any]) -> str:
    if not analysis or not analysis.get("rows"):
        return ""
    summary_html = _split_sentence_paragraphs(str(analysis.get("management_summary") or ""))
    actions = [str(item).strip() for item in analysis.get("actions") or [] if str(item).strip()]
    action_items = "".join(f"<li>{_esc(item)}</li>" for item in actions)
    return (
        '<div class="competitor-strategy">'
        '<div class="competitor-summary-card"><h4>竞争格局摘要</h4>'
        f"{summary_html}</div>"
        '<div class="competitor-action-card"><h4>运营建议动作</h4>'
        f'<ol class="competitor-action-list competitor-action-list--dense">{action_items}</ol></div>'
        "</div>"
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
    numbered = _numbered_list_html(content)
    if numbered:
        return f'<div class="insight-text">{numbered}</div>'
    return f'<div class="insight-text">{_paragraph_html(content)}</div>'


def render_tip_list(tips: list[str]) -> str:
    """信源优化建议：与「数据分析与优化建议」同款白卡段落流。"""
    from html import unescape as html_unescape

    cleaned: list[str] = []
    for item in tips:
        tip = str(item).strip()
        if not tip:
            continue
        tip = re.sub(r"^针对\s*", "", tip)
        tip = re.sub(r"^【(?:深度|广度|维度|策略)】\s*", "", tip)
        tip = re.sub(r"验收口径[:：]?\s*", "", tip)
        if "验收口径" in tip:
            continue
        if tip and tip not in cleaned:
            cleaned.append(tip)
    if not cleaned:
        return ""
    cards: list[str] = []
    for index, tip in enumerate(cleaned[:12], start=1):
        # 2026-08-04 - 模型若把 <strong> 写进 tip 字符串，_esc 会变成页面上的「代码」；先剥标签再标重点
        plain = html_unescape(re.sub(r"<[^>]+>", "", tip)).strip()
        text = _highlight_analysis_plain(plain)
        cards.append(
            '<div class="analysis-block analysis-card pack-item tip-as-analysis">'
            f'<p class="para--short"><span class="tip-card-index">{index:02d}</span>{text}</p>'
            "</div>"
        )
    return f'<div class="tip-analysis-stack">{"".join(cards)}</div>'


def render_prompt_comment(text: str | None) -> str:
    content = str(text or "").strip()
    if not content:
        return ""
    if content.startswith("<"):
        return f'<div class="prompt-comment">{content}</div>'
    # 点评多为短句，默认不缩进
    return f'<p class="prompt-comment para--short">{_esc(content)}</p>'


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


def _split_dense_analysis_paragraphs(html: str) -> str:
    """2026-08-04 - 分析结论超长单段拆成多条 <p>，避免一卡密密麻麻。

    仅按中文句号/分号拆；不碰小数点。模型已输出多段 <p> 时，单段不足 2 个句号则保持原样。
    """
    from html import unescape as html_unescape

    body = str(html or "")
    if not body:
        return body

    def _split_p(match: re.Match[str]) -> str:
        attrs = match.group(1) or ""
        inner = match.group(2)
        plain = html_unescape(re.sub(r"<[^>]+>", "", inner)).strip()
        # 只认中文句子边界，避免 52.7% 被英文句点误伤（此处本就不拆 .）
        sents = [s.strip() for s in re.split(r"(?<=[。；])", plain) if s and s.strip()]
        if len(sents) < 2:
            return match.group(0)
        # 已是「一句一卡」量级：勿再拆
        if len(sents) == 1 or (len(sents) == 2 and len(plain) < 160):
            return match.group(0)
        if len(sents) < 3 and len(plain) < 120:
            return match.group(0)
        merged: list[str] = []
        for sent in sents:
            if merged and len(sent) < 12:
                merged[-1] = merged[-1] + sent
            else:
                merged.append(sent)
        if len(merged) < 2:
            return match.group(0)
        cls = ' class="para--short"'
        if "para--short" in attrs:
            return "".join(f"<p{attrs}>{_esc(s)}</p>" for s in merged)
        return "".join(f"<p{cls}>{_esc(s)}</p>" for s in merged)

    return re.sub(r"<p(\s[^>]*)?>(.*?)</p>", _split_p, body, flags=re.I | re.S)


def _wrap_analysis_blocks(html: str) -> str:
    """按参考图：每段正文独立白卡片；章节 h2/h3 保留为标题卡（新提示词三块结构依赖）。"""
    blocks: list[str] = []
    # 2026-08-04 - 原先丢弃 h2、不认 h3 →「分析结论/攻坚/渠道/P0」标题写不全
    pattern = re.compile(
        r"(<h2\b[^>]*>.*?</h2>)|(<h3\b[^>]*>.*?</h3>)|(<p\b[^>]*>.*?</p>)|(<ul\b[^>]*>.*?</ul>)|(<ol\b[^>]*>.*?</ol>)",
        re.I | re.S,
    )
    for match in pattern.finditer(html or ""):
        chunk = match.group(0).strip()
        if not chunk:
            continue
        if re.match(r"<h2\b", chunk, re.I):
            blocks.append(
                f'<div class="analysis-block analysis-card pack-item analysis-section-head">{chunk}</div>'
            )
            continue
        if re.match(r"<h3\b", chunk, re.I):
            blocks.append(
                f'<div class="analysis-block analysis-card pack-item analysis-section-sub">{chunk}</div>'
            )
            continue
        blocks.append(f'<div class="analysis-block analysis-card pack-item">{chunk}</div>')
    if blocks:
        return "\n".join(blocks)
    # 无识别到的块时回退：整段包一张卡
    fallback = (html or "").strip()
    return f'<div class="analysis-block analysis-card pack-item">{fallback}</div>' if fallback else ""


_EMPHASIS_RED = "#ff6666"
_EMPHASIS_BLUE = "#66ccff"
# 行动项里常见落点站点/平台，作次要蓝高亮（长词优先）
_EMPHASIS_BLUE_TERMS = (
    "百度百科",
    "百度知道",
    "百家号",
    "搜狐号",
    "小红书",
    "广告门",
    "梅花网",
    "DeepSeek",
    "通义千问",
    "百度 AI+",
    "今日头条",
    "博客园",
    "豆丁网",
    "大众网",
    "爱企查",
    "微信公众平台",
    "知乎",
    "夸克",
    "新浪",
    "搜狐",
    "网易",
    "抖音",
    "微博",
    "Kimi",
    "元宝",
    "豆包",
)
_EMPHASIS_BLUE_PHRASES = (
    "内容分发策略",
    "内容相关性",
    "需强化推荐位次",
    "需增加权威信源引用",
    "平台覆盖不均",
    "自媒体和垂直网站覆盖不足",
    "以合规口径执行",
)


def _highlight_analysis_plain(text: str) -> str:
    """与分析卡同口径：主强调红、次要蓝（「」交替 + 站点名）。"""
    esc = _esc(text)
    quote_idx = 0

    def _quote_repl(match: re.Match[str]) -> str:
        nonlocal quote_idx
        color = _EMPHASIS_RED if quote_idx % 2 == 0 else _EMPHASIS_BLUE
        quote_idx += 1
        return f'「<strong style="color:{color};">{match.group(1)}</strong>」'

    esc = re.sub(r"「([^」]{1,48})」", _quote_repl, esc)
    for phrase in _EMPHASIS_BLUE_PHRASES:
        token = f'<strong style="color:{_EMPHASIS_BLUE};">{phrase}</strong>'
        if phrase in esc and token not in esc:
            esc = esc.replace(phrase, token, 1)
    for term in _EMPHASIS_BLUE_TERMS:
        token = f'<strong style="color:{_EMPHASIS_BLUE};">{term}</strong>'
        if term not in esc or token in esc:
            continue
        # 勿拆开已包在 <strong> 内的更长短语（如 搜狐号 里的 搜狐）
        replaced = False
        for match in re.finditer(re.escape(term), esc):
            before = esc[: match.start()]
            if before.count("<strong") > before.count("</strong>"):
                continue
            esc = esc[: match.start()] + token + esc[match.end() :]
            replaced = True
            break
        if not replaced:
            continue
    # 未染色的百分比 / 百分点 → 红
    def _metric_repl(match: re.Match[str]) -> str:
        before = esc[: match.start()]
        if before.count("<strong") > before.count("</strong>"):
            return match.group(0)
        return f'<strong style="color:{_EMPHASIS_RED};">{match.group(0)}</strong>'

    esc = re.sub(r"\d+(?:\.\d+)?(?:%|个百分点)", _metric_repl, esc)
    return esc


def enrich_analysis_emphasis_html(html: str) -> str:
    """2026-08-04 - 对齐旧报告标重点：裸 strong 补色，百分比红，站点/动作短语蓝。"""
    body = str(html or "")
    if not body:
        return body

    def _color_bare_strong(match: re.Match[str]) -> str:
        attrs = match.group(1) or ""
        inner = match.group(2)
        if re.search(r"color\s*:", attrs, flags=re.I):
            return match.group(0)
        plain = re.sub(r"<[^>]+>", "", inner)
        # 动作/补充语气 → 蓝，其余重点 → 红
        if re.search(r"需|建议|优先|加强|布局|优化|补充|覆盖不足|相关性|分发", plain):
            color = _EMPHASIS_BLUE
        else:
            color = _EMPHASIS_RED
        return f'<strong style="color:{color};">{inner}</strong>'

    body = re.sub(
        r"<strong(\s[^>]*)?>(.*?)</strong>",
        _color_bare_strong,
        body,
        flags=re.I | re.S,
    )

    def _enrich_text_chunk(chunk: str) -> str:
        if not chunk or "<" in chunk:
            # 已是含标签片段时，只在标签外补；简化：对整段做有限替换
            out = chunk
        else:
            out = chunk
        for phrase in _EMPHASIS_BLUE_PHRASES:
            token = f'<strong style="color:{_EMPHASIS_BLUE};">{phrase}</strong>'
            if phrase in out and token not in out:
                # 避免写进已有 strong
                out = out.replace(phrase, token, 1)
        for term in _EMPHASIS_BLUE_TERMS:
            token = f'<strong style="color:{_EMPHASIS_BLUE};">{term}</strong>'
            if term not in out or token in out:
                continue
            # 跳过已在 strong 内的命中
            parts: list[str] = []
            last = 0
            for match in re.finditer(re.escape(term), out):
                before = out[: match.start()]
                if before.count("<strong") > before.count("</strong>"):
                    continue
                parts.append(out[last : match.start()])
                parts.append(token)
                last = match.end()
                break
            else:
                continue
            parts.append(out[last:])
            out = "".join(parts)

        def _metric_repl(match: re.Match[str]) -> str:
            before = out[: match.start()]
            if before.count("<strong") > before.count("</strong>"):
                return match.group(0)
            return f'<strong style="color:{_EMPHASIS_RED};">{match.group(0)}</strong>'

        out = re.sub(r"\d+(?:\.\d+)?(?:%|个百分点)", _metric_repl, out)
        return out

    def _enrich_leaf(match: re.Match[str]) -> str:
        tag, attrs, inner = match.group(1), match.group(2) or "", match.group(3)
        return f"<{tag}{attrs}>{_enrich_text_chunk(inner)}</{tag}>"

    body = re.sub(
        r"<(p|li|h2|h3)(\s[^>]*)?>(.*?)</\1>",
        _enrich_leaf,
        body,
        flags=re.I | re.S,
    )
    return body


def render_priority_actions(rows: list[dict[str, Any]]) -> str:
    """行动项：与下方分析同款白卡长段落流，含红/蓝关键词高亮；不展示优先级/周期。"""
    if not rows:
        return ""
    cards: list[str] = []
    for row in rows:
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        # 禁止展示「验收口径」类附注，避免给客户交付制造刚性承诺
        # 白卡行动项不缩进
        cards.append(
            '<div class="analysis-block analysis-card pack-item">'
            f'<p class="para--short">{_highlight_analysis_plain(title)}</p></div>'
        )
    return "\n".join(cards)


def _analysis_plain_key(text: str) -> str:
    plain = re.sub(r"<[^>]+>", "", str(text or ""))
    plain = re.sub(r"\s+", "", plain)
    plain = re.sub(
        r"^(门户类|垂直类|问答类|自媒体类|行业类|新闻类)[:：]",
        "",
        plain,
    )
    return plain


def _near_dup_action(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) < 18 or len(b) < 18:
        return False
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return shorter in longer and (len(shorter) / len(longer)) >= 0.78


def _explode_lists_to_paragraphs(
    html: str,
    *,
    dedupe_titles: list[str] | None = None,
) -> str:
    """ul/ol → 独立 p（一条一卡）；与 priority 近重复则丢弃。"""
    body = str(html or "")
    if not body:
        return body
    seen = {_analysis_plain_key(t) for t in (dedupe_titles or []) if _analysis_plain_key(t)}

    def _repl(match: re.Match[str]) -> str:
        chunk = match.group(0)
        lis = re.findall(r"<li\b[^>]*>(.*?)</li>", chunk, flags=re.I | re.S)
        if not lis:
            return chunk
        parts: list[str] = []
        for li in lis:
            inner = str(li or "").strip()
            if not inner:
                continue
            key = _analysis_plain_key(inner)
            if not key:
                continue
            if any(_near_dup_action(key, prev) for prev in seen):
                continue
            seen.add(key)
            # 分类前缀保留原 HTML；统一短段不缩进
            parts.append(f'<p class="para--short">{inner}</p>')
        return "".join(parts)

    return re.sub(r"<(ul|ol)\b[^>]*>.*?</\1>", _repl, body, flags=re.I | re.S)


def ensure_analysis_action_items(
    html: str,
    *,
    fill_titles: list[str],
    min_count: int = 8,
    max_count: int = 10,
) -> str:
    """第5节采取措施建议：li 不足 8 条时用诊断短板行动项补齐（不编造无依据条目）。"""
    body = str(html or "").strip()
    if not body:
        return body
    # 2026-08-04 - 新提示词已含分析结论/攻坚/渠道路径时勿再灌「围绕语义词」凑条，避免写全后反被注水
    if re.search(r"分析结论|攻坚优先级|渠道路径", body):
        return body
    existing = re.findall(r"<li\b[^>]*>.*?</li>", body, flags=re.I | re.S)
    # 粗略只统计「采取措施」相关 ul；若无法定位则按全文 li 计
    section_match = re.search(
        r"(采取措施建议|action_recommendations)([\s\S]*?)(?=<h2\b|$)",
        body,
        flags=re.I,
    )
    scope = section_match.group(0) if section_match else body
    lis = re.findall(r"<li\b[^>]*>.*?</li>", scope, flags=re.I | re.S)
    if len(lis) >= min_count:
        return body

    seen = {re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", li)) for li in lis}
    extras: list[str] = []
    for title in fill_titles:
        plain = str(title or "").strip()
        if not plain:
            continue
        key = re.sub(r"\s+", "", plain)
        if not key or key in seen:
            continue
        seen.add(key)
        extras.append(f"<li>{_esc(plain)}</li>")
        if len(lis) + len(extras) >= max_count:
            break
    if not extras:
        return body

    # 插入最后一个 </ul> 前；若无 ul 则在文末追加一节
    if re.search(r"</ul>", body, flags=re.I):
        parts = re.split(r"(</ul>)", body, flags=re.I)
        # 插到最后一个 </ul> 之前
        for i in range(len(parts) - 1, -1, -1):
            if parts[i].lower() == "</ul>":
                parts[i] = "".join(extras) + parts[i]
                break
        return "".join(parts)
    block = (
        '<h2 class="analysis-h2">5. 采取措施建议</h2>'
        f"<ul>{''.join(lis)}{''.join(extras)}</ul>"
    )
    return f"{body}\n{block}"


def render_analysis_html(
    sections: dict[str, Any],
    *,
    analysis_html: str | None = None,
    priority_actions: list[dict[str, Any]] | None = None,
    source_action_tips: list[str] | None = None,
    analysis_action_tips: list[str] | None = None,
) -> str:
    from app.services.report_text_sanitize import sanitize_analysis_html

    del analysis_action_tips  # 已取消【深度】分层块，参数保留兼容旧调用

    priority_titles = [
        str(row.get("title") or "").strip()
        for row in (priority_actions or [])
        if str(row.get("title") or "").strip()
    ]
    fill_titles = list(priority_titles)
    fill_titles.extend(str(x).strip() for x in (source_action_tips or []) if str(x).strip())

    raw_analysis = str(analysis_html or "").strip()
    # 2026-08-04 - 新提示词三块（分析结论→攻坚→渠道）时不再置顶短标题行动项、不再凑条
    use_v2_structure = bool(
        raw_analysis and re.search(r"分析结论|攻坚优先级|渠道路径", raw_analysis)
    )

    if raw_analysis:
        body = sanitize_analysis_html(raw_analysis)
        body = _split_dense_analysis_paragraphs(body)
        if not use_v2_structure:
            body = ensure_analysis_action_items(body, fill_titles=fill_titles, min_count=8, max_count=10)
        body = _normalize_analysis_h2(body)
        # 4A：措施列表拆成独立段落卡；v2 保留原列表/标题顺序，仅与短标题去重
        body = _explode_lists_to_paragraphs(
            body,
            dedupe_titles=[] if use_v2_structure else priority_titles,
        )
        # 2026-08-04 - 对齐旧报告红/蓝标重点
        body = enrich_analysis_emphasis_html(body)
        body = _wrap_analysis_blocks(body)
    else:
        chunks: list[str] = []
        for key, title in _ANALYSIS_TITLES.items():
            raw = str(sections.get(key) or "").strip()
            if not raw:
                continue
            if raw.startswith("<"):
                chunks.append(f'<div class="analysis-block analysis-card pack-item">{raw}</div>')
            else:
                for part in re.split(r"\n+", raw):
                    part = part.strip()
                    if part:
                        chunks.append(
                            f'<div class="analysis-block analysis-card pack-item">'
                            f"<p class=\"para--short\">{_esc(part)}</p></div>"
                        )
        body = "\n".join(chunks)

    if use_v2_structure:
        return body

    # 旧五段结构：行动项置顶（历史交付口径）；新三块结构已含攻坚正文，勿再前置短标题卡
    head: list[str] = []
    if priority_actions:
        head.append(render_priority_actions(priority_actions))
    tips = [str(item).strip() for item in (source_action_tips or []) if str(item).strip()]
    # 有独立「信源优化建议」页时，tips 仅用于第5节凑满，不再在分析页追加「信源优化补充」
    if tips and "采取措施建议" not in body and not priority_actions:
        items = "".join(f"<li>{_esc(item)}</li>" for item in tips[:12])
        head.append(
            '<div class="analysis-block analysis-card pack-item">'
            '<h2 class="analysis-h2">信源优化补充</h2>'
            f"<ul>{items}</ul></div>"
        )
    if head:
        body = f"{''.join(head)}\n{body}"
    return body
