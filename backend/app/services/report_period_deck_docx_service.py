"""周期监测报告 Word：与 HTML/PDF 同源 bundle，原生 docx 章节。"""

from __future__ import annotations

import io
from datetime import date
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from sqlalchemy.orm import Session

from app.services.report_period_comparison_service import (
    TYPE_LABELS,
    _RANK_TREND_TYPES,
    _fmt_pct,
    _fmt_rank,
    assemble_period_report_bundle,
    build_v2_conclusions,
)
from app.services.report_period_service import PERIOD_COMPARISON_REPORT_TYPES
from app.services.report_premium_font_service import configure_matplotlib_cjk

_TITLE_RGB = RGBColor(0x12, 0x38, 0x5F)
_SECTION_RGB = RGBColor(0x17, 0x40, 0x6A)
_BODY_RGB = RGBColor(0x33, 0x4E, 0x6F)
_MUTED_RGB = RGBColor(0x58, 0x70, 0x8F)


def _prev_period_scope(report_type: str) -> str:
    return {"weekly": "上周", "monthly": "上月", "quarterly": "上季度", "annual": "上年度"}.get(
        report_type, "上一周期"
    )


def _parse_report_date(value: Any) -> date | None:
    from datetime import datetime

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


def _set_docx_font(document: Document) -> None:
    normal = document.styles["Normal"]
    normal.font.name = "Microsoft YaHei"
    normal.font.size = Pt(11)
    normal.font.color.rgb = _BODY_RGB
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")


def _section_title(document: Document, text: str) -> None:
    p = document.add_paragraph()
    run = p.add_run(text)
    run.bold = True
    run.font.size = Pt(14)
    run.font.color.rgb = _SECTION_RGB


def _note(document: Document, text: str) -> None:
    if not str(text or "").strip():
        return
    p = document.add_paragraph(str(text).strip())
    for run in p.runs:
        run.font.size = Pt(10)
        run.font.color.rgb = _MUTED_RGB


def _bullets(document: Document, items: list[str]) -> None:
    for item in items:
        t = str(item or "").strip()
        if t:
            document.add_paragraph(t, style="List Bullet")


def _add_table(document: Document, headers: list[str], rows: list[list[str]]) -> None:
    if not headers:
        return
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for i, h in enumerate(headers):
        table.rows[0].cells[i].text = h
    for row in rows:
        cells = table.add_row().cells
        for i, val in enumerate(row):
            if i < len(cells):
                cells[i].text = str(val if val is not None else "—")
    document.add_paragraph("")


def _append_png(document: Document, png: bytes | None, *, width: float = 6.2) -> None:
    if not png:
        return
    document.add_picture(io.BytesIO(png), width=Inches(width))
    document.add_paragraph("")


