from typing import Any
import re

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.api.dependencies import CurrentSession
from app.core.platform_order import sort_platform_codes
from app.core.region_catalog import normalize_region_codes
from app.models.brand import BrandAsset, BrandCompetitor, BrandKeywordGroup, BrandWordGroup
from app.models.tenant import Tenant
from app.schemas.brand import (
    BrandAssetSaveRequest,
    BrandKeywordGroupSaveRequest,
    BrandWordGroupSaveRequest,
    BrandWordGroupsSaveRequest,
    CompetitorSaveRequest,
)
from app.services.platform_selection import normalize_platform_selections, selection_codes
from app.services.tenant_scope import ensure_sales_tenant_access


def resolve_tenant_id(current: CurrentSession, requested_tenant_id: int | None) -> int:
    """平台端可指定企业；客户端强制使用当前身份绑定企业。"""
    if current.identity.identity_type == "CUSTOMER":
        if current.identity.tenant_id is None:
            raise ValueError("当前客户身份未绑定企业")
        return current.identity.tenant_id
    if requested_tenant_id is None:
        raise ValueError("平台端需要指定企业")
    return requested_tenant_id


def sanitize_brand_asset_payload_for_grants(
    db: Session,
    current: CurrentSession,
    payload: BrandAssetSaveRequest,
) -> BrandAssetSaveRequest:
    """无地区/平台编辑权时，请求体回填库内原值，避免审批 diff / 误覆盖。"""
    from app.services.menu_permission_service import (
        has_identity_menu_permission,
        identity_allowed_monitor_platforms,
    )

    identity_id = current.identity.id
    can_regions = has_identity_menu_permission(db, identity_id, "platform.audit.regions", "can_update")
    # 2026-07-30 - 平台编辑权=职位白名单非空
    can_models = bool(identity_allowed_monitor_platforms(db, current.identity))
    if can_regions and can_models:
        return payload
    if payload.tenant_id is None:
        return payload
    asset = get_brand_asset(db, int(payload.tenant_id))
    if asset is None:
        return payload
    data = payload.model_dump(mode="python")
    if not can_regions:
        data["region_codes"] = list(asset.region_codes_json or [])
    if not can_models:
        existing_groups = {item.id: item for item in list_keyword_groups(db, asset.tenant_id)}
        groups = []
        for item in data.get("keyword_groups") or []:
            gid = item.get("id")
            if gid and gid in existing_groups:
                item = dict(item)
                item["platforms"] = list(existing_groups[gid].platforms_json or [])
            groups.append(item)
        data["keyword_groups"] = groups
        data["monitored_platforms"] = list(asset.monitored_platforms_json or [])
    return BrandAssetSaveRequest(**data)


def _guard_tenant_write(db: Session, current: CurrentSession, tenant_id: int) -> None:
    ensure_tenant(db, tenant_id)
    ensure_sales_tenant_access(db, current, tenant_id)


def ensure_tenant(db: Session, tenant_id: int) -> Tenant:
    """确认企业存在且未删除。"""
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise ValueError("企业不存在")
    return tenant


def get_brand_asset(db: Session, tenant_id: int) -> BrandAsset | None:
    """读取企业品牌资产配置。"""
    return db.scalar(select(BrandAsset).where(BrandAsset.tenant_id == tenant_id, BrandAsset.deleted.is_(False)))


def list_keyword_groups(db: Session, tenant_id: int) -> list[BrandKeywordGroup]:
    """读取企业监测词组，按排序稳定返回。"""
    return list(
        db.scalars(
            select(BrandKeywordGroup)
            .where(BrandKeywordGroup.tenant_id == tenant_id, BrandKeywordGroup.deleted.is_(False))
            .order_by(BrandKeywordGroup.sort_order.asc(), BrandKeywordGroup.id.asc())
        )
    )


def default_keyword_group_name(index: int = 0, *, group_id: int | None = None) -> str:
    if group_id:
        return f"词组 {group_id}"
    return f"词组 {index + 1}"


_GENERIC_KEYWORD_GROUP_NAME = re.compile(r"^词组(?:\s*\d+)?$")


def is_generic_keyword_group_name(name: str | None) -> bool:
    """未自定义命名的默认词组名，展示时应回退到监测关键词。"""
    text = str(name or "").strip()
    return not text or bool(_GENERIC_KEYWORD_GROUP_NAME.match(text))


