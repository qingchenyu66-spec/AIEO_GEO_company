"""商品卡分析口径与开关。"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.tenant import Tenant
from app.services.goods_card_analytics_service import (
    build_goods_card_summary,
    extract_goods,
    hit_brand,
    hit_contains,
    require_goods_card_enabled,
)


def test_extract_goods_empty_safe():
    assert extract_goods(None) == []
    assert extract_goods({}) == []
    assert extract_goods({"goods": "x"}) == []
    assert extract_goods({"goods": [{"title": "宝得聪 DHA", "price": "99"}]})[0]["title"] == "宝得聪 DHA"


def test_hit_brand_and_competitor_false_positive():
    assert hit_brand("宝得聪婴幼儿DHA", ["宝得聪"]) == "宝得聪"
    assert hit_contains("一本全练习册", ["一本"]) is None
    assert hit_contains("一本英语", ["一本"]) == "一本"


def test_platform_cn_uses_catalog_not_raw_code():
    from app.services.goods_card_analytics_service import _platform_cn, _platform_name_map

    label = _platform_cn("baiduai")
    assert label == _platform_name_map()["baiduai"]
    assert label != "baiduai"


def test_require_goods_card_disabled():
    db = SessionLocal()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.deleted.is_(False)).limit(1))
        assert tenant is not None
        prev = bool(getattr(tenant, "goods_card_enabled", False))
        tenant.goods_card_enabled = False
        db.commit()
        try:
            require_goods_card_enabled(db, tenant.id)
            assert False, "expected PermissionError"
        except PermissionError as exc:
            assert "未开通" in str(exc)
        finally:
            tenant.goods_card_enabled = prev
            db.commit()
    finally:
        db.close()


def test_build_summary_kpi_denominator(monkeypatch):
    db = SessionLocal()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.deleted.is_(False)).limit(1))
        assert tenant is not None
        prev = bool(getattr(tenant, "goods_card_enabled", False))
        tenant.goods_card_enabled = True
        db.commit()

        def _fake_load(_db, _tenant_id, *, start_date, end_date):
            return [
                {
                    "subtask_id": "g1",
                    "platform": "qianwen_mobile",
                    "platform_cn": "千问·手机",
                    "prompt": "儿童DHA品牌推荐",
                    "has_goods": True,
                    "goods_n": 1,
                    "goods": [
                        {
                            "title": "宝得聪 DHA",
                            "thumbnail": "https://example.com/a.png",
                            "price": "99",
                            "mall": "京东",
                            "url": "https://example.com/p",
                            "mall_platform": "jd",
                            "mall_product_id": None,
                        },
                        {
                            "title": "纽曼思藻油",
                            "thumbnail": None,
                            "price": None,
                            "mall": None,
                            "url": None,
                            "mall_platform": None,
                            "mall_product_id": None,
                        },
                    ],
                    "brand_hits": [{"term": "宝得聪", "title": "宝得聪 DHA"}],
                    "comp_hits": {"纽曼思": [{"term": "纽曼思", "title": "纽曼思藻油"}]},
                    "page_screenshot": None,
                    "updated_at": (datetime.now() - timedelta(hours=1)).isoformat(sep=" ", timespec="seconds"),
                },
                {
                    "subtask_id": "g2",
                    "platform": "qianwen_mobile",
                    "platform_cn": "千问·手机",
                    "prompt": "宝得聪值得买吗",
                    "has_goods": False,
                    "goods_n": 0,
                    "goods": [],
                    "brand_hits": [],
                    "comp_hits": {},
                    "page_screenshot": None,
                    "updated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
                },
                {
                    # 从未出卡的平台不进分母
                    "subtask_id": "g3",
                    "platform": "doubao",
                    "platform_cn": "豆包",
                    "prompt": "PC 问法",
                    "has_goods": False,
                    "goods_n": 0,
                    "goods": [],
                    "brand_hits": [],
                    "comp_hits": {},
                    "page_screenshot": None,
                    "updated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
                },
            ]

        monkeypatch.setattr(
            "app.services.goods_card_analytics_service._load_completed_samples",
            _fake_load,
        )
        monkeypatch.setattr(
            "app.services.goods_card_analytics_service.tenant_has_mobile_monitor_platform",
            lambda *_a, **_k: True,
        )
        monkeypatch.setattr(
            "app.services.goods_card_analytics_service._brand_match_terms",
            lambda *_a, **_k: ["宝得聪"],
        )
        monkeypatch.setattr(
            "app.services.goods_card_analytics_service._competitor_map",
            lambda *_a, **_k: {"纽曼思": ["纽曼思"]},
        )
        monkeypatch.setattr(
            "app.services.goods_card_analytics_service.get_brand_asset",
            lambda *_a, **_k: None,
        )
        monkeypatch.setattr(
            "app.services.goods_card_analytics_service.list_competitors",
            lambda *_a, **_k: [],
        )

        data = build_goods_card_summary(db, tenant.id, days=7)
        # 分母仅曾出卡平台 → g1+g2，不含 doubao
        assert data["sample_total"] == 2
        assert data["goods_task_total"] == 1
        assert data["kpi"]["out_rate"] == 50.0
        assert data["kpi"]["brand_rate"] == 100.0
        assert data["denominator_platforms"] == ["qianwen_mobile"]
        assert data["diagnosis"] is not None
        assert len(data["hits"]) == 2
    finally:
        tenant.goods_card_enabled = prev
        db.commit()
        db.close()
