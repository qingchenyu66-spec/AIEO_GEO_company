"""用户列表范围：运营/管理员看全部，销售仅看自己创建的。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.management_service import can_manage_all_users


def test_can_manage_all_users_operation_sees_all(monkeypatch):
    db = MagicMock()
    identity = SimpleNamespace(identity_type="PLATFORM", position_id=2)
    monkeypatch.setattr("app.services.management_service.is_sales_identity", lambda _db, _id: False)
    assert can_manage_all_users(db, identity) is True


def test_can_manage_all_users_sales_limited_to_own(monkeypatch):
    db = MagicMock()
    identity = SimpleNamespace(identity_type="PLATFORM", position_id=3)
    monkeypatch.setattr("app.services.management_service.is_sales_identity", lambda _db, _id: True)
    assert can_manage_all_users(db, identity) is False
