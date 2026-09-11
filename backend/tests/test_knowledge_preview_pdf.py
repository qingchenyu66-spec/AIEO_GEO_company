"""知识库原版预览 PDF 转换。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.knowledge_preview_pdf_service import (
    KnowledgePreviewPdfError,
    ensure_knowledge_preview_pdf,
    preview_cache_path,
)


def test_pdf_preview_returns_original(tmp_path: Path):
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.4\n% demo\n")
    preview = ensure_knowledge_preview_pdf(source, "pdf")
    assert preview == source
    assert not preview_cache_path(source).exists()


def test_txt_preview_builds_cached_pdf(tmp_path: Path):
    source = tmp_path / "notes.txt"
    source.write_text("知识库预览测试\n第二行", encoding="utf-8")
    preview = ensure_knowledge_preview_pdf(source, "txt")
    assert preview == preview_cache_path(source)
    assert preview.is_file()
    assert preview.read_bytes()[:4] == b"%PDF"

    mtime = preview.stat().st_mtime
    again = ensure_knowledge_preview_pdf(source, "txt")
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


def test_image_preview_builds_pdf(tmp_path: Path):
    from PIL import Image

    source = tmp_path / "banner.png"
    Image.new("RGB", (120, 80), color=(30, 120, 200)).save(source)
    preview = ensure_knowledge_preview_pdf(source, "png")
    assert preview.is_file()
    assert preview.read_bytes()[:4] == b"%PDF"


def test_html_preview_builds_pdf(tmp_path: Path):
    source = tmp_path / "intro.html"
    source.write_text("<html><body><h1>知识库 HTML</h1><p>预览内容</p></body></html>", encoding="utf-8")
    preview = ensure_knowledge_preview_pdf(source, "html")
    assert preview.is_file()
    assert preview.read_bytes()[:4] == b"%PDF"


def test_png_signature_ok():
    from app.services.knowledge_service import _validate_file_signature

    _validate_file_signature(".png", b"\x89PNG\r\n\x1a\nxxxx")


def test_webp_signature_rejects_fake_riff():
    from app.services.knowledge_service import _validate_file_signature

    with pytest.raises(ValueError, match="不匹配"):
        _validate_file_signature(".webp", b"RIFF....FAKE")
