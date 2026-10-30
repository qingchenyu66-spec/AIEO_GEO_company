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


def _platform_display_name(code: str) -> str:
    """审批预览用中文名；只读 fallback 目录，避免每次刷新去拉模力文档。"""
    from app.services.molizhishu_catalog_service import _FALLBACK_CATALOG

    for item in _FALLBACK_CATALOG:
        if str(item.get("code") or "").strip() == code:
            name = str(item.get("name") or "").strip()
            if name:
                return name
    return code


def _platform_labels(raw: Any) -> list[str]:
    """平台列表展示：兼容 string[] 与 {code,mode}[]。"""
    labels: list[str] = []
    for item in normalize_platform_selections(raw if isinstance(raw, list) else []):
        mode = _MODE_SHORT.get(str(item.get("mode") or "standard"), "快速")
        code = str(item.get("code") or "").strip()
        labels.append(f"{_platform_display_name(code)}({mode})")
    return labels


def _body(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = payload or {}
    body = raw.get("body")
    return body if isinstance(body, dict) else raw


def _lead_original_body(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = payload or {}
    original = raw.get("original_body")
    if isinstance(original, dict):
        return original
    return _body(raw)


def _join_list(items: list[Any] | None, *, limit: int = 8) -> str:
    values = [str(item).strip() for item in (items or []) if str(item or "").strip()]
    if not values:
        return "（空）"
    if len(values) <= limit:
        return "、".join(values)
    return "、".join(values[:limit]) + f" 等 {len(values)} 项"


def _change(
    field: str,
    *,
    before: str | None = None,
    after: str | None = None,
    kind: str = "update",
    before_image_url: str | None = None,
    after_image_url: str | None = None,
) -> dict[str, str]:
    item: dict[str, str] = {"field": field, "kind": kind}
    if before is not None:
        item["before"] = before
    if after is not None:
        item["after"] = after
    if before_image_url:
        item["before_image_url"] = before_image_url
    if after_image_url:
        item["after_image_url"] = after_image_url
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


def _group_keyword_list(group: dict[str, Any]) -> list[Any]:
    keywords = group.get("monitor_keywords") or []
    if keywords:
        return keywords
    if group.get("monitor_keyword"):
        return [group.get("monitor_keyword")]
    return []


def _logo_staging_change_row(db: Session | None, tenant_id: int | None, body: dict[str, Any]) -> dict[str, str] | None:
    # 2026-08-25 - Logo 随企业资料进审批 - 预览展示新旧图
    key = str(body.get("logo_staging_key") or "").strip()
    if not key:
        return None
    after_url = f"/api/v1/brand/logo-staging/{key}"
    before_url: str | None = None
    before_label = "（无）"
    if tenant_id and db is not None:
        tenant = db.get(Tenant, tenant_id)
        if tenant and tenant.logo_path:
            before_url = f"/api/v1/management/tenants/{tenant_id}/logo"
            before_label = "当前 Logo"
    return _change(
        "企业 Logo",
        before=before_label,
        after="新 Logo",
        kind="add" if not before_url else "update",
        before_image_url=before_url,
        after_image_url=after_url,
    )


def _goods_card_label(enabled: bool) -> str:
    return "开通" if enabled else "关闭"


def _append_goods_card_preview_row(
    rows: list[dict[str, str]],
    body: dict[str, Any],
    *,
    before_enabled: bool | None = None,
    kind: str = "add",
) -> None:
    """审批对照展示商品卡开关；body 未带该字段时不写入（避免误报变更）。"""
    # 2026-09-04 - 创建/改企业审批预览漏商品卡，审核人看不到开没开
    if "goods_card_enabled" not in body:
        return
    after = _goods_card_label(body.get("goods_card_enabled") is True)
    if before_enabled is None:
        rows.append(_change("商品卡", after=after, kind=kind))
        return
    before = _goods_card_label(bool(before_enabled))
    if before != after:
        rows.append(_change("商品卡", before=before, after=after, kind="update"))


def _brand_bootstrap_changes(body: dict[str, Any]) -> list[dict[str, str]]:
    """新建企业草稿：把官网、监测词、品牌词、竞品等提交内容摊开展示。"""
    # 2026-08-18 - 新建审批只写「N 平台」- 对齐改配置预览，摊开平台/模式和露出词
    # 2026-08-18 - 预览缺中文平台名/词组状态/竞品分类 - 一并摊开
    rows: list[dict[str, str]] = [
        _change("官网 / 主站", after=str(body.get("official_url") or "").strip() or "（空）", kind="add"),
        _change("品牌说明", after=str(body.get("description") or "").strip() or "（空）", kind="add"),
    ]
    # 新建草稿前端总会带 goods_card_enabled；缺省按关闭展示
    _append_goods_card_preview_row(
        rows,
        {"goods_card_enabled": body.get("goods_card_enabled") is True},
        kind="add",
    )
    regions = region_display_labels(body.get("region_codes"))
    if regions and regions != "—":
        rows.append(_change("监测地区", after=regions, kind="add"))
    times = _join_list(body.get("schedule_times"))
    if times:
        rows.append(_change("监测时段", after=times, kind="add"))
    keyword_groups = [item for item in (body.get("keyword_groups") or []) if isinstance(item, dict)]
    rows.append(_change("监测词组数", after=str(len(keyword_groups)), kind="add"))
    for index, group in enumerate(keyword_groups[:8]):
        name = str(group.get("name") or f"词组{index + 1}").strip() or f"词组{index + 1}"
        prefix = f"监测词组「{name}」"
        # 2026-08-18 - 词组预览一行塞词/平台/模式 - 拆成字段行，停用才单独标
        if not group.get("status", True):
            rows.append(_change(f"{prefix}状态", after="停用", kind="add"))
        rows.append(
            _change(f"{prefix}监测词", after=_join_list(_group_keyword_list(group), limit=6), kind="add")
        )
        rows.append(
            _change(f"{prefix}平台", after=_join_list(_platform_labels(group.get("platforms")), limit=6), kind="add")
        )
        rows.append(
            _change(f"{prefix}露出词", after=_join_list(group.get("exposure_terms"), limit=8), kind="add")
        )
    brand_groups = [item for item in (body.get("brand_word_groups") or []) if isinstance(item, dict)]
    if brand_groups:
        rows.append(_change("品牌词组数", after=str(len(brand_groups)), kind="add"))
        for index, group in enumerate(brand_groups[:8]):
            name = str(group.get("name") or f"品牌词组{index + 1}").strip() or f"品牌词组{index + 1}"
            prefix = f"品牌词组「{name}」"
            run_mode = str(group.get("run_mode") or "once").strip().lower()
            mode_label = "每周" if run_mode == "weekly" else "仅本次"
            if not group.get("status", True):
                rows.append(_change(f"{prefix}状态", after="停用", kind="add"))
            rows.append(_change(f"{prefix}运行", after=mode_label, kind="add"))
            rows.append(
                _change(f"{prefix}平台", after=_join_list(_platform_labels(group.get("platforms")), limit=6), kind="add")
            )
            rows.append(
                _change(f"{prefix}品牌词", after=_join_list(_group_keyword_list(group), limit=6), kind="add")
            )
    competitors = [item for item in (body.get("competitors") or []) if isinstance(item, dict)]
    competitor_labels: list[str] = []
    for item in competitors:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        category = str(item.get("category") or "").strip() or "直接竞品"
        competitor_labels.append(f"{name}（{category}）")
    rows.append(_change("竞品", after=_join_list(competitor_labels, limit=20), kind="add"))
    logo_row = _logo_staging_change_row(None, None, body)
    if logo_row:
        rows.append(logo_row)
    return rows


def _brand_changes(db: Session, tenant_id: int | None, body: dict[str, Any]) -> list[dict[str, str]]:
    if tenant_id is None:
        return _brand_bootstrap_changes(body)

    asset = get_brand_asset(db, tenant_id)
    groups = list_keyword_groups(db, tenant_id)
    before = asset_to_dict(asset, groups) if asset else None
    after_name = str(body.get("company_full_name") or body.get("brand_name") or "").strip()

    if before is None:
        rows = [
            _change("操作类型", after="新建企业配置", kind="info"),
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
        logo_row = _logo_staging_change_row(db, tenant_id, body)
        if logo_row:
            rows.append(logo_row)
        _append_goods_card_preview_row(rows, body, kind="add")
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

    logo_row = _logo_staging_change_row(db, tenant_id, body)
    if logo_row:
        rows.append(logo_row)

    if db is not None and tenant_id is not None:
        tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
        before_goods = bool(getattr(tenant, "goods_card_enabled", False)) if tenant else False
        _append_goods_card_preview_row(rows, body, before_enabled=before_goods)

    if not rows:
        rows.append(_change("变更说明", after="提交内容与当前生效配置一致或差异未识别", kind="info"))
    return rows


def brand_asset_has_changes(db: Session, tenant_id: int | None, body: dict[str, Any]) -> bool:
    """是否存在可识别的企业配置变更（用于无变更时跳过销售审批）。"""
    # 2026-08-25 - Logo 暂存 key 本身即变更，勿因其它字段相同被短路
    if str(body.get("logo_staging_key") or "").strip():
        return True
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
        rows.append(_change("登录账号", after=str(body.get("username") or "—"), kind="update"))
        rows.append(_change("显示名称", after=str(body.get("display_name") or "—"), kind="update"))
        rows.append(_change("登录身份", after=_identity_summary(body.get("identities")), kind="update"))
        return rows

    new_username = str(body.get("username") or "").strip()
    if new_username and new_username != (user.username or ""):
        rows.append(_change("登录账号", before=user.username or "（空）", after=new_username))
    new_name = str(body.get("display_name") or "").strip()
    if new_name and new_name != (user.display_name or ""):
        rows.append(_change("显示名称", before=user.display_name or "（空）", after=new_name))
    rows.append(_change("登录身份", after=_identity_summary(body.get("identities")), kind="update"))
    return rows


def _tenant_changes(body: dict[str, Any], *, is_create: bool) -> list[dict[str, str]]:
    kind = "add" if is_create else "update"
    return [
        _change("操作类型", after="新增企业" if is_create else "修改企业资料", kind=kind),
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


def _lead_field_map(body: dict[str, Any]) -> dict[str, str]:
    """统一字段展示文案，供原文/采用对照。"""
    prompts = [str(item).strip() for item in (body.get("prompts") or []) if str(item or "").strip()]
    fields: dict[str, str] = {
        "品牌名称": str(body.get("brand_name") or "—").strip() or "—",
        "竞品": _join_list(body.get("competitors"), limit=20),
        "监测地区": region_display_labels(body.get("region_codes")),
        "诊断平台": _lead_platform_display(body.get("platforms")),
        "诊断天数": f"{body.get('schedule_days') or 3} 天",
    }
    if not prompts:
        fields["检测问题"] = "（空）"
    else:
        for index, prompt in enumerate(prompts, start=1):
            fields[f"检测问题 {index}"] = prompt
    note = str(body.get("contact_note") or "").strip()
    fields["销售备注"] = note or "（无）"
    return fields


def _lead_changes(body: dict[str, Any], *, is_create: bool, original: dict[str, Any] | None = None) -> list[dict[str, str]]:
    # 2026-08-04 - 售前诊断审批对照：变更前=销售原文，变更后=审批采用
    adopted_map = _lead_field_map(body)
    original_map = _lead_field_map(original or body)
    keys = list(dict.fromkeys([*original_map.keys(), *adopted_map.keys()]))
    rows = [
        _change(
            "操作类型",
            after="新建售前诊断" if is_create else "修改售前诊断",
            kind="info",
        )
    ]
    for key in keys:
        before = original_map.get(key, "—")
        after = adopted_map.get(key, "—")
        kind = "update" if before != after else ("add" if is_create else "info")
        rows.append(_change(key, before=before, after=after, kind=kind))
    return rows


def _lead_platform_display(raw: Any) -> str:
    from app.services.molizhishu_catalog_service import get_supported_platform_catalog

    name_map = {
        str(item.get("code") or "").strip(): str(item.get("name") or item.get("code") or "").strip()
        for item in get_supported_platform_catalog()
        if str(item.get("code") or "").strip()
    }
    labels: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict):
            code = str(item.get("code") or item.get("platform") or "").strip()
        else:
            code = str(item or "").strip()
        if not code:
            continue
        labels.append(name_map.get(code) or code)
    return _join_list(labels, limit=32)


def _brand_word_group_changes(body: dict[str, Any]) -> list[dict[str, str]]:
    groups = [item for item in (body.get("groups") or []) if isinstance(item, dict)]
    rows = [
        _change("操作类型", after="修改品牌词配置", kind="info"),
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
        if record.tenant_id is None:
            # 2026-08-18 - 新建企业草稿：审批预览先展示企业名称/服务期，再摊开配置
            tenant_rows = _tenant_changes(
                {
                    "name": body.get("company_full_name"),
                    "service_start_date": body.get("service_start_date"),
                    "service_end_date": body.get("service_end_date"),
                },
                is_create=True,
            )
            changes = tenant_rows + changes
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
    elif key == "management.tenant.restore":
        tenant = db.scalar(select(Tenant).where(Tenant.id == record.tenant_id)) if record.tenant_id else None
        changes = [
            _change("操作类型", after="恢复企业服务", kind="info"),
            _change("企业名称", after=(tenant.name if tenant else "—"), kind="update"),
        ]
    elif key == "reports.custom_period":
        changes = [
            _change("操作类型", after="导出周期报告", kind="info"),
            _change("报告类型", after=str(body.get("report_type") or "custom"), kind="add"),
            _change("开始日期", after=str(body.get("period_start") or "—"), kind="add"),
            _change("结束日期", after=str(body.get("period_end") or "—"), kind="add"),
        ]
    elif key in {"reports.generate", "reports.update", "reports.publish"}:
        action = {"reports.generate": "create", "reports.update": "update", "reports.publish": "publish"}[key]
        changes = _report_changes(body, action=action)
    elif key == "lead_diagnosis.create":
        changes = _lead_changes(body, is_create=True, original=_lead_original_body(payload))
    elif key == "lead_diagnosis.update":
        changes = _lead_changes(body, is_create=False, original=_lead_original_body(payload))
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
