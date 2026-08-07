"""结项章节抽到周报母版的最小自检。"""

from __future__ import annotations

from app.services.report_completion_html_service import (
    extract_completion_deck_sections,
    _split_section_pack_parts,
)


def test_split_section_pack_parts_by_h3() -> None:
    body = "<p class='sub'>intro</p><h3>A</h3><p>a</p><h3>B</h3><p>b</p>"
    parts = _split_section_pack_parts(body)
    assert len(parts) == 3
    assert parts[0].startswith("<p class='sub'>")
    assert "<h3>A</h3>" in parts[1]
    assert "<h3>B</h3>" in parts[2]


def test_split_section_pack_parts_by_blocks() -> None:
    body = (
        "<p class='sub'>intro</p>"
        "<div class=\"score-grid\">s</div>"
        "<table><tr><td>t</td></tr></table>"
        "<div class=\"evidence-grid\"><article class=\"evidence-card\">e</article></div>"
    )
    parts = _split_section_pack_parts(body)
    assert len(parts) == 4
    assert "score-grid" in parts[1]
    assert parts[2].startswith("<table")
    assert "evidence-grid" in parts[3]


def test_coalesce_h3_with_following_table() -> None:
    body = (
        "<h3>品牌提及率趋势</h3><p class='sub'>c</p><svg></svg>"
        "<h3>问题词成绩榜</h3><p class='sub'>s</p>"
        "<table><tr><td>1</td></tr></table>"
    )
    parts = _split_section_pack_parts(body)
    assert any("问题词成绩榜" in p and "<table" in p for p in parts)
    assert not any(p.strip().endswith("</p>") and "问题词成绩榜" in p and "<table" not in p for p in parts)


def test_extract_completion_deck_sections() -> None:
    html = """
    <html><body><main>
      <section class="hero">skip</section>
      <section class="section"><h2>01 服务概况</h2><p class="sub">x</p><h3>范围</h3><p>y</p></section>
      <section class="section"><h2>02 成绩总览</h2><div class="score-grid">z</div></section>
    </main></body></html>
    """
    sections = extract_completion_deck_sections(html)
    assert len(sections) == 2
    assert sections[0]["title"] == "01 服务概况"
    assert len(sections[0]["parts"]) >= 2
    assert sections[1]["title"] == "02 成绩总览"
    assert sections[1]["parts"]