def keyword_group_name(
    group: BrandKeywordGroup | BrandWordGroup | dict[str, Any] | None,
    index: int = 0,
) -> str:
    if group is None:
        return default_keyword_group_name(index)
    # 2026-07-31 - 品牌词审批通过时 BrandWordGroup 被当 dict.get 炸 500 - 监测/品牌词 ORM 共用字段读取
    if isinstance(group, (BrandKeywordGroup, BrandWordGroup)):
        text = str(group.name or "").strip()
        if text:
            return text
        if group.id:
            return default_keyword_group_name(index, group_id=group.id)
        return default_keyword_group_name(group.sort_order if group.sort_order is not None else index)
    text = str(group.get("name") or "").strip()
    if text:
        return text
    group_id = group.get("id")
    if group_id:
        return default_keyword_group_name(index, group_id=int(group_id))
    sort_order = group.get("sort_order")
    if sort_order is not None:
        return default_keyword_group_name(int(sort_order))
    return default_keyword_group_name(index)


def keyword_group_monitor_keywords(
    group: BrandKeywordGroup | BrandWordGroup | dict[str, Any] | None,
) -> list[str]:
    """Return deduplicated monitor keywords for a keyword group."""
    if group is None:
        return []
    if isinstance(group, (BrandKeywordGroup, BrandWordGroup)):
        raw = list(group.monitor_keywords_json or [])
        if not raw:
            primary = str(group.monitor_keyword or "").strip()
            return [primary] if primary else []
        return _dedupe([str(item or "").strip() for item in raw if str(item or "").strip()])
    raw = list(group.get("monitor_keywords") or [])
    if not raw:
        primary = str(group.get("monitor_keyword") or "").strip()
        return [primary] if primary else []
    return _dedupe([str(item or "").strip() for item in raw if str(item or "").strip()])


def keyword_group_primary_keyword(group: BrandKeywordGroup | dict[str, Any] | None) -> str:
    keywords = keyword_group_monitor_keywords(group)
    return keywords[0] if keywords else ""


def keyword_group_display_label(group: BrandKeywordGroup | dict[str, Any] | None) -> str:
    name = keyword_group_name(group)
    keywords = keyword_group_monitor_keywords(group)
    if not is_generic_keyword_group_name(name):
        return name
    if not keywords:
        return name
    if len(keywords) == 1:
        return keywords[0]
    return f"{keywords[0]}等{len(keywords)}词"


def keyword_group_platform_configs(
    group: BrandKeywordGroup | BrandWordGroup | dict[str, Any] | None,
    asset: BrandAsset | None = None,
) -> list[dict[str, Any]]:
    """词组平台配置（code/mode/screenshot）；无配置时回退企业级 code 列表。"""
    if group is None:
        codes = list(asset.monitored_platforms_json or []) if asset else []
        return normalize_platform_selections(codes)
    # 2026-07-31 - 同上：BrandWordGroup 走 ORM 分支读 platforms_json，勿 .get
    if isinstance(group, (BrandKeywordGroup, BrandWordGroup)):
        raw = list(group.platforms_json or [])
    else:
        raw = list(group.get("platforms") or [])
    configs = normalize_platform_selections(raw)
    if configs:
        return configs
    codes = list(asset.monitored_platforms_json or []) if asset else []
    return normalize_platform_selections(codes)


def keyword_group_platforms(
    group: BrandKeywordGroup | BrandWordGroup | dict[str, Any] | None,
    asset: BrandAsset | None = None,
) -> list[str]:
    """词组绑定的监测平台编码；无配置时回退企业级平台范围（兼容旧数据）。"""
    return selection_codes(keyword_group_platform_configs(group, asset))


def tenant_purchased_platforms(db: Session, tenant_id: int, asset: BrandAsset | None = None) -> list[str]:
    """企业已购/可用平台：优先汇总各启用词组平台。"""
    asset = asset or get_brand_asset(db, tenant_id)
    if asset is None:
        return []
    union: set[str] = set()
    for group in list_keyword_groups(db, tenant_id):
        if not group.status or group.deleted:
            continue
        union.update(keyword_group_platforms(group, asset))
    if union:
        return sort_platform_codes(list(union))
    return sort_platform_codes(list(asset.monitored_platforms_json or []))


def _fallback_keyword_groups(asset: BrandAsset) -> list[dict[str, Any]]:
    """旧数据没有词组表时，用旧字段临时拼出一组可用关系。"""
    monitor_keywords = _dedupe([asset.company_full_name, asset.brand_name, asset.brand_short_name, *(asset.monitor_keywords_json or [])])
    aliases = _dedupe([asset.brand_short_name, *(asset.aliases_json or [])])
    result: list[dict[str, Any]] = []
    for index, keyword in enumerate(monitor_keywords):
        result.append({
            "id": None,
            "tenant_id": asset.tenant_id,
            "name": default_keyword_group_name(index),
            "monitor_keyword": keyword,
            "monitor_keywords": [keyword],
            "exposure_terms": aliases if index == 0 else [keyword],
            "platforms": sort_platform_codes(list(asset.monitored_platforms_json or [])),
            "sort_order": index,
            "status": True,
        })
    return result


