"""Lead diagnosis create platforms validation."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.lead_diagnosis import LeadDiagnosisCreateRequest
from app.services.lead_diagnosis_service import _platform_configs_for_lead


def test_create_request_requires_platforms() -> None:
    with pytest.raises(ValidationError):
        LeadDiagnosisCreateRequest(
            brand_name="测试品牌",
            prompts=["测试品牌哪家好"],
            platforms=[],
        )


def test_create_request_filters_unknown_platforms() -> None:
    payload = LeadDiagnosisCreateRequest(
        brand_name="测试品牌",
        prompts=["测试品牌哪家好"],
        platforms=["doubao", "not_a_real_platform_xyz"],
    )
    assert "doubao" in payload.platforms
    assert "not_a_real_platform_xyz" not in payload.platforms


def test_platform_configs_for_lead_uses_selected() -> None:
    lead = SimpleNamespace(platforms_json=["doubao", "quark"])
    configs = _platform_configs_for_lead(lead)
    assert [item.platform for item in configs] == ["doubao", "quark"]


def test_platform_configs_for_lead_empty_falls_back_to_catalog() -> None:
    lead = SimpleNamespace(platforms_json=[])
    configs = _platform_configs_for_lead(lead)
    assert len(configs) >= 1


def test_assert_lead_platforms_allowed_blocks_outside_whitelist(monkeypatch) -> None:
    from app.services.lead_diagnosis_service import assert_lead_platforms_allowed

    current = SimpleNamespace(identity=SimpleNamespace(id=1, position_id=2))
    monkeypatch.setattr(
        "app.services.menu_permission_service.identity_allowed_monitor_platforms",
        lambda db, identity: ["doubao", "kimi"],
    )
    assert_lead_platforms_allowed(None, current, ["doubao"])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="未授权"):
        assert_lead_platforms_allowed(None, current, ["doubao", "deepseek_mobile"])  # type: ignore[arg-type]


def test_assert_lead_platforms_allowed_empty_whitelist(monkeypatch) -> None:
    from app.services.lead_diagnosis_service import assert_lead_platforms_allowed

    current = SimpleNamespace(identity=SimpleNamespace(id=1, position_id=2))
    monkeypatch.setattr(
        "app.services.menu_permission_service.identity_allowed_monitor_platforms",
        lambda db, identity: [],
    )
    with pytest.raises(ValueError, match="未配置可诊断平台"):
        assert_lead_platforms_allowed(None, current, ["doubao"])  # type: ignore[arg-type]
