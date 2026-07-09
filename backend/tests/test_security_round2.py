"""Round-2 security fixes: upload chunking, parse timeout, identity PATCH."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.schemas.permission import UserIdentityCreateItem, UserUpdateRequest
from app.services.knowledge_parse_service import fail_stale_knowledge_parses
from app.services.management_service import update_managed_user


def test_fail_stale_knowledge_parses_marks_old_parsing():
    db = MagicMock()
    stale = SimpleNamespace(
        parse_status="parsing",
        updated_at=datetime.now() - timedelta(minutes=30),
        parse_error=None,
        parsed_at=None,
    )
    db.scalars.return_value = [stale]
    result = fail_stale_knowledge_parses(db, timeout_minutes=10, limit=10)
    assert result["failed"] == 1
    assert stale.parse_status == "failed"
    assert "超时" in (stale.parse_error or "")
    db.commit.assert_called_once()


def test_update_user_keeps_omitted_identity_without_remove_flag():
    """Omitted identity types must NOT be deleted unless remove_identity_types is set."""
    db = MagicMock()
    platform = SimpleNamespace(
        id=1,
        identity_type="PLATFORM",
        deleted=False,
        status=True,
        identity_code="PLATFORM_1_ADMIN",
        tenant_id=None,
        position_id=None,
        identity_name="平台",
        role_code="PLATFORM_ADMIN",
        is_default=True,
    )
    customer = SimpleNamespace(
        id=2,
        identity_type="CUSTOMER",
        deleted=False,
        status=True,
        identity_code="CUSTOMER_1_USER",
        tenant_id=7,
        position_id=None,
        identity_name="客户",
        role_code="CUSTOMER_ADMIN",
        is_default=False,
    )
    user = SimpleNamespace(
        id=9,
        display_name="旧名",
        identities=[platform, customer],
        created_by=1,
        deleted=False,
        status=True,
    )
    current_user = SimpleNamespace(id=1)
    current_identity = SimpleNamespace(identity_type="PLATFORM", role_code="PLATFORM_ADMIN")

    # get_managed_user path: first scalar returns user
    db.scalar.side_effect = [user, None, None]

    payload = UserUpdateRequest(
        display_name="新名",
        identities=[
            UserIdentityCreateItem(
                identity_type="PLATFORM",
                role_code="PLATFORM_ADMIN",
                identity_name="平台",
                position_id=None,
                tenant_id=None,
                tenant_name=None,
                menu_ids=[],
            )
        ],
        remove_identity_types=[],
    )

    # Avoid deep upsert DB; patch upsert to no-op after keep-check
    from unittest.mock import patch

    with patch("app.services.management_service.get_managed_user", return_value=user), patch(
        "app.services.management_service._upsert_identity_for_user"
    ) as upsert:
        update_managed_user(db, 9, payload, current_user, current_identity, commit=False)
        assert customer.deleted is False
        assert customer.status is True
        upsert.assert_called_once()


def test_update_user_removes_only_when_explicit():
    db = MagicMock()
    platform = SimpleNamespace(
        id=1,
        identity_type="PLATFORM",
        deleted=False,
        status=True,
    )
    customer = SimpleNamespace(
        id=2,
        identity_type="CUSTOMER",
        deleted=False,
        status=True,
    )
    user = SimpleNamespace(id=9, display_name="旧名", identities=[platform, customer])
    current_user = SimpleNamespace(id=1)
    current_identity = SimpleNamespace(identity_type="PLATFORM", role_code="PLATFORM_ADMIN")
    payload = UserUpdateRequest(
        display_name="新名",
        identities=[
            UserIdentityCreateItem(
                identity_type="PLATFORM",
                role_code="PLATFORM_ADMIN",
                identity_name="平台",
                position_id=None,
                tenant_id=None,
                tenant_name=None,
                menu_ids=[],
            )
        ],
        remove_identity_types=["CUSTOMER"],
    )
    from unittest.mock import patch

    with patch("app.services.management_service.get_managed_user", return_value=user), patch(
        "app.services.management_service._upsert_identity_for_user"
    ):
        update_managed_user(db, 9, payload, current_user, current_identity, commit=False)
        assert customer.deleted is True
        assert customer.status is False
        assert platform.deleted is False