def keyword_group_to_dict(group: BrandKeywordGroup) -> dict[str, Any]:
    """序列化监测词组。"""
    monitor_keywords = keyword_group_monitor_keywords(group)
    primary = monitor_keywords[0] if monitor_keywords else str(group.monitor_keyword or "").strip()
    payload = {
        "id": group.id,
        "tenant_id": group.tenant_id,
        "name": keyword_group_name(group),
        "monitor_keyword": primary,
        "monitor_keywords": monitor_keywords,
        "exposure_terms": group.exposure_terms_json or [],
        "platforms": keyword_group_platform_configs(group),
        "sort_order": group.sort_order,
        "status": group.status,
    }
    payload["display_name"] = keyword_group_display_label(group)
    return payload


def ensure_keyword_group_payload(group: BrandKeywordGroup | dict[str, Any], index: int = 0) -> dict[str, Any]:
    """统一输出词组结构，确保 monitor_keywords 始终完整返回。"""
    if isinstance(group, BrandKeywordGroup):
        payload = keyword_group_to_dict(group)
    else:
        monitor_keywords = keyword_group_monitor_keywords(group)
        primary = monitor_keywords[0] if monitor_keywords else str(group.get("monitor_keyword") or "").strip()
        payload = {
            "id": group.get("id"),
            "tenant_id": group.get("tenant_id"),
            "name": keyword_group_name(group, index),
            "monitor_keyword": primary,
            "monitor_keywords": monitor_keywords,
            "exposure_terms": list(group.get("exposure_terms") or []),
            "platforms": keyword_group_platform_configs(group, asset=None),
            "sort_order": group.get("sort_order", index),
            "status": group.get("status", True),
        }
    payload["display_name"] = keyword_group_display_label(
        group if isinstance(group, BrandKeywordGroup) else payload
    )
    return payload


def editable_keyword_groups(db: Session, tenant_id: int) -> list[BrandKeywordGroup | dict[str, Any]]:
    """企业管理页读取全部词组（含停用）；无词组表数据时不再用企业名拼默认词。"""
    asset = get_brand_asset(db, tenant_id)
    if asset is None:
        return []
    rows = list_keyword_groups(db, tenant_id)
    # 2026-07-30 - 监测词进来为空；旧字段回退仅给调度/监测用 active_keyword_groups
    return list(rows)


def _normalize_group_monitor_keywords(item: BrandKeywordGroupSaveRequest) -> list[str]:
    keywords = _dedupe([str(value or "").strip() for value in (item.monitor_keywords or []) if str(value or "").strip()])
    legacy = str(item.monitor_keyword or "").strip()
    if legacy and legacy not in keywords:
        keywords.insert(0, legacy)
    return keywords


def merge_platform_selections_for_grants(
    existing: list[Any] | None,
    incoming: list[Any] | None,
    *,
    allowed_codes: set[str] | None,
) -> list[dict[str, Any]]:
    """按职位可配平台合并。allowed_codes=None 表示无权改平台，原样保留。"""
    existing_n = normalize_platform_selections(existing or [])
    incoming_n = normalize_platform_selections(incoming or [])
    if allowed_codes is None:
        return existing_n
    preserved = [item for item in existing_n if item["code"] not in allowed_codes]
    updated = [item for item in incoming_n if item["code"] in allowed_codes]
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in [*updated, *preserved]:
        code = item["code"]
        if code in seen:
            continue
        seen.add(code)
        result.append(item)
    return result


