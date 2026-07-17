"""未开服企业仍可按 tenant_id 绑定客户账号。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.schemas.permission import UserIdentityCreateItem
from app.services.management_service import _resolve_tenant


def test_resolve_tenant_by_id_allows_inactive():
    db = MagicMock()
    inactive = SimpleNamespace(id=125, status=False, deleted=False, name="载望保研")
    db.scalar.return_value = inactive
    item = UserIdentityCreateItem(
        identity_type="CUSTOMER",
        role_code="TENANT_ADMIN",
        tenant_id=125,
    )
    assert _resolve_tenant(db, item) is inactive


def test_resolve_tenant_by_id_rejects_missing():
    db = MagicMock()
    db.scalar.return_value = None
    item = UserIdentityCreateItem(
        identity_type="CUSTOMER",
        role_code="TENANT_ADMIN",
        tenant_id=99999,
    )
    with pytest.raises(ValueError, match="不存在或已删除"):
        _resolve_tenant(db, item)
