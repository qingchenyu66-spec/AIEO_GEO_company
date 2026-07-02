import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base
from app.models.ops import SystemConfig
from app.services.system_config_service import (
    CONFIG_REGISTRY,
    apply_config_value_to_settings,
    bootstrap_system_configs,
    coerce_config_value,
    list_system_configs,
    update_system_config,
)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine, tables=[SystemConfig.__table__])
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_coerce_config_value_bool_and_int():
    assert coerce_config_value("启用", "bool") is True
    assert coerce_config_value("false", "bool") is False
    assert coerce_config_value("30", "int") == 30


def test_bootstrap_seeds_registry_rows(db_session):
    bootstrap_system_configs(db_session)
    rows = db_session.query(SystemConfig).all()
    assert len(rows) == len(CONFIG_REGISTRY)


def test_update_applies_runtime_settings(db_session, monkeypatch):
    original = settings.molizhishu_submit_rate_per_minute
    bootstrap_system_configs(db_session)
    row = db_session.query(SystemConfig).filter_by(config_key="molizhishu_submit_rate_per_minute").one()
    update_system_config(db_session, row.id, "42")
    db_session.commit()
    assert settings.molizhishu_submit_rate_per_minute == 42
    object.__setattr__(settings, "molizhishu_submit_rate_per_minute", original)


def test_list_system_configs_filters_category(db_session):
    bootstrap_system_configs(db_session)
    secrets = list_system_configs(db_session, category="secrets")
    assert secrets
    assert all(item["category"] == "secrets" for item in secrets)
