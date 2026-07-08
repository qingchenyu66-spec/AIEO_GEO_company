"""将 GEO 报告导出为 PDF / Word 文档。"""

from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Any, Literal
from urllib.parse import quote

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Image as PdfImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.molizhishu_catalog_service import get_supported_platform_catalog
from app.services.report_period_content_service import format_diagnosis_display_title
from app.services.report_chart_service import (
    build_entity_rank_trend_chart,
    build_mention_rate_bar_chart,
    build_platform_mention_chart,
    build_rank_trend_chart,
)

REPORT_TYPE_LABELS = {
    "diagnosis": "企业诊断",
    "weekly": "监测周报",
    "monthly": "监测月报",
    "quarterly": "监测季报",
    "annual": "监测年报",
    "comparison": "对比报告",
    "periodic": "周期报告",
}

PDF_FONT = "STSong-Light"
ExportFormat = Literal["pdf", "docx"]
REPORT_HERO_TAGLINE = "GEO 全平台监测 · 竞品对标 · 决策级诊断"
INSIGHT_SECTION_TITLE = "核心洞察"
INSIGHT_SECTION_SUBTITLE = "基于多轮抓取、语义词矩阵与引用信源交叉验证"
ANALYSIS_SECTION_TITLE = "数据分析与优化建议"
REPORT_FOOTER_NOTE = "本报告由 GEO Monitor 售前诊断引擎输出，仅供售前研判与客户沟通使用。"
REPORT_SECTION_TITLES = [
    ("industry_analysis", "1. 行业分析"),
    ("ranking_analysis", "2. 排名分析"),
    ("mention_analysis", "3. 提及率分析"),
    ("source_analysis", "4. 引用网站分析"),
    ("action_recommendations", "5. 优化建议"),
]


def _register_pdf_font() -> None:
    if PDF_FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(PDF_FONT))


def _platform_label_map() -> dict[str, str]:
    return {
        str(item.get("code") or ""): str(item.get("name") or item.get("code") or "")
        for item in get_supported_platform_catalog()
    }


def _platform_label(code: str, names: dict[str, str]) -> str:
    return names.get(code) or code


def _safe_filename(title: str, suffix: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\s]+', "_", title.strip())
    cleaned = cleaned.strip("._") or "geo_report"
    return f"{cleaned[:72]}.{suffix}"


def _format_rank(value: Any) -> str:
    if value is None or value == "":
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return f"#{int(number)}"
    return f"#{number:.1f}"


def _format_report_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return moment.strftime("%Y年%m月%d日 %H:%M")
    except ValueError:
        return text[:19]


def _split_narrative_paragraphs(text: Any) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    numbered = [part.strip() for part in re.split(r"(?=\d+\.\s)", raw) if part.strip()]
    if len(numbered) > 1:
        return numbered
    if raw.count("；") >= 2:
        chunks: list[str] = []
        for part in raw.split("；"):
            cleaned = part.strip()
            if not cleaned:
                continue
            if not cleaned.endswith(("。", "！", "？", "；")):
                cleaned += "。"
            chunks.append(cleaned)
        return chunks
    lines = [line.strip() for line in re.split(r"\n+", raw) if line.strip()]
    return lines or [raw]


def _has_report_sections(sections: dict[str, Any]) -> bool:
    return any(str(sections.get(key) or "").strip() for key, _ in REPORT_SECTION_TITLES)


def _append_pdf_narrative_sections(
    story: list[Any],
    sections: dict[str, Any],
    *,
    section_style: ParagraphStyle,
    subheading_style: ParagraphStyle,
    body_style: ParagraphStyle,
    intro: str | None = None,
) -> None:
    if not _has_report_sections(sections):
        return
    story.append(Spacer(1, 4))
    story.append(Paragraph(ANALYSIS_SECTION_TITLE, section_style))
    if intro:
        story.append(Paragraph(intro, body_style))
        story.append(Spacer(1, 4))
    for index, (key, title) in enumerate(REPORT_SECTION_TITLES):
        text = str(sections.get(key) or "").strip()
        if not text:
            continue
        if index:
            story.append(Spacer(1, 6))
        story.append(Paragraph(title, subheading_style))
        for paragraph in _split_narrative_paragraphs(text):
            story.append(Paragraph(paragraph.replace("\n", "<br/>"), body_style))
    story.append(Spacer(1, 8))


