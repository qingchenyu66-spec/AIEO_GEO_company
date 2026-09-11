"""Extract plain text from knowledge base uploads."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from docx import Document
from pypdf import PdfReader


class KnowledgeTextExtractError(ValueError):
    """Raised when file text cannot be extracted."""


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self._chunks.append(text)

    def text(self) -> str:
        return "\n".join(self._chunks)


def extract_knowledge_text(file_path: Path, file_ext: str) -> str:
    """Read local knowledge file and return normalized plain text."""
    ext = file_ext.lower().lstrip(".")
    if ext in {"txt", "md"}:
        return _read_text_file(file_path)
    if ext in {"html", "htm"}:
        return _read_html(file_path)
    if ext in {"doc", "docx"}:
        if ext == "doc":
            raise KnowledgeTextExtractError("旧版 .doc 暂不支持解析，请另存为 .docx 后重新上传")
        return _read_docx(file_path)
    if ext in {"ppt", "pptx"}:
        if ext == "ppt":
            raise KnowledgeTextExtractError("旧版 .ppt 暂不支持文本解析，请另存为 .pptx 后重新上传")
        return _read_pptx(file_path)
    if ext == "pdf":
        return _read_pdf(file_path)
    if ext in {"png", "jpg", "jpeg", "webp"}:
        raise KnowledgeTextExtractError("图片暂不支持文本解析，可使用原版预览查看")
    raise KnowledgeTextExtractError(f"不支持的文件类型：.{ext}")


def _read_text_file(file_path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
        try:
            text = file_path.read_text(encoding=encoding)
            normalized = _normalize_text(text)
            if normalized:
                return normalized
        except UnicodeDecodeError:
            continue
    raise KnowledgeTextExtractError("文本文件编码无法识别")


def _read_html(file_path: Path) -> str:
    raw = None
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
        try:
            raw = file_path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    if raw is None:
        raise KnowledgeTextExtractError("HTML 文件编码无法识别")
    parser = _HTMLTextExtractor()
    try:
        parser.feed(raw)
        parser.close()
    except Exception as exc:
        raise KnowledgeTextExtractError("HTML 文件解析失败") from exc
    normalized = _normalize_text(parser.text())
    if not normalized:
        raise KnowledgeTextExtractError("HTML 未提取到有效文本")
    return normalized


def _read_docx(file_path: Path) -> str:
    try:
        document = Document(str(file_path))
    except Exception as exc:
        raise KnowledgeTextExtractError("Word 文件读取失败") from exc
    parts = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    normalized = _normalize_text("\n".join(parts))
    if not normalized:
        raise KnowledgeTextExtractError("Word 文件未提取到有效文本")
    return normalized


def _read_pptx(file_path: Path) -> str:
    try:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
    except ImportError as exc:
        raise KnowledgeTextExtractError("缺少 python-pptx，无法解析 PPT") from exc
    try:
        presentation = Presentation(str(file_path))
    except Exception as exc:
        raise KnowledgeTextExtractError("PPT 文件读取失败") from exc

    parts: list[str] = []

    def collect_shape_text(shape) -> None:  # noqa: ANN001
        if getattr(shape, "has_text_frame", False):
            text = (shape.text_frame.text or "").strip()
            if text:
                parts.append(text)
        if getattr(shape, "has_table", False):
            for row in shape.table.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            for child in shape.shapes:
                collect_shape_text(child)

    for index, slide in enumerate(presentation.slides, start=1):
        before = len(parts)
        for shape in slide.shapes:
            collect_shape_text(shape)
        if len(parts) > before:
            parts.insert(before, f"幻灯片 {index}")
    normalized = _normalize_text("\n".join(parts))
    if not normalized:
        raise KnowledgeTextExtractError("PPT 未提取到有效文本")
    return normalized


def _read_pdf(file_path: Path) -> str:
    try:
        reader = PdfReader(str(file_path))
    except Exception as exc:
        raise KnowledgeTextExtractError("PDF 文件读取失败") from exc
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        cleaned = text.strip()
        if cleaned:
            parts.append(cleaned)
    normalized = _normalize_text("\n".join(parts))
    if not normalized:
        raise KnowledgeTextExtractError("PDF 未提取到可复制文本，可能是扫描件")
    return normalized


def _normalize_text(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    compact = "\n".join(line for line in lines if line)
    return compact.strip()
