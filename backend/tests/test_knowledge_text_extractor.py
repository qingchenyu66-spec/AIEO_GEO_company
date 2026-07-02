"""Tests for knowledge text extraction."""

from pathlib import Path

import pytest
from docx import Document

from app.services.knowledge_text_extractor import KnowledgeTextExtractError, extract_knowledge_text


def test_extract_markdown_text(tmp_path: Path) -> None:
    file_path = tmp_path / "guide.md"
    file_path.write_text("# 标题\n\n这是 GEO 资料正文。", encoding="utf-8")
    text = extract_knowledge_text(file_path, "md")
    assert "GEO 资料正文" in text


def test_extract_docx_text(tmp_path: Path) -> None:
    file_path = tmp_path / "brief.docx"
    document = Document()
    document.add_paragraph("艾迪亚品牌白皮书")
    document.add_paragraph("核心卖点：电梯媒体覆盖")
    document.save(str(file_path))
    text = extract_knowledge_text(file_path, "docx")
    assert "艾迪亚品牌白皮书" in text
    assert "核心卖点" in text


def test_extract_legacy_doc_rejected(tmp_path: Path) -> None:
    file_path = tmp_path / "legacy.doc"
    file_path.write_bytes(b"fake")
    with pytest.raises(KnowledgeTextExtractError, match="docx"):
        extract_knowledge_text(file_path, "doc")
