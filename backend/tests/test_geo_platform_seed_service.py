import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.brand import BrandAsset, BrandKeywordGroup
from app.models.platform import GeoPlatform
from app.services.geo_platform_seed_service import sync_geo_platforms_from_catalog


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(
        bind=engine,
        tables=[GeoPlatform.__table__, BrandKeywordGroup.__table__, BrandAsset.__table__],
    )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_sync_geo_platforms_from_catalog(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.services.platform_catalog_lifecycle_service.get_supported_platform_catalog",
        lambda force_refresh=False: [
            {"code": "doubao", "name": "豆包", "description": "test", "channel": "web", "sort_order": 10},
            {"code": "kimi", "name": "Kimi", "description": "kimi", "channel": "web", "sort_order": 80},
        ],
    )
    monkeypatch.setattr(
        "app.services.platform_catalog_lifecycle_service.upsert_platform_service_notification",
        lambda *args, **kwargs: None,
    )
    result = sync_geo_platforms_from_catalog(db_session)
    assert result["created"] == 2
    assert result["total"] == 2

    monkeypatch.setattr(
        "app.services.platform_catalog_lifecycle_service.get_supported_platform_catalog",
        lambda force_refresh=False: [
            {"code": "doubao", "name": "豆包新版", "description": "test2", "channel": "web", "sort_order": 10},
        ],
    )
    result2 = sync_geo_platforms_from_catalog(db_session)
    assert result2["total"] == 1
    assert "kimi" in (result2.get("delisted_codes") or [])
    row = db_session.query(GeoPlatform).filter_by(platform_code="doubao").one()
    assert row.platform_name == "豆包新版"
    kimi = db_session.query(GeoPlatform).filter_by(platform_code="kimi").one()
    assert kimi.catalog_listed is False