def save_keyword_groups(
    db: Session,
    asset: BrandAsset,
    payload: BrandAssetSaveRequest,
    *,
    allow_platform_edit: bool = True,
    allowed_platform_codes: set[str] | None = None,
) -> None:
    """用前端提交的词组覆盖当前企业词组。"""
    existing = {item.id: item for item in list_keyword_groups(db, asset.tenant_id)}
    seen_ids: set[int] = set()
    source_groups = payload.keyword_groups
    if not source_groups:
        # 2026-07-30 - 空词组不再用企业全称/品牌名自动造监测词
        source_groups = []
    allow_codes = allowed_platform_codes if allow_platform_edit else None
    for index, item in enumerate(source_groups):
        keywords = _normalize_group_monitor_keywords(item)
        if not keywords:
            continue
        primary = keywords[0]
        group_name = str(item.name or "").strip() or default_keyword_group_name(index)
        group = existing.get(item.id) if item.id else None
        creating = group is None
        if group is None:
            # 2026-07-30 - 平台范围多选 - 新建词组只允许授权端；无授权则空（保留已有配置语义）
            seed_platforms = merge_platform_selections_for_grants(
                [],
                item.platforms or [],
                allowed_codes=allow_codes if allow_platform_edit else set(),
            )
            if not allow_platform_edit:
                seed_platforms = normalize_platform_selections(asset.monitored_platforms_json or [])
            group = BrandKeywordGroup(
                tenant_id=asset.tenant_id,
                brand_asset_id=asset.id,
                name=group_name,
                monitor_keyword=primary,
                monitor_keywords_json=list(keywords),
                exposure_terms_json=_dedupe(item.exposure_terms or keywords),
                platforms_json=seed_platforms,
            )
            db.add(group)
        group.brand_asset_id = asset.id
        group.name = group_name
        group.monitor_keyword = primary
        group.monitor_keywords_json = list(keywords)
        flag_modified(group, "monitor_keywords_json")
        group.exposure_terms_json = _dedupe(item.exposure_terms or keywords)
        flag_modified(group, "exposure_terms_json")
        if allow_platform_edit and not creating:
            group.platforms_json = merge_platform_selections_for_grants(
                group.platforms_json,
                item.platforms or [],
                allowed_codes=allow_codes,
            )
            flag_modified(group, "platforms_json")
        elif allow_platform_edit and creating:
            # 已在 seed 写入
            pass
        group.sort_order = item.sort_order if item.sort_order is not None else index
        group.status = item.status
        group.deleted = False
        if group.id:
            seen_ids.add(group.id)
    for group_id, group in existing.items():
        if group_id not in seen_ids:
            group.deleted = True

    union_platforms: list[str] = []
    for item in db.scalars(
        select(BrandKeywordGroup).where(
            BrandKeywordGroup.tenant_id == asset.tenant_id,
            BrandKeywordGroup.deleted.is_(False),
            BrandKeywordGroup.status.is_(True),
        )
    ):
        union_platforms.extend(keyword_group_platforms(item))
    if union_platforms:
        asset.monitored_platforms_json = sort_platform_codes(_dedupe(union_platforms))
    elif allow_platform_edit and payload.monitored_platforms:
        asset.monitored_platforms_json = sort_platform_codes(_dedupe(payload.monitored_platforms))


def default_brand_word_group_name(index: int) -> str:
    return f"品牌词组 {index + 1}"


def list_brand_word_groups(db: Session, tenant_id: int) -> list[BrandWordGroup]:
    """读取企业品牌词组，按排序稳定返回。"""
    return list(
        db.scalars(
            select(BrandWordGroup)
            .where(BrandWordGroup.tenant_id == tenant_id, BrandWordGroup.deleted.is_(False))
            .order_by(BrandWordGroup.sort_order.asc(), BrandWordGroup.id.asc())
        )
    )


def brand_word_group_to_dict(group: BrandWordGroup) -> dict[str, Any]:
    """序列化品牌词组（无露出词字段）。"""
    monitor_keywords = keyword_group_monitor_keywords(
        {
            "monitor_keyword": group.monitor_keyword,
            "monitor_keywords": group.monitor_keywords_json or [],
        }
    )
    primary = monitor_keywords[0] if monitor_keywords else str(group.monitor_keyword or "").strip()
    run_mode = str(group.run_mode or "once").strip().lower()
    if run_mode not in {"once", "weekly"}:
        run_mode = "once"
    payload = {
        "id": group.id,
        "tenant_id": group.tenant_id,
        "name": str(group.name or "").strip() or default_brand_word_group_name(group.sort_order or 0),
        "monitor_keyword": primary,
        "monitor_keywords": monitor_keywords,
        "platforms": normalize_platform_selections(group.platforms_json or []),
        "run_mode": run_mode,
        "sort_order": group.sort_order,
        "status": group.status,
    }
    payload["display_name"] = keyword_group_display_label(payload)
    return payload


def _normalize_brand_word_monitor_keywords(item: BrandWordGroupSaveRequest) -> list[str]:
    keywords = _dedupe([str(value or "").strip() for value in (item.monitor_keywords or []) if str(value or "").strip()])
    legacy = str(item.monitor_keyword or "").strip()
    if legacy and legacy not in keywords:
        keywords.insert(0, legacy)
    return keywords


