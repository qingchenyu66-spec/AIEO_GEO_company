"""企业操作记录：客户登录写入，平台身份不写。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.api.v1.endpoints.customer_enterprise import ENTERPRISE_AUDIT_ACTIONS
from app.services.operation_log_service import record_customer_login


def test_enterprise_audit_actions_cover_login_recharge_competitor() -> None:
    assert "登录" in ENTERPRISE_AUDIT_ACTIONS
    assert "充值" in ENTERPRISE_AUDIT_ACTIONS
    assert "竞品" in ENTERPRISE_AUDIT_ACTIONS
    assert "竞品配置" in ENTERPRISE_AUDIT_ACTIONS


def test_record_customer_login_skips_platform() -> None:
    db = MagicMock()
    user = SimpleNamespace(id=1, display_name="运营", username="ops")
    identity = SimpleNamespace(identity_type="PLATFORM", tenant_id=6, identity_name="平台")
    assert record_customer_login(db, user=user, identity=identity) is None
    db.add.assert_not_called()


def test_record_customer_login_writes_customer() -> None:
    db = MagicMock()
    user = SimpleNamespace(id=2, display_name="张三", username="zhang")
    identity = SimpleNamespace(identity_type="CUSTOMER", tenant_id=6, identity_name="艾迪亚")
    row = record_customer_login(db, user=user, identity=identity)
    assert row is not None
    assert row.action_type == "登录"
    assert row.tenant_id == 6
    assert row.operator_name == "张三"
    assert row.description == "登录成功"
