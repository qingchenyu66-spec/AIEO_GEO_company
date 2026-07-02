"""将 GEO 报告导出为 PDF / Word 文档。"""

from __future__ import annotations

import io
import re
from typing import Any, Literal
from urllib.parse import quote

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.molizhishu_catalog_service import get_supported_platform_catalog

REPORT_TYPE_LABELS = {
    "diagnosis": "企业诊断",
    "weekly": "监测周报",
    "monthly": "监测月报",
    "annual": "监测年报",
    "comparison": "对比报告",
    "periodic": "周期报告",
}

PDF_FONT = "STSong-Light"
ExportFormat = Literal["pdf", "docx"]


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


def _normalize_export_payload(report: dict[str, Any]) -> dict[str, Any]:
    content = report.get("report_content") or {}
    kpis = content.get("kpis") or {}
    diagnosis = content.get("diagnosis") or {}
    snapshot = content.get("monitor_snapshot") or {}
    ai_insights = content.get("ai_insights") or {}
    health_score = diagnosis.get("health_score") or kpis.get("health_score")
    return {
        "title": report.get("report_title") or "GEO 监测报告",
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
        "ai_source": ai_insights.get("source"),
        "highlights": snapshot.get("highlights") or [],
        "diagnosis": diagnosis,
        "platform_stats": snapshot.get("platform_stats") or [],
        "top_sources": snapshot.get("top_sources") or [],
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
        fontSize=18,
        leading=24,
        textColor=colors.HexColor("#12385f"),
        spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontName=PDF_FONT,
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#58708f"),
        spaceAfter=6,
    )
    section_style = ParagraphStyle(
        "SectionTitle",
        parent=styles["Heading2"],
        fontName=PDF_FONT,
        fontSize=13,
        leading=18,
        textColor=colors.HexColor("#17406a"),
        spaceBefore=10,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName=PDF_FONT,
        fontSize=10,
        leading=15,
        textColor=colors.HexColor("#45627f"),
    )
    bullet_style = ParagraphStyle(
        "Bullet",
        parent=body_style,
        leftIndent=12,
        bulletIndent=0,
        spaceAfter=4,
    )

    story: list[Any] = []
    story.append(Paragraph(payload["title"], title_style))
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
        story.append(Paragraph("执行摘要", section_style))
        ai_note = "（DeepSeek 生成）" if payload.get("ai_source") == "deepseek" else ""
        story.append(Paragraph(f'{payload["executive_summary"]}{ai_note}', body_style))

    if payload["highlights"]:
        story.append(Paragraph("核心结论", section_style))
        for line in payload["highlights"]:
            story.append(Paragraph(f"• {line}", bullet_style))

    diagnosis = payload["diagnosis"]
    diagnosis_blocks = [
        ("口碑情绪", diagnosis.get("sentiment_summary")),
        ("优势亮点", diagnosis.get("strength_points")),
        ("待改善项", diagnosis.get("weakness_points")),
        ("优化建议", diagnosis.get("recommendation")),
    ]
    if any(text for _, text in diagnosis_blocks if text):
        story.append(Paragraph("品牌诊断", section_style))
        for heading, text in diagnosis_blocks:
            if not text:
                continue
            story.append(Paragraph(f"<b>{heading}</b>", body_style))
            story.append(Paragraph(str(text).replace("\n", "<br/>"), body_style))
            story.append(Spacer(1, 4))

    if payload["platform_stats"]:
        story.append(Paragraph("各平台表现", section_style))
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

    generated = payload["generated_at"]
    if generated:
        story.append(Spacer(1, 10))
        story.append(Paragraph(f"生成时间：{generated}", subtitle_style))

    doc.build(story)
    return buffer.getvalue()


def _set_docx_default_font(document: Document, font_name: str = "Microsoft YaHei") -> None:
    normal = document.styles["Normal"]
    normal.font.name = font_name
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), font_name)
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = RGBColor(0x45, 0x62, 0x7F)


def _add_docx_section_title(document: Document, text: str) -> None:
    paragraph = document.add_paragraph()
    run = paragraph.add_run(text)
    run.bold = True
    run.font.size = Pt(12)
    run.font.color.rgb = RGBColor(0x17, 0x40, 0x6A)


def _build_docx(payload: dict[str, Any], platform_names: dict[str, str]) -> bytes:
    document = Document()
    _set_docx_default_font(document)

    title = document.add_heading(payload["title"], level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    for run in title.runs:
        run.font.color.rgb = RGBColor(0x12, 0x38, 0x5F)

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
        _add_docx_section_title(document, "执行摘要")
        paragraph = document.add_paragraph(payload["executive_summary"])
        if payload.get("ai_source") == "deepseek":
            note = paragraph.add_run("（DeepSeek 生成）")
            note.font.color.rgb = RGBColor(0x2D, 0x6C, 0xDF)

    if payload["highlights"]:
        _add_docx_section_title(document, "核心结论")
        for line in payload["highlights"]:
            document.add_paragraph(line, style="List Bullet")

    diagnosis = payload["diagnosis"]
    diagnosis_blocks = [
        ("口碑情绪", diagnosis.get("sentiment_summary")),
        ("优势亮点", diagnosis.get("strength_points")),
        ("待改善项", diagnosis.get("weakness_points")),
        ("优化建议", diagnosis.get("recommendation")),
    ]
    if any(text for _, text in diagnosis_blocks if text):
        _add_docx_section_title(document, "品牌诊断")
        for heading, text in diagnosis_blocks:
            if not text:
                continue
            paragraph = document.add_paragraph()
            label = paragraph.add_run(f"{heading}：")
            label.bold = True
            paragraph.add_run(str(text))

    if payload["platform_stats"]:
        _add_docx_section_title(document, "各平台表现")
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

    if payload["generated_at"]:
        footer = document.add_paragraph(f"生成时间：{payload['generated_at']}")
        footer.runs[0].font.color.rgb = RGBColor(0x7A, 0x93, 0xB0)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def build_report_export(report: dict[str, Any], export_format: ExportFormat) -> tuple[bytes, str, str]:
    """返回文件内容、文件名、MIME 类型。"""
    payload = _normalize_export_payload(report)
    platform_names = _platform_label_map()
    if export_format == "pdf":
        content = _build_pdf(payload, platform_names)
        mime = "application/pdf"
    else:
        content = _build_docx(payload, platform_names)
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    filename = _safe_filename(payload["title"], export_format)
    return content, filename, mime


def content_disposition(filename: str) -> str:
    return f"attachment; filename*=UTF-8''{quote(filename)}"
