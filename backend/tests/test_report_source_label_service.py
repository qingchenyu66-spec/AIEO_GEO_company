"""report_source_label_service：字典 / 官网豁免 / site 票 / LLM 缓存。"""

from __future__ import annotations

from app.services.report_source_label_service import (
    build_official_site_label_map,
    enrich_domain_rows,
    enrich_source_row,
    pick_site_label_from_votes,
    resolve_chinese_site_name,
    resolve_missing_site_labels_with_llm,
    short_entity_label,
)


def test_known_domain_dict_hits() -> None:
    assert resolve_chinese_site_name(domain="jcdecaux.com.cn") == "德高广告"
    assert resolve_chinese_site_name(domain="chinabidding.com.cn") == "中国采购与招标网"
    assert resolve_chinese_site_name(domain="jobui.com") == "职友集"
    assert resolve_chinese_site_name(domain="hezegd.com") == "菏泽广电网"


def test_site_votes_prefer_chinese_publisher() -> None:
    label = pick_site_label_from_votes(
        {"职友集": 106, "Jobui": 4},
        brand="艾迪亚控股集团有限公司",
    )
    assert label == "职友集"


def test_site_votes_skip_brand_like_name() -> None:
    label = pick_site_label_from_votes(
        {"艾迪亚传媒": 153, "Imtcmkj": 176},
        brand="艾迪亚控股集团有限公司",
    )
    # 品牌向 / 非中文发布方名应被跳过
    assert label is None


def test_enrich_row_uses_site_votes_when_dict_misses(monkeypatch) -> None:
    from app.services import report_source_label_service as svc

    # 临时去掉字典命中，验证票路径
    monkeypatch.setitem(svc._DOMAIN_CN_NAMES, "example-vote.test", "不应命中")
    row = enrich_source_row(
        {
            "domain": "cold-site.example",
            "site_votes": {"冷门资讯网": 9, "Cold": 2},
        },
        brand="某品牌",
    )
    assert row["site_cn"] == "冷门资讯网"


def test_enrich_domain_rows_without_llm_keeps_dict() -> None:
    rows = enrich_domain_rows(
        [{"domain": "jobui.com", "count": 1}],
        brand="艾迪亚",
        use_llm=False,
    )
    assert rows[0]["site_cn"] == "职友集"


def test_ac_imtcmkj_falls_back_to_domain_when_no_viable_candidate(monkeypatch) -> None:
    """A+C：无合格中文发布方候选时不采纳盲猜缓存，回退域名。"""
    from app.services import report_source_label_service as svc

    monkeypatch.setattr(svc, "_load_llm_cache", lambda: {"imtcmkj.com": "天创科技"})
    saved: dict = {}
    monkeypatch.setattr(svc, "_save_llm_cache", lambda cache: saved.update(cache))

    called = {"n": 0}

    class _FakeClient:
        report_enabled = True

        def resolve_domain_site_labels(self, items):
            called["n"] += 1
            return {"imtcmkj.com": "天创科技"}

    monkeypatch.setattr(
        "app.services.deepseek_client.DeepseekClient",
        lambda: _FakeClient(),
    )
    svc._DOMAIN_CN_NAMES.pop("imtcmkj.com", None)

    rows = enrich_domain_rows(
        [
            {
                "domain": "imtcmkj.com",
                "site_votes": {"Imtcmkj": 176, "艾迪亚传媒": 153},
            }
        ],
        brand="艾迪亚控股集团有限公司",
        use_llm=True,
    )
    assert rows[0]["site_cn"] == "imtcmkj.com"
    assert called["n"] == 0  # 无合格候选，不调 LLM
    assert saved.get("imtcmkj.com") != "天创科技"


def test_ac_cache_applied_only_when_in_viable(monkeypatch) -> None:
    """A+C：缓存命中也必须落在合格候选内。"""
    from app.services import report_source_label_service as svc

    monkeypatch.setattr(svc, "_load_llm_cache", lambda: {"rare-pub.example": "冷门资讯网"})
    saved: dict = {}
    monkeypatch.setattr(svc, "_save_llm_cache", lambda cache: saved.update(dict(cache)))

    class _FakeClient:
        report_enabled = True

        def resolve_domain_site_labels(self, items):  # pragma: no cover
            raise AssertionError("cache hit should skip LLM")

    monkeypatch.setattr(
        "app.services.deepseek_client.DeepseekClient",
        lambda: _FakeClient(),
    )
    svc._DOMAIN_CN_NAMES.pop("rare-pub.example", None)

    resolved = resolve_missing_site_labels_with_llm(
        [
            {
                "domain": "rare-pub.example",
                "site_votes": {"冷门资讯网": 2, "RarePub": 9},
                "site_cn": "rare-pub.example",
            }
        ],
        brand="某品牌",
    )
    assert resolved.get("rare-pub.example") == "冷门资讯网"


def test_official_exemption_brand_and_competitor() -> None:
    """方案2：品牌/竞品主站豁免 → 2b 展示名；类别官网。"""
    labels = build_official_site_label_map(
        [
            ("https://www.imtcmkj.com/", "艾迪亚"),
            ("https://www.focusmedia.cn", "分众传媒"),
        ]
    )
    assert short_entity_label("艾迪亚控股集团有限公司") == "艾迪亚"
    brand_row = enrich_source_row(
        {"domain": "imtcmkj.com", "site_votes": {"Imtcmkj": 10}},
        brand="艾迪亚控股集团有限公司",
        official_site_labels=labels,
    )
    assert brand_row["site_cn"] == "艾迪亚"
    assert brand_row["category_label"] == "官网/自有阵地"

    comp_row = enrich_source_row(
        {"domain": "m.focusmedia.cn"},
        brand="艾迪亚控股集团有限公司",
        official_site_labels=labels,
    )
    assert comp_row["site_cn"] == "分众传媒"
    assert comp_row["category_label"] == "官网/自有阵地"
