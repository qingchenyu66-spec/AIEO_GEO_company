"""Tests for report narrative paragraph splitting."""

from app.services.report_export_service import _split_narrative_paragraphs


def test_split_numbered_recommendations() -> None:
    text = "1. 垂直行业站：发布对比；2. 问答平台：结构化回答；3. 权威门户：输出案例。"
    parts = _split_narrative_paragraphs(text)
    assert len(parts) == 3
    assert parts[0].startswith("1.")


def test_split_semicolon_paragraphs() -> None:
    text = "第一句内容；第二句内容；第三句内容"
    parts = _split_narrative_paragraphs(text)
    assert len(parts) == 3
