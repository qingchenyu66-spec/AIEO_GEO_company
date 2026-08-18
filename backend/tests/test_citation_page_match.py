"""方案 A：summary / 抓网页补露出词命中。"""

from __future__ import annotations


def test_matched_keywords_include_summary_without_fetch():
    from app.services.citation_page_match import matched_source_keywords

    source = {
        "title": "5大品牌深度横评",
        "url": "https://news.ifeng.com/c/example",
        "site": "ifeng",
        "summary": "宝得聪适合婴幼儿营养补充",
    }
    assert matched_source_keywords(source, ["宝得聪"]) == ["宝得聪"]
    assert matched_source_keywords(source, ["宝得聪"], allow_page_fetch=False) == ["宝得聪"]


def test_matched_keywords_fetch_when_local_miss(monkeypatch):
    from app.services import citation_page_match as mod

    source = {
        "title": "5大品牌深度横评",
        "url": "https://news.ifeng.com/c/example",
        "site": "ifeng",
        "summary": "",
    }
    assert mod.matched_source_keywords(source, ["宝得聪"]) == []

    monkeypatch.setattr(
        mod,
        "fetch_citation_match_blob",
        lambda url, **kwargs: "正文提到宝得聪配方奶粉",
    )
    budget = [2]
    assert mod.matched_source_keywords(
        source, ["宝得聪"], allow_page_fetch=True, fetch_budget=budget
    ) == ["宝得聪"]
    assert budget[0] == 1


def test_matched_keywords_respect_fetch_budget(monkeypatch):
    from app.services import citation_page_match as mod

    calls = {"n": 0}

    def _fake(url, **kwargs):
        calls["n"] += 1
        return "宝得聪"

    monkeypatch.setattr(mod, "fetch_citation_match_blob", _fake)
    source = {"title": "x", "url": "https://example.com/a", "summary": ""}
    assert mod.matched_source_keywords(
        source, ["宝得聪"], allow_page_fetch=True, fetch_budget=[0]
    ) == []
    assert calls["n"] == 0


def test_aggregate_pair_maps_summary_counts_as_branded():
    from datetime import date
    from types import SimpleNamespace

    from app.services.monitor_service import _aggregate_source_stats_pair_maps

    item = SimpleNamespace(
        id=1,
        platform="qianwen",
        prompt="婴幼儿奶粉推荐",
        reference_list_json=[
            {
                "title": "5大品牌深度横评",
                "url": "https://news.ifeng.com/c/example",
                "site": "ifeng",
                "summary": "宝得聪位列推荐",
            },
        ],
    )
    branded, all_map, daily, by_plat = _aggregate_source_stats_pair_maps(
        [item],  # type: ignore[arg-type]
        business_day_by_id={1: date(2026, 8, 12)},
        subtask_tenant_map={1: 124},
        purchased_platforms_by_tenant={124: {"qianwen"}},
        exposure_terms_by_tenant={124: ["宝得聪"]},
        allow_page_fetch=False,
    )
    assert "https://news.ifeng.com/c/example" in branded
    assert daily["2026-08-12"] == 1
    assert by_plat["qianwen"]["2026-08-12"] == 1
    assert len(all_map) == 1