def save_brand_word_groups(
    db: Session,
    payload: BrandWordGroupsSaveRequest,
    current: CurrentSession,
) -> tuple[BrandAsset, list[BrandWordGroup]]:
    """覆盖保存品牌词组；不触碰监测词组。

    返回资产与保存后全部启用词组（once/weekly 均供保存后立即提交一轮；
    weekly 仍由周一 Beat 按周调度）。
    """
    from app.services.menu_permission_service import identity_allowed_monitor_platforms

    tenant_id = resolve_tenant_id(current, payload.tenant_id)
    _guard_tenant_write(db, current, tenant_id)
    asset = get_brand_asset(db, tenant_id)
    if asset is None:
        raise ValueError("请先保存企业资料或监测词配置，再配置品牌词")

    # 2026-07-30 - 平台编辑权=职位白名单；有权则仅改授权端
    allowed_set = set(identity_allowed_monitor_platforms(db, current.identity))
    can_models = bool(allowed_set)
    allowed_codes: set[str] | None = allowed_set if can_models else None

    existing = {item.id: item for item in list_brand_word_groups(db, tenant_id)}
    seen_ids: set[int] = set()

    for index, item in enumerate(payload.groups or []):
        keywords = _normalize_brand_word_monitor_keywords(item)
        if not keywords:
            continue
        platforms = normalize_platform_selections(item.platforms or [])
        primary = keywords[0]
        group_name = str(item.name or "").strip() or default_brand_word_group_name(index)
        run_mode = str(item.run_mode or "once").strip().lower()
        if run_mode not in {"once", "weekly"}:
            raise ValueError("运行时间仅支持「仅本次」或「周」")
        group = existing.get(item.id) if item.id else None
        creating = group is None
        if group is None:
            seed_platforms = merge_platform_selections_for_grants(
                [],
                platforms,
                allowed_codes=allowed_codes if can_models else set(),
            )
            if not can_models:
                seed_platforms = normalize_platform_selections(asset.monitored_platforms_json or [])
            if item.status and not seed_platforms:
                raise ValueError("每个启用的品牌词组至少选择一个监测平台")
            group = BrandWordGroup(
                tenant_id=asset.tenant_id,
                brand_asset_id=asset.id,
                name=group_name,
                monitor_keyword=primary,
                monitor_keywords_json=list(keywords),
                platforms_json=seed_platforms,
                run_mode=run_mode,
            )
            db.add(group)
        group.brand_asset_id = asset.id
        group.name = group_name
        group.monitor_keyword = primary
        group.monitor_keywords_json = list(keywords)
        flag_modified(group, "monitor_keywords_json")
        if can_models and not creating:
            group.platforms_json = merge_platform_selections_for_grants(
                group.platforms_json,
                platforms,
                allowed_codes=allowed_codes,
            )
            flag_modified(group, "platforms_json")
        if item.status and not keyword_group_platforms(group, asset):
            raise ValueError("每个启用的品牌词组至少选择一个监测平台")
        group.run_mode = run_mode
        group.sort_order = item.sort_order if item.sort_order is not None else index
        group.status = item.status
        group.deleted = False
        if group.id:
            seen_ids.add(group.id)

    for group_id, group in existing.items():
        if group_id not in seen_ids:
            group.deleted = True

    db.commit()
    db.refresh(asset)
    # 保存后立即提交：once / weekly 一视同仁（提交走 bwonce-*，不占用周一 weekly key）
    submit_groups = [
        item
        for item in list_brand_word_groups(db, tenant_id)
        if item.status
        and keyword_group_monitor_keywords(
            {
                "monitor_keyword": item.monitor_keyword,
                "monitor_keywords": item.monitor_keywords_json or [],
            }
        )
    ]
    from app.services.monitor_service import invalidate_monitor_summary_cache

    invalidate_monitor_summary_cache(tenant_id, bust_overview=True)
    return asset, submit_groups


def active_brand_word_groups(
    db: Session,
    tenant_id: int,
    *,
    run_mode: str | None = None,
) -> list[dict[str, Any]]:
    """启用中的品牌词组；可按 run_mode 过滤。"""
    rows = []
    for item in list_brand_word_groups(db, tenant_id):
        if not item.status:
            continue
        payload = brand_word_group_to_dict(item)
        if not payload.get("monitor_keywords"):
            continue
        if run_mode and payload.get("run_mode") != run_mode:
            continue
        rows.append(payload)
    return rows


