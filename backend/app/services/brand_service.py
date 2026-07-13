from typing import Any
import re

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.api.dependencies import CurrentSession
from app.core.platform_order import sort_platform_codes
from app.core.region_catalog import normalize_region_codes
from app.models.brand import BrandAsset, BrandCompetitor, BrandKeywordGroup
from app.models.tenant import Tenant
from app.schemas.brand import BrandAssetSaveRequest, BrandKeywordGroupSaveRequest, CompetitorSaveRequest
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


def keyword_group_name(group: BrandKeywordGroup | dict[str, Any] | None, index: int = 0) -> str:
    if group is None:
        return default_keyword_group_name(index)
    if isinstance(group, BrandKeywordGroup):
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


def keyword_group_monitor_keywords(group: BrandKeywordGroup | dict[str, Any] | None) -> list[str]:
    """Return deduplicated monitor keywords for a keyword group."""
    if group is None:
        return []
    if isinstance(group, BrandKeywordGroup):
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


def keyword_group_platforms(
    group: BrandKeywordGroup | dict[str, Any] | None,
    asset: BrandAsset | None = None,
) -> list[str]:
    """词组绑定的监测平台；无配置时回退企业级平台范围（兼容旧数据）。"""
    if group is None:
        return sort_platform_codes(list(asset.monitored_platforms_json or [])) if asset else []
    if isinstance(group, BrandKeywordGroup):
        raw = list(group.platforms_json or [])
    else:
        raw = list(group.get("platforms") or [])
    codes = sort_platform_codes(_dedupe([str(code or "").strip() for code in raw if str(code or "").strip()]))
    if codes:
        return codes
    return sort_platform_codes(list(asset.monitored_platforms_json or [])) if asset else []


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
        "platforms": keyword_group_platforms(group),
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
            "platforms": keyword_group_platforms(group, asset=None),
            "sort_order": group.get("sort_order", index),
            "status": group.get("status", True),
        }
    payload["display_name"] = keyword_group_display_label(
        group if isinstance(group, BrandKeywordGroup) else payload
    )
    return payload


def editable_keyword_groups(db: Session, tenant_id: int) -> list[BrandKeywordGroup | dict[str, Any]]:
    """企业管理页读取全部词组（含停用），无词组表数据时回退旧字段。"""
    asset = get_brand_asset(db, tenant_id)
    if asset is None:
        return []
    rows = list_keyword_groups(db, tenant_id)
    if rows:
        return list(rows)
    return _fallback_keyword_groups(asset)


def _normalize_group_monitor_keywords(item: BrandKeywordGroupSaveRequest) -> list[str]:
    keywords = _dedupe([str(value or "").strip() for value in (item.monitor_keywords or []) if str(value or "").strip()])
    legacy = str(item.monitor_keyword or "").strip()
    if legacy and legacy not in keywords:
        keywords.insert(0, legacy)
    return keywords


def save_keyword_groups(db: Session, asset: BrandAsset, payload: BrandAssetSaveRequest) -> None:
    """用前端提交的词组覆盖当前企业词组。"""
    existing = {item.id: item for item in list_keyword_groups(db, asset.tenant_id)}
    seen_ids: set[int] = set()
    source_groups = payload.keyword_groups
    if not source_groups:
        source_groups = [
            type("_Group", (), {"id": None, "monitor_keyword": keyword, "monitor_keywords": [keyword], "exposure_terms": [keyword], "sort_order": index, "status": True})()
            for index, keyword in enumerate(_dedupe([payload.company_full_name, payload.brand_name, *payload.monitor_keywords]))
        ]
    for index, item in enumerate(source_groups):
        keywords = _normalize_group_monitor_keywords(item)
        if not keywords:
            continue
        primary = keywords[0]
        group_name = str(item.name or "").strip() or default_keyword_group_name(index)
        group = existing.get(item.id) if item.id else None
        if group is None:
            group = BrandKeywordGroup(
                tenant_id=asset.tenant_id,
                brand_asset_id=asset.id,
                name=group_name,
                monitor_keyword=primary,
                monitor_keywords_json=list(keywords),
                exposure_terms_json=_dedupe(item.exposure_terms or keywords),
                platforms_json=sort_platform_codes(_dedupe(item.platforms or [])),
            )
            db.add(group)
        group.brand_asset_id = asset.id
        group.name = group_name
        group.monitor_keyword = primary
        group.monitor_keywords_json = list(keywords)
        flag_modified(group, "monitor_keywords_json")
        group.exposure_terms_json = _dedupe(item.exposure_terms or keywords)
        flag_modified(group, "exposure_terms_json")
        platforms = sort_platform_codes(_dedupe(item.platforms or []))
        group.platforms_json = platforms
        flag_modified(group, "platforms_json")
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
    elif payload.monitored_platforms:
        asset.monitored_platforms_json = sort_platform_codes(_dedupe(payload.monitored_platforms))


