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
    get_runtime_config,
    invalidate_runtime_config_cache,
    list_system_configs,
    mask_secret_value,
    serialize_config_row,
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


def test_get_runtime_config_reads_db_over_stale_settings(db_session):
    """Simulate another API worker: DB already updated, local settings still old."""
    bootstrap_system_configs(db_session)
    row = db_session.query(SystemConfig).filter_by(config_key="snapshot_backfill_notify_owner").one()
    row.config_value = "false"
    db_session.commit()
    object.__setattr__(settings, "snapshot_backfill_notify_owner", True)
    invalidate_runtime_config_cache()
    assert get_runtime_config("snapshot_backfill_notify_owner", db=db_session) is False
    assert settings.snapshot_backfill_notify_owner is False


def test_list_system_configs_filters_category(db_session):
    bootstrap_system_configs(db_session)
    secrets = list_system_configs(db_session, category="secrets")
    assert secrets
    assert all(item["category"] == "secrets" for item in secrets)
    notif = list_system_configs(db_session, category="notification")
    assert {item["config_key"] for item in notif} >= {
        "snapshot_backfill_weak_rank_after",
        "snapshot_backfill_notify_owner",
        "snapshot_backfill_notify_operation",
        "snapshot_backfill_notify_admin",
        "tenant_expiry_notify_days",
        "tenant_expiry_notify_position_ids",
    }


def test_mask_secret_value():
    assert mask_secret_value("abcd1234") == "ab****34"
    assert mask_secret_value("") == ""


def test_serialize_config_row_masks_secret(db_session):
    bootstrap_system_configs(db_session)
    row = db_session.query(SystemConfig).filter_by(config_key="molizhishu_token").one()
    row.config_value = "secret-token-value"
    payload = serialize_config_row(row)
    assert payload["secret"] is True
    assert "secret-token-value" not in payload["config_value"]
    assert "****" in payload["config_value"]
