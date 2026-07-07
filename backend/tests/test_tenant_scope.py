"""Unit tests for tenant scope sales access guards."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.api.dependencies import CurrentSession
from app.services.tenant_scope import (
    assert_monitor_task_access,
    ensure_lead_diagnosis_task_access,
    ensure_sales_tenant_access,
    resolve_and_guard_tenant_id,
)


def _sales_current(user_id: int = 1) -> CurrentSession:
    user = SimpleNamespace(id=user_id, display_name="销售甲")
    identity = SimpleNamespace(
        id=10,
        identity_type="PLATFORM",
        position_id=99,
        identity_name="销售甲",
        tenant_id=None,
    )
    return CurrentSession(user=user, identity=identity)


def _sales_db(*, tenant_id: int, owner_user_id: int) -> MagicMock:
    db = MagicMock()
    position = SimpleNamespace(position_code="PLATFORM_SALES", position_name="销售")
    tenant = SimpleNamespace(id=tenant_id, owner_user_id=owner_user_id, deleted=False)
    db.scalar.side_effect = [tenant, position, tenant]
    return db


def test_sales_can_access_owned_tenant():
    db = MagicMock()
    position = SimpleNamespace(position_code="PLATFORM_SALES", position_name="销售")
    tenant = SimpleNamespace(id=7, owner_user_id=1, deleted=False)
    db.scalar.side_effect = [position, tenant]
    ensure_sales_tenant_access(db, _sales_current(user_id=1), 7)


def test_sales_cannot_access_foreign_tenant():
    db = MagicMock()
    position = SimpleNamespace(position_code="PLATFORM_SALES", position_name="销售")
    tenant = SimpleNamespace(id=8, owner_user_id=2, deleted=False)
    db.scalar.side_effect = [position, tenant]
    with pytest.raises(PermissionError):
        ensure_sales_tenant_access(db, _sales_current(user_id=1), 8)


def test_sales_monitor_task_guard():
    db = MagicMock()
    position = SimpleNamespace(position_code="PLATFORM_SALES", position_name="销售")
    tenant = SimpleNamespace(id=8, owner_user_id=2, deleted=False)
    db.scalar.side_effect = [position, tenant]
    with pytest.raises(PermissionError):
        assert_monitor_task_access(db, _sales_current(user_id=1), 8, task_id="task-8")


def test_sales_lead_diagnosis_task_blocks_foreign_owner():
    db = MagicMock()
    position = SimpleNamespace(position_code="PLATFORM_SALES", position_name="销售")
    db.scalar.side_effect = [position, 99]
    with pytest.raises(PermissionError, match="售前诊断"):
        ensure_lead_diagnosis_task_access(db, _sales_current(user_id=1), "lead-task-1")


def test_sales_lead_diagnosis_task_allows_owner():
    db = MagicMock()
    position = SimpleNamespace(position_code="PLATFORM_SALES", position_name="销售")
    db.scalar.side_effect = [position, 1]
    ensure_lead_diagnosis_task_access(db, _sales_current(user_id=1), "lead-task-1")


def test_sales_monitor_task_without_tenant_requires_lead_access():
    db = MagicMock()
    position = SimpleNamespace(position_code="PLATFORM_SALES", position_name="销售")
    db.scalar.side_effect = [position, 1]
    assert_monitor_task_access(db, _sales_current(user_id=1), None, task_id="lead-task-1")


def test_sales_monitor_task_without_tenant_blocks_orphan():
    db = MagicMock()
    position = SimpleNamespace(position_code="PLATFORM_SALES", position_name="销售")
    db.scalar.side_effect = [position, None, position]
    with pytest.raises(PermissionError):
        assert_monitor_task_access(db, _sales_current(user_id=1), None, task_id="orphan-task")


def test_resolve_and_guard_tenant_id():
    db = _sales_db(tenant_id=7, owner_user_id=1)
    assert resolve_and_guard_tenant_id(db, _sales_current(user_id=1), 7) == 7


def test_resolve_and_guard_rejects_foreign():
    db = _sales_db(tenant_id=8, owner_user_id=2)
    with pytest.raises(PermissionError):
        resolve_and_guard_tenant_id(db, _sales_current(user_id=1), 8)
