"""Extract plain text from knowledge base uploads."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from pypdf import PdfReader


class KnowledgeTextExtractError(ValueError):
    """Raised when file text cannot be extracted."""


def extract_knowledge_text(file_path: Path, file_ext: str) -> str:
    """Read local knowledge file and return normalized plain text."""
    ext = file_ext.lower().lstrip(".")
    if ext in {"txt", "md"}:
        return _read_text_file(file_path)
    if ext in {"doc", "docx"}:
        if ext == "doc":
            raise KnowledgeTextExtractError("旧版 .doc 暂不支持解析，请另存为 .docx 后重新上传")
        return _read_docx(file_path)
    if ext == "pdf":
        return _read_pdf(file_path)
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
