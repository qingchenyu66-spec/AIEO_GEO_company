"""审批单变更预览：供运营/管理员查看具体新增或修改内容。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.region_catalog import region_display_labels
from app.models.approval import OperationApproval
from app.models.tenant import Tenant
from app.models.user import User
from app.services.brand_service import asset_to_dict, get_brand_asset, list_keyword_groups
from app.services.platform_selection import normalize_platform_selections, selection_codes


_MODE_SHORT = {
    "standard": "快速",
    "search": "快速",
    "reasoning": "深度思考",
    "reasoning_search": "深度思考",
}


def _platform_labels(raw: Any) -> list[str]:
    """平台列表展示：兼容 string[] 与 {code,mode}[]。"""
    labels: list[str] = []
    for item in normalize_platform_selections(raw if isinstance(raw, list) else []):
        mode = _MODE_SHORT.get(str(item.get("mode") or "standard"), "快速")
        labels.append(f"{item['code']}({mode})")
    return labels


def _body(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = payload or {}
    body = raw.get("body")
    return body if isinstance(body, dict) else raw


def _join_list(items: list[Any] | None, *, limit: int = 8) -> str:
    values = [str(item).strip() for item in (items or []) if str(item or "").strip()]
    if not values:
        return "（空）"
    if len(values) <= limit:
        return "、".join(values)
    return "、".join(values[:limit]) + f" 等 {len(values)} 项"


def _change(field: str, *, before: str | None = None, after: str | None = None, kind: str = "update") -> dict[str, str]:
    item: dict[str, str] = {"field": field, "kind": kind}
    if before is not None:
        item["before"] = before
    if after is not None:
        item["after"] = after
    return item


def _identity_summary(identities: list[dict[str, Any]] | None) -> str:
    parts: list[str] = []
    for item in identities or []:
        if not isinstance(item, dict):
            continue
        identity_type = "平台" if item.get("identity_type") == "PLATFORM" else "客户"
        role = str(item.get("role_code") or item.get("identity_name") or "").strip()
        tenant_name = str(item.get("tenant_name") or "").strip()
        chunk = f"{identity_type}/{role}" if role else identity_type
        if tenant_name:
            chunk += f"@{tenant_name}"
        parts.append(chunk)
    return "；".join(parts) or "（未配置身份）"


def _brand_changes(db: Session, tenant_id: int | None, body: dict[str, Any]) -> list[dict[str, str]]:
    if tenant_id is None:
        return [_change("企业配置", after="保存企业品牌与监测配置", kind="info")]

    asset = get_brand_asset(db, tenant_id)
    groups = list_keyword_groups(db, tenant_id)
    before = asset_to_dict(asset, groups) if asset else None
    after_name = str(body.get("company_full_name") or body.get("brand_name") or "").strip()

    if before is None:
        rows = [
            _change("操作类型", after="首次保存企业配置", kind="info"),
            _change("企业全称", after=after_name or "—", kind="add"),
            _change("监测地区", after=region_display_labels(body.get("region_codes")), kind="add"),
            _change("监测时段", after=_join_list(body.get("schedule_times")), kind="add"),
            _change("监测词组数", after=str(len(body.get("keyword_groups") or [])), kind="add"),
        ]
        groups_payload = body.get("keyword_groups") or []
        if groups_payload:
            first = groups_payload[0] if isinstance(groups_payload[0], dict) else {}
            rows.append(
                _change(
                    "词组示例",
                    after=f"{first.get('name') or '词组1'}：监测词 {_join_list(first.get('monitor_keywords') or ([first.get('monitor_keyword')] if first.get('monitor_keyword') else []), limit=5)}",
                    kind="add",
                )
            )
        return rows

    rows: list[dict[str, str]] = []
    pairs = [
        ("company_full_name", "企业全称"),
        ("brand_name", "品牌名"),
        ("brand_short_name", "品牌简称"),
        ("official_url", "官网"),
        ("description", "品牌说明"),
        ("schedule_type", "调度类型"),
    ]
    for key, label in pairs:
        old_val = str(before.get(key) or "").strip()
        new_val = str(body.get(key) or "").strip()
        if old_val != new_val:
            rows.append(_change(label, before=old_val or "（空）", after=new_val or "（空）"))

    old_freq = before.get("schedule_frequency")
    new_freq = body.get("schedule_frequency")
    if old_freq is not None and new_freq is not None and int(old_freq or 0) != int(new_freq or 0):
        rows.append(_change("每日执行次数", before=str(old_freq), after=str(new_freq)))

    old_regions = region_display_labels(before.get("region_codes"))
    new_regions = region_display_labels(body.get("region_codes"))
    if old_regions != new_regions:
        rows.append(_change("监测地区", before=old_regions, after=new_regions))

    old_times = _join_list(before.get("schedule_times"))
    new_times = _join_list(body.get("schedule_times"))
    if old_times != new_times:
        rows.append(_change("监测时段", before=old_times, after=new_times))

    old_weekdays = _join_list(before.get("schedule_weekdays"))
    new_weekdays = _join_list(body.get("schedule_weekdays"))
    if old_weekdays != new_weekdays:
        rows.append(_change("每周执行日", before=old_weekdays, after=new_weekdays))

    old_month_days = _join_list(before.get("schedule_month_days"))
    new_month_days = _join_list(body.get("schedule_month_days"))
    if old_month_days != new_month_days:
        rows.append(_change("每月执行日", before=old_month_days, after=new_month_days))

    old_aliases = _join_list(before.get("aliases"))
    new_aliases = _join_list(body.get("aliases"))
    if old_aliases != new_aliases:
        rows.append(_change("露出词/别名", before=old_aliases, after=new_aliases))

    old_groups = before.get("keyword_groups") or []
    new_groups = body.get("keyword_groups") or []
    if len(old_groups) != len(new_groups):
        rows.append(_change("监测词组数量", before=str(len(old_groups)), after=str(len(new_groups))))

    def _group_keywords(group: dict[str, Any]) -> list[str]:
        raw = group.get("monitor_keywords")
        if isinstance(raw, list) and raw:
            return [str(item).strip() for item in raw if str(item or "").strip()]
        single = str(group.get("monitor_keyword") or "").strip()
        return [single] if single else []

    def _group_key(group: dict[str, Any], index: int) -> str:
        gid = group.get("id")
        if gid is not None:
            return f"id:{gid}"
        name = str(group.get("name") or "").strip()
        return f"name:{name}" if name else f"idx:{index}"

    old_by_key = {_group_key(group, index): group for index, group in enumerate(old_groups) if isinstance(group, dict)}
    new_by_key = {_group_key(group, index): group for index, group in enumerate(new_groups) if isinstance(group, dict)}

    for key, group in new_by_key.items():
        if key in old_by_key:
            continue
        name = str(group.get("name") or "未命名词组").strip()
        rows.append(
            _change(
                f"新增词组「{name}」",
                after=f"监测词 {_join_list(_group_keywords(group), limit=6)}；平台 {_join_list(_platform_labels(group.get('platforms')), limit=6)}",
                kind="add",
            )
        )

    for key, group in old_by_key.items():
        if key in new_by_key:
            continue
        name = str(group.get("name") or "未命名词组").strip()
        rows.append(
            _change(
                f"删除词组「{name}」",
                before=f"监测词 {_join_list(_group_keywords(group), limit=6)}",
                kind="delete",
            )
        )

    for key, old_group in old_by_key.items():
        new_group = new_by_key.get(key)
        if new_group is None:
            continue
        name = str(new_group.get("name") or old_group.get("name") or "未命名词组").strip()
        old_kw = _join_list(_group_keywords(old_group), limit=8)
        new_kw = _join_list(_group_keywords(new_group), limit=8)
        if old_kw != new_kw:
            rows.append(_change(f"词组「{name}」监测词", before=old_kw, after=new_kw))
        old_exp = _join_list(old_group.get("exposure_terms"), limit=8)
        new_exp = _join_list(new_group.get("exposure_terms"), limit=8)
        if old_exp != new_exp:
            rows.append(_change(f"词组「{name}」露出词", before=old_exp, after=new_exp))
        old_plat = _join_list(_platform_labels(old_group.get("platforms")), limit=6)
        new_plat = _join_list(_platform_labels(new_group.get("platforms")), limit=6)
        if old_plat != new_plat:
            rows.append(_change(f"词组「{name}」平台", before=old_plat, after=new_plat))
        old_name = str(old_group.get("name") or "").strip()
        new_name = str(new_group.get("name") or "").strip()
        if old_name and new_name and old_name != new_name:
            rows.append(_change("词组名称", before=old_name, after=new_name))
        old_status = bool(old_group.get("status", True))
        new_status = bool(new_group.get("status", True))
        if old_status != new_status:
            rows.append(
                _change(
                    f"词组「{name}」状态",
                    before="启用" if old_status else "停用",
                    after="启用" if new_status else "停用",
                )
            )

    old_codes: set[str] = set()
    new_codes: set[str] = set()
    for group in old_groups:
        if isinstance(group, dict):
            old_codes.update(selection_codes(group.get("platforms")))
    for group in new_groups:
        if isinstance(group, dict):
            new_codes.update(selection_codes(group.get("platforms")))
    old_platforms = _join_list(sorted(old_codes))
    new_platforms = _join_list(sorted(new_codes))
    if old_platforms != new_platforms and not any(row.get("field", "").endswith("」平台") for row in rows):
        rows.append(_change("监测平台（汇总）", before=old_platforms, after=new_platforms))

    if not rows:
        rows.append(_change("变更说明", after="提交内容与当前生效配置一致或差异未识别", kind="info"))
    return rows


def brand_asset_has_changes(db: Session, tenant_id: int | None, body: dict[str, Any]) -> bool:
    """是否存在可识别的企业配置变更（用于无变更时跳过销售审批）。"""
    # 2026-07-29 - 无差异仍进审批制造空单：先用完整 diff 判定，确认无变更再短路
    rows = _brand_changes(db, tenant_id, body)
    for row in rows:
        if row.get("field") == "变更说明" and row.get("kind") == "info":
            continue
        return True
    return False


def _user_create_changes(db: Session, body: dict[str, Any]) -> list[dict[str, str]]:
    tenant_ids: list[int] = []
    tenant_names: list[str] = []
    for item in body.get("identities") or []:
        if not isinstance(item, dict):
            continue
        tid = item.get("tenant_id")
        tname = item.get("tenant_name")
        if tname:
            tenant_names.append(str(tname))
        elif tid:
            tenant_ids.append(int(tid))
    if tenant_ids:
        name_map = {
            tenant.id: tenant.name
            for tenant in db.scalars(select(Tenant).where(Tenant.id.in_(tenant_ids)))
        }
        tenant_names.extend(name_map[tid] for tid in tenant_ids if tid in name_map)
    return [
        _change("操作类型", after="新建用户账号", kind="info"),
        _change("登录账号", after=str(body.get("username") or "—"), kind="add"),
        _change("显示名称", after=str(body.get("display_name") or "—"), kind="add"),
        _change("登录身份", after=_identity_summary(body.get("identities")), kind="add"),
        _change("关联企业", after=_join_list(tenant_names) if tenant_names else "无", kind="add"),
    ]


def _user_update_changes(db: Session, body: dict[str, Any], user_id: int | None) -> list[dict[str, str]]:
    user = db.scalar(select(User).where(User.id == user_id)) if user_id else None
    rows = [_change("操作类型", after=f"修改用户 #{user_id}", kind="info")]
    if user is None:
        rows.append(_change("显示名称", after=str(body.get("display_name") or "—"), kind="update"))
        rows.append(_change("登录身份", after=_identity_summary(body.get("identities")), kind="update"))
        return rows

    new_name = str(body.get("display_name") or "").strip()
    if new_name and new_name != (user.display_name or ""):
        rows.append(_change("显示名称", before=user.display_name or "（空）", after=new_name))
    rows.append(_change("登录身份", after=_identity_summary(body.get("identities")), kind="update"))
    return rows


def _tenant_changes(body: dict[str, Any], *, is_create: bool) -> list[dict[str, str]]:
    kind = "add" if is_create else "update"
    return [
        _change("操作类型", after="新建企业" if is_create else "修改企业资料", kind="info"),
        _change("企业名称", after=str(body.get("name") or "—"), kind=kind),
        _change("企业编码", after=str(body.get("code") or "（自动生成）"), kind=kind),
        _change("服务开始", after=str(body.get("service_start_date") or "—"), kind=kind),
        _change("服务结束", after=str(body.get("service_end_date") or "—"), kind=kind),
    ]


def _report_changes(body: dict[str, Any], *, action: str) -> list[dict[str, str]]:
    title = str(body.get("report_title") or body.get("title") or "未命名报告")
    if action == "publish":
        return [_change("操作类型", after="发布分析报告", kind="info"), _change("报告标题", after=title, kind="update")]
    if action == "create":
        return [_change("操作类型", after="生成分析报告", kind="info"), _change("报告标题", after=title, kind="add")]
    return [_change("操作类型", after="编辑分析报告", kind="info"), _change("报告标题", after=title, kind="update")]


def _lead_changes(body: dict[str, Any], *, is_create: bool) -> list[dict[str, str]]:
    kind = "add" if is_create else "update"
    return [
        _change("操作类型", after="新建售前诊断" if is_create else "修改售前诊断", kind="info"),
        _change("品牌名称", after=str(body.get("brand_name") or "—"), kind=kind),
        _change("检测问题", after=_join_list(body.get("prompts"), limit=5), kind=kind),
        _change("竞品", after=_join_list(body.get("competitors"), limit=5), kind=kind),
        _change("监测地区", after=region_display_labels(body.get("region_codes")), kind=kind),
        _change("诊断天数", after=str(body.get("schedule_days") or "3"), kind=kind),
        _change("销售备注", after=str(body.get("contact_note") or "（无）"), kind=kind),
    ]


def _brand_word_group_changes(body: dict[str, Any]) -> list[dict[str, str]]:
    groups = [item for item in (body.get("groups") or []) if isinstance(item, dict)]
    rows = [
        _change("操作类型", after="保存品牌词配置", kind="info"),
        _change("词组数量", after=str(len(groups)), kind="update"),
    ]
    for index, group in enumerate(groups[:8]):
        name = str(group.get("name") or f"词组{index + 1}").strip() or f"词组{index + 1}"
        keywords = group.get("monitor_keywords") or []
        if not keywords and group.get("monitor_keyword"):
            keywords = [group.get("monitor_keyword")]
        run_mode = str(group.get("run_mode") or "once").strip().lower()
        mode_label = "每周" if run_mode == "weekly" else "仅本次"
        status_label = "启用" if group.get("status", True) else "停用"
        plat_n = len(group.get("platforms") or [])
        rows.append(
            _change(
                f"词组「{name}」",
                after=f"{status_label} · {mode_label} · {plat_n} 平台 · {_join_list(keywords, limit=6)}",
                kind="update",
            )
        )
    if len(groups) > 8:
        rows.append(_change("其余词组", after=f"另有 {len(groups) - 8} 组未展开", kind="info"))
    if not groups:
        rows.append(_change("变更说明", after="提交了空品牌词列表（将清空启用配置）", kind="info"))
    return rows


def build_approval_preview(db: Session, record: OperationApproval) -> dict[str, Any]:
    payload = record.payload_json if isinstance(record.payload_json, dict) else {}
    body = _body(payload)
    key = record.operation_key

    if key == "brand.asset.upsert":
        changes = _brand_changes(db, record.tenant_id, body)
    elif key == "brand.brand_word_groups.upsert":
        changes = _brand_word_group_changes(body)
    elif key == "management.user.create":
        changes = _user_create_changes(db, body)
    elif key == "management.user.update":
        changes = _user_update_changes(db, body, int(payload.get("user_id") or record.target_id or 0) or None)
    elif key == "management.tenant.create":
        changes = _tenant_changes(body, is_create=True)
    elif key == "management.tenant.update":
        changes = _tenant_changes(body, is_create=False)
    elif key in {"reports.generate", "reports.update", "reports.publish"}:
        action = {"reports.generate": "create", "reports.update": "update", "reports.publish": "publish"}[key]
        changes = _report_changes(body, action=action)
    elif key == "lead_diagnosis.create":
        changes = _lead_changes(body, is_create=True)
    elif key == "lead_diagnosis.update":
        changes = _lead_changes(body, is_create=False)
    elif key == "lead_diagnosis.submit_run":
        changes = [
            _change("操作类型", after="提交售前诊断抓取", kind="info"),
            _change("诊断 ID", after=str(payload.get("lead_id") or record.target_id or "—"), kind="info"),
            _change("调度窗口", after=str(payload.get("schedule_key") or "下一窗口"), kind="info"),
        ]
    elif key == "diagnosis.record.create":
        changes = [
            _change("操作类型", after="创建品牌诊断记录", kind="info"),
            _change("诊断标题", after=str(body.get("diagnosis_title") or "品牌诊断"), kind="add"),
        ]
    else:
        changes = [_change("原始参数", after="请在技术支持下查看 payload", kind="info")]

    return {"changes": changes, "change_count": len(changes)}
