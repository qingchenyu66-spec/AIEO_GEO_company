"""会话身份需带回 position_code，供前端区分销售。"""

from types import SimpleNamespace

from app.api.v1.endpoints.auth import identity_info


def test_identity_info_includes_position_code(monkeypatch) -> None:
    position = SimpleNamespace(position_name="销售", position_code="PLATFORM_SALES")
    identity = SimpleNamespace(
        id=1,
        identity_type="PLATFORM",
        identity_name="销售",
        role_code="PLATFORM_OPERATOR",
        position_id=9,
        tenant_id=None,
        tenant=None,
        is_default=True,
    )
    db = SimpleNamespace(scalar=lambda *_a, **_k: position)
    info = identity_info(identity, db)  # type: ignore[arg-type]
    assert info["position_code"] == "PLATFORM_SALES"
    assert info["position_name"] == "销售"