def save_brand_asset(db: Session, payload: BrandAssetSaveRequest, current: CurrentSession) -> BrandAsset:
    """新增或更新企业品牌资产。"""
    from app.services.menu_permission_service import (
        has_identity_menu_permission,
        identity_allowed_monitor_platforms,
    )

    tenant_id = resolve_tenant_id(current, payload.tenant_id)
    _guard_tenant_write(db, current, tenant_id)
    identity_id = current.identity.id
    # 2026-07-30 - 地区看菜单编辑权；平台看职位白名单
    can_profile = has_identity_menu_permission(db, identity_id, "platform.audit.profile", "can_update")
    can_regions = has_identity_menu_permission(db, identity_id, "platform.audit.regions", "can_update")
    can_keywords = has_identity_menu_permission(db, identity_id, "platform.audit.keywords", "can_update")
    allowed_platform_codes: set[str] | None = set(identity_allowed_monitor_platforms(db, current.identity))
    can_models = bool(allowed_platform_codes)
    can_schedule = has_identity_menu_permission(db, identity_id, "platform.audit.schedule", "can_update")
    if not can_models:
        allowed_platform_codes = None

    asset = get_brand_asset(db, tenant_id)
    if asset is None:
        if not can_profile:
            raise PermissionError("无企业资料编辑权限，无法新建企业配置")
        asset = BrandAsset(
            tenant_id=tenant_id,
            company_full_name=payload.company_full_name,
            brand_name=payload.brand_name,
            brand_short_name=payload.brand_short_name,
            monitor_keywords_json=[],
            aliases_json=[],
            product_keywords_json=[],
            monitored_platforms_json=[],
            schedule_times_json=[],
            schedule_weekdays_json=[],
            schedule_month_days_json=[],
        )
        db.add(asset)
    if can_profile:
        asset.company_full_name = payload.company_full_name
        asset.brand_name = payload.brand_name
        asset.brand_short_name = payload.brand_short_name
        asset.official_url = payload.official_url
        asset.description = payload.description
    if can_keywords or not asset.monitor_keywords_json:
        asset.monitor_keywords_json = _dedupe([*payload.monitor_keywords, *payload.product_keywords])
        asset.aliases_json = _dedupe([payload.brand_short_name, *payload.aliases])
        asset.product_keywords_json = []
    if can_models and not payload.keyword_groups:
        asset.monitored_platforms_json = sort_platform_codes(_dedupe(payload.monitored_platforms))
    if can_regions:
        asset.region_codes_json = normalize_region_codes(payload.region_codes)
    elif getattr(asset, "region_codes_json", None) is None:
        asset.region_codes_json = []
    if can_schedule:
        asset.schedule_type = payload.schedule_type
        asset.schedule_times_json = _dedupe(payload.schedule_times)
        asset.schedule_frequency = payload.schedule_frequency
        asset.schedule_weekdays_json = _int_dedupe(payload.schedule_weekdays, 1, 7)
        asset.schedule_month_days_json = _int_dedupe(payload.schedule_month_days, 1, 31)
    asset.status = True
    asset.deleted = False
    db.flush()
    if can_keywords:
        save_keyword_groups(
            db,
            asset,
            payload,
            allow_platform_edit=can_models,
            allowed_platform_codes=allowed_platform_codes,
        )
    db.commit()
    db.refresh(asset)
    # 露出词/平台变更后清摘要与信源缓存，避免脏读至多 6h
    from app.services.monitor_service import invalidate_monitor_summary_cache

    invalidate_monitor_summary_cache(tenant_id, bust_overview=True)
    return asset


def list_competitors(db: Session, tenant_id: int) -> list[BrandCompetitor]:
    """读取企业竞品库。"""
    return list(
        db.scalars(
            select(BrandCompetitor)
            .where(BrandCompetitor.tenant_id == tenant_id, BrandCompetitor.deleted.is_(False))
            .order_by(BrandCompetitor.id.desc())
        )
    )


def save_competitor(db: Session, payload: CompetitorSaveRequest, current: CurrentSession, competitor_id: int | None = None) -> BrandCompetitor:
    """新增或更新竞品。"""
    tenant_id = resolve_tenant_id(current, payload.tenant_id)
    _guard_tenant_write(db, current, tenant_id)
    competitor = None
    if competitor_id is not None:
        competitor = db.scalar(
            select(BrandCompetitor).where(
                BrandCompetitor.id == competitor_id,
                BrandCompetitor.tenant_id == tenant_id,
                BrandCompetitor.deleted.is_(False),
            )
        )
        if competitor is None:
            raise ValueError("竞品不存在")
    if competitor is None:
        competitor = BrandCompetitor(tenant_id=tenant_id, name=payload.name, aliases_json=[])
        db.add(competitor)
    competitor.name = payload.name
    competitor.short_name = payload.short_name
    competitor.aliases_json = _dedupe([payload.short_name, *payload.aliases])
    competitor.website_url = payload.website_url
    competitor.category = payload.category
    competitor.status = True
    competitor.deleted = False
    db.commit()
    db.refresh(competitor)
    from app.services.monitor_service import invalidate_monitor_summary_cache

    invalidate_monitor_summary_cache(tenant_id, bust_overview=True)
    return competitor


