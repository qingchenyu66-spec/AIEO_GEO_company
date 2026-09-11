"""知识库原版预览：统一产出 PDF（优先 LibreOffice，否则 Playwright / reportlab）。"""

from __future__ import annotations

import html
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_SOFFICE_CANDIDATES = (
    Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
    Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
    Path("/usr/bin/soffice"),
    Path("/usr/bin/libreoffice"),
)


class KnowledgePreviewPdfError(ValueError):
    """预览 PDF 生成失败。"""


def preview_cache_path(source_path: Path) -> Path:
    return source_path.with_suffix(source_path.suffix + ".preview.pdf")


def resolve_soffice_binary() -> str | None:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    for path in _SOFFICE_CANDIDATES:
        if path.is_file():
            return str(path)
    return None


def ensure_knowledge_preview_pdf(source_path: Path, file_ext: str | None) -> Path:
    """返回可内嵌预览的 PDF 路径；PDF 原文件直接返回，其它类型写入旁路缓存。"""
    if not source_path.is_file():
        raise KnowledgePreviewPdfError("文件不存在于存储目录")
    ext = (file_ext or source_path.suffix.lstrip(".")).lower().strip()
    if ext == "pdf":
        return source_path

    cache = preview_cache_path(source_path)
    if cache.is_file() and cache.stat().st_mtime >= source_path.stat().st_mtime:
        return cache

    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = cache.with_suffix(".tmp.pdf")
    try:
        if tmp_out.exists():
            tmp_out.unlink()
        _convert_to_pdf(source_path, ext, tmp_out)
        if not tmp_out.is_file() or tmp_out.stat().st_size <= 0:
            raise KnowledgePreviewPdfError("预览 PDF 生成结果为空")
        tmp_out.replace(cache)
    except Exception:
        tmp_out.unlink(missing_ok=True)
        raise
    return cache


def _convert_to_pdf(source_path: Path, ext: str, out_pdf: Path) -> None:
    soffice = resolve_soffice_binary()
    if soffice and ext in {"doc", "docx", "md", "txt", "odt", "rtf", "ppt", "pptx", "html", "htm"}:
        try:
            _convert_with_soffice(soffice, source_path, out_pdf)
            return
        except Exception as exc:
            logger.warning("LibreOffice 转换失败，改用内置回退: %s", exc)

    if ext == "docx":
        _convert_docx_with_playwright(source_path, out_pdf)
        return
    if ext == "pptx":
        _convert_pptx_with_playwright(source_path, out_pdf)
        return
    if ext in {"html", "htm"}:
        _convert_html_with_playwright(source_path, out_pdf)
        return
    if ext in {"png", "jpg", "jpeg", "webp"}:
        _convert_image_with_reportlab(source_path, out_pdf)
        return
    if ext in {"md", "txt"}:
        _convert_plain_with_reportlab(source_path, out_pdf)
        return
    if ext == "doc":
        raise KnowledgePreviewPdfError(
            "旧版 .doc 暂不支持原版预览，请转为 .docx 后上传，或在服务器安装 LibreOffice"
        )
    if ext == "ppt":
        raise KnowledgePreviewPdfError(
            "旧版 .ppt 暂不支持原版预览，请转为 .pptx 后上传，或在服务器安装 LibreOffice"
        )
    raise KnowledgePreviewPdfError(f"暂不支持预览该格式: .{ext}")


def _convert_with_soffice(soffice: str, source_path: Path, out_pdf: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="kb-preview-") as tmp:
        tmp_dir = Path(tmp)
        cmd = [
            soffice,
            "--headless",
            "--nologo",
            "--nolockcheck",
            "--nodefault",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            str(tmp_dir),
            str(source_path),
        ]
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()[:300]
            raise KnowledgePreviewPdfError(detail or "LibreOffice 转换失败")
        produced = list(tmp_dir.glob("*.pdf"))
        if not produced:
            raise KnowledgePreviewPdfError("LibreOffice 未产出 PDF")
        shutil.copyfile(produced[0], out_pdf)


def _html_to_pdf_bytes(page_html: str) -> bytes:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise KnowledgePreviewPdfError("缺少 Playwright，无法生成预览 PDF") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                java_script_enabled=False,
                viewport={"width": 900, "height": 1200},
            )
            page = context.new_page()
            page.set_content(page_html, wait_until="domcontentloaded", timeout=60_000)
            try:
                page.evaluate("() => document.fonts.ready")
            except Exception:
                pass
            pdf_bytes = page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "16mm", "right": "14mm", "bottom": "16mm", "left": "14mm"},
            )
        finally:
            browser.close()
    return pdf_bytes