def _append_docx_narrative_sections(document: Document, sections: dict[str, Any], *, intro: str | None = None) -> None:
    if not _has_report_sections(sections):
        return
    _add_docx_section_title(document, ANALYSIS_SECTION_TITLE)
    if intro:
        hint = document.add_paragraph(intro)
        hint.runs[0].font.color.rgb = RGBColor(0x58, 0x70, 0x8F)
        hint.runs[0].font.size = Pt(10)
    for key, title in REPORT_SECTION_TITLES:
        text = str(sections.get(key) or "").strip()
        if not text:
            continue
        heading = document.add_paragraph()
        heading_run = heading.add_run(title)
        heading_run.bold = True
        heading_run.font.color.rgb = RGBColor(0x22, 0x72, 0xD9)
        heading_run.font.size = Pt(12.5)
        for paragraph in _split_narrative_paragraphs(text):
            body = document.add_paragraph(paragraph)
            body.paragraph_format.left_indent = Pt(6)
            body.paragraph_format.space_after = Pt(6)
            for run in body.runs:
                run.font.color.rgb = RGBColor(0x33, 0x4E, 0x6F)


def _append_pdf_insight_block(
    story: list[Any],
    *,
    title: str,
    subtitle: str,
    body: str,
    section_style: ParagraphStyle,
    subtitle_style: ParagraphStyle,
    body_style: ParagraphStyle,
) -> None:
    story.append(Paragraph(title, section_style))
    if subtitle:
        story.append(Paragraph(subtitle, subtitle_style))
    card = Table([[Paragraph(body.replace("\n", "<br/>"), body_style)]], colWidths=[174 * mm])
    card.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f4f9ff")),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#c7dcf5")),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.append(card)
    story.append(Spacer(1, 8))


def _append_docx_insight_block(document: Document, *, title: str, subtitle: str, body: str) -> None:
    _add_docx_section_title(document, title)
    if subtitle:
        hint = document.add_paragraph(subtitle)
        hint.runs[0].font.color.rgb = RGBColor(0x58, 0x70, 0x8F)
        hint.runs[0].font.size = Pt(10)
    paragraph = document.add_paragraph(body)
    paragraph.paragraph_format.left_indent = Pt(8)
    paragraph.paragraph_format.space_before = Pt(4)
    paragraph.paragraph_format.space_after = Pt(8)
    for run in paragraph.runs:
        run.font.color.rgb = RGBColor(0x33, 0x4E, 0x6F)


def _append_png_to_pdf(story: list[Any], png_bytes: bytes | None, *, width_mm: float = 170, height_mm: float = 72) -> None:
    if not png_bytes:
        return
    story.append(PdfImage(io.BytesIO(png_bytes), width=width_mm * mm, height=height_mm * mm))
    story.append(Spacer(1, 6))


def _append_png_to_docx(document: Document, png_bytes: bytes | None, *, width_inches: float = 6.3) -> None:
    if not png_bytes:
        return
    document.add_picture(io.BytesIO(png_bytes), width=Inches(width_inches))
    document.add_paragraph("")


def _rank_cell_bg(rank: Any) -> colors.Color | None:
    try:
        value = float(rank)
    except (TypeError, ValueError):
        return None
    if value <= 3:
        return colors.HexColor("#dcfce7")
    if value <= 5:
        return colors.HexColor("#fef9c3")
    return colors.HexColor("#ffedd5")