def delete_competitor(db: Session, current: CurrentSession, competitor_id: int, tenant_id: int | None = None) -> None:
    """逻辑删除竞品。"""
    resolved_tenant_id = resolve_tenant_id(current, tenant_id)
    _guard_tenant_write(db, current, resolved_tenant_id)
    competitor = db.scalar(
        select(BrandCompetitor).where(
            BrandCompetitor.id == competitor_id,
            BrandCompetitor.tenant_id == resolved_tenant_id,
            BrandCompetitor.deleted.is_(False),
        )
    )
    if competitor is None:
        raise ValueError("竞品不存在")
    competitor.deleted = True
    db.commit()
    from app.services.monitor_service import invalidate_monitor_summary_cache

    invalidate_monitor_summary_cache(resolved_tenant_id, bust_overview=True)


def asset_to_dict(
    asset: BrandAsset | None,
    keyword_groups: list[BrandKeywordGroup | dict[str, Any]] | None = None,
    brand_word_groups: list[BrandWordGroup | dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """序列化品牌资产。"""
    if asset is None:
        return None
    normalized_groups: list[dict[str, Any]] = []
    for index, item in enumerate(keyword_groups or []):
        normalized_groups.append(ensure_keyword_group_payload(item, index))
    normalized_brand_words: list[dict[str, Any]] = []
    for item in brand_word_groups or []:
        if isinstance(item, BrandWordGroup):
            normalized_brand_words.append(brand_word_group_to_dict(item))
        else:
            run_mode = str(item.get("run_mode") or "once").strip().lower()
            if run_mode not in {"once", "weekly"}:
                run_mode = "once"
            row = ensure_keyword_group_payload(item)
            row["run_mode"] = run_mode
            normalized_brand_words.append(row)
    return {
        "id": asset.id,
        "tenant_id": asset.tenant_id,
        "company_full_name": asset.company_full_name,
        "brand_name": asset.brand_name,
        "brand_short_name": asset.brand_short_name,
        "monitor_keywords": asset.monitor_keywords_json,
        "aliases": asset.aliases_json,
        "product_keywords": asset.product_keywords_json,
        "monitored_platforms": sort_platform_codes(asset.monitored_platforms_json),
        "keyword_groups": normalized_groups,
        "brand_word_groups": normalized_brand_words,
        "region_codes": normalize_region_codes(asset.region_codes_json or []),
        "official_url": asset.official_url,
        "description": asset.description,
        "schedule_type": asset.schedule_type,
        "schedule_times": asset.schedule_times_json,
        "schedule_frequency": asset.schedule_frequency,
        "schedule_weekdays": asset.schedule_weekdays_json,
        "schedule_month_days": asset.schedule_month_days_json,
    }


def competitor_to_dict(competitor: BrandCompetitor) -> dict[str, Any]:
    """序列化竞品。"""
    return {
        "id": competitor.id,
        "tenant_id": competitor.tenant_id,
        "name": competitor.name,
        "short_name": competitor.short_name,
        "aliases": competitor.aliases_json,
        "website_url": competitor.website_url,
        "category": competitor.category,
    }


def active_keyword_groups(db: Session, tenant_id: int) -> list[dict[str, Any]]:
    """返回启用词组；没有新表数据时回退到旧字段。"""
    asset = get_brand_asset(db, tenant_id)
    if asset is None:
        return []
    groups = [
        keyword_group_to_dict(item)
        for item in list_keyword_groups(db, tenant_id)
        if item.status and keyword_group_monitor_keywords(item)
    ]
    return groups or _fallback_keyword_groups(asset)


def collect_exposure_term_options(
    keyword_groups: list[dict[str, Any]] | None = None,
    *,
    asset: BrandAsset | None = None,
) -> list[str]:
    """Collect deduplicated exposure terms for filter dropdowns."""
    seen: set[str] = set()
    terms: list[str] = []
    for group in keyword_groups or []:
        if not group.get("status", True):
            continue
        for term in group.get("exposure_terms") or []:
            text = str(term or "").strip()
            if text and text not in seen:
                seen.add(text)
                terms.append(text)
    if asset is not None:
        for raw in (
            asset.brand_short_name,
            asset.brand_name,
            *(asset.aliases_json or []),
        ):
            text = str(raw or "").strip()
            if text and text not in seen:
                seen.add(text)
                terms.append(text)
    return sorted(terms, key=lambda item: item.casefold())


def _is_industry_monitor_keyword(text: str, asset: BrandAsset) -> bool:
    """判断词组监测词是否为行业/场景词，而非品牌名。"""
    keyword = str(text or "").strip()
    if not keyword:
        return True
    anchors = [
        str(asset.brand_name or "").strip(),
        str(asset.brand_short_name or "").strip(),
        str(asset.company_full_name or "").strip(),
    ]
    anchors = [item for item in anchors if item]
    if any(keyword == anchor or keyword in anchor or anchor in keyword for anchor in anchors):
        return False
    industry_tokens = ("优化", "监测", "推广", "诊断", "SEO", "AEO", "DSO")
    if any(token in keyword for token in industry_tokens) and not keyword.endswith("公司"):
        return True
    scene_tokens = (
        "广告", "传媒", "媒体", "户外", "电梯", "机场", "地铁", "高铁", "公交",
        "LED", "大屏", "站牌", "灯箱", "分众", "梯媒",
    )
    return any(token.casefold() in keyword.casefold() for token in scene_tokens)


def ranking_task_is_industry_scoped(
    monitor_keywords: str | None,
    prompt: str | None,
    asset: BrandAsset | None,
) -> bool:
    """任务是否场景/行业排名监测（prompt 或 monitor_keywords 任一为场景词即可）。"""
    if asset is None:
        return False
    for text in (str(monitor_keywords or "").strip(), str(prompt or "").strip()):
        if text and _is_industry_monitor_keyword(text, asset):
            return True
    return False


def brand_exposure_terms(asset: BrandAsset, groups: list[dict[str, Any]]) -> list[str]:
    """收集露出词。行业场景词组的监测词不当地做露出词，但其 exposure_terms 仍要保留。"""
    terms: list[str] = []
    for group in groups:
        if not group.get("status", True):
            continue
        for term in group.get("exposure_terms") or []:
            text = str(term or "").strip()
            if text and text not in terms:
                terms.append(text)
    # 纯行业词组客户若误配空露出词，回退品牌名/简称，避免信源统计被掏空。
    if not terms and asset is not None:
        for raw in (
            asset.brand_short_name,
            asset.brand_name,
            asset.company_full_name,
            *(asset.aliases_json or []),
        ):
            text = str(raw or "").strip()
            if text and text not in terms:
                terms.append(text)
    return terms


def molizhishu_monitor_terms(
    db: Session,
    tenant_id: int,
    *,
    keyword_group: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    """生成提交模力的 monitorKeywords / aliases。

    监测词组：别名以露出词为主；品牌词组无露出词，别名用组内品牌词 + 企业资产别名。
    """
    asset = get_brand_asset(db, tenant_id)
    if asset is None:
        raise ValueError("当前企业未配置品牌资产，请先维护品牌主词和简称")
    groups = active_keyword_groups(db, tenant_id)
    monitor_keyword = (
        str(asset.brand_short_name or "").strip()
        or str(asset.brand_name or "").strip()
        or str(asset.company_full_name or "").strip()
    )
    exposure = brand_exposure_terms(asset, groups)
    if keyword_group and keyword_group.get("status", True):
        group_keywords = keyword_group_monitor_keywords(keyword_group)
        group_exposure = [
            str(term or "").strip()
            for term in (keyword_group.get("exposure_terms") or [])
            if str(term or "").strip()
        ]
        # 品牌词组无露出词：组内品牌词本身作为匹配别名
        match_terms = group_exposure or [
            kw for kw in group_keywords if kw and not _is_industry_monitor_keyword(kw, asset)
        ]
        for group_keyword in group_keywords:
            if group_keyword and not _is_industry_monitor_keyword(group_keyword, asset):
                if not monitor_keyword:
                    monitor_keyword = group_keyword
        for text in match_terms:
            if text and text not in exposure:
                exposure.append(text)
    aliases = _dedupe([
        str(asset.brand_name or "").strip(),
        str(asset.company_full_name or "").strip(),
        *exposure,
        *(asset.aliases_json or []),
    ])
    aliases = [item for item in aliases if item and item != monitor_keyword]
    if not monitor_keyword and aliases:
        monitor_keyword = aliases[0]
    return monitor_keyword, aliases


def molizhishu_brand_payload(db: Session, tenant_id: int) -> tuple[str, list[str], list[dict[str, Any]]]:
    """把企业品牌资产转换为模力指数 monitorKeywords、aliases、competitors。"""
    monitor_keyword, aliases = molizhishu_monitor_terms(db, tenant_id)
    competitors = [
        {"name": item.name, "aliases": item.aliases_json}
        for item in list_competitors(db, tenant_id)
        if item.status and item.name
    ]
    return monitor_keyword, aliases, competitors


def _dedupe(values: list[str | None]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = (value or "").strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            result.append(text)
    return result


def _int_dedupe(values: list[int], min_value: int, max_value: int) -> list[int]:
    result: list[int] = []
    for value in values:
        if min_value <= value <= max_value and value not in result:
            result.append(value)
    return result
