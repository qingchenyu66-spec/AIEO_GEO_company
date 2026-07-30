"""非管理员不可分配/修改管理员账号。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.schemas.permission import UserIdentityCreateItem
from app.services.management_service import (
    assert_actor_can_assign_identities,
    assert_actor_can_manage_target_user,
)


def test_non_admin_cannot_assign_admin_role():
    db = MagicMock()
    actor = SimpleNamespace(identity_type="PLATFORM", position_id=2, role_code="PLATFORM_OPERATOR")
    # is_platform_admin: position lookup returns OPERATION
    db.scalar.return_value = SimpleNamespace(position_code="PLATFORM_OPERATION", deleted=False)
    item = UserIdentityCreateItem(
        identity_type="PLATFORM",
        role_code="PLATFORM_ADMIN",
        position_id=1,
        identity_name="管理员",
        menu_ids=[],
    )
    with pytest.raises(PermissionError, match="管理员"):
        assert_actor_can_assign_identities(db, actor, [item])


def test_admin_can_assign_admin_role(monkeypatch):
    db = MagicMock()
    actor = SimpleNamespace(identity_type="PLATFORM", position_id=1, role_code="PLATFORM_ADMIN")
    monkeypatch.setattr(
        "app.services.management_service.is_platform_admin_identity",
        lambda _db, _identity: True,
    )
    item = UserIdentityCreateItem(
        identity_type="PLATFORM",
        role_code="PLATFORM_ADMIN",
        position_id=1,
        identity_name="管理员",
        menu_ids=[],
    )
    assert_actor_can_assign_identities(db, actor, [item])


def test_non_admin_cannot_manage_existing_admin(monkeypatch):
    db = MagicMock()
    actor = SimpleNamespace(identity_type="PLATFORM", position_id=2, role_code="PLATFORM_OPERATOR")
    monkeypatch.setattr(
        "app.services.management_service.is_platform_admin_identity",
        lambda _db, identity: getattr(identity, "role_code", "") == "PLATFORM_ADMIN",
    )
    target = SimpleNamespace(
        identities=[
            SimpleNamespace(deleted=False, identity_type="PLATFORM", role_code="PLATFORM_ADMIN", position_id=1),
        ]
    )
    with pytest.raises(PermissionError, match="修改管理员"):
        assert_actor_can_manage_target_user(db, actor, target)
