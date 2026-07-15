"""操作日志展示用中文标签与可读描述。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import parse_qs

_METHOD_LABELS = {
    "POST": "提交",
    "PUT": "修改",
    "PATCH": "更新",
    "DELETE": "删除",
}

_API_PREFIX_MODULES = (
    ("/api/v1/monitor/", "监测运营"),
    ("/api/v1/auth/", "登录认证"),
    ("/api/v1/brand/", "品牌资产"),
    ("/api/v1/diagnosis/", "诊断中心"),
    ("/api/v1/lead-diagnosis/", "售前诊断"),
    ("/api/v1/knowledge/", "知识库"),
    ("/api/v1/reports/", "报告中心"),
    ("/api/v1/management/", "平台管理"),
    ("/api/v1/analytics/", "数据分析"),
    ("/api/v1/platforms/", "平台对接"),
    ("/api/v1/alerts/", "告警任务"),
    ("/api/v1/notifications/", "消息通知"),
    ("/api/v1/ops/", "系统运维"),
)

_PATH_IN_DESC = re.compile(r"^(GET|POST|PUT|PATCH|DELETE)\s+(/api/\S+)")

_ROUTE_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("POST", re.compile(r"^/api/v1/auth/switch-identity$"), "切换登录身份：切换到其他已授权身份"),
    ("POST", re.compile(r"^/api/v1/auth/logout$"), "退出登录：结束当前会话"),
    ("POST", re.compile(r"^/api/v1/monitor/tasks$"), "创建监测任务：提交新一轮 GEO 检测抓取"),
    ("POST", re.compile(r"^/api/v1/monitor/tasks/\d+/sync$"), "同步监测任务：拉取最新进度与检测结果"),
    (
        "POST",
        re.compile(r"^/api/v1/monitor/subtasks/[^/]+/snapshot-backfill$"),
        "快照补录：粘贴 AI 回答正文并重算排名与健康分",
    ),
    ("POST", re.compile(r"^/api/v1/monitor/scheduled/run-due$"), "执行到期调度：自动提交已到期的定时监测任务"),
    ("PUT", re.compile(r"^/api/v1/brand/asset$"), "修改品牌资产：更新品牌名称、关键词等基础信息"),
    ("POST", re.compile(r"^/api/v1/brand/competitors$"), "新增竞品：添加到竞品监测列表"),
    ("PUT", re.compile(r"^/api/v1/brand/competitors/\d+$"), "修改竞品：更新竞品名称或监测配置"),
    ("DELETE", re.compile(r"^/api/v1/brand/competitors/\d+$"), "删除竞品：从监测列表移除"),
    ("POST", re.compile(r"^/api/v1/lead-diagnosis/?$"), "新建售前诊断：为潜在客户创建诊断项目"),
    ("PUT", re.compile(r"^/api/v1/lead-diagnosis/\d+$"), "修改售前诊断：更新客户信息或诊断配置"),
    ("POST", re.compile(r"^/api/v1/lead-diagnosis/\d+/submit-run$"), "提交售前诊断：启动三时段全平台抓取"),
    ("POST", re.compile(r"^/api/v1/lead-diagnosis/\d+/refresh$"), "刷新售前诊断：重新汇总诊断结果"),
    ("POST", re.compile(r"^/api/v1/diagnosis/records$"), "创建诊断记录：保存品牌诊断结论"),
    ("POST", re.compile(r"^/api/v1/platforms/sync-catalog$"), "同步模型平台目录：更新系统支持平台列表"),
    ("PUT", re.compile(r"^/api/v1/platforms/\d+$"), "修改模型平台：更新平台启用状态或显示配置"),
    ("POST", re.compile(r"^/api/v1/notifications/\d+/read$"), "标记消息已读"),
    ("POST", re.compile(r"^/api/v1/notifications/read-all$"), "全部消息标记已读"),
]

_LEGACY_FRIENDLY = {
    "切换登录身份": "切换登录身份：切换到其他已授权身份",
    "退出登录": "退出登录：结束当前会话",
}


def module_from_api_path(path: str) -> str:
    for prefix, label in _API_PREFIX_MODULES:
        if path.startswith(prefix):
            return label
    return "接口操作"


def path_from_description(description: str | None) -> str | None:
    if not description:
        return None
    match = _PATH_IN_DESC.match(description.strip())
    if not match:
        return None
    return match.group(2).split("?")[0]


def _method_from_description(description: str) -> str | None:
    match = _PATH_IN_DESC.match(description.strip())
    if not match:
        return None
    return match.group(1)


def _match_route_description(method: str, path: str) -> str | None:
    for rule_method, pattern, label in _ROUTE_RULES:
        if rule_method == method and pattern.match(path):
            return label
    return None


def build_friendly_audit_description(
    method: str,
    path: str,
    query_params: Mapping[str, str] | None = None,
) -> str:
    normalized_path = path.split("?")[0]
    matched = _match_route_description(method, normalized_path)
    if matched:
        return matched
    module = module_from_api_path(normalized_path)
    verb = _METHOD_LABELS.get(method, method)
    detail = f"{verb}{module}相关操作"
    if query_params:
        tenant_id = query_params.get("tenant_id")
        if tenant_id and tenant_id.isdigit():
            detail = f"{detail}（企业 ID {tenant_id}）"
    return detail


def humanize_action_type(action_type: str | None) -> str:
    if not action_type:
        return "未知"
    if action_type.startswith("API."):
        method = action_type[4:]
        return _METHOD_LABELS.get(method, method)
    return action_type


def humanize_target_module(
    target_module: str | None,
    *,
    description: str | None = None,
) -> str | None:
    if target_module and target_module != "api.audit":
        return target_module
    path = path_from_description(description)
    if path:
        return module_from_api_path(path)
    if target_module == "api.audit":
        return "接口操作"
    return target_module


def humanize_description(description: str | None) -> str:
    if not description:
        return "未记录操作详情"
    text = description.strip()
    if text in _LEGACY_FRIENDLY:
        return _LEGACY_FRIENDLY[text]
    match = _PATH_IN_DESC.match(text)
    if not match:
        return text
    method = match.group(1)
    raw_target = match.group(2)
    path_only = raw_target.split("?")[0]
    query_string = raw_target.split("?", 1)[1] if "?" in raw_target else ""
    query_params = {key: values[0] for key, values in parse_qs(query_string).items() if values}
    return build_friendly_audit_description(method, path_only, query_params)


def action_type_for_method(method: str) -> str:
    return _METHOD_LABELS.get(method, method)
