"""信源类型：规则 + LLM 缓存。"""

from __future__ import annotations

import json

from app.services.source_category_service import (
    CATEGORY_LEGACY_ALIASES,
    classify_source_category_id,
    classify_source_category_label,
    collect_domains_for_llm_labeling,
    enrich_source_stat_row,
    merge_category_cache,
    normalize_category_id,
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


def test_rule_table_beats_stale_llm_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.source_category_service._CACHE_PATH",
        tmp_path / "cache.json",
    )
    merge_category_cache({"dianhua.cn": "other"})
    assert classify_source_category_id(domain="dianhua.cn") == "b2b"


def test_dianhua_directory_is_b2b() -> None:
    assert classify_source_category_id(domain="dianhua.cn") == "b2b"
    assert classify_source_category_label(domain="dianhua.cn") == "B2B/黄页/渠道站"
    assert (
        classify_source_category_id(
            title="大王椰板材(宣城店)-电话邦",
            url="https://www.dianhua.cn/shop/1",
            site="电话邦",
        )
        == "b2b"
    )


def test_recruitment_and_ranking_categories() -> None:
    assert classify_source_category_id(domain="m.zhipin.com") == "recruitment"
    assert classify_source_category_id(domain="m.maigoo.com") == "ranking"
    assert classify_source_category_id(domain="m.cnpp.cn") == "ranking"
    assert classify_source_category_label(domain="m.zhipin.com") == "招聘/职场"


def test_social_includes_video_platforms() -> None:
    assert classify_source_category_id(domain="www.bilibili.com") == "social"
    assert classify_source_category_id(domain="m.toutiao.com") == "social"
    assert normalize_category_id("video") == "social"
    assert CATEGORY_LEGACY_ALIASES["video"] == "social"


def test_smzdm_is_forum_not_media() -> None:
    assert classify_source_category_id(domain="www.smzdm.com") == "forum"


def test_pchouse_is_media_not_official() -> None:
    assert classify_source_category_id(domain="news.pchouse.com.cn") == "media"
    assert classify_source_category_label(domain="m.pchouse.com.cn") == "行业媒体/新闻"
    assert (
        classify_source_category_id(
            title="有安全可靠的板材吗?哪个品牌好?_百科精选_太平洋家居",
            url="https://m.pchouse.com.cn/post/1",
            site="太平洋家居网",
        )
        == "media"
    )


def test_bjd_is_media_not_ecommerce() -> None:
    assert (
        classify_source_category_id(
            domain="news.bjd.com.cn",
            site="北京日报网",
            title="装修选材关注点:一线板材品牌怎么选_京报网",
        )
        == "media"
    )
    assert classify_source_category_id(domain="xinwen.bjd.com.cn") == "media"


def test_ecommerce_requires_host_not_title_keyword() -> None:
    assert (
        classify_source_category_id(
            title="没穿几次 消费者质疑知名品牌淘宝旗舰店",
            domain="ce.cn",
            site="中国经济网",
        )
        == "media"
    )
    assert (
        classify_source_category_id(
            title="会员商城系统哪家强",
            url="https://m.fkw.com/a/1",
        )
        == "other"
    )
    assert classify_source_category_id(url="https://item.jd.com/123.html") == "ecommerce"


def test_corporate_heuristic_skips_major_platform_subdomains() -> None:
    assert (
        classify_source_category_id(
            title="景典传媒_北京景典传媒科技股份有限公司|投资界",
            url="https://m.pedaily.cn/company/1",
            site="投资界",
        )
        == "media"
    )


def test_cache_prunes_rule_conflicts(tmp_path, monkeypatch) -> None:
    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr("app.services.source_category_service._CACHE_PATH", cache_path)
    cache_path.write_text(
        '{"dianhua.cn":"qa","news.bjd.com.cn":"ecommerce","cold-vertical.example":"media","old.video":"video"}',
        encoding="utf-8",
    )
    from app.services.source_category_service import _load_category_cache

    loaded = _load_category_cache()
    assert "dianhua.cn" not in loaded
    assert "news.bjd.com.cn" not in loaded
    assert loaded.get("cold-vertical.example") == "media"
    assert loaded.get("old.video") == "social"
    assert classify_source_category_id(domain="dianhua.cn") == "b2b"
    assert classify_source_category_id(domain="news.bjd.com.cn") == "media"


def test_merge_cache_rejects_rule_conflicts(tmp_path, monkeypatch) -> None:
    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr("app.services.source_category_service._CACHE_PATH", cache_path)
    merge_category_cache({"dianhua.cn": "qa", "cold-vertical.example": "forum"})
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert "dianhua.cn" not in payload
    assert payload.get("cold-vertical.example") == "forum"


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
