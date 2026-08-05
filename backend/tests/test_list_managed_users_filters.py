"""用户列表筛选：所属端 + 职位落在同一身份；关键字可命中职位名。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.management_service import list_managed_users


def _capture_stmt(monkeypatch, **filters):
    recorded: dict = {}
    db = MagicMock()

    def scalars(stmt):
        recorded["stmt"] = stmt
        result = MagicMock()
        result.unique.return_value = []
        return result

    db.scalars.side_effect = scalars
    monkeypatch.setattr(
        "app.services.management_service.can_manage_all_users",
        lambda *_args, **_kwargs: True,
    )
    user = SimpleNamespace(id=1)
    identity = SimpleNamespace(identity_type="PLATFORM", position_id=1)
    list_managed_users(db, user, identity, **filters)
    return recorded["stmt"]


def test_list_managed_users_combines_identity_and_position(monkeypatch):
    # 2026-08-05 - 双身份串匹风险 - 端+职位必须 and 在同一 any() 条件里
    stmt = _capture_stmt(monkeypatch, identity_type="PLATFORM", position_id=42)
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "PLATFORM" in sql
    assert "42" in sql
    assert "identity_type = 'PLATFORM' AND sys_user_identity.position_id = 42" in sql


def test_list_managed_users_keyword_matches_position_name(monkeypatch):
    stmt = _capture_stmt(monkeypatch, keyword="销售")
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "销售" in sql
    assert "position_name" in sql.lower() or "sys_position" in sql.lower()