def save_brand_asset(db: Session, payload: BrandAssetSaveRequest, current: CurrentSession) -> BrandAsset:
    """新增或更新企业品牌资产。"""
    tenant_id = resolve_tenant_id(current, payload.tenant_id)
    _guard_tenant_write(db, current, tenant_id)
    asset = get_brand_asset(db, tenant_id)
    if asset is None:
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
    asset.company_full_name = payload.company_full_name
    asset.brand_name = payload.brand_name
    asset.brand_short_name = payload.brand_short_name
    asset.monitor_keywords_json = _dedupe([payload.brand_name, payload.brand_short_name, *payload.monitor_keywords, *payload.product_keywords])
    asset.aliases_json = _dedupe([payload.brand_short_name, *payload.aliases])
    asset.product_keywords_json = []
    if not payload.keyword_groups:
        asset.monitored_platforms_json = sort_platform_codes(_dedupe(payload.monitored_platforms))
    asset.region_codes_json = normalize_region_codes(payload.region_codes)
    asset.official_url = payload.official_url
    asset.description = payload.description
    asset.schedule_type = payload.schedule_type
    asset.schedule_times_json = _dedupe(payload.schedule_times)
    asset.schedule_frequency = payload.schedule_frequency
    asset.schedule_weekdays_json = _int_dedupe(payload.schedule_weekdays, 1, 7)
    asset.schedule_month_days_json = _int_dedupe(payload.schedule_month_days, 1, 31)
    asset.status = True
    asset.deleted = False
    db.flush()
    save_keyword_groups(db, asset, payload)
    db.commit()
    db.refresh(asset)
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


def asset_to_dict(
    asset: BrandAsset | None,
    keyword_groups: list[BrandKeywordGroup | dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """序列化品牌资产。"""
    if asset is None:
        return None
    normalized_groups: list[dict[str, Any]] = []
    for index, item in enumerate(keyword_groups or []):
        normalized_groups.append(ensure_keyword_group_payload(item, index))
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


def brand_exposure_terms(asset: BrandAsset, groups: list[dict[str, Any]]) -> list[str]:
    """收集品牌词组的露出词，排除行业词组里的行业词。"""
    terms: list[str] = []
    for group in groups:
        if not group.get("status", True):
            continue
        keywords = keyword_group_monitor_keywords(group)
        if keywords and all(_is_industry_monitor_keyword(keyword, asset) for keyword in keywords):
            continue
        for term in group.get("exposure_terms") or []:
            text = str(term or "").strip()
            if text and text not in terms:
                terms.append(text)
    return terms


def molizhishu_monitor_terms(
    db: Session,
    tenant_id: int,
    *,
    keyword_group: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    """生成提交模力指数的 monitorKeywords 与 aliases：主词用简称/品牌名，别名用露出词。"""
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
        for group_keyword in keyword_group_monitor_keywords(keyword_group):
            if group_keyword and not _is_industry_monitor_keyword(group_keyword, asset):
                if not monitor_keyword:
                    monitor_keyword = group_keyword
        for term in keyword_group.get("exposure_terms") or []:
            text = str(term or "").strip()
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
