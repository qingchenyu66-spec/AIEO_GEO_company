"""Tests for lead diagnosis sales ownership isolation."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.lead_diagnosis_service import (
    ensure_lead_diagnosis_owner_access,
    ensure_lead_diagnosis_owner_access_by_id,
    list_lead_diagnoses,
)


def test_ensure_lead_diagnosis_owner_access_allows_ops() -> None:
    db = MagicMock()
    current = SimpleNamespace(user=SimpleNamespace(id=1), identity=SimpleNamespace(id=10))
    lead = SimpleNamespace(created_by_user_id=99)

    with patch("app.services.lead_diagnosis_service.is_sales_identity", return_value=False):
        ensure_lead_diagnosis_owner_access(db, current, lead)  # no raise


def test_ensure_lead_diagnosis_owner_access_blocks_other_sales() -> None:
    db = MagicMock()
    current = SimpleNamespace(user=SimpleNamespace(id=7), identity=SimpleNamespace(id=10))
    lead = SimpleNamespace(created_by_user_id=8)

    with patch("app.services.lead_diagnosis_service.is_sales_identity", return_value=True):
        with pytest.raises(PermissionError, match="无权访问"):
            ensure_lead_diagnosis_owner_access(db, current, lead)


def test_ensure_lead_diagnosis_owner_access_allows_owner_sales() -> None:
    db = MagicMock()
    current = SimpleNamespace(user=SimpleNamespace(id=7), identity=SimpleNamespace(id=10))
    lead = SimpleNamespace(created_by_user_id=7)

    with patch("app.services.lead_diagnosis_service.is_sales_identity", return_value=True):
        ensure_lead_diagnosis_owner_access(db, current, lead)


def test_ensure_lead_diagnosis_owner_access_by_id_not_found() -> None:
    db = MagicMock()
    db.scalar.return_value = None
    current = SimpleNamespace(user=SimpleNamespace(id=1), identity=SimpleNamespace(id=10))

    with pytest.raises(ValueError, match="不存在"):
        ensure_lead_diagnosis_owner_access_by_id(db, current, 404)


def test_list_lead_diagnoses_filters_by_creator_for_sales() -> None:
    db = MagicMock()
    current = SimpleNamespace(user=SimpleNamespace(id=5), identity=SimpleNamespace(id=10))
    db.scalars.return_value = []

    with patch("app.services.lead_diagnosis_service.is_sales_identity", return_value=True):
        with patch("app.services.lead_diagnosis_service.require_lead_diagnosis_access"):
            list_lead_diagnoses(db, current)

    stmt = db.scalars.call_args[0][0]
    compiled = str(stmt)
    assert "created_by_user_id" in compiled