def _convert_docx_with_playwright(source_path: Path, out_pdf: Path) -> None:
    try:
        import mammoth
    except ImportError as exc:
        raise KnowledgePreviewPdfError("缺少 mammoth，无法转换 Word 预览") from exc

    with source_path.open("rb") as handle:
        result = mammoth.convert_to_html(handle)
    body_html = result.value or "<p>（文档无内容）</p>"
    page_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <style>
    body {{
      margin: 24px;
      color: #1f2937;
      font: 14px/1.7 "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
    }}
    img {{ max-width: 100%; height: auto; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
    td, th {{ border: 1px solid #d1d5db; padding: 6px 8px; vertical-align: top; }}
    h1, h2, h3 {{ color: #111827; line-height: 1.35; }}
    p {{ margin: 0 0 10px; }}
  </style>
</head>
<body>{body_html}</body>
</html>"""
    out_pdf.write_bytes(_html_to_pdf_bytes(page_html))


def _convert_pptx_with_playwright(source_path: Path, out_pdf: Path) -> None:
    try:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
    except ImportError as exc:
        raise KnowledgePreviewPdfError("缺少 python-pptx，无法转换 PPT 预览") from exc

    try:
        presentation = Presentation(str(source_path))
    except Exception as exc:
        raise KnowledgePreviewPdfError("PPT 文件读取失败") from exc

    slides_html: list[str] = []

    def shape_html(shape) -> str:  # noqa: ANN001
        chunks: list[str] = []
        if getattr(shape, "has_text_frame", False):
            text = html.escape((shape.text_frame.text or "").strip())
            if text:
                chunks.append(f"<p>{text.replace(chr(10), '<br/>')}</p>")
        if getattr(shape, "has_table", False):
            rows = []
            for row in shape.table.rows:
                cells = "".join(
                    f"<td>{html.escape(cell.text.strip())}</td>" for cell in row.cells
                )
                rows.append(f"<tr>{cells}</tr>")
            if rows:
                chunks.append(f"<table>{''.join(rows)}</table>")
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            for child in shape.shapes:
                piece = shape_html(child)
                if piece:
                    chunks.append(piece)
        return "".join(chunks)

    for index, slide in enumerate(presentation.slides, start=1):
        body = "".join(shape_html(shape) for shape in slide.shapes) or "<p>（本页无文本）</p>"
        slides_html.append(
            f'<section class="slide"><h2>幻灯片 {index}</h2>{body}</section>'
        )

    page_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <style>
    body {{
      margin: 0;
      color: #1f2937;
      font: 14px/1.7 "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
      background: #f3f4f6;
    }}
    .slide {{
      background: #fff;
      margin: 16px;
      padding: 20px 24px;
      border: 1px solid #e5e7eb;
      border-radius: 12px;
      page-break-after: always;
    }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
    td, th {{ border: 1px solid #d1d5db; padding: 6px 8px; }}
    p {{ margin: 0 0 8px; }}
  </style>
</head>
<body>{''.join(slides_html) or '<section class="slide"><p>（演示文稿无内容）</p></section>'}</body>
</html>"""
    out_pdf.write_bytes(_html_to_pdf_bytes(page_html))


def _convert_html_with_playwright(source_path: Path, out_pdf: Path) -> None:
    raw = None
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
        try:
            raw = source_path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    if raw is None:
        raise KnowledgePreviewPdfError("HTML 文件编码无法识别")
    # 关闭 JS 后直接渲染；缺头尾时包一层，避免空白页
    lowered = raw.lstrip().lower()
    if "<html" not in lowered:
        raw = f"<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>{raw}</body></html>"
    out_pdf.write_bytes(_html_to_pdf_bytes(raw))


def _convert_image_with_reportlab(source_path: Path, out_pdf: Path) -> None:
    from io import BytesIO

    from PIL import Image
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    try:
        image = Image.open(source_path)
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=92)
        buffer.seek(0)
        reader = ImageReader(buffer)
        img_w, img_h = image.size
    except Exception as exc:
        raise KnowledgePreviewPdfError("图片读取失败，无法生成预览") from exc

    page_w, page_h = A4
    margin = 36
    max_w = page_w - margin * 2
    max_h = page_h - margin * 2
    scale = min(max_w / float(img_w), max_h / float(img_h), 1.0)
    draw_w = img_w * scale
    draw_h = img_h * scale
    x = (page_w - draw_w) / 2
    y = (page_h - draw_h) / 2

    pdf = canvas.Canvas(str(out_pdf), pagesize=A4)
    pdf.drawImage(reader, x, y, width=draw_w, height=draw_h, preserveAspectRatio=True, mask="auto")
    pdf.showPage()
    pdf.save()


def _convert_plain_with_reportlab(source_path: Path, out_pdf: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    font_name = "STSong-Light"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(font_name))

    raw = source_path.read_text(encoding="utf-8", errors="ignore")
    style = ParagraphStyle(
        "KnowledgePreviewBody",
        fontName=font_name,
        fontSize=11,
        leading=18,
        spaceAfter=6,
    )
    doc = SimpleDocTemplate(
        str(out_pdf),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    story: list = []
    for line in raw.splitlines() or [""]:
        safe = html.escape(line).replace(" ", "&nbsp;") or "&nbsp;"
        story.append(Paragraph(safe, style))
        story.append(Spacer(1, 2))
    doc.build(story)