def _normalize_export_payload(report: dict[str, Any]) -> dict[str, Any]:
    content = report.get("report_content") or {}
    kpis = content.get("kpis") or {}
    diagnosis = content.get("diagnosis") or {}
    snapshot = content.get("monitor_snapshot") or {}
    ai_insights = content.get("ai_insights") or {}
    health_score = diagnosis.get("health_score") or kpis.get("health_score")
    report_type = str(report.get("report_type") or "")
    title = report.get("report_title") or "GEO 监测报告"
    if report_type == "diagnosis":
        title = format_diagnosis_display_title(title)
    return {
        "title": title,
        "type_label": report.get("report_type_label") or REPORT_TYPE_LABELS.get(report.get("report_type"), "报告"),
        "status_label": report.get("status_label") or report.get("status") or "",
        "tenant_name": report.get("tenant_name") or "",
        "summary": report.get("data_summary") or "",
        "period_label": content.get("period_label") or "",
        "brand_name": content.get("brand_name") or report.get("tenant_name") or "",
        "company_name": content.get("company_name") or "",
        "generated_at": content.get("generated_at") or report.get("created_at") or "",
        "health_score": health_score,
        "mention_rate": kpis.get("mention_rate"),
        "avg_rank": kpis.get("avg_rank"),
        "top3_rate": kpis.get("top3_rate"),
        "positive_rate": kpis.get("positive_rate"),
        "completed_count": kpis.get("completed_count"),
        "source_count": kpis.get("source_count"),
        "executive_summary": ai_insights.get("executive_summary"),
        "highlights": snapshot.get("highlights") or [],
        "diagnosis": diagnosis,
        "platform_stats": snapshot.get("platform_stats") or [],
        "top_sources": snapshot.get("top_sources") or [],
        "prompt_analytics": snapshot.get("prompt_analytics") or [],
        "source_analysis": snapshot.get("source_analysis") or {},
        "rank_trend": snapshot.get("rank_trend") or [],
        "tracked_entities": snapshot.get("tracked_entities") or [],
        "brand_city_rankings": snapshot.get("brand_city_rankings") or [],
        "report_sections": content.get("report_sections") or {},
        "premium_content": content.get("premium_content") or {},
        "report_modules": content.get("report_modules") or {},
        "report_type": report.get("report_type") or "",
        "period_start": content.get("period_start"),
        "period_end": content.get("period_end"),
        "sentiment_counts": snapshot.get("sentiment_counts") or {},
    }

