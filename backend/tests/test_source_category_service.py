"""信源类型：规则 + LLM 缓存。"""

from __future__ import annotations

from app.services.source_category_service import (
    classify_source_category_id,
    classify_source_category_label,
    collect_domains_for_llm_labeling,
    enrich_source_stat_row,
    merge_category_cache,
    resolve_source_categories_with_llm,
)


def test_dealer_corporate_site_is_official() -> None:
    assert (
        classify_source_category_id(
            title="公司简介_海南装饰材料,海口装饰材料,海南旺顺祥业贸易有限公司",
            url="https://www.hkwsxy.com/about.html",
        )
        == "official"
    )
    assert (
        classify_source_category_id(
            title="海南装饰材料|海口装饰材料|海口旺顺祥业贸易有限公司",
            url="https://hkwsxy.com/",
        )
        == "official"
    )
    assert (
        classify_source_category_id(
            title="大王椰官方网站-饰面美学大师",
            url="https://m.dwywood.com/news/info/73.html",
        )
        == "official"
    )


def test_dianhua_directory_is_enterprise() -> None:
    assert classify_source_category_id(domain="dianhua.cn") == "enterprise"
    assert classify_source_category_label(domain="dianhua.cn") == "企业库/工商"
    assert (
        classify_source_category_id(
            title="大王椰板材(宣城店)-电话邦",
            url="https://www.dianhua.cn/shop/1",
            site="电话邦",
        )
        == "enterprise"
    )


def test_pchouse_is_media_not_official() -> None:
    assert classify_source_category_id(domain="news.pchouse.com.cn") == "media"
    assert classify_source_category_label(domain="m.pchouse.com.cn") == "行业媒体"


def test_unknown_domain_defaults_other() -> None:
    assert classify_source_category_id(domain="cold-vertical.example") == "other"
    assert classify_source_category_label(domain="cold-vertical.example") == "其他"


def test_official_exemption_still_works() -> None:
    assert (
        classify_source_category_id(
            domain="imtcmkj.com",
            official_site_labels={"imtcmkj.com": "艾迪亚"},
        )
        == "official"
    )


def test_enrich_source_stat_row_adds_category_fields() -> None:
    row = enrich_source_stat_row(
        {"title": "测试", "url": "https://www.zhihu.com/q/1", "count": 2},
    )
    assert row["category"] == "qa"
    assert row["category_label"] == "问答社区"


def test_collect_domains_for_llm_skips_known_rules(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.source_category_service._CACHE_PATH",
        tmp_path / "cache.json",
    )
    rows = [
        {"title": "知乎帖", "url": "https://www.zhihu.com/q/1", "count": 9},
        {"title": "冷门", "url": "https://cold-vertical.example/a", "count": 3},
    ]
    pending = collect_domains_for_llm_labeling(rows)
    assert len(pending) == 1
    assert pending[0]["domain"] == "cold-vertical.example"


def test_llm_category_merge_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.source_category_service._CACHE_PATH",
        tmp_path / "cache.json",
    )

    class _FakeClient:
        report_enabled = True

        def resolve_domain_source_categories(self, items):
            return {"cold-vertical.example": "media"}

    monkeypatch.setattr(
        "app.services.deepseek_client.DeepseekClient",
        lambda: _FakeClient(),
    )
    resolved = resolve_source_categories_with_llm(
        [{"domain": "cold-vertical.example", "titles": ["行业观察"]}],
    )
    assert resolved == {"cold-vertical.example": "media"}
    assert classify_source_category_id(domain="cold-vertical.example") == "media"


def test_merge_category_cache_persists(tmp_path, monkeypatch) -> None:
    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr("app.services.source_category_service._CACHE_PATH", cache_path)
    merge_category_cache({"sample.test": "forum"})
    assert classify_source_category_id(domain="www.sample.test") == "forum"