def _configure_mpl() -> None:
    family = configure_matplotlib_cjk()
    if family:
        plt.rcParams["font.sans-serif"] = [family, "DejaVu Sans"]
    else:
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def _figure_png(fig: plt.Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", pad_inches=0.35, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _trend_point_label(point: dict[str, Any]) -> str:
    sub = point.get("sub")
    label = str(point.get("label") or "—")
    return label if not sub else f"{label} ({sub})"


def _build_trend_line_chart(points: list[dict[str, Any]], *, field: str, title: str, ylabel: str, invert: bool = False) -> bytes | None:
    if not points:
        return None
    labels = [_trend_point_label(p) for p in points]
    values = [p.get(field) for p in points]
    if all(v is None for v in values):
        return None
    _configure_mpl()
    fig, ax = plt.subplots(figsize=(7.0, 3.0))
    nums = [float(v) if v is not None else float("nan") for v in values]
    ax.plot(labels, nums, marker="o", linewidth=2.2, color="#1677ff")
    ax.set_title(title, fontsize=12, color="#0b3a6e")
    ax.set_ylabel(ylabel)
    if invert:
        ax.invert_yaxis()
    ax.grid(True, linestyle="--", alpha=0.35)
    plt.xticks(rotation=30, ha="right")
    return _figure_png(fig)


def _completed_count(comparison: dict[str, Any], snapshot: dict[str, Any]) -> int:
    snap_kpis = snapshot.get("kpis") or {}
    completed = int(snap_kpis.get("completed_count") or snap_kpis.get("subtask_count") or 0)
    if completed <= 0:
        metric = (comparison.get("kpis") or {}).get("completed_count") or {}
        if isinstance(metric, dict):
            completed = int(metric.get("current") or 0)
        else:
            completed = int(metric or 0)
    return completed


def render_period_deck_docx_from_bundle(bundle: dict[str, Any]) -> bytes:
    """bundle 与 assemble_period_report_bundle / deck HTML 同源。"""
    report_type = str(bundle.get("report_type") or "")
    brand = str(bundle.get("brand_name") or "品牌")
    type_label = TYPE_LABELS.get(report_type, "GEO 监测报告")
    period_lbl = str(bundle.get("period_lbl") or "")
    generated: date = bundle.get("generated") or date.today()
    comparison = bundle.get("comparison") or {}
    snapshot = bundle.get("snapshot") or {}
    preface = bundle.get("preface") or {}
    content_modules = bundle.get("content_modules") or {}
    trend = bundle.get("trend") or {}
    keyword_analytics = bundle.get("keyword_analytics") or {}
    competitor_analytics = bundle.get("competitor_analytics") or {}
    prev_scope = _prev_period_scope(report_type)

    document = Document()
    _set_docx_font(document)

    title = document.add_heading(f"{brand} · {type_label}", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    for run in title.runs:
        run.font.color.rgb = _TITLE_RGB
    meta = document.add_paragraph(f"统计周期：{preface.get('period_range') or period_lbl}")
    meta.add_run(f"\n生成日期：{generated.strftime('%Y-%m-%d')}")
    for run in meta.runs:
        run.font.color.rgb = _MUTED_RGB
    document.add_paragraph("")

    _section_title(document, "报告前言")
    _note(document, str(preface.get("sample_description") or ""))
    preface_rows = [
        ["报告名称", str(preface.get("report_title") or "—")],
        ["发布主体", str(preface.get("publisher") or "—")],
        ["监测工具", str(preface.get("monitor_tool") or "—")],
        ["统计周期", str(preface.get("period_range") or "—")],
        ["监测词组", str(preface.get("monitor_keywords") or "—")],
        ["纳入竞品", str(preface.get("competitors") or "—")],
    ]
    _add_table(document, ["项目", "内容"], preface_rows)
    dims = [str(x) for x in (preface.get("core_dimensions") or []) if str(x).strip()]
    if dims:
        document.add_paragraph("核心监测维度")
        _bullets(document, dims)
    if preface.get("purpose"):
        document.add_paragraph(str(preface.get("purpose") or ""))

    _section_title(document, f"核心指标 · 环比{prev_scope}")
    kpis = comparison.get("kpis") or {}
    kpi_rows = [
        [
            "综合健康分",
            str(int(kpis.get("health_score", {}).get("current"))) if (kpis.get("health_score") or {}).get("current") is not None else "—",
            str(kpis.get("health_score", {}).get("text") or "—"),
        ],
        ["品牌提及率", _fmt_pct((kpis.get("mention_rate") or {}).get("current")), str((kpis.get("mention_rate") or {}).get("text") or "—")],
        ["平均推荐排名", _fmt_rank((kpis.get("avg_rank") or {}).get("current")), str((kpis.get("avg_rank") or {}).get("text") or "—")],
        ["Top3 露出率", _fmt_pct((kpis.get("top3_rate") or {}).get("current")), str((kpis.get("top3_rate") or {}).get("text") or "—")],
    ]
    _add_table(document, ["指标", "本期", "环比"], kpi_rows)
    completed = _completed_count(comparison, snapshot)
    prev_lbl = str(comparison.get("previous_period_label") or "")
    _note(document, f"本期有效监测样本 {completed} 条 · 对比周期 {prev_lbl}")
    warn = str(comparison.get("sample_warn") or "").replace("子任务", "样本")
    _note(document, warn)

    conclusions = build_v2_conclusions(comparison, keyword_analytics, competitor_analytics)
    if not conclusions:
        conclusions = [str(x) for x in (comparison.get("highlights") or [])[:6]]
    if conclusions:
        _section_title(document, "核心结论")
        _bullets(document, conclusions)

    points = list(trend.get("points") or [])
    if points:
        _section_title(document, f"{trend.get('title') or '趋势分析'} · 品牌提及率与平均排名")
        if trend.get("summary"):
            document.add_paragraph(str(trend.get("summary")))
        _append_png(document, _build_trend_line_chart(points, field="mention_rate", title="品牌提及率（%）", ylabel="提及率 %"))
        _append_png(document, _build_trend_line_chart(points, field="avg_rank", title="平均推荐排名（越小越靠前）", ylabel="排名", invert=True))
        trend_rows = []
        for point in points:
            trend_rows.append(
                [
                    _trend_point_label(point),
                    str(int(point.get("completed") or 0)),
                    _fmt_pct(point.get("mention_rate")),
                    _fmt_rank(point.get("avg_rank")),
                    _fmt_pct(point.get("top3_rate")),
                ]
            )
        _add_table(document, ["时间", "样本数", "提及率", "平均排名", "Top3率"], trend_rows)

    kw_rows_data = keyword_analytics.get("rows") or []
    platform_sections = keyword_analytics.get("platform_sections") or []
    if report_type == "weekly" and platform_sections:
        _section_title(document, f"核心监测词表现 · 环比{prev_scope}")
        _note(document, "按企业开通平台分栏统计；环比为同平台对比上一周期，排名数字越小越靠前。")
        for line in keyword_analytics.get("highlights") or []:
            _note(document, f"• {line}")
        headers = ["#", "监控词", "样本", "提及率", "上期提及率", "提及变化", "平均排名", "上期排名", "排名变化", "Top3率", "表现"]
        for section in platform_sections:
            _section_title(document, str(section.get("name") or section.get("platform") or "平台"))
            kw_rows = []
            for idx, row in enumerate(section.get("rows") or [], 1):
                mr = row.get("mention_rate") or {}
                ar = row.get("avg_rank") or {}
                kw_rows.append(
                    [
                        str(idx),
                        str(row.get("keyword") or "—"),
                        str(row.get("completed") or 0),
                        _fmt_pct(mr.get("current")),
                        _fmt_pct(mr.get("previous")),
                        str(mr.get("text") or "—"),
                        _fmt_rank(ar.get("current")),
                        _fmt_rank(ar.get("previous")),
                        str(ar.get("text") or "—"),
                        _fmt_pct(row.get("top3_rate")),
                        str(row.get("status") or "—"),
                    ]
                )
            if kw_rows:
                _add_table(document, headers, kw_rows)
    elif kw_rows_data:
        _section_title(document, f"核心监测词表现 · 环比{prev_scope}")
        _note(document, "按本周期监测关键词配置聚合统计；排名数字越小越靠前。")
        for line in keyword_analytics.get("highlights") or []:
            _note(document, f"• {line}")
        kw_rows = []
        for idx, row in enumerate(kw_rows_data, 1):
            mr = row.get("mention_rate") or {}
            ar = row.get("avg_rank") or {}
            kw_rows.append(
                [
                    str(idx),
                    str(row.get("keyword") or "—"),
                    str(row.get("completed") or 0),
                    _fmt_pct(mr.get("current")),
                    _fmt_pct(mr.get("previous")),
                    str(mr.get("text") or "—"),
                    _fmt_rank(ar.get("current")),
                    _fmt_rank(ar.get("previous")),
                    str(ar.get("text") or "—"),
                    _fmt_pct(row.get("top3_rate")),
                    str(row.get("status") or "—"),
                ]
            )
        headers = ["#", "监控词", "样本", "提及率", "上期提及率", "提及变化", "平均排名", "上期排名", "排名变化", "Top3率", "表现"]
        _add_table(document, headers, kw_rows)

        matrix = keyword_analytics.get("weak_platform_matrix") or {}
        plat_names = list(matrix.get("platforms") or [])
        matrix_rows = list(matrix.get("rows") or [])
        if report_type in _RANK_TREND_TYPES and plat_names and matrix_rows:
            _section_title(document, "短板监控词 × 平台表现")
            _note(document, "仅展示本期表现最弱的 TOP3 监控词；单元格为「提及率 · 平均排名」。")
            m_headers = ["监控词", *plat_names]
            m_body = []
            for row in matrix_rows:
                cells = [str(c.get("text") or "—") for c in (row.get("cells") or [])]
                m_body.append([str(row.get("keyword") or "—"), *cells])
            _add_table(document, m_headers, m_body)

    comp_rows = competitor_analytics.get("rows") or []
    if comp_rows:
        _section_title(document, f"竞品对比分析 · 环比{prev_scope}")
        _note(document, "基于 AI 推荐场景中的品牌与竞品表现统计。")
        for line in competitor_analytics.get("highlights") or []:
            _note(document, f"• {line}")
        analysis = competitor_analytics.get("analysis") or {}
        if analysis.get("management_summary"):
            document.add_paragraph(f"竞争格局摘要：{analysis.get('management_summary')}")
        body = []
        for row in comp_rows:
            mr = row.get("mention_rate") or {}
            ar = row.get("avg_rank") or {}
            name = str(row.get("name") or "—")
            if row.get("is_brand"):
                name = f"{name} ★"
            body.append(
                [
                    name,
                    _fmt_pct(mr.get("current")),
                    _fmt_pct(mr.get("previous")),
                    str(mr.get("text") or "—"),
                    _fmt_rank(ar.get("current")),
                    _fmt_rank(ar.get("previous")),
                    str(ar.get("text") or "—"),
                    str(row.get("gap_mention_text") or "—"),
                    str(row.get("gap_rank_text") or "—"),
                ]
            )
        _add_table(
            document,
            ["品牌/竞品", "提及率", "上期提及率", "提及变化", "平均排名", "上期排名", "排名变化", "提及率差距", "排名差距"],
            body,
        )
        for action in analysis.get("actions") or []:
            _note(document, f"建议：{action}")

    platform_rows = comparison.get("platform_rows") or []
    if platform_rows:
        _section_title(document, f"分平台环比表现 · 环比{prev_scope}")
        plat_body = []
        for row in platform_rows:
            mr = row.get("mention_rate") or {}
            ar = row.get("avg_rank") or {}
            plat_body.append(
                [
                    str(row.get("name") or "—"),
                    _fmt_rank(ar.get("previous")),
                    _fmt_rank(ar.get("current")),
                    str(ar.get("text") or "—"),
                    _fmt_pct(mr.get("previous")),
                    _fmt_pct(mr.get("current")),
                    str(mr.get("text") or "—"),
                    str(int(row.get("completed") or 0)),
                ]
            )
        _add_table(
            document,
            ["平台", "上期排名", "本期排名", "排名环比", "上期提及率", "本期提及率", "提及环比", "样本"],
            plat_body,
        )

    if report_type == "weekly":
        risk = content_modules.get("risk_and_strategy") or {}
        plan = content_modules.get("action_plan") or {}
        sources = list((content_modules.get("source_influence") or {}).get("rows") or [])[:3]
        _section_title(document, "本周关注与下周规划")
        _bullets(document, [str(x) for x in (risk.get("problems") or [])[:3]])
        if sources:
            document.add_paragraph("高频引用信源 TOP3")
            _bullets(document, [f"{r.get('title')} · {int(r.get('count') or 0)}次" for r in sources])
        _bullets(document, [str(x) for x in (plan.get("goals") or [])[:2]])
        _bullets(document, [str(x) for x in (plan.get("actions") or [])[:2]])
    else:
        source = content_modules.get("source_influence") or {}
        src_rows = list(source.get("rows") or [])[:8]
        if src_rows:
            _section_title(document, "核心信源传播影响力分析")
            s_body = [
                [str(r.get("title") or "—"), f"{int(r.get('count') or 0)}次", str(r.get("value_analysis") or "—")]
                for r in src_rows
            ]
            _add_table(document, ["信源渠道", "引用", "渠道价值拆解"], s_body)
            if source.get("conclusion"):
                document.add_paragraph(f"核心判断：{source.get('conclusion')}")

        risk = content_modules.get("risk_and_strategy") or {}
        problems = [str(x) for x in (risk.get("problems") or []) if str(x).strip()]
        dimensions = list(risk.get("dimensions") or [])
        if problems or dimensions:
            _section_title(document, "分维度优化建议")
            if problems:
                document.add_paragraph("当前主要待改进方向")
                _bullets(document, problems)
            for dim in dimensions:
                document.add_paragraph(str(dim.get("title") or ""))
                _bullets(document, [str(x) for x in (dim.get("actions") or [])])

        plan = content_modules.get("action_plan") or {}
        if plan.get("title"):
            _section_title(document, str(plan.get("title") or "下一周期品牌传播工作设想"))
            if plan.get("goals"):
                document.add_paragraph(f"努力方向（{plan.get('period_label') or '下一周期'}）")
                _bullets(document, [str(x) for x in plan.get("goals") or []])
            if plan.get("actions"):
                document.add_paragraph("重点推进事项")
                _bullets(document, [str(x) for x in plan.get("actions") or []])

    disclaimer = content_modules.get("disclaimer") or {}
    notes = [str(x) for x in (disclaimer.get("notes") or []) if str(x).strip()]
    if notes:
        _section_title(document, "报告备注说明")
        for i, note in enumerate(notes, 1):
            document.add_paragraph(f"{i}. {note}")

    footer = document.add_paragraph(f"报告出具时间：{generated.strftime('%Y年%m月%d日')}")
    for run in footer.runs:
        run.font.size = Pt(10)
        run.font.color.rgb = _MUTED_RGB

    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def _resolve_period_bounds(report: dict[str, Any]) -> tuple[date, date]:
    # 2026-08-06 - 导出 job 的 report 只有 report_content 内 period_*，与 normalize 对齐
    content = report.get("report_content") or {}
    period_start = _parse_report_date(report.get("period_start") or content.get("period_start"))
    period_end = _parse_report_date(report.get("period_end") or content.get("period_end"))
    if period_start is None or period_end is None:
        raise ValueError("period report missing period_start/period_end")
    return period_start, period_end


def build_period_deck_docx(db: Session, report: dict[str, Any], *, tenant_id: int) -> bytes:
    # 2026-08-06 - 周期 Word 与 HTML/PDF 同源 bundle，弃用 report_content_json 旧 A4 docx
    report_type = str(report.get("report_type") or "")
    if report_type not in PERIOD_COMPARISON_REPORT_TYPES:
        raise ValueError(f"unsupported period deck docx type: {report_type}")
    period_start, period_end = _resolve_period_bounds(report)
    content = report.get("report_content") or {}
    generated = _parse_report_date(
        report.get("generated_at") or content.get("generated_at") or report.get("created_at")
    )
    bundle = assemble_period_report_bundle(
        db,
        tenant_id=tenant_id,
        report_type=report_type,
        period_start=period_start,
        period_end=period_end,
        generated=generated,
        align_span=bool(report.get("manual_span")),
    )
    return render_period_deck_docx_from_bundle(bundle)
