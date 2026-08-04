"""Tests for lead diagnosis duplicate-create cooldown."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.lead_diagnosis_service import (
    assert_lead_diagnosis_create_allowed,
    normalize_lead_brand_name,
)


def test_normalize_lead_brand_name() -> None:
    assert normalize_lead_brand_name("  广东品牌  ") == "广东品牌"


def test_assert_lead_diagnosis_create_allowed_blocks_recent_duplicate() -> None:
    db = MagicMock()
    existing = SimpleNamespace(
        id=12,
        brand_name="艾迪亚控股",
        created_at=datetime.now() - timedelta(days=2),
    )
    current = SimpleNamespace(user=SimpleNamespace(id=7))

    with patch(
        "app.services.lead_diagnosis_service.find_recent_lead_diagnosis_by_brand",
        return_value=existing,
    ):
        with pytest.raises(ValueError, match="7 天内只能创建一条"):
            assert_lead_diagnosis_create_allowed(db, current, "艾迪亚控股")


def test_assert_lead_diagnosis_create_allowed_passes_when_no_duplicate() -> None:
    db = MagicMock()
    current = SimpleNamespace(user=SimpleNamespace(id=7))

    with patch(
        "app.services.lead_diagnosis_service.find_recent_lead_diagnosis_by_brand",
        return_value=None,
    ):
        assert assert_lead_diagnosis_create_allowed(db, current, "新品牌") is None
