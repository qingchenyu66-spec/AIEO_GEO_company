"""分享页信源抽取单测（豆包 + 跨平台 JSON/锚点）。"""

from __future__ import annotations

from pathlib import Path

from app.services.share_page_fetch_service import (
    SharePageFetchResult,
    _clean_answer_text,
    _claimed_material_count,
    _http_refs_enough,
    _refs_from_html,
    _result_from_html,
    extract_doubao_references,
    extract_json_title_url_references,
    extract_kimi_references,
    fetch_share_page,
)

PROBE = Path(__file__).resolve().parents[1] / "_doubao_share_probe.html"
PROBE_DIR = Path(__file__).resolve().parents[1] / "_share_ref_probe"


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


def test_result_from_html_accepts_doubao_ssr_probe() -> None:
    if not PROBE.exists():
        return
    html = PROBE.read_text(encoding="utf-8")
    hit = _result_from_html(html, host="www.doubao.com", title="probe")
    assert hit is not None
    assert len(hit.answer_content) >= 80
    assert hit.references


def test_fetch_share_page_prefers_http(monkeypatch) -> None:
    fake = SharePageFetchResult(
        answer_content="x" * 100,
        references=[],
        title="t",
        source_host="www.doubao.com",
    )
    monkeypatch.setattr(
        "app.services.share_page_fetch_service._try_http_fetch",
        lambda url, host: fake,
    )
    out = fetch_share_page("https://www.doubao.com/thread/abc1234567890")
    assert out.answer_content == fake.answer_content
    assert out.title == "t"


def test_kimi_and_json_parsers_on_local_probes() -> None:
    kimi = PROBE_DIR / "kimi.html"
    yuanbao = PROBE_DIR / "yuanbao_after.html"
    if not kimi.exists() or not yuanbao.exists():
        return
    kimi_refs = extract_kimi_references(kimi.read_text(encoding="utf-8", errors="replace"))
    assert len(kimi_refs) >= 5
    assert all(r.get("url", "").startswith("http") for r in kimi_refs)
    yb_refs = extract_json_title_url_references(
        yuanbao.read_text(encoding="utf-8", errors="replace"),
        page_host="yuanbao.tencent.com",
    )
    assert len(yb_refs) >= 5
    assert not any("yuanbao.tencent.com" in str(r.get("url")) for r in yb_refs)


def test_qianwen_http_not_enough_when_claim_exceeds_refs() -> None:
    hit = SharePageFetchResult(
        answer_content=("正文" * 40),
        references=[{"title": "a", "url": "https://blog.csdn.net/x", "site": "blog.csdn.net"}],
        source_host="www.qianwen.com",
        claimed_refs=18,
    )
    assert _claimed_material_count("已完成思考，参考了18篇材料") == 18
    assert _http_refs_enough(hit, "www.qianwen.com") is False
    hit2 = SharePageFetchResult(
        answer_content=("正文" * 40),
        references=[
            {"title": "a", "url": "https://a.com/1", "site": "a.com"},
            {"title": "b", "url": "https://b.com/2", "site": "b.com"},
        ],
        source_host="www.qianwen.com",
        claimed_refs=2,
    )
    assert _http_refs_enough(hit2, "www.qianwen.com") is True


def test_deepseek_anchor_route_on_local_probe() -> None:
    path = PROBE_DIR / "deepseek.html"
    if not path.exists():
        return
    refs = _refs_from_html(path.read_text(encoding="utf-8", errors="replace"), "chat.deepseek.com")
    assert len(refs) >= 5
    assert all("deepseek.com" not in str(r.get("url")) for r in refs)