def _build_pdf(payload: dict[str, Any], platform_names: dict[str, str]) -> bytes:
    _register_pdf_font()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=payload["title"],
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontName=PDF_FONT,
        fontSize=20,
        leading=28,
        textColor=colors.HexColor("#12385f"),
        spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontName=PDF_FONT,
        fontSize=11,
        leading=16,
        textColor=colors.HexColor("#58708f"),
        spaceAfter=6,
    )
    section_style = ParagraphStyle(
        "SectionTitle",
        parent=styles["Heading2"],
        fontName=PDF_FONT,
        fontSize=15,
        leading=21,
        textColor=colors.HexColor("#17406a"),
        spaceBefore=10,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName=PDF_FONT,
        fontSize=11.5,
        leading=17,
        textColor=colors.HexColor("#45627f"),
    )
    bullet_style = ParagraphStyle(
        "Bullet",
        parent=body_style,
        leftIndent=14,
        bulletIndent=0,
        spaceAfter=6,
        leading=16,
    )
    subheading_style = ParagraphStyle(
        "Subheading",
        parent=body_style,
        fontSize=12.5,
        leading=18,
        textColor=colors.HexColor("#17406a"),
        spaceBefore=4,
        spaceAfter=6,
    )
    lead_style = ParagraphStyle(
        "Lead",
        parent=body_style,
        fontSize=12,
        leading=19,
        textColor=colors.HexColor("#334e6f"),
        spaceAfter=8,
    )

    tagline_style = ParagraphStyle(
        "ReportTagline",
        parent=subtitle_style,
        fontSize=10.5,
        leading=15,
        textColor=colors.HexColor("#2272d9"),
        spaceAfter=8,
    )
    footer_style = ParagraphStyle(
        "ReportFooter",
        parent=subtitle_style,
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor("#8aa0ba"),
        spaceBefore=6,
    )

    story: list[Any] = []
    story.append(Paragraph(payload["title"], title_style))
    story.append(Paragraph(REPORT_HERO_TAGLINE, tagline_style))
    meta_bits = [payload["type_label"], payload["period_label"], payload["tenant_name"]]
    story.append(Paragraph(" · ".join(item for item in meta_bits if item), subtitle_style))
    if payload["summary"]:
        story.append(Paragraph(payload["summary"], body_style))
    story.append(Spacer(1, 8))

    kpi_rows = [
        ["健康分", "品牌提及率", "平均排名", "引用信源"],
        [
            str(payload["health_score"] if payload["health_score"] is not None else "—"),
            f'{payload["mention_rate"]}%' if payload["mention_rate"] is not None else "—",
            _format_rank(payload["avg_rank"]),
            str(payload["source_count"] if payload["source_count"] is not None else "0"),
        ],
    ]
    kpi_table = Table(kpi_rows, colWidths=[40 * mm, 40 * mm, 40 * mm, 40 * mm])
    kpi_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), PDF_FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef4fb")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#58708f")),
                ("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor("#12385f")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9e8f6")),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(kpi_table)

    if payload.get("executive_summary"):
        _append_pdf_insight_block(
            story,
            title=INSIGHT_SECTION_TITLE,
            subtitle=INSIGHT_SECTION_SUBTITLE,
            body=str(payload["executive_summary"]),
            section_style=section_style,
            subtitle_style=subtitle_style,
            body_style=lead_style,
        )

    diagnosis = payload["diagnosis"]
    sections = payload.get("report_sections") or {}
    if not payload.get("executive_summary") and diagnosis.get("sentiment_summary"):
        _append_pdf_insight_block(
            story,
            title=INSIGHT_SECTION_TITLE,
            subtitle=INSIGHT_SECTION_SUBTITLE,
            body=str(diagnosis["sentiment_summary"]),
            section_style=section_style,
            subtitle_style=subtitle_style,
            body_style=lead_style,
        )

    if payload["highlights"]:
        story.append(Paragraph("核心发现", section_style))
        for line in payload["highlights"]:
            story.append(Paragraph(f"• {line}", bullet_style))
        story.append(Spacer(1, 6))

    if _has_report_sections(sections):
        _append_pdf_narrative_sections(
            story,
            sections,
            section_style=section_style,
            subheading_style=subheading_style,
            body_style=body_style,
            intro="基于监测样本、竞品对标与引用信源交叉分析，形成可落地的优化路径。",
        )
    else:
        fallback_blocks = [
            ("优势亮点", diagnosis.get("strength_points")),
            ("待改善项", diagnosis.get("weakness_points")),
            ("GEO 优化建议", diagnosis.get("recommendation")),
        ]
        fallback_sections = {
            "industry_analysis": diagnosis.get("sentiment_summary"),
            "action_recommendations": next((text for _, text in fallback_blocks if text), None),
        }
        if any(str(fallback_sections.get(key) or "").strip() for key in fallback_sections):
            _append_pdf_narrative_sections(
                story,
                {key: value for key, value in fallback_sections.items() if value},
                section_style=section_style,
                subheading_style=subheading_style,
                body_style=body_style,
            )
        else:
            for heading, text in fallback_blocks:
                if not text:
                    continue
                story.append(Paragraph(str(heading), subheading_style))
                for paragraph in _split_narrative_paragraphs(text):
                    story.append(Paragraph(paragraph, body_style))
                story.append(Spacer(1, 6))

    if payload["platform_stats"]:
        story.append(Paragraph("各平台表现", section_style))
        platform_chart = build_platform_mention_chart(payload["platform_stats"])
        _append_png_to_pdf(story, platform_chart)
        platform_rows = [["平台", "完成数", "提及率", "平均排名"]]
        for row in payload["platform_stats"]:
            platform_rows.append(
                [
                    _platform_label(str(row.get("platform") or ""), platform_names),
                    f'{row.get("completed")}/{row.get("total")}',
                    f'{row.get("mention_rate")}%',
                    _format_rank(row.get("avg_rank")),
                ]
            )
        platform_table = Table(platform_rows, colWidths=[45 * mm, 30 * mm, 30 * mm, 35 * mm])
        platform_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), PDF_FONT),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef4fb")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9e8f6")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(platform_table)

    rank_trend = payload.get("rank_trend") or []
    if rank_trend:
        story.append(Paragraph("平均排名趋势图", section_style))
        story.append(Paragraph("品牌及竞品平均排名", body_style))
        entity_chart = build_entity_rank_trend_chart(
            rank_trend,
            brand=payload.get("brand_name") or payload.get("tenant_name") or "",
            tracked_entities=payload.get("tracked_entities") or [],
            title="平均排名趋势图",
            subtitle="品牌及竞品平均排名",
        )
        _append_png_to_pdf(story, entity_chart, height_mm=82)
        story.append(Paragraph("各轮次明细如下（排名越小越靠前）：", body_style))
        trend_rows = [["轮次", "样本", "提及率", "平均排名"]]
        for row in rank_trend:
            trend_rows.append([
                str(row.get("schedule_label") or row.get("schedule_key") or "—"),
                str(row.get("sample_count") or 0),
                f'{row.get("mention_rate")}%',
                _format_rank(row.get("avg_rank")),
            ])
        trend_table = Table(trend_rows, colWidths=[55 * mm, 25 * mm, 25 * mm, 35 * mm])
        trend_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), PDF_FONT),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef4fb")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9e8f6")),
                    *[
                        ("BACKGROUND", (3, row_index), (3, row_index), bg)
                        for row_index, row in enumerate(rank_trend, start=1)
                        if (bg := _rank_cell_bg(row.get("avg_rank"))) is not None
                    ],
                ]
            )
        )
        story.append(trend_table)
        story.append(Spacer(1, 6))

    city_rankings = payload.get("brand_city_rankings") or []
    if city_rankings:
        story.append(Paragraph("品牌区域排名", section_style))
        story.append(Paragraph("按监测地区汇总的品牌与竞品平均排名、提及率。", body_style))
        for block in city_rankings:
            region_name = str(block.get("region_name") or "全部区域")
            story.append(Paragraph(f"监测地区：{region_name}（样本 {block.get('sample_count') or 0}）", body_style))
            rows = block.get("rows") or []
            if not rows:
                continue
            table_rows = [["品牌", "提及率", "平均排名"]]
            for row in rows:
                name = str(row.get("name") or "—")
                if row.get("is_brand"):
                    name = f"{name}（本品牌）"
                table_rows.append([
                    name,
                    f'{row.get("mention_rate")}%',
                    _format_rank(row.get("avg_rank")),
                ])
            city_table = Table(table_rows, colWidths=[70 * mm, 30 * mm, 30 * mm])
            city_table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), PDF_FONT),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef4fb")),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9e8f6")),
                    ]
                )
            )
            story.append(city_table)
            story.append(Spacer(1, 4))

    for prompt_index, prompt_block in enumerate(payload.get("prompt_analytics") or [], start=1):
        prompt = str(prompt_block.get("prompt") or "")
        if not prompt:
            continue
        story.append(Paragraph(f"语义词 {prompt_index}：{prompt}", section_style))
        summary_bits = [
            f"样本 {prompt_block.get('sample_count') or 0}",
            f"品牌提及率 {prompt_block.get('brand_mention_rate')}%",
            f"平均排名 {_format_rank(prompt_block.get('brand_avg_rank'))}",
        ]
        story.append(Paragraph(" · ".join(summary_bits), body_style))

        round_trend = prompt_block.get("round_trend") or []
        if round_trend:
            story.append(Paragraph(f"问题{prompt_index}趋势图", body_style))
            prompt_trend_chart = build_entity_rank_trend_chart(
                round_trend,
                brand=payload.get("brand_name") or payload.get("tenant_name") or "",
                tracked_entities=payload.get("tracked_entities") or [],
                title=f"问题{prompt_index}趋势图",
                subtitle=prompt[:48] + ("…" if len(prompt) > 48 else ""),
            )
            _append_png_to_pdf(story, prompt_trend_chart, height_mm=78)

            story.append(Paragraph("品牌排名变化趋势", body_style))
            change_rows = [["日期", prompt[:36] + ("…" if len(prompt) > 36 else "")]]
            change_styles: list[tuple] = []
            for row_index, row in enumerate(round_trend, start=1):
                change_rows.append([
                    str(row.get("schedule_label") or row.get("schedule_key") or "—"),
                    _format_rank(row.get("avg_rank")),
                ])
                bg = _rank_cell_bg(row.get("avg_rank"))
                if bg is not None:
                    change_styles.append(("BACKGROUND", (1, row_index), (1, row_index), bg))
            change_table = Table(change_rows, colWidths=[55 * mm, 35 * mm])
            change_table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), PDF_FONT),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef4fb")),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9e8f6")),
                        *change_styles,
                    ]
                )
            )
            story.append(change_table)
            story.append(Spacer(1, 6))

        mention_table = prompt_block.get("mention_table") or []
        if mention_table:
            story.append(Paragraph("品牌提及率分析", body_style))
            mention_chart = build_mention_rate_bar_chart(
                mention_table,
                title=f"语义词：{prompt[:40]}",
                brand=payload.get("brand_name") or payload.get("tenant_name") or "",
            )
            _append_png_to_pdf(story, mention_chart, height_mm=max(72, min(120, len(mention_table[:12]) * 8)))
            rows = [["品牌", "提及次数", "提及率", "平均排名"]]
            for row in mention_table[:10]:
                marker = " ★" if row.get("is_brand") else (" ◆" if row.get("is_competitor") else "")
                rows.append([
                    f'{row.get("name")}{marker}',
                    f'{row.get("mention_count")}/{row.get("sample_count")}',
                    f'{row.get("mention_rate")}%',
                    _format_rank(row.get("avg_rank")),
                ])
            table = Table(rows, colWidths=[55 * mm, 30 * mm, 25 * mm, 30 * mm])
            table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), PDF_FONT),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef4fb")),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9e8f6")),
                    ]
                )
            )
            story.append(table)
            story.append(Spacer(1, 6))

    source_analysis = payload.get("source_analysis") or {}
    if source_analysis.get("coverage_note"):
        story.append(Paragraph("引用信源覆盖", section_style))
        story.append(Paragraph(str(source_analysis["coverage_note"]), body_style))
        domain_stats = source_analysis.get("domain_stats") or []
        if domain_stats:
            domain_rows = [["域名", "引用次数", "品牌相关"]]
            for row in domain_stats[:10]:
                domain_rows.append([
                    str(row.get("domain") or "—"),
                    str(row.get("count") or 0),
                    str(row.get("brand_related_count") or 0),
                ])
            domain_table = Table(domain_rows, colWidths=[90 * mm, 30 * mm, 30 * mm])
            domain_table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), PDF_FONT),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef4fb")),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9e8f6")),
                    ]
                )
            )
            story.append(domain_table)

    if payload["top_sources"]:
        story.append(Paragraph("高频引用信源", section_style))
        source_rows = [["序号", "标题", "引用次数"]]
        for index, row in enumerate(payload["top_sources"], start=1):
            title = str(row.get("title") or row.get("url") or "—")
            if len(title) > 48:
                title = title[:47] + "…"
            source_rows.append([str(index), title, str(row.get("count") or 0)])
        source_table = Table(source_rows, colWidths=[14 * mm, 110 * mm, 24 * mm])
        source_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), PDF_FONT),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef4fb")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9e8f6")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(source_table)

    generated = _format_report_timestamp(payload["generated_at"])
    story.append(Spacer(1, 10))
    if generated:
        story.append(Paragraph(f"报告出具时间：{generated}", footer_style))
    story.append(Paragraph(REPORT_FOOTER_NOTE, footer_style))

    doc.build(story)
    return buffer.getvalue()


