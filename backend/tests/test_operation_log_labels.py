"""Tests for operation log Chinese display labels."""

from app.services.operation_log_labels import (
    build_friendly_audit_description,
    humanize_action_type,
    humanize_description,
    humanize_target_module,
    module_from_api_path,
)


def test_humanize_action_type_api_prefix() -> None:
    assert humanize_action_type("API.POST") == "提交"
    assert humanize_action_type("API.PUT") == "修改"
    assert humanize_action_type("企业新增") == "企业新增"


def test_humanize_target_module_legacy_audit() -> None:
    assert (
        humanize_target_module(
            "api.audit",
            description="POST /api/v1/auth/switch-identity",
        )
        == "登录认证"
    )
    assert (
        humanize_target_module(
            "api.audit",
            description="切换登录身份",
        )
        == "接口操作"
    )
    assert humanize_target_module("企业管理") == "企业管理"


def test_module_from_api_path() -> None:
    assert module_from_api_path("/api/v1/monitor/tasks") == "监测运营"
    assert module_from_api_path("/api/v1/unknown/foo") == "接口操作"


def test_humanize_description_from_api_path() -> None:
    assert humanize_description("POST /api/v1/monitor/tasks") == (
        "创建监测任务：向模力指数提交新一轮 GEO 检测"
    )
    assert humanize_description("修改企业「艾迪亚」：名称「旧名」→「新名」") == (
        "修改企业「艾迪亚」：名称「旧名」→「新名」"
    )


def test_build_friendly_audit_description_with_tenant_query() -> None:
    text = build_friendly_audit_description(
        "POST",
        "/api/v1/analytics/summary",
        {"tenant_id": "6"},
    )
    assert "数据分析" in text
    assert "企业 ID 6" in text
