"""算力自助核心服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.brand import BrandAsset
from app.models.credit import (
    CREDIT_PRICE_DEFAULT_PLATFORM_KEY,
    CREDIT_PRICE_GLOBAL_TENANT_KEY,
    CreditSubmitBlock,
    CreditTermsVersion,
    TenantCreditCellFinalize,
    TenantCreditLedger,
)
from app.models.tenant import DEFAULT_CREDIT_POLICY, Tenant
from app.services.molizhishu_balance_service import fetch_molizhishu_balance
from app.services.system_config_service import get_runtime_config

DEEP_THINK_ADDON_CODE = "deep_think_addon"
BILLING_MODE_HOSTED = "hosted"
BILLING_MODE_CREDIT = "credit"
PLATFORM_ESTIMATE_CACHE_KEY = "ops:credit:next_window_estimate"
CUSTOMER_VISIBLE_LEDGER_TYPES = ("recharge", "adjust", "settle")


def normalize_price_platform_key(platform_code: str | None) -> str:
    code = str(platform_code or "").strip()
    return code if code else CREDIT_PRICE_DEFAULT_PLATFORM_KEY


def normalize_price_tenant_key(scope: str, tenant_id: int | None) -> int:
    if scope == "global":
        return CREDIT_PRICE_GLOBAL_TENANT_KEY
    return int(tenant_id or 0)


def display_price_platform_code(platform_key: str | None) -> str | None:
    key = str(platform_key or "").strip()
    return None if not key or key == CREDIT_PRICE_DEFAULT_PLATFORM_KEY else key


@dataclass
class SubmitGateResult:
    allowed: bool
    reason: str | None = None
    message: str | None = None
    reserve_ref: str | None = None
    reserved_credits: Decimal | None = None


def is_credit_tenant(tenant: Tenant | None) -> bool:
    return bool(tenant and tenant.billing_mode == BILLING_MODE_CREDIT)


def dedupe_credit_tenant_list_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # 2026-08-28 - 算力企业列表同名重复 - 写测易重复建户，展示层只留 tenant_id 最大的一条
    by_name: dict[str, dict[str, Any]] = {}
    for row in items:
        tenant_id = int(row.get("tenant_id") or 0)
        name_key = str(row.get("name") or "").strip().casefold() or f"#{tenant_id}"
        prev = by_name.get(name_key)
        if prev is None or tenant_id > int(prev.get("tenant_id") or 0):
            by_name[name_key] = row
    return sorted(by_name.values(), key=lambda row: str(row.get("name") or ""))


# 2026-09-08 - 方案 A 正式口径：配额/白名单退役，读写都剥掉，防暗开关
RETIRED_CREDIT_POLICY_KEYS = frozenset(
    {
        "keyword_limit",
        "schedule_slots_limit",
        "region_limit",
        "region_editable",
        "daily_credit_cap",
    }
)


def merge_credit_policy(raw: dict | None) -> dict[str, Any]:
    merged = dict(DEFAULT_CREDIT_POLICY)
    if raw:
        merged.update(raw)
    for key in RETIRED_CREDIT_POLICY_KEYS:
        merged.pop(key, None)
    return merged


def assert_no_retired_quota_writes(
    credit_policy: dict | None = None,
    platform_whitelist: list | None = None,
) -> None:
    """方案 A：禁止再写入已退役配额/白名单（非空白名单直接 400）。"""
    if isinstance(credit_policy, dict):
        bad = sorted(k for k in credit_policy if k in RETIRED_CREDIT_POLICY_KEYS)
        if bad:
            raise ValueError(
                "已废弃配额字段不可写入："
                + "、".join(bad)
                + "。算力自助仅靠客户算力余额与平台真金双闸。"
            )
    if platform_whitelist is not None and len(list(platform_whitelist)) > 0:
        raise ValueError("平台白名单已废弃，不可再写入。客户可自选监测平台，由算力余额约束。")


def credits_from_yuan(tenant: Tenant, yuan: Decimal) -> Decimal:
    # 2026-08-28 - 充值按企业汇率换算 - 运营填人民币，服务端按 credits_per_yuan 入账
    policy = merge_credit_policy(tenant.credit_policy_json)
    rate = Decimal(str(policy.get("credits_per_yuan") or 4.2))
    if rate <= 0:
        raise ValueError("企业汇率无效")
    return (Decimal(str(yuan)) * rate).quantize(Decimal("0.1"))


def tenant_available_credits(tenant: Tenant) -> Decimal:
    balance = Decimal(str(tenant.credit_balance or 0))
    reserved = Decimal(str(tenant.credit_reserved or 0))
    return balance - reserved


def _ledger_balance_snapshot(tenant: Tenant, entry_type: str) -> Decimal:
    # 2026-08-28 - 客户可见流水余额用账面 credit_balance；预扣/释放用可用额供运营排查
    if entry_type in CUSTOMER_VISIBLE_LEDGER_TYPES:
        return Decimal(str(tenant.credit_balance or 0))
    return tenant_available_credits(tenant)


def _recompute_customer_ledger_balances(db: Session, tenant_id: int) -> dict[int, Decimal]:
    """隐藏预扣/释放后，按当前账面余额倒推客户可见流水的连贯余额。"""
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        return {}
    visible_rows = list(
        db.scalars(
            select(TenantCreditLedger)
            .where(
                TenantCreditLedger.tenant_id == tenant_id,
                TenantCreditLedger.entry_type.in_(CUSTOMER_VISIBLE_LEDGER_TYPES),
            )
            .order_by(TenantCreditLedger.id.desc())
        )
    )
    balances: dict[int, Decimal] = {}
    running = Decimal(str(tenant.credit_balance or 0))
    for row in visible_rows:
        balances[row.id] = running
        running -= Decimal(str(row.amount or 0))
    return balances


def estimate_brand_words_immediate_credits(
    db: Session,
    tenant: Tenant,
    asset: BrandAsset,
    groups: list[Any],
) -> dict[str, Any]:
    """勾选立即跑的品牌词组预估算力（按平台×地区×词数）。"""
    from app.services.brand_service import normalize_platform_selections

    region_count = max(1, len(asset.region_codes_json or []) or 1)
    total = Decimal("0")
    group_count = 0
    for item in groups or []:
        run_now = bool(getattr(item, "run_immediately", False) if hasattr(item, "run_immediately") else item.get("run_immediately"))
        status = bool(getattr(item, "status", True) if hasattr(item, "status") else item.get("status", True))
        if not run_now or not status:
            continue
        platforms = normalize_platform_selections(
            getattr(item, "platforms", None) or item.get("platforms") or []
        )
        if not platforms:
            continue
        keywords = getattr(item, "monitor_keywords", None) or item.get("monitor_keywords") or []
        if not keywords and getattr(item, "monitor_keyword", None):
            keywords = [item.monitor_keyword]
        if not keywords and item.get("monitor_keyword"):
            keywords = [item.get("monitor_keyword")]
        prompt_count = len([k for k in keywords if str(k or "").strip()])
        if prompt_count <= 0:
            continue
        codes = [str(p.get("code") if isinstance(p, dict) else getattr(p, "code", "")) for p in platforms]
        codes = [c for c in codes if c]
        total += estimate_group_credits(
            db,
            tenant,
            platform_codes=codes,
            region_count=region_count,
            prompt_count=prompt_count,
        )
        group_count += 1
    return {
        "credits": float(total),
        "group_count": group_count,
        "region_count": region_count,
    }


def tenant_today_credit_deduct(db: Session, tenant_id: int | None = None) -> Decimal:
    """今日已扣：当日 settle 流水绝对值之和；tenant_id 为空则全平台 credit 企业合计。"""
    today_start = datetime.combine(datetime.now().date(), datetime.min.time())
    stmt = select(func.coalesce(func.sum(-TenantCreditLedger.amount), 0)).where(
        TenantCreditLedger.entry_type == "settle",
        TenantCreditLedger.created_at >= today_start,
    )
    if tenant_id is not None:
        stmt = stmt.where(TenantCreditLedger.tenant_id == int(tenant_id))
    return Decimal(str(db.scalar(stmt) or 0))


def list_open_credit_reserves(db: Session, tenant_id: int, *, limit: int = 30) -> list[dict[str, Any]]:
    """运营手工 release：列出该 ref 仍有剩余预扣占用的批次。"""
    reserves = list(
        db.scalars(
            select(TenantCreditLedger)
            .where(
                TenantCreditLedger.tenant_id == tenant_id,
                TenantCreditLedger.entry_type == "reserve",
            )
            .order_by(TenantCreditLedger.created_at.desc())
            .limit(max(1, min(limit * 5, 200)))
        )
    )
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for row in reserves:
        ref_id = str(row.ref_id or "").strip()
        if not ref_id or ref_id in seen:
            continue
        seen.add(ref_id)
        remaining = ref_reserve_remaining(db, tenant_id, ref_id)
        if remaining <= 0 or batch_force_closed(db, tenant_id, ref_id):
            continue
        items.append(
            {
                "ref_id": ref_id,
                "amount": float(remaining),
                "window_key": row.window_key,
                "reason": row.reason,
                "created_at": row.created_at.isoformat(sep=" ", timespec="minutes"),
            }
        )
        if len(items) >= limit:
            break
    return items


def cell_prepaid_share(
    db: Session,
    tenant: Tenant,
    platform_code: str | None,
    *,
    reserve_detail: dict | None = None,
) -> Decimal:
    """本格预扣份额：优先用预扣当时记账；否则按 min(单价×1, 同格封顶)。

    2026-09-09 - 产品：自动重试免费，只收一格，预扣不再为重试锁 2×。
    """
    code = str(platform_code or "").strip()
    if isinstance(reserve_detail, dict):
        shares = reserve_detail.get("shares_by_platform")
        if isinstance(shares, dict) and code in shares:
            return Decimal(str(shares[code]))
        default_share = reserve_detail.get("default_cell_share")
        if default_share is not None:
            return Decimal(str(default_share))
    unit = resolve_credits_per_subtask(db, tenant_id=tenant.id, platform_code=code or None)
    # settle_cell_credit_cap 是绝对算力上限（默认 2），不是倍数
    cap = Decimal(str(merge_credit_policy(tenant.credit_policy_json).get("settle_cell_credit_cap", 2)))
    if unit <= 0:
        return Decimal("0")
    return min(unit, cap)


def build_reserve_batch_detail(
    db: Session,
    tenant: Tenant,
    *,
    platform_codes: list[str],
    prompt_count: int,
    region_count: int,
) -> dict[str, Any]:
    shares: dict[str, float] = {}
    for code in platform_codes:
        key = str(code or "").strip()
        if not key:
            continue
        shares[key] = float(cell_prepaid_share(db, tenant, key))
    cap = float(merge_credit_policy(tenant.credit_policy_json).get("settle_cell_credit_cap", 2))
    return {
        "shares_by_platform": shares,
        "default_cell_share": cap,
        "prompt_count": int(prompt_count),
        "region_count": int(max(1, region_count)),
        "settle_cell_credit_cap": cap,
        # 2026-09-07 - 预扣按「同格封顶份额」记账，结算时按平台份额动预扣，避免现价漂移
        "reserve_basis": "cap_per_cell",
    }


def estimate_schedule_reserve_credits(
    db: Session,
    tenant: Tenant,
    *,
    platform_codes: list[str],
    prompt_count: int,
    region_count: int = 1,
) -> Decimal:
    """提交闸预扣额：按格单价份额×词×区（重试免费，按 1× 锁）。"""
    if not is_credit_tenant(tenant) or not platform_codes or prompt_count <= 0:
        return Decimal("0")
    total = Decimal("0")
    for code in platform_codes:
        total += cell_prepaid_share(db, tenant, code)
    return total * Decimal(max(1, region_count)) * Decimal(max(1, prompt_count))


def ref_reserve_remaining(db: Session, tenant_id: int, ref_id: str) -> Decimal:
    """该批次预扣还剩多少未释放/未按份额消化。"""
    ref = str(ref_id or "").strip()
    if not ref:
        return Decimal("0")
    rows = list(
        db.scalars(
            select(TenantCreditLedger).where(
                TenantCreditLedger.tenant_id == tenant_id,
                TenantCreditLedger.ref_id == ref,
            )
        )
    )
    reserved = Decimal("0")
    released = Decimal("0")
    consumed = Decimal("0")
    for row in rows:
        amt = Decimal(str(row.amount or 0))
        detail = row.detail_json if isinstance(row.detail_json, dict) else {}
        if row.entry_type == "reserve":
            reserved += abs(amt)
        elif row.entry_type == "release":
            released += abs(amt)
        elif row.entry_type == "settle":
            share = detail.get("prepaid_share")
            if share is None:
                share = detail.get("cell_prepaid_share")
            if share is not None:
                consumed += Decimal(str(share))
            else:
                # 旧整批 settle：按实扣额视作消化预扣
                consumed += abs(amt)
    return max(Decimal("0"), reserved - released - consumed)


def batch_force_closed(db: Session, tenant_id: int, ref_id: str) -> bool:
    """仅运营手工强制放预扣算关批；正常清尾/TTL 的 batch_close 不得挡晚到补扣。"""
    rows = db.scalars(
        select(TenantCreditLedger).where(
            TenantCreditLedger.tenant_id == tenant_id,
            TenantCreditLedger.ref_id == ref_id,
            TenantCreditLedger.entry_type == "release",
        )
    )
    for row in rows:
        detail = row.detail_json if isinstance(row.detail_json, dict) else {}
        # 2026-09-07 - 正常清尾与强制放搅在一起会漏扣；只认 batch_force_closed
        if detail.get("batch_force_closed"):
            return True
    return False


def get_reserve_detail(db: Session, tenant_id: int, ref_id: str) -> dict[str, Any] | None:
    row = db.scalar(
        select(TenantCreditLedger)
        .where(
            TenantCreditLedger.tenant_id == tenant_id,
            TenantCreditLedger.ref_id == ref_id,
            TenantCreditLedger.entry_type == "reserve",
        )
        .order_by(TenantCreditLedger.id.desc())
        .limit(1)
    )
    if row is None:
        return None
    return row.detail_json if isinstance(row.detail_json, dict) else None


def has_open_credit_reserve(db: Session, tenant_id: int, ref_id: str) -> bool:
    """同 ref 仍有剩余预扣占用则视为开放（按格 settle 后不得当成已关而叠扣）。"""
    ref = str(ref_id or "").strip()
    if not ref:
        return False
    if batch_force_closed(db, tenant_id, ref):
        return False
    return ref_reserve_remaining(db, tenant_id, ref) > 0


def _config_int(key: str, default: int) -> int:
    try:
        return int(get_runtime_config(key))
    except (TypeError, ValueError, KeyError):
        return default


def _config_decimal(key: str, default: str) -> Decimal:
    try:
        return Decimal(str(get_runtime_config(key)))
    except (TypeError, ValueError, KeyError, Exception):
        return Decimal(default)


def platform_molizhishu_yuan_per_subtask() -> Decimal:
    # 2026-08-28 - 模力真金闸子任务成本 - 系统配置可调，默认对齐定价文档加权 0.19 元/条
    return _config_decimal("platform_molizhishu_yuan_per_subtask", "0.19")


def estimate_schedule_submit_credits(
    db: Session,
    tenant: Tenant,
    *,
    platform_codes: list[str],
    prompt_count: int,
    region_count: int = 1,
) -> Decimal:
    """调度提交预扣额（闸用）：按同格封顶份额锁足，覆盖一次自动重试。"""
    return estimate_schedule_reserve_credits(
        db,
        tenant,
        platform_codes=platform_codes,
        prompt_count=prompt_count,
        region_count=region_count,
    )


def estimate_next_window_platform_cost(db: Session) -> dict[str, Any]:
    """下一监测窗全平台子任务数与模力真金预估（供 runway / can_submit_platform）。"""
    from datetime import datetime

    from app.models.brand import BrandAsset

    tenants = list(db.scalars(select(Tenant).where(Tenant.deleted.is_(False), Tenant.status.is_(True))))
    subtasks = 0
    for tenant in tenants:
        asset = db.scalar(
            select(BrandAsset).where(BrandAsset.tenant_id == tenant.id, BrandAsset.deleted.is_(False))
        )
        if asset is None:
            continue
        est = estimate_daily_credits(db, tenant, asset)
        slots = max(1, int(est.get("schedule_slots") or 1))
        subtasks += int(est.get("subtasks_per_day") or 0) // slots
    yuan_per = platform_molizhishu_yuan_per_subtask()
    estimated_yuan = float((Decimal(subtasks) * yuan_per).quantize(Decimal("0.0001")))
    window_key = datetime.now().strftime("%Y%m%d-%H%M")
    return {
        "subtask_count": subtasks,
        "estimated_yuan": estimated_yuan,
        "yuan_per_subtask": float(yuan_per),
        "window_key": window_key,
        "updated_at": datetime.now().isoformat(sep=" ", timespec="minutes"),
    }


def resolve_credits_per_subtask(
    db: Session,
    *,
    tenant_id: int | None,
    platform_code: str | None,
    deep_think: bool = False,
) -> Decimal:
    base = _lookup_price(db, tenant_id=tenant_id, platform_code=platform_code)
    if deep_think:
        addon = _lookup_price(db, tenant_id=tenant_id, platform_code=DEEP_THINK_ADDON_CODE)
        if addon is None:
            addon = _lookup_price(db, tenant_id=None, platform_code=DEEP_THINK_ADDON_CODE)
        if addon is not None:
            base += addon
    return base


def _lookup_price(db: Session, *, tenant_id: int | None, platform_code: str | None) -> Decimal:
    from app.models.credit import CreditPriceRule

    platform_key = normalize_price_platform_key(platform_code)
    if tenant_id is not None:
        tenant_key = normalize_price_tenant_key("tenant", tenant_id)
        row = db.scalar(
            select(CreditPriceRule)
            .where(
                CreditPriceRule.scope == "tenant",
                CreditPriceRule.tenant_key == tenant_key,
                CreditPriceRule.platform_key == platform_key,
                CreditPriceRule.status.is_(True),
            )
            .limit(1)
        )
        if row:
            return Decimal(str(row.credits_per_subtask))
        if platform_key != CREDIT_PRICE_DEFAULT_PLATFORM_KEY:
            row = db.scalar(
                select(CreditPriceRule)
                .where(
                    CreditPriceRule.scope == "tenant",
                    CreditPriceRule.tenant_key == tenant_key,
                    CreditPriceRule.platform_key == CREDIT_PRICE_DEFAULT_PLATFORM_KEY,
                    CreditPriceRule.status.is_(True),
                )
                .limit(1)
            )
            if row:
                return Decimal(str(row.credits_per_subtask))

    row = db.scalar(
        select(CreditPriceRule)
        .where(
            CreditPriceRule.scope == "global",
            CreditPriceRule.tenant_key == CREDIT_PRICE_GLOBAL_TENANT_KEY,
            CreditPriceRule.platform_key == platform_key,
            CreditPriceRule.status.is_(True),
        )
        .limit(1)
    )
    if row:
        return Decimal(str(row.credits_per_subtask))

    if platform_key != CREDIT_PRICE_DEFAULT_PLATFORM_KEY:
        row = db.scalar(
            select(CreditPriceRule)
            .where(
                CreditPriceRule.scope == "global",
                CreditPriceRule.tenant_key == CREDIT_PRICE_GLOBAL_TENANT_KEY,
                CreditPriceRule.platform_key == CREDIT_PRICE_DEFAULT_PLATFORM_KEY,
                CreditPriceRule.status.is_(True),
            )
            .limit(1)
        )
        if row:
            return Decimal(str(row.credits_per_subtask))
    return Decimal("1")


def cap_settle_credits(raw: Decimal, policy: dict | None) -> Decimal:
    # 2026-08-27 - 同格含 auto-retry 累计 settle 封顶（默认 2 算力）
    cap = Decimal(str(merge_credit_policy(policy).get("settle_cell_credit_cap", 2)))
    return min(raw, cap)


def estimate_daily_credits(
    db: Session,
    tenant: Tenant,
    asset: BrandAsset,
    *,
    keyword_count: int | None = None,
) -> dict[str, Any]:
    from app.services.brand_service import tenant_purchased_platforms
    from app.services.schedule_service import schedule_times_for_asset

    keywords = keyword_count
    if keywords is None:
        keywords = len(asset.monitor_keywords_json or [])
    platforms = tenant_purchased_platforms(db, tenant.id, asset)
    # 2026-09-07 - 算力自助不再用租户白名单裁切日预估平台集
    slots = len(schedule_times_for_asset(asset))
    regions = max(1, len(asset.region_codes_json or []) or 1)
    if not asset.region_codes_json:
        regions = 1
    platform_unit_sum = sum(
        resolve_credits_per_subtask(db, tenant_id=tenant.id, platform_code=code)
        for code in platforms
    )
    default_unit = resolve_credits_per_subtask(db, tenant_id=tenant.id, platform_code=None)
    subtasks_per_day = keywords * max(1, len(platforms)) * max(1, slots) * regions
    # 2026-08-28 - 日预估按平台单价累加 - 与 estimate_group_credits / 提交预扣口径一致
    credits_per_day = Decimal(max(1, keywords)) * Decimal(max(1, slots)) * Decimal(regions) * platform_unit_sum
    avg_unit = (credits_per_day / Decimal(subtasks_per_day)) if subtasks_per_day else default_unit
    return {
        "keyword_count": keywords,
        "platform_count": len(platforms),
        "schedule_slots": slots,
        "region_count": regions,
        "subtasks_per_day": subtasks_per_day,
        "credits_per_day": float(credits_per_day),
        "credits_per_subtask": float(avg_unit),
    }


def estimate_group_credits(
    db: Session,
    tenant: Tenant,
    *,
    platform_codes: list[str],
    region_count: int,
    prompt_count: int = 1,
    deep_think: bool = False,
) -> Decimal:
    total = Decimal("0")
    for code in platform_codes:
        total += resolve_credits_per_subtask(
            db,
            tenant_id=tenant.id,
            platform_code=code,
            deep_think=deep_think,
        )
    regions = max(1, region_count)
    return total * Decimal(regions) * Decimal(max(1, prompt_count))


def get_cached_platform_window_estimate() -> dict[str, Any]:
    from app.core.redis_client import get_json_cache

    return get_json_cache(PLATFORM_ESTIMATE_CACHE_KEY) or {
        "subtask_count": 0,
        "estimated_yuan": 0.0,
        "window_key": None,
        "updated_at": None,
    }


def set_cached_platform_window_estimate(payload: dict[str, Any], *, ttl_seconds: int = 120) -> None:
    from app.core.redis_client import set_json_cache

    set_json_cache(PLATFORM_ESTIMATE_CACHE_KEY, payload, ttl_seconds=ttl_seconds)


def evaluate_platform_runway(
    db: Session, *, extra_yuan: Decimal = Decimal("0")
) -> tuple[bool | None, Decimal | None, Decimal | None]:
    """评估模力真金是否够下一窗。

    返回 (sufficient|None未知, balance, estimate)。供看板告警；提交硬闸见 can_submit_platform。
    """
    cached = get_cached_platform_window_estimate()
    estimate = Decimal(str(cached.get("estimated_yuan") or 0)) + extra_yuan
    snapshot = fetch_molizhishu_balance()
    if not snapshot.get("available"):
        return None, None, estimate
    # 2026-08-27 - fetch_molizhishu_balance 用 current_balance，勿读不存在的 balance 键
    balance_raw = snapshot.get("current_balance")
    if balance_raw is None:
        return None, None, estimate
    balance = Decimal(str(balance_raw))
    buffer_yuan = _config_decimal("platform_balance_buffer_yuan", "500")
    runway_windows = _config_int("platform_balance_runway_windows", 1)
    required = estimate * Decimal(runway_windows) + buffer_yuan
    return balance >= required, balance, estimate


def can_submit_platform(db: Session, *, extra_yuan: Decimal = Decimal("0")) -> tuple[bool, Decimal | None, Decimal | None]:
    # 2026-09-09 - 方案乙：真金不足/查不到均不硬拦提交；仅返回快照供看板
    _sufficient, balance, estimate = evaluate_platform_runway(db, extra_yuan=extra_yuan)
    return True, balance, estimate


def is_offline_price_terms(terms: CreditTermsVersion | None) -> bool:
    """单价调整由销售线下沟通，不进客户条款、不进运营声明列表。"""
    if terms is None:
        return False
    code = str(terms.version_code or "")
    title = str(terms.title or "")
    return code.startswith("auto-") or title.startswith("算力单价调整")


def pending_terms_block(db: Session, tenant_id: int) -> CreditTermsVersion | None:
    # 2026-09-08 - 条款不硬闸；保留符号供旧测/脚本导入，恒无待确认
    del db, tenant_id
    return None


def resolve_customer_credit_terms(db: Session, tenant_id: int) -> CreditTermsVersion | None:
    """客户算力中心展示：当前已生效的最新正式服务条款；单价自动声明不展示。

    按 effective_at 取「最新」时，验证脚本/预发布里把生效日填到未来会压过刚发布的正式版。
    因此先筛 effective_at <= now；若尚无已生效记录，再回退到最近发布的正式版。
    """
    del tenant_id  # 2026-09-08 - 不再按 ack 排队；全租户看同一套正式条款
    formal = (
        CreditTermsVersion.status == "published",
        ~CreditTermsVersion.version_code.like("auto-%"),
        ~CreditTermsVersion.title.like("算力单价调整%"),
    )
    now = datetime.now()
    current = db.scalar(
        select(CreditTermsVersion)
        .where(*formal, CreditTermsVersion.effective_at <= now)
        .order_by(CreditTermsVersion.effective_at.desc(), CreditTermsVersion.id.desc())
    )
    if current is not None:
        return current
    # MySQL 不支持 NULLS LAST；DESC 下 NULL 已靠后，勿用 .nulls_last()
    return db.scalar(
        select(CreditTermsVersion)
        .where(*formal)
        .order_by(CreditTermsVersion.published_at.desc(), CreditTermsVersion.id.desc())
    )

def validate_credit_monitor_save(tenant: Tenant, payload) -> None:
    """Credit 企业监测配置校验。

    2026-09-07 - 方案 A：词数/场次/地区/平台均由客户自助支配，仅余额/预扣闸门；本函数保留调用点兼容，不再限额。
    """
    return


def record_submit_block(
    db: Session,
    *,
    tenant_id: int,
    window_key: str,
    block_reason: str,
    required_credits: Decimal | None = None,
    available_credits: Decimal | None = None,
    platform_balance_snapshot: Decimal | None = None,
    platform_required_estimate: Decimal | None = None,
) -> CreditSubmitBlock:
    row = CreditSubmitBlock(
        tenant_id=tenant_id,
        window_key=window_key,
        block_reason=block_reason,
        required_credits=required_credits,
        available_credits=available_credits,
        platform_balance_snapshot=platform_balance_snapshot,
        platform_required_estimate=platform_required_estimate,
    )
    db.add(row)
    db.flush()
    return row


def _notify_credit_block(db: Session, *, tenant: Tenant, block_reason: str, window_key: str) -> None:
    from app.services.system_notification_service import upsert_credit_block_notification

    upsert_credit_block_notification(db, tenant=tenant, block_reason=block_reason, window_key=window_key)


def _notify_balance_capped(
    db: Session,
    *,
    tenant: Tenant,
    window_key: str | None,
    ref_id: str,
    requested: Decimal,
    charged: Decimal,
) -> None:
    """结算因余额封顶少收：写入拦截表并通知平台运营（同窗去重）。"""
    from app.services.system_notification_service import upsert_credit_balance_capped_notification

    wk = (window_key or ref_id or "settle")[:32]
    since = datetime.now() - timedelta(hours=24)
    existed = db.scalar(
        select(CreditSubmitBlock.id).where(
            CreditSubmitBlock.tenant_id == tenant.id,
            CreditSubmitBlock.window_key == wk,
            CreditSubmitBlock.block_reason == "balance_capped",
            CreditSubmitBlock.created_at >= since,
        ).limit(1)
    )
    if existed is None:
        record_submit_block(
            db,
            tenant_id=tenant.id,
            window_key=wk,
            block_reason="balance_capped",
            required_credits=requested,
            available_credits=charged,
        )
    upsert_credit_balance_capped_notification(
        db,
        tenant=tenant,
        window_key=wk,
        requested=float(requested),
        charged=float(charged),
    )


def reserve_credits(
    db: Session,
    tenant: Tenant,
    amount: Decimal,
    *,
    ref_id: str,
    ref_type: str,
    window_key: str | None = None,
    operator_user_id: int | None = None,
    reason: str | None = None,
    detail_json: dict | None = None,
) -> bool:
    if amount <= 0:
        return True
    # 2026-09-09 - 先锁租户再复检 open reserve，避免多 worker 同 ref 叠扣
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant.id).with_for_update())
    if tenant is None:
        return False
    if has_open_credit_reserve(db, tenant.id, ref_id):
        return True
    available = tenant_available_credits(tenant)
    if amount > available:
        return False
    # 2026-09-07 - 按格结算要等跑完+auto-retry；30 分钟 TTL 会提前扫掉预扣
    ttl = _config_int("credit_reserve_ttl_seconds", 7200)
    expires = datetime.now() + timedelta(seconds=ttl)
    tenant.credit_reserved = Decimal(str(tenant.credit_reserved or 0)) + amount
    db.add(
        TenantCreditLedger(
            tenant_id=tenant.id,
            amount=-amount,
            balance_after=_ledger_balance_snapshot(tenant, "reserve"),
            entry_type="reserve",
            ref_type=ref_type,
            ref_id=ref_id,
            window_key=window_key,
            operator_user_id=operator_user_id,
            reason=reason,
            reserve_expires_at=expires,
            detail_json=detail_json,
        )
    )
    db.flush()
    return True


def release_reserve(
    db: Session,
    *,
    tenant_id: int,
    ref_id: str,
    amount: Decimal | None = None,
    reason: str | None = None,
    detail_json: dict | None = None,
) -> None:
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if tenant is None:
        return
    rows = list(
        db.scalars(
            select(TenantCreditLedger).where(
                TenantCreditLedger.tenant_id == tenant_id,
                TenantCreditLedger.ref_id == ref_id,
                TenantCreditLedger.entry_type == "reserve",
            )
        )
    )
    if not rows:
        return
    release_amount = amount
    ref_left = ref_reserve_remaining(db, tenant_id, ref_id)
    if release_amount is None:
        # 2026-09-07 - 整批释放按「该 ref 剩余占用」算，勿把其它批次的 reserved 一并清掉
        # 2026-09-09 - remaining≤0 说明本 ref 已结清/已释放，禁止用「历史 reserve 总额」兜底偷邻批
        release_amount = ref_left
        if release_amount <= 0:
            return
    else:
        # 2026-09-09 - 显式 amount（按格份额）也不得超过本 ref 剩余，防偷邻批
        release_amount = min(Decimal(str(release_amount)), ref_left)
    release_amount = min(release_amount, Decimal(str(tenant.credit_reserved or 0)))
    if release_amount <= 0:
        return
    tenant.credit_reserved = Decimal(str(tenant.credit_reserved or 0)) - release_amount
    db.add(
        TenantCreditLedger(
            tenant_id=tenant_id,
            amount=release_amount,
            balance_after=_ledger_balance_snapshot(tenant, "release"),
            entry_type="release",
            ref_type=rows[0].ref_type,
            ref_id=ref_id,
            window_key=rows[0].window_key,
            reason=reason or "释放预扣",
            detail_json=detail_json,
        )
    )
    db.flush()


def settle_credits(
    db: Session,
    *,
    tenant_id: int,
    ref_id: str,
    credits: Decimal,
    platform_code: str | None = None,
    keyword: str | None = None,
    window_key: str | None = None,
    detail_json: dict | None = None,
    prepaid_share: Decimal | None = None,
) -> None:
    """实扣余额。prepaid_share 有值时只动该格预扣份额（重试多扣只打余额，不偷邻格预扣）。"""
    if credits <= 0:
        release_reserve(
            db,
            tenant_id=tenant_id,
            ref_id=ref_id,
            amount=prepaid_share,
            reason="未计费释放预扣",
            detail_json=detail_json,
        )
        return
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if tenant is None:
        return
    reserved = Decimal(str(tenant.credit_reserved or 0))
    # 2026-09-09 - 整批/按格都只动本 ref 剩余预扣，勿用租户总 reserved 偷邻批
    ref_left = ref_reserve_remaining(db, tenant_id, ref_id)
    if prepaid_share is not None:
        share = min(Decimal(str(prepaid_share)), ref_left)
        deduct = min(share, reserved)
        leftover = Decimal("0")
    else:
        deduct = min(credits, reserved, ref_left) if reserved > 0 else Decimal("0")
        leftover = max(Decimal("0"), ref_left - deduct)
    if deduct > 0:
        tenant.credit_reserved = reserved - deduct
    # 2026-09-11 - 产品确认：结算允许余额为负，按应扣全额入账（不再 balance_capped 少收）
    balance_before = Decimal(str(tenant.credit_balance or 0))
    charge = credits
    tenant.credit_balance = balance_before - charge
    settle_detail = detail_json
    if settle_detail is None and (platform_code or keyword):
        settle_detail = {
            "subtasks": [
                {
                    "platform_code": platform_code,
                    "keyword": keyword,
                    "credits": float(credits),
                    "charged": float(charge),
                    "status": "settled",
                }
            ]
        }
    # 预扣消化额按实际 deduct 记账（整批/按格统一），避免 remaining 虚高再被二次释放
    if deduct > 0:
        settle_detail = dict(settle_detail or {})
        settle_detail["prepaid_share"] = float(deduct)
    db.add(
        TenantCreditLedger(
            tenant_id=tenant_id,
            amount=-charge,
            balance_after=_ledger_balance_snapshot(tenant, "settle"),
            entry_type="settle",
            ref_type="subtask",
            ref_id=ref_id,
            platform_code=platform_code,
            keyword=keyword,
            window_key=window_key,
            detail_json=settle_detail,
        )
    )
    # 整批 settle 只释放本 ref 残余预扣；按格路径由调用方逐格 release/settle
    if leftover > 0:
        release_reserve(
            db,
            tenant_id=tenant_id,
            ref_id=ref_id,
            amount=leftover,
            reason="结算后释放剩余预扣",
        )
    db.flush()


def finalize_schedule_submit(
    db: Session,
    tenant: Tenant,
    *,
    reserve_ref: str,
    reserved_credits: Decimal | None,
    submit_status: str,
    platform_code: str | None = None,
    keyword: str | None = None,
    window_key: str | None = None,
) -> None:
    """提交口：成功只保留预扣；失败整批释放。实扣改到子任务终态按格 settle。"""
    if not is_credit_tenant(tenant) or not reserved_credits:
        return
    if submit_status in {"completed", "submitted", "running"}:
        # 2026-09-07 - 提交成功不再整批 settle；等模力 amount 出来再按格扣/释放
        return
    release_reserve(db, tenant_id=tenant.id, ref_id=reserve_ref, reason="提交失败释放预扣")


def resolve_schedule_credit_reserve_ref(db: Session, task: Any) -> str | None:
    """从任务 meta 或调度记录解析本批预扣 ref（一般为 group_key）。"""
    raw = task.raw_request_json if isinstance(getattr(task, "raw_request_json", None), dict) else {}
    meta = raw.get("_geo_credit") if isinstance(raw.get("_geo_credit"), dict) else {}
    ref = str(meta.get("reserve_ref") or "").strip()
    if ref:
        return ref[:64]
    task_id = str(getattr(task, "task_id", "") or "").strip()
    if not task_id:
        return None
    from app.models.monitor import GeoMonitorScheduleRun

    run = db.scalar(
        select(GeoMonitorScheduleRun).where(GeoMonitorScheduleRun.task_id == task_id).limit(1)
    )
    if run and run.schedule_key:
        return str(run.schedule_key)[:64]
    return None


def cell_credit_already_finalized(
    db: Session,
    *,
    tenant_id: int,
    batch_ref: str,
    origin_subtask_id: str,
) -> bool:
    hit = db.scalar(
        select(TenantCreditCellFinalize.id).where(
            TenantCreditCellFinalize.tenant_id == tenant_id,
            TenantCreditCellFinalize.batch_ref == batch_ref,
            TenantCreditCellFinalize.origin_subtask_id == origin_subtask_id,
        ).limit(1)
    )
    if hit is not None:
        return True
    # 兼容迁移前仅写过 ledger detail 的旧数据
    rows = db.scalars(
        select(TenantCreditLedger).where(
            TenantCreditLedger.tenant_id == tenant_id,
            TenantCreditLedger.ref_id == batch_ref,
            TenantCreditLedger.entry_type.in_(("settle", "release")),
        )
    )
    for row in rows:
        detail = row.detail_json if isinstance(row.detail_json, dict) else {}
        if detail.get("origin_subtask_id") == origin_subtask_id:
            return True
    return False


def _cell_billed_attempt_count(origin: Any) -> int:
    """计费次数：产品定重试免费，有模力计费最多按 1 格收。"""
    raw = origin.raw_result_json if isinstance(getattr(origin, "raw_result_json", None), dict) else {}
    attempts = raw.get("_credit_attempt_amounts")
    if isinstance(attempts, list) and attempts:
        if any(Decimal(str(item or 0)) > 0 for item in attempts):
            return 1
    amount = getattr(origin, "amount", None)
    if amount is not None and Decimal(str(amount)) > 0:
        return 1
    return 0


def cell_ready_for_credit_settle(origin: Any) -> bool:
    """子任务终态且不在自动重试等待中，才可按格结算。"""
    from app.services.monitor_auto_retry_service import (
        subtask_failure_awaits_or_in_auto_retry,
        subtask_hard_failed,
    )

    if subtask_failure_awaits_or_in_auto_retry(origin):
        return False
    status = str(getattr(origin, "status", "") or "").lower()
    if status in {"completed", "partial_completed"}:
        return True
    if subtask_hard_failed(origin):
        return True
    return False


def compute_cell_settle_credits(db: Session, tenant: Tenant, origin: Any) -> Decimal:
    """有模力计费按平台单价×计费次数，同格封顶（绝对算力）；未计费为 0。"""
    unit = resolve_credits_per_subtask(
        db,
        tenant_id=tenant.id,
        platform_code=str(getattr(origin, "platform", None) or "") or None,
    )
    billed = _cell_billed_attempt_count(origin)
    if billed <= 0:
        return Decimal("0")
    return cap_settle_credits(
        unit * Decimal(billed),
        getattr(tenant, "credit_policy_json", None),
    )


def _claim_cell_credit_finalize_safe(
    db: Session,
    *,
    tenant_id: int,
    batch_ref: str,
    origin_subtask_id: str,
    entry_type: str,
    credits: Decimal,
) -> TenantCreditCellFinalize | None:
    try:
        with db.begin_nested():
            row = TenantCreditCellFinalize(
                tenant_id=tenant_id,
                batch_ref=batch_ref,
                origin_subtask_id=origin_subtask_id,
                entry_type=entry_type,
                credits=credits,
            )
            db.add(row)
            db.flush()
            return row
    except IntegrityError:
        return None


def finalize_monitor_cell_credit(
    db: Session,
    tenant: Tenant,
    *,
    origin: Any,
    batch_ref: str,
    window_key: str | None = None,
) -> bool:
    """按格 settle/release。已结算过返回 False。"""
    origin_id = str(getattr(origin, "subtask_id", "") or "").strip()
    if not origin_id or not batch_ref:
        return False
    # 2026-09-09 - 切回托管后：本批仍有开放预扣则继续结清，避免白跑/TTL 误释
    if not is_credit_tenant(tenant) and not has_open_credit_reserve(db, tenant.id, batch_ref):
        return False
    if batch_force_closed(db, tenant.id, batch_ref):
        # 运营整批释放后不再补扣
        _claim_cell_credit_finalize_safe(
            db,
            tenant_id=tenant.id,
            batch_ref=batch_ref,
            origin_subtask_id=origin_id,
            entry_type="skipped",
            credits=Decimal("0"),
        )
        return False
    if not cell_ready_for_credit_settle(origin):
        return False
    if cell_credit_already_finalized(
        db, tenant_id=tenant.id, batch_ref=batch_ref, origin_subtask_id=origin_id
    ):
        return False

    reserve_detail = get_reserve_detail(db, tenant.id, batch_ref)
    platform = str(getattr(origin, "platform", None) or "") or None
    unit = resolve_credits_per_subtask(db, tenant_id=tenant.id, platform_code=platform)
    prepaid_share = cell_prepaid_share(db, tenant, platform, reserve_detail=reserve_detail)
    credits = compute_cell_settle_credits(db, tenant, origin)
    billed = _cell_billed_attempt_count(origin)
    entry_type = "settle" if credits > 0 else "release"
    detail = {
        "origin_subtask_id": origin_id,
        "billed_attempts": billed,
        "cell_unit": float(unit),
        "prepaid_share": float(prepaid_share),
        "cell_prepaid_share": float(prepaid_share),
        "molizhishu_amount": float(origin.amount) if getattr(origin, "amount", None) is not None else None,
        "auto_retry_status": getattr(origin, "auto_retry_status", None),
        "subtasks": [
            {
                "subtask_id": origin_id,
                "platform_code": getattr(origin, "platform", None),
                "keyword": (getattr(origin, "prompt", None) or "")[:200],
                "credits": float(credits),
                "status": "settled" if credits > 0 else "released_unbilled",
            }
        ],
    }
    # 2026-09-09 - claim 与 settle/release 同 savepoint：中途失败整段回滚，禁止「已 claim 未入账」漏扣
    try:
        with db.begin_nested():
            claimed = TenantCreditCellFinalize(
                tenant_id=tenant.id,
                batch_ref=batch_ref,
                origin_subtask_id=origin_id,
                entry_type=entry_type,
                credits=credits,
            )
            db.add(claimed)
            db.flush()
            if credits <= 0:
                release_reserve(
                    db,
                    tenant_id=tenant.id,
                    ref_id=batch_ref,
                    amount=prepaid_share,
                    reason="模力未计费释放预扣",
                    detail_json=detail,
                )
            else:
                settle_credits(
                    db,
                    tenant_id=tenant.id,
                    ref_id=batch_ref,
                    credits=credits,
                    platform_code=platform,
                    keyword=(getattr(origin, "prompt", None) or "")[:200] or None,
                    window_key=window_key,
                    detail_json=detail,
                    prepaid_share=prepaid_share,
                )
            ledger = db.scalar(
                select(TenantCreditLedger)
                .where(
                    TenantCreditLedger.tenant_id == tenant.id,
                    TenantCreditLedger.ref_id == batch_ref,
                    TenantCreditLedger.entry_type == entry_type,
                )
                .order_by(TenantCreditLedger.id.desc())
                .limit(1)
            )
            if ledger is not None:
                claimed.ledger_id = ledger.id
            db.flush()
        return True
    except IntegrityError:
        return False


def maybe_release_batch_reserve_remainder(
    db: Session,
    tenant: Tenant,
    *,
    batch_ref: str,
    origins: list[Any],
) -> bool:
    """本批格子均已终态且已按格落账后，清掉残余预扣。"""
    if not origins or batch_force_closed(db, tenant.id, batch_ref):
        return False
    for origin in origins:
        if not cell_ready_for_credit_settle(origin):
            return False
        oid = str(getattr(origin, "subtask_id", "") or "").strip()
        if oid and not cell_credit_already_finalized(
            db, tenant_id=tenant.id, batch_ref=batch_ref, origin_subtask_id=oid
        ):
            return False
    remaining = ref_reserve_remaining(db, tenant.id, batch_ref)
    if remaining <= 0:
        return False
    release_reserve(
        db,
        tenant_id=tenant.id,
        ref_id=batch_ref,
        amount=remaining,
        reason="整批结算后释放残余预扣",
        detail_json={"batch_close": True, "remainder": float(remaining)},
    )
    return True


def settle_ready_credit_cells_for_task(db: Session, task: Any) -> int:
    """同步/重试收尾后：对本单（或重试单关联的原格）可结算格子落账。"""
    from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
    from app.services.monitor_auto_retry_service import GEO_AUTO_RETRY_META, is_auto_retry_task

    tenant_id = getattr(task, "tenant_id", None)
    if not tenant_id:
        return 0
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        return 0
    # 非 credit 时由 finalize_monitor_cell_credit 按「是否仍有本批预扣」决定是否结清

    finalized = 0
    if is_auto_retry_task(task):
        raw = task.raw_request_json if isinstance(task.raw_request_json, dict) else {}
        meta = raw.get(GEO_AUTO_RETRY_META) or {}
        origin_ids = [
            str(p.get("subtask_id") or "").strip()
            for p in (meta.get("pairs") or [])
            if p.get("subtask_id")
        ]
        origins: list[Any] = []
        batch_refs: set[str] = set()
        for origin_id in {oid for oid in origin_ids if oid}:
            origin = db.scalar(select(GeoMonitorSubtask).where(GeoMonitorSubtask.subtask_id == origin_id))
            if origin is None:
                continue
            origins.append(origin)
            origin_task = db.scalar(
                select(GeoMonitorTask).where(
                    GeoMonitorTask.task_id == origin.task_id,
                    GeoMonitorTask.deleted.is_(False),
                )
            )
            batch_ref = resolve_schedule_credit_reserve_ref(db, origin_task) if origin_task else None
            if not batch_ref:
                continue
            batch_refs.add(batch_ref)
            window_key = None
            oraw = origin_task.raw_request_json if origin_task and isinstance(origin_task.raw_request_json, dict) else {}
            ometa = oraw.get("_geo_credit") if isinstance(oraw.get("_geo_credit"), dict) else {}
            window_key = ometa.get("window_key")
            if finalize_monitor_cell_credit(
                db, tenant, origin=origin, batch_ref=batch_ref, window_key=window_key
            ):
                finalized += 1
        for batch_ref in batch_refs:
            origin_task_ids = {o.task_id for o in origins}
            all_origins = []
            for tid in origin_task_ids:
                all_origins.extend(
                    list(db.scalars(select(GeoMonitorSubtask).where(GeoMonitorSubtask.task_id == tid)))
                )
            maybe_release_batch_reserve_remainder(db, tenant, batch_ref=batch_ref, origins=all_origins)
        return finalized

    batch_ref = resolve_schedule_credit_reserve_ref(db, task)
    if not batch_ref:
        return 0
    raw = task.raw_request_json if isinstance(task.raw_request_json, dict) else {}
    meta = raw.get("_geo_credit") if isinstance(raw.get("_geo_credit"), dict) else {}
    window_key = meta.get("window_key")
    subtasks = list(getattr(task, "subtasks", None) or [])
    if not subtasks:
        subtasks = list(
            db.scalars(select(GeoMonitorSubtask).where(GeoMonitorSubtask.task_id == task.task_id))
        )
    for origin in subtasks:
        if finalize_monitor_cell_credit(
            db, tenant, origin=origin, batch_ref=batch_ref, window_key=window_key
        ):
            finalized += 1
    maybe_release_batch_reserve_remainder(db, tenant, batch_ref=batch_ref, origins=subtasks)
    return finalized


def recharge_credits(
    db: Session,
    tenant: Tenant,
    amount: Decimal,
    *,
    operator_user_id: int,
    reason: str,
    detail_json: dict | None = None,
) -> TenantCreditLedger:
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant.id).with_for_update())
    tenant.credit_balance = Decimal(str(tenant.credit_balance or 0)) + amount
    row = TenantCreditLedger(
        tenant_id=tenant.id,
        amount=amount,
        balance_after=_ledger_balance_snapshot(tenant, "recharge" if amount > 0 else "adjust"),
        entry_type="recharge" if amount > 0 else "adjust",
        ref_type="manual",
        operator_user_id=operator_user_id,
        reason=reason,
        detail_json=detail_json,
    )
    db.add(row)
    db.flush()
    return row


def preflight_schedule_submit(
    db: Session,
    tenant: Tenant | None,
    *,
    window_key: str,
    reserve_ref: str,
    credits_needed: Decimal,
    reserve: bool = True,
    reserve_detail: dict | None = None,
) -> SubmitGateResult:
    if tenant is None:
        return SubmitGateResult(False, "inactive", "企业不存在")
    if not tenant.status:
        record_submit_block(
            db,
            tenant_id=tenant.id,
            window_key=window_key,
            block_reason="inactive",
        )
        return SubmitGateResult(False, "inactive", "企业服务已停服")
    open_same_ref = False
    if is_credit_tenant(tenant):
        # 2026-09-08 - 服务条款改为查阅即可，提交不再因未确认条款硬闸
        # 同 ref 预扣已锁住时可用额变低，重试勿再报「算力不足」
        open_same_ref = bool(str(reserve_ref or "").strip()) and has_open_credit_reserve(
            db, tenant.id, reserve_ref
        )
        if not open_same_ref and credits_needed > tenant_available_credits(tenant):
            record_submit_block(
                db,
                tenant_id=tenant.id,
                window_key=window_key,
                block_reason="tenant_credit",
                required_credits=credits_needed,
                available_credits=tenant_available_credits(tenant),
            )
            _notify_credit_block(db, tenant=tenant, block_reason="tenant_credit", window_key=window_key)
            return SubmitGateResult(False, "tenant_credit", "算力不足，请联系销售充值")
    # 2026-09-09 - 方案乙：模力真金不足/查不到不硬拦（下游失败由模力侧体现）
    if is_credit_tenant(tenant) and credits_needed > 0 and reserve:
        if open_same_ref:
            remaining = ref_reserve_remaining(db, tenant.id, reserve_ref)
            return SubmitGateResult(
                True,
                reserve_ref=reserve_ref,
                reserved_credits=remaining if remaining > 0 else credits_needed,
            )
        if not reserve_credits(
            db,
            tenant,
            credits_needed,
            ref_id=reserve_ref,
            ref_type="reserve_batch",
            window_key=window_key,
            detail_json=reserve_detail,
        ):
            record_submit_block(
                db,
                tenant_id=tenant.id,
                window_key=window_key,
                block_reason="tenant_credit",
                required_credits=credits_needed,
                available_credits=tenant_available_credits(tenant),
            )
            _notify_credit_block(db, tenant=tenant, block_reason="tenant_credit", window_key=window_key)
            return SubmitGateResult(False, "tenant_credit", "算力不足，请联系销售充值")
        return SubmitGateResult(True, reserve_ref=reserve_ref, reserved_credits=credits_needed)
    return SubmitGateResult(True)


def apply_schedule_credit_gate(
    db: Session,
    tenant: Tenant | None,
    *,
    group_key: str,
    schedule_key: str,
    platform_codes: list[str],
    prompt_count: int,
    region_count: int = 1,
) -> SubmitGateResult:
    """调度提交前的算力闸：条款 + 余额预扣。托管企业不走，避免模力余额接口拖死代管提交。"""
    if not is_credit_tenant(tenant):
        return SubmitGateResult(True)
    # 调度 group_key 已按地区分片时 region_count=1；多区同批提交传真实区数
    regions = max(1, int(region_count or 1))
    credits_needed = estimate_schedule_submit_credits(
        db,
        tenant,
        platform_codes=platform_codes,
        prompt_count=prompt_count,
        region_count=regions,
    )
    window_key = str(schedule_key or group_key)[:32]
    reserve_ref = str(group_key or "")[:64]
    detail = build_reserve_batch_detail(
        db,
        tenant,
        platform_codes=platform_codes,
        prompt_count=prompt_count,
        region_count=regions,
    )
    return preflight_schedule_submit(
        db,
        tenant,
        window_key=window_key,
        reserve_ref=reserve_ref,
        credits_needed=credits_needed,
        reserve_detail=detail,
    )


def apply_manual_monitor_credit_gate(
    db: Session,
    tenant: Tenant | None,
    *,
    platform_codes: list[str],
    prompt_count: int,
    region_count: int = 1,
    reserve_ref: str | None = None,
) -> SubmitGateResult:
    """平台监控页直提：credit 企业同样预扣，避免绕过调度白跑。"""
    if not is_credit_tenant(tenant):
        return SubmitGateResult(True)
    from uuid import uuid4

    regions = max(1, int(region_count or 1))
    ref = (reserve_ref or f"manual-{uuid4().hex[:20]}")[:64]
    window_key = datetime.now().strftime("%Y%m%d-%H%M")[:32]
    credits_needed = estimate_schedule_submit_credits(
        db,
        tenant,
        platform_codes=platform_codes,
        prompt_count=prompt_count,
        region_count=regions,
    )
    detail = build_reserve_batch_detail(
        db,
        tenant,
        platform_codes=platform_codes,
        prompt_count=prompt_count,
        region_count=regions,
    )
    detail["submit_channel"] = "manual_monitor"
    return preflight_schedule_submit(
        db,
        tenant,
        window_key=window_key,
        reserve_ref=ref,
        credits_needed=credits_needed,
        reserve_detail=detail,
    )


def scan_credit_three_day_shortfall(db: Session) -> int:
    """方案甲：可用 < 日预估×3 时通知企业；后台仍保留预扣，仅客户侧不展示。"""
    from app.services.brand_service import get_brand_asset

    tenants = list(
        db.scalars(
            select(Tenant).where(
                Tenant.deleted.is_(False),
                Tenant.status.is_(True),
                Tenant.billing_mode == BILLING_MODE_CREDIT,
            )
        )
    )
    sent = 0
    for tenant in tenants:
        asset = get_brand_asset(db, tenant.id)
        if asset is None:
            continue
        estimate = estimate_daily_credits(db, tenant, asset)
        if notify_tenant_three_day_shortfall_if_needed(db, tenant, estimate):
            sent += 1
    return sent


def notify_tenant_three_day_shortfall_if_needed(
    db: Session,
    tenant: Tenant,
    estimate: dict[str, Any] | None = None,
) -> bool:
    """单企检查：不足三日预估则写通知（按日去重）。返回是否新写入/更新。"""
    from app.services.brand_service import get_brand_asset
    from app.services.system_notification_service import upsert_credit_three_day_shortfall_notification

    if not is_credit_tenant(tenant) or not tenant.status:
        return False
    if estimate is None:
        asset = get_brand_asset(db, tenant.id)
        if asset is None:
            return False
        estimate = estimate_daily_credits(db, tenant, asset)
    daily = Decimal(str((estimate or {}).get("credits_per_day") or 0))
    if daily <= 0:
        return False
    available = tenant_available_credits(tenant)
    need = daily * Decimal("3")
    if available >= need:
        return False
    row = upsert_credit_three_day_shortfall_notification(
        db,
        tenant=tenant,
        available=float(available),
        credits_per_day=float(daily),
        need_three_days=float(need),
    )
    return row is not None


def credit_ops_summary(db: Session) -> dict[str, Any]:
    credit_tenants = list(
        db.scalars(select(Tenant).where(Tenant.deleted.is_(False), Tenant.billing_mode == BILLING_MODE_CREDIT))
    )
    total_balance = sum(Decimal(str(t.credit_balance or 0)) for t in credit_tenants)
    zero_balance = [t for t in credit_tenants if Decimal(str(t.credit_balance or 0)) <= 0]
    today_start = datetime.combine(datetime.now().date(), datetime.min.time())
    today_deduct = tenant_today_credit_deduct(db)
    blocks_24h = db.scalar(
        select(func.count()).select_from(CreditSubmitBlock).where(
            CreditSubmitBlock.created_at >= datetime.now() - timedelta(hours=24)
        )
    ) or 0
    tenant_credit_blocks = db.scalar(
        select(func.count()).select_from(CreditSubmitBlock).where(
            CreditSubmitBlock.created_at >= datetime.now() - timedelta(hours=24),
            CreditSubmitBlock.block_reason == "tenant_credit",
        )
    ) or 0
    platform_blocks = db.scalar(
        select(func.count()).select_from(CreditSubmitBlock).where(
            CreditSubmitBlock.created_at >= datetime.now() - timedelta(hours=24),
            CreditSubmitBlock.block_reason == "platform_balance",
        )
    ) or 0
    since_24h = datetime.now() - timedelta(hours=24)
    balance_capped_blocks = db.scalar(
        select(func.count()).select_from(CreditSubmitBlock).where(
            CreditSubmitBlock.created_at >= since_24h,
            CreditSubmitBlock.block_reason == "balance_capped",
        )
    ) or 0
    # 流水侧汇总少收差额（比拦截表去重更贴近真实少收）
    undercharge_credits = Decimal("0")
    settle_rows = list(
        db.scalars(
            select(TenantCreditLedger).where(
                TenantCreditLedger.entry_type == "settle",
                TenantCreditLedger.created_at >= since_24h,
            )
        )
    )
    for row in settle_rows:
        detail = row.detail_json if isinstance(row.detail_json, dict) else {}
        if not detail.get("balance_capped"):
            continue
        shortfall = detail.get("shortfall_credits")
        if shortfall is not None:
            undercharge_credits += Decimal(str(shortfall))
            continue
        requested = detail.get("requested_credits")
        charged = detail.get("charged_credits")
        if requested is not None and charged is not None:
            undercharge_credits += max(Decimal("0"), Decimal(str(requested)) - Decimal(str(charged)))
    molizhishu = fetch_molizhishu_balance()
    cached = get_cached_platform_window_estimate()
    estimate_yuan = Decimal(str(cached.get("estimated_yuan") or 0))
    balance = Decimal(str(molizhishu.get("current_balance") or molizhishu.get("balance") or 0))
    runway_threshold = _config_int("platform_balance_runway_windows", 1)
    runway = float(balance / estimate_yuan) if estimate_yuan > 0 else None
    sufficient, gate_balance, gate_estimate = evaluate_platform_runway(db)
    runway_low = runway is not None and estimate_yuan > 0 and runway < float(runway_threshold)
    # 乙：提交不硬拦，但不足/未知仍告警运营
    platform_balance_low = sufficient is False
    platform_balance_unknown = sufficient is None
    platform_gate_ok = sufficient is True
    if runway_low or platform_balance_low or platform_balance_unknown:
        from app.services.system_notification_service import upsert_credit_runway_alert

        upsert_credit_runway_alert(
            db,
            runway_windows=runway,
            runway_threshold=runway_threshold,
            molizhishu_balance=float(gate_balance or balance),
            next_window_yuan=float(gate_estimate or estimate_yuan),
            platform_gate_ok=platform_gate_ok,
        )
    return {
        "credit_tenant_count": len(credit_tenants),
        "credit_total_balance": float(total_balance),
        "credit_today_deduct": float(today_deduct),
        "zero_balance_count": len(zero_balance),
        "blocks_24h": int(blocks_24h),
        "tenant_credit_blocks_24h": int(tenant_credit_blocks),
        "platform_balance_blocks_24h": int(platform_blocks),
        "balance_capped_blocks_24h": int(balance_capped_blocks),
        "undercharge_credits_24h": float(undercharge_credits),
        "molizhishu_balance": molizhishu,
        "next_window_estimate": cached,
        "runway_windows": runway,
        "runway_threshold_windows": runway_threshold,
        "runway_low": runway_low,
        "platform_balance_low": platform_balance_low,
        "platform_gate_ok": platform_gate_ok,
        "zero_balance_tenants": [
            {
                "tenant_id": t.id,
                "name": t.name,
                "owner_user_id": t.owner_user_id,
                "credit_balance": float(t.credit_balance or 0),
            }
            for t in zero_balance
        ],
    }


def list_price_rules(
    db: Session,
    *,
    scope: str | None = None,
    tenant_id: int | None = None,
) -> list:
    from app.models.credit import CreditPriceRule

    stmt = select(CreditPriceRule).order_by(CreditPriceRule.scope, CreditPriceRule.tenant_id, CreditPriceRule.platform_code)
    if scope:
        stmt = stmt.where(CreditPriceRule.scope == scope)
    if tenant_id is not None:
        stmt = stmt.where(CreditPriceRule.tenant_id == tenant_id)
    return list(db.scalars(stmt))


def publish_policy_change_terms(
    db: Session,
    *,
    title: str,
    content_html: str,
    notice_days: int = 7,
) -> Any:
    """H3：单价/硬顶变更自动挂 terms，生效前 notice_days 内提醒确认。"""
    from datetime import timedelta
    from uuid import uuid4

    from app.models.credit import CreditTermsVersion
    from app.services.announcement_sanitize import sanitize_announcement_html

    now = datetime.now()
    # 2026-09-04 - 仅到秒会撞 version_code（连改多条单价 503）- 加微秒+短随机
    version_code = f"auto-{now.strftime('%Y%m%d%H%M%S%f')}-{uuid4().hex[:6]}"
    row = CreditTermsVersion(
        version_code=version_code,
        title=title,
        content_html=sanitize_announcement_html(content_html),
        effective_at=now + timedelta(days=max(1, notice_days)),
        notice_days=notice_days,
        status="published",
        published_at=now,
    )
    db.add(row)
    db.flush()
    # 2026-09-08 - 自动条款也不再推送「请确认」通知
    return row


def upsert_price_rule(
    db: Session,
    *,
    scope: str,
    tenant_id: int | None,
    platform_code: str | None,
    credits_per_subtask: Decimal,
    status: bool = True,
) -> Any:
    from app.models.credit import CreditPriceRule

    if scope not in {"global", "tenant"}:
        raise ValueError("scope 须为 global 或 tenant")
    if scope == "tenant" and tenant_id is None:
        raise ValueError("tenant 级单价须指定 tenant_id")
    if scope == "global":
        tenant_id = None
    if credits_per_subtask <= 0:
        raise ValueError("单价须大于 0")
    tenant_key = normalize_price_tenant_key(scope, tenant_id)
    platform_key = normalize_price_platform_key(platform_code)
    row = db.scalar(
        select(CreditPriceRule)
        .where(
            CreditPriceRule.scope == scope,
            CreditPriceRule.tenant_key == tenant_key,
            CreditPriceRule.platform_key == platform_key,
        )
        .limit(1)
    )
    if row is None:
        row = CreditPriceRule(
            scope=scope,
            tenant_id=tenant_id,
            tenant_key=tenant_key,
            platform_code=platform_code,
            platform_key=platform_key,
            credits_per_subtask=credits_per_subtask,
            status=status,
        )
        db.add(row)
    else:
        row.tenant_id = tenant_id
        row.platform_code = platform_code
        row.credits_per_subtask = credits_per_subtask
        row.status = status
    db.flush()
    # 2026-09-08 - 改价不再自动发条款；单价由销售线下沟通，避免客户/运营列表被 auto 声明刷屏
    return row


def scan_stale_reserves(db: Session) -> int:
    now = datetime.now()
    rows = list(
        db.scalars(
            select(TenantCreditLedger).where(
                TenantCreditLedger.entry_type == "reserve",
                TenantCreditLedger.reserve_expires_at.is_not(None),
                TenantCreditLedger.reserve_expires_at < now,
            )
        )
    )
    released = 0
    seen_refs: set[tuple[int, str]] = set()
    for row in rows:
        key = (row.tenant_id, row.ref_id or "")
        if not row.ref_id or key in seen_refs:
            continue
        seen_refs.add(key)
        if not _reserve_ref_is_orphan(db, row.tenant_id, row.ref_id):
            # 2026-09-07 - 任务还在跑/待结算时勿 TTL 整批释放，避免数字乱跳后补扣
            continue
        remaining = ref_reserve_remaining(db, row.tenant_id, row.ref_id)
        if remaining <= 0:
            continue
        release_reserve(
            db,
            tenant_id=row.tenant_id,
            ref_id=row.ref_id,
            amount=remaining,
            reason="预扣超时自动释放",
            # 2026-09-07 - TTL 清预扣勿打 batch_force_closed/batch_close，避免晚到格子被当成「运营强制关」漏扣
            detail_json={"stale": True},
        )
        released += 1
    if released:
        db.flush()
    return released


def _tasks_linked_to_reserve_ref(db: Session, tenant_id: int, ref_id: str) -> list[Any]:
    """调度 run + 打了 _geo_credit.reserve_ref 的近期任务。"""
    from sqlalchemy import String, cast

    from app.models.monitor import GeoMonitorScheduleRun, GeoMonitorTask

    found: dict[str, Any] = {}
    run = db.scalar(
        select(GeoMonitorScheduleRun)
        .where(
            GeoMonitorScheduleRun.tenant_id == tenant_id,
            GeoMonitorScheduleRun.schedule_key == ref_id,
        )
        .limit(1)
    )
    if run and run.task_id:
        task = db.scalar(
            select(GeoMonitorTask).where(
                GeoMonitorTask.task_id == run.task_id,
                GeoMonitorTask.deleted.is_(False),
            )
        )
        if task is not None:
            found[str(task.task_id)] = task

    # ponytail: JSON LIKE 近 40 条再核对 meta；全表扫成本高，漏网靠 schedule_run 主路径
    candidates = list(
        db.scalars(
            select(GeoMonitorTask)
            .where(
                GeoMonitorTask.tenant_id == tenant_id,
                GeoMonitorTask.deleted.is_(False),
                cast(GeoMonitorTask.raw_request_json, String).like(f"%{ref_id}%"),
            )
            .order_by(GeoMonitorTask.id.desc())
            .limit(40)
        )
    )
    for task in candidates:
        raw = task.raw_request_json if isinstance(task.raw_request_json, dict) else {}
        meta = raw.get("_geo_credit") if isinstance(raw.get("_geo_credit"), dict) else {}
        if str(meta.get("reserve_ref") or "").strip() == ref_id:
            found[str(task.task_id)] = task
    return list(found.values())


def _reserve_ref_is_orphan(db: Session, tenant_id: int, ref_id: str) -> bool:
    """无在途主任务、无自动重试等待、无未落账格子时才允许 TTL 清预扣。"""
    from app.models.monitor import GeoMonitorSubtask
    from app.services.monitor_auto_retry_service import subtask_failure_awaits_or_in_auto_retry

    terminal = {"completed", "partial_completed", "failed", "stopped"}
    tasks = _tasks_linked_to_reserve_ref(db, tenant_id, ref_id)
    if not tasks:
        return True
    for task in tasks:
        if str(getattr(task, "status", "") or "").lower() not in terminal:
            return False
        subtasks = list(
            db.scalars(select(GeoMonitorSubtask).where(GeoMonitorSubtask.task_id == task.task_id))
        )
        for sub in subtasks:
            if subtask_failure_awaits_or_in_auto_retry(sub):
                return False
            oid = str(getattr(sub, "subtask_id", "") or "").strip()
            if oid and not cell_credit_already_finalized(
                db, tenant_id=tenant_id, batch_ref=ref_id, origin_subtask_id=oid
            ):
                # 2026-09-07 - 主任务已终态但格子未 settle / 还在等重试时勿 TTL 退预扣
                return False
    return True


def ledger_row_to_dict(row: TenantCreditLedger, *, tenant_name: str | None = None) -> dict[str, Any]:
    payload = {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "tenant_name": tenant_name,
        "amount": float(row.amount),
        "balance_after": float(row.balance_after),
        "entry_type": row.entry_type,
        "ref_type": row.ref_type,
        "ref_id": row.ref_id,
        "platform_code": row.platform_code,
        "keyword": row.keyword,
        "window_key": row.window_key,
        "reason": row.reason,
        "created_at": row.created_at.isoformat(sep=" ", timespec="minutes"),
        "has_detail": bool(row.detail_json) or row.entry_type == "settle",
    }
    return payload


def resolve_ledger_subtasks(db: Session, tenant_id: int, row: TenantCreditLedger) -> list[dict[str, Any]]:
    """E2：流水关联子任务明细（detail_json / 调度 batch / 单子任务）。"""
    from app.models.monitor import GeoMonitorScheduleRun, GeoMonitorSubtask, GeoMonitorTask

    if isinstance(row.detail_json, dict):
        raw = row.detail_json.get("subtasks")
        if isinstance(raw, list) and raw:
            return [item for item in raw if isinstance(item, dict)]
    items: list[dict[str, Any]] = []
    if row.ref_id:
        run = db.scalar(
            select(GeoMonitorScheduleRun).where(
                GeoMonitorScheduleRun.tenant_id == tenant_id,
                GeoMonitorScheduleRun.schedule_key == row.ref_id,
            )
        )
        if run and run.task_id:
            for sub in db.scalars(select(GeoMonitorSubtask).where(GeoMonitorSubtask.task_id == run.task_id)):
                items.append(
                    {
                        "subtask_id": sub.subtask_id,
                        "platform_code": sub.platform,
                        "keyword": (sub.prompt or "")[:200],
                        "status": sub.status,
                        "credits": float(sub.amount or 0),
                    }
                )
            if items:
                return items
        sub = db.scalar(
            select(GeoMonitorSubtask)
            .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
            .where(GeoMonitorTask.tenant_id == tenant_id, GeoMonitorSubtask.subtask_id == row.ref_id)
        )
        if sub is not None:
            return [
                {
                    "subtask_id": sub.subtask_id,
                    "platform_code": sub.platform,
                    "keyword": (sub.prompt or "")[:200],
                    "status": sub.status,
                    "credits": float(sub.amount or 0),
                }
            ]
    return items


def get_ledger_entry_detail(
    db: Session,
    tenant_id: int,
    ledger_id: int,
    *,
    customer_visible_only: bool = False,
) -> dict[str, Any] | None:
    row = db.scalar(
        select(TenantCreditLedger).where(
            TenantCreditLedger.id == ledger_id,
            TenantCreditLedger.tenant_id == tenant_id,
        )
    )
    if row is None:
        return None
    # 2026-09-08 - 客户详情与列表同口径，禁止猜 id 读到预扣/释放
    if customer_visible_only and row.entry_type not in CUSTOMER_VISIBLE_LEDGER_TYPES:
        return None
    tenant = db.get(Tenant, tenant_id)
    data = ledger_row_to_dict(row, tenant_name=tenant.name if tenant else None)
    data["subtasks"] = resolve_ledger_subtasks(db, tenant_id, row)
    return data


def _ledger_tenant_filter_ids(
    db: Session,
    *,
    tenant_id: int | None = None,
    tenant_name: str | None = None,
) -> list[int] | None:
    """None=不限企业；[]=名称未命中。"""
    if tenant_id is not None:
        return [tenant_id]
    keyword = str(tenant_name or "").strip()
    if not keyword:
        return None
    return list(
        db.scalars(
            select(Tenant.id).where(
                Tenant.deleted.is_(False),
                func.lower(Tenant.name).like(f"%{keyword.lower()}%"),
            )
        )
    )


def list_credit_ledger(
    db: Session,
    *,
    tenant_id: int | None = None,
    tenant_name: str | None = None,
    page: int = 1,
    page_size: int = 20,
    exclude_internal: bool = False,
) -> dict[str, Any]:
    stmt = select(TenantCreditLedger).order_by(TenantCreditLedger.created_at.desc())
    tenant_ids = _ledger_tenant_filter_ids(db, tenant_id=tenant_id, tenant_name=tenant_name)
    if tenant_ids is not None:
        if not tenant_ids:
            return {"items": [], "page": page, "page_size": page_size}
        stmt = stmt.where(TenantCreditLedger.tenant_id.in_(tenant_ids))
    # 2026-08-27 - 客户算力流水 - 预扣/释放是内部账务，列表只展示充值/调整/扣费
    if exclude_internal:
        stmt = stmt.where(TenantCreditLedger.entry_type.in_(CUSTOMER_VISIBLE_LEDGER_TYPES))
    offset = (page - 1) * page_size
    rows = list(db.scalars(stmt.offset(offset).limit(page_size)))
    tenant_map = {
        t.id: t.name
        for t in db.scalars(select(Tenant).where(Tenant.id.in_([r.tenant_id for r in rows] or [0])))
    }
    balance_maps: dict[int, dict[int, Decimal]] = {}
    if exclude_internal and tenant_id is not None:
        balance_maps[tenant_id] = _recompute_customer_ledger_balances(db, tenant_id)
    items = []
    for row in rows:
        payload = ledger_row_to_dict(row, tenant_name=tenant_map.get(row.tenant_id))
        tenant_balances = balance_maps.get(row.tenant_id)
        if tenant_balances and row.id in tenant_balances:
            payload["balance_after"] = float(tenant_balances[row.id])
        items.append(payload)
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
    }


if __name__ == "__main__":
    assert cap_settle_credits(Decimal("2.5"), None) == Decimal("2")
