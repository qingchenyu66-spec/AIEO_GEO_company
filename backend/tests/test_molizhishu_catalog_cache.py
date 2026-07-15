"""Catalog cache must not treat process-start fallback as a fresh sync."""

from app.services import molizhishu_catalog_service as catalog


def test_initial_fallback_cache_is_not_treated_as_fresh(monkeypatch):
    catalog._cache.clear()
    catalog._cache.update({
        "catalog": [dict(item) for item in catalog._FALLBACK_CATALOG],
        "fetched_at": None,
        "source": "fallback",
        "source_url": catalog.MOLIZHISHU_PLATFORM_DOC_URL,
    })
    called = {"n": 0}

    def fake_fetch(url: str):
        called["n"] += 1
        return [
            {"code": "doubao", "name": "豆包", "description": "x", "channel": "web", "sort_order": 10},
            {"code": "antafu", "name": "蚂蚁阿福", "description": "y", "channel": "web", "sort_order": 90},
        ]

    monkeypatch.setattr(catalog, "_fetch_doc_catalog", fake_fetch)
    rows = catalog.get_supported_platform_catalog()
    assert called["n"] == 1
    assert {item["code"] for item in rows} >= {"doubao", "antafu"}
    assert catalog.get_platform_catalog_meta()["source"] == "molizhishu_doc"


def test_fallback_source_reattempts_even_within_ttl(monkeypatch):
    catalog._cache.clear()
    catalog._cache.update({
        "catalog": [dict(item) for item in catalog._FALLBACK_CATALOG[:2]],
        "fetched_at": catalog.datetime.now(),
        "source": "fallback",
        "source_url": catalog.MOLIZHISHU_PLATFORM_DOC_URL,
    })
    called = {"n": 0}

    def fake_fetch(url: str):
        called["n"] += 1
        return [{"code": "kimi", "name": "Kimi", "description": "z", "channel": "web", "sort_order": 80}]

    monkeypatch.setattr(catalog, "_fetch_doc_catalog", fake_fetch)
    rows = catalog.get_supported_platform_catalog()
    assert called["n"] == 1
    assert rows[0]["code"] == "kimi"
