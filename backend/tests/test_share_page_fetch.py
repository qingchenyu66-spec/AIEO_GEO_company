"""豆包分享页信源抽取单测（基于本地 probe HTML）。"""

from __future__ import annotations

from pathlib import Path

from app.services.share_page_fetch_service import _clean_answer_text, extract_doubao_references

PROBE = Path(__file__).resolve().parents[1] / "_doubao_share_probe.html"


def test_extract_doubao_references_from_probe_html() -> None:
    if not PROBE.exists():
        # CI 无 probe 文件时跳过；本地开发可保留 probe
        return
    html = PROBE.read_text(encoding="utf-8")
    refs = extract_doubao_references(html)
    assert len(refs) >= 3
    urls = {row["url"] for row in refs}
    assert any("aitntnews.com" in u or "juejin.cn" in u or "csdn.net" in u for u in urls)
    assert all(row.get("title") for row in refs)


def test_clean_answer_text_strips_ui_noise() -> None:
    text = "打开豆包\n2026 年 7 月 22 日•内容由 AI 生成，不能完全保障真实\n正文第一段\n\n正文第二段"
    cleaned = _clean_answer_text(text)
    assert "打开豆包" not in cleaned
    assert "正文第一段" in cleaned
    assert "正文第二段" in cleaned