def _set_docx_default_font(document: Document, font_name: str = "Microsoft YaHei") -> None:
    normal = document.styles["Normal"]
    normal.font.name = font_name
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), font_name)
    normal.font.size = Pt(12)
    normal.font.color.rgb = RGBColor(0x45, 0x62, 0x7F)


def _add_docx_section_title(document: Document, text: str) -> None:
    paragraph = document.add_paragraph()
    run = paragraph.add_run(text)
    run.bold = True
    run.font.size = Pt(14)
    run.font.color.rgb = RGBColor(0x17, 0x40, 0x6A)


def _build_docx(payload: dict[str, Any], platform_names: dict[str, str]) -> bytes:
    document = Document()
    _set_docx_default_font(document)

    title = document.add_heading(payload["title"], level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    for run in title.runs:
        run.font.color.rgb = RGBColor(0x12, 0x38, 0x5F)

    tagline = document.add_paragraph(REPORT_HERO_TAGLINE)
    tagline.runs[0].font.color.rgb = RGBColor(0x22, 0x72, 0xD9)
    tagline.runs[0].font.size = Pt(10.5)

    meta = " · ".join(item for item in [payload["type_label"], payload["period_label"], payload["tenant_name"]] if item)
    if meta:
        meta_paragraph = document.add_paragraph(meta)
        meta_paragraph.runs[0].font.color.rgb = RGBColor(0x58, 0x70, 0x8F)
    if payload["summary"]:
        document.add_paragraph(payload["summary"])

    kpi_table = document.add_table(rows=2, cols=4)
    kpi_table.style = "Table Grid"
    headers = ["健康分", "品牌提及率", "平均排名", "引用信源"]
    values = [
        str(payload["health_score"] if payload["health_score"] is not None else "—"),
        f'{payload["mention_rate"]}%' if payload["mention_rate"] is not None else "—",
        _format_rank(payload["avg_rank"]),
        str(payload["source_count"] if payload["source_count"] is not None else "0"),
    ]
    for index, label in enumerate(headers):
        kpi_table.rows[0].cells[index].text = label
        kpi_table.rows[1].cells[index].text = values[index]

    if payload.get("executive_summary"):
        _append_docx_insight_block(
            document,
            title=INSIGHT_SECTION_TITLE,
            subtitle=INSIGHT_SECTION_SUBTITLE,
            body=str(payload["executive_summary"]),
        )

    if payload["highlights"]:
        _add_docx_section_title(document, "核心发现")
        for line in payload["highlights"]:
            document.add_paragraph(line, style="List Bullet")

    diagnosis = payload["diagnosis"]
    sections = payload.get("report_sections") or {}
    if not payload.get("executive_summary") and diagnosis.get("sentiment_summary"):
        _append_docx_insight_block(
            document,
            title=INSIGHT_SECTION_TITLE,
            subtitle=INSIGHT_SECTION_SUBTITLE,
            body=str(diagnosis["sentiment_summary"]),
        )

    if _has_report_sections(sections):
        _append_docx_narrative_sections(
            document,
            sections,
            intro="基于监测样本、竞品对标与引用信源交叉分析，形成可落地的优化路径。",
        )
    elif any(diagnosis.get(key) for key in ("strength_points", "weakness_points", "recommendation")):
        fallback = {
            "ranking_analysis": diagnosis.get("strength_points"),
            "mention_analysis": diagnosis.get("weakness_points"),
            "action_recommendations": diagnosis.get("recommendation"),
        }
        _append_docx_narrative_sections(document, fallback)

    if payload["platform_stats"]:
        _add_docx_section_title(document, "各平台表现")
        platform_chart = build_platform_mention_chart(payload["platform_stats"])
        _append_png_to_docx(document, platform_chart)
        table = document.add_table(rows=1, cols=4)
        table.style = "Table Grid"
        headers = ["平台", "完成数", "提及率", "平均排名"]
        for index, label in enumerate(headers):
            table.rows[0].cells[index].text = label
        for row in payload["platform_stats"]:
            cells = table.add_row().cells
            cells[0].text = _platform_label(str(row.get("platform") or ""), platform_names)
            cells[1].text = f'{row.get("completed")}/{row.get("total")}'
            cells[2].text = f'{row.get("mention_rate")}%'
            cells[3].text = _format_rank(row.get("avg_rank"))

    rank_trend = payload.get("rank_trend") or []
    if rank_trend:
        _add_docx_section_title(document, "平均排名趋势图")
        entity_chart = build_entity_rank_trend_chart(
            rank_trend,
            brand=payload.get("brand_name") or payload.get("tenant_name") or "",
            tracked_entities=payload.get("tracked_entities") or [],
            title="平均排名趋势图",
            subtitle="品牌及竞品平均排名",
        )
        _append_png_to_docx(document, entity_chart)
        document.add_paragraph("各轮次明细如下（排名越小越靠前）：")
        table = document.add_table(rows=1, cols=4)
        table.style = "Table Grid"
        for index, label in enumerate(["轮次", "样本", "提及率", "平均排名"]):
            table.rows[0].cells[index].text = label
        for row in rank_trend:
            cells = table.add_row().cells
            cells[0].text = str(row.get("schedule_label") or row.get("schedule_key") or "—")
            cells[1].text = str(row.get("sample_count") or 0)
            cells[2].text = f'{row.get("mention_rate")}%'
            cells[3].text = _format_rank(row.get("avg_rank"))

    city_rankings = payload.get("brand_city_rankings") or []
    if city_rankings:
        _add_docx_section_title(document, "品牌区域排名")
        document.add_paragraph("按监测地区汇总的品牌与竞品平均排名、提及率。")
        for block in city_rankings:
            region_name = str(block.get("region_name") or "全部区域")
            document.add_paragraph(f"监测地区：{region_name}（样本 {block.get('sample_count') or 0}）")
            rows = block.get("rows") or []
            if not rows:
                continue
            table = document.add_table(rows=1, cols=3)
            table.style = "Table Grid"
            for index, label in enumerate(["品牌", "提及率", "平均排名"]):
                table.rows[0].cells[index].text = label
            for row in rows:
                cells = table.add_row().cells
                name = str(row.get("name") or "—")
                if row.get("is_brand"):
                    name = f"{name}（本品牌）"
                cells[0].text = name
                cells[1].text = f'{row.get("mention_rate")}%'
                cells[2].text = _format_rank(row.get("avg_rank"))

    for prompt_index, prompt_block in enumerate(payload.get("prompt_analytics") or [], start=1):
        prompt = str(prompt_block.get("prompt") or "")
        if not prompt:
            continue
        _add_docx_section_title(document, f"语义词 {prompt_index}：{prompt}")
        document.add_paragraph(
            f"样本 {prompt_block.get('sample_count') or 0} · "
            f"品牌提及率 {prompt_block.get('brand_mention_rate')}% · "
            f"平均排名 {_format_rank(prompt_block.get('brand_avg_rank'))}"
        )
        round_trend = prompt_block.get("round_trend") or []
        if round_trend:
            prompt_trend_chart = build_entity_rank_trend_chart(
                round_trend,
                brand=payload.get("brand_name") or payload.get("tenant_name") or "",
                tracked_entities=payload.get("tracked_entities") or [],
                title=f"问题{prompt_index}趋势图",
                subtitle=prompt[:48],
            )
            _append_png_to_docx(document, prompt_trend_chart)
        mention_table = prompt_block.get("mention_table") or []
        if mention_table:
            mention_chart = build_mention_rate_bar_chart(
                mention_table,
                title=f"语义词：{prompt[:40]}",
                brand=payload.get("brand_name") or payload.get("tenant_name") or "",
            )
            _append_png_to_docx(document, mention_chart)
            table = document.add_table(rows=1, cols=4)
            table.style = "Table Grid"
            for index, label in enumerate(["品牌", "提及次数", "提及率", "平均排名"]):
                table.rows[0].cells[index].text = label
            for row in mention_table[:10]:
                cells = table.add_row().cells
                marker = " ★" if row.get("is_brand") else (" ◆" if row.get("is_competitor") else "")
                cells[0].text = f'{row.get("name")}{marker}'
                cells[1].text = f'{row.get("mention_count")}/{row.get("sample_count")}'
                cells[2].text = f'{row.get("mention_rate")}%'
                cells[3].text = _format_rank(row.get("avg_rank"))

    source_analysis = payload.get("source_analysis") or {}
    if source_analysis.get("coverage_note"):
        _add_docx_section_title(document, "引用信源覆盖")
        document.add_paragraph(str(source_analysis["coverage_note"]))

    if payload["top_sources"]:
        _add_docx_section_title(document, "高频引用信源")
        table = document.add_table(rows=1, cols=3)
        table.style = "Table Grid"
        for index, label in enumerate(["序号", "标题", "引用次数"]):
            table.rows[0].cells[index].text = label
        for index, row in enumerate(payload["top_sources"], start=1):
            cells = table.add_row().cells
            cells[0].text = str(index)
            cells[1].text = str(row.get("title") or row.get("url") or "—")
            cells[2].text = str(row.get("count") or 0)

    generated = _format_report_timestamp(payload["generated_at"])
    if generated:
        footer = document.add_paragraph(f"报告出具时间：{generated}")
        footer.runs[0].font.color.rgb = RGBColor(0x8A, 0xA0, 0xBA)
        footer.runs[0].font.size = Pt(10.5)
    note = document.add_paragraph(REPORT_FOOTER_NOTE)
    note.runs[0].font.color.rgb = RGBColor(0x8A, 0xA0, 0xBA)
    note.runs[0].font.size = Pt(10.5)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def build_report_export(report: dict[str, Any], export_format: ExportFormat) -> tuple[bytes, str, str]:
    """返回文件内容、文件名、MIME 类型。"""
    payload = _normalize_export_payload(report)
    platform_names = _platform_label_map()
    if export_format == "pdf":
        content = _build_pdf_premium_or_fallback(payload, platform_names)
        mime = "application/pdf"
    else:
        content = _build_docx(payload, platform_names)
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    filename = _safe_filename(payload["title"], export_format)
    return content, filename, mime


def _build_pdf_premium_or_fallback(payload: dict[str, Any], platform_names: dict[str, str]) -> bytes:
    """优先 Premium 深色模板；Playwright 不可用时回退 ReportLab。"""
    import logging

    from app.services.report_premium_context_service import enrich_export_payload_for_premium
    from app.services.report_premium_pdf_service import build_premium_pdf

    logger = logging.getLogger(__name__)
    enriched = enrich_export_payload_for_premium(payload, report_type=payload.get("report_type"))
    try:
        return build_premium_pdf(enriched)
    except Exception as exc:
        logger.warning("Premium PDF 生成失败，回退 ReportLab：%s", exc)
        return _build_pdf(enriched, platform_names)


def content_disposition(filename: str) -> str:
    return f"attachment; filename*=UTF-8''{quote(filename)}"
