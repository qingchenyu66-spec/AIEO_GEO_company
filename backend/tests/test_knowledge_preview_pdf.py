"""知识库原版预览 PDF 转换。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from app.services.knowledge_preview_pdf_service import (
    KnowledgePreviewPdfError,
    ensure_knowledge_preview_pdf,
    preview_cache_path,
)


def _write_blank_pdf(path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with path.open("wb") as handle:
        writer.write(handle)


def test_pdf_preview_returns_titled_cache(tmp_path: Path):
    source = tmp_path / "sample.pdf"
    _write_blank_pdf(source)
    preview = ensure_knowledge_preview_pdf(source, "pdf", title="sample.pdf")
    assert preview == preview_cache_path(source)
    assert preview.is_file()
    meta = PdfReader(str(preview)).metadata
    assert meta is not None
    assert (meta.get("/Title") or meta.title) == "sample.pdf"


def test_txt_preview_builds_cached_pdf(tmp_path: Path):
    source = tmp_path / "notes.txt"
    source.write_text("知识库预览测试\n第二行", encoding="utf-8")
    preview = ensure_knowledge_preview_pdf(source, "txt", title="notes.txt")
    assert preview == preview_cache_path(source)
    assert preview.is_file()
    assert preview.read_bytes()[:4] == b"%PDF"

    mtime = preview.stat().st_mtime
    again = ensure_knowledge_preview_pdf(source, "txt", title="notes.txt")
    assert again == preview
    assert again.stat().st_mtime == mtime


def test_doc_without_soffice_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "legacy.doc"
    source.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"x" * 20)
    monkeypatch.setattr(
        "app.services.knowledge_preview_pdf_service.resolve_soffice_binary",
        lambda: None,
    )
    with pytest.raises(KnowledgePreviewPdfError, match="doc"):
        ensure_knowledge_preview_pdf(source, "doc")


def test_image_preview_sets_pdf_title(tmp_path: Path):
    from PIL import Image

    source = tmp_path / "banner.png"
    Image.new("RGB", (120, 80), color=(30, 120, 200)).save(source)
    title = "20200907-demo.jpg"
    preview = ensure_knowledge_preview_pdf(source, "png", title=title)
    assert preview.is_file()
    assert preview.read_bytes()[:4] == b"%PDF"
    meta = PdfReader(str(preview)).metadata
    assert meta is not None
    assert (meta.get("/Title") or meta.title) == title


def test_html_preview_builds_pdf(tmp_path: Path):
    source = tmp_path / "intro.html"
    source.write_text("<html><body><h1>知识库 HTML</h1><p>预览内容</p></body></html>", encoding="utf-8")
    preview = ensure_knowledge_preview_pdf(source, "html", title="intro.html")
    assert preview.is_file()
    assert preview.read_bytes()[:4] == b"%PDF"


def test_png_signature_ok():
    from app.services.knowledge_service import _validate_file_signature

    _validate_file_signature(".png", b"\x89PNG\r\n\x1a\nxxxx")


def test_webp_signature_rejects_fake_riff():
    from app.services.knowledge_service import _validate_file_signature

    with pytest.raises(ValueError, match="不匹配"):
        _validate_file_signature(".webp", b"RIFF....FAKE")
