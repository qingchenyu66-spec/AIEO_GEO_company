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
