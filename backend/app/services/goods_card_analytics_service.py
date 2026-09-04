"""商品卡分析：从日常 GEO 监测子任务 raw_result_json.goods 聚合（对齐桌面范例口径）。"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.monitor_purpose import PURPOSE_GEO
from app.models.brand import BrandAsset, BrandCompetitor, BrandKeywordGroup
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.models.tenant import Tenant
from app.services.brand_service import collect_exposure_term_options, get_brand_asset, list_competitors
from app.services.media_proxy_service import public_screenshot_url
from app.services.molizhishu_catalog_service import get_supported_platform_catalog
from app.services.platform_selection import selection_codes

# 2026-08-25 - 短竞品名子串误命中（与桌面范例一致）
_COMPETITOR_FALSE_POSITIVE: dict[str, list[str]] = {
    "一本": ["一本全", "一本通"],
}

_COMPLETED = frozenset({"completed", "partial_completed"})


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s or "")).lower()


def hit_brand(title: str, terms: list[str]) -> str | None:
    t = _norm(title)
    for term in terms:
        if term and _norm(term) in t:
            return term
    return None


def hit_contains(title: str, terms: list[str]) -> str | None:
    t = _norm(title)
    for term in terms:
        if not term:
            continue
        nt = _norm(term)
        if nt not in t:
            continue
        blocked = _COMPETITOR_FALSE_POSITIVE.get(term) or _COMPETITOR_FALSE_POSITIVE.get(nt)
        if blocked and any(bp in t for bp in blocked):
            continue
        return term
    return None


def extract_goods(raw: Any) -> list[dict[str, Any]]:
    """从模力 raw_result_json 抽取商品卡列表。"""
    if not isinstance(raw, dict):
        return []
    goods = raw.get("goods")
    if goods is None:
        goods = raw.get("goodsList") or raw.get("goods_list")
    if not isinstance(goods, list):
        return []
    out: list[dict[str, Any]] = []
    for item in goods:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        thumb = str(
            item.get("thumbnail")
            or item.get("thumb")
            or item.get("image")
            or item.get("pic")
            or ""
        ).strip()
        price = str(item.get("price") or "").strip() or None
        mall = str(item.get("mall") or item.get("mallName") or item.get("shop") or "").strip() or None
        mall_platform = str(item.get("mall_platform") or item.get("mallPlatform") or mall or "").strip() or None
        product_id = str(
            item.get("mall_product_id") or item.get("mallProductId") or item.get("productId") or ""
        ).strip() or None
        url = str(item.get("url") or item.get("link") or "").strip() or None
        out.append(
            {
                "title": title,
                "thumbnail": thumb or None,
                "price": price,
                "mall": mall,
                "mall_platform": mall_platform,
                "mall_product_id": product_id,
                "url": url,
            }
        )
    return out


def resolve_goods_web_url(item: dict[str, Any]) -> tuple[str | None, str]:
    """返回 (可打开链接, kind=http|app|none)。"""
    raw = str(item.get("url") or "").strip()
    mall_platform = str(item.get("mall_platform") or item.get("mall") or "").strip()
    product_id = str(item.get("mall_product_id") or "").strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw, "http"
    plat = mall_platform.lower()
    if product_id and (
        plat in {"douyin", "jinritemai", "dy"}
        or mall_platform in {"抖音", "Douyin"}
        or raw.startswith("sslocal://")
    ):
        return (
            "https://haohuo.jinritemai.com/ecommerce/trade/detail/index.html"
            f"?id={product_id}&origin_type=604",
            "http",
        )
    if raw:
        return raw, "app"
    return None, "none"


def _pct(num: int, den: int) -> float | None:
    if den <= 0:
        return None
    return round(num / den * 100, 1)


def _fmt_rate(v: float | None) -> str:
    return "—" if v is None else f"{v}%"


def is_brand_prompt(prompt: str, company_terms: list[str]) -> bool:
    p = _norm(prompt)
    return any(t and _norm(t) in p for t in company_terms)


def _platform_name_map() -> dict[str, str]:
    return {
        str(item.get("code") or ""): str(item.get("name") or item.get("code") or "")
        for item in get_supported_platform_catalog()
    }


def _platform_cn(code: str) -> str:
    # 2026-09-02 - 命中明细平台列勿露 code - 走全站平台目录，避免 baiduai 等未进手写表
    return _platform_name_map().get(code, code)


def tenant_has_mobile_monitor_platform(db: Session, tenant_id: int) -> bool:
    groups = db.scalars(
        select(BrandKeywordGroup).where(
            BrandKeywordGroup.tenant_id == tenant_id,
            BrandKeywordGroup.deleted.is_(False),
            BrandKeywordGroup.status.is_(True),
        )
    )
    for group in groups:
        for code in selection_codes(group.platforms_json or []):
            if str(code).endswith("_mobile"):
                return True
    asset = get_brand_asset(db, tenant_id)
    if asset:
        for code in asset.monitored_platforms_json or []:
            if str(code).endswith("_mobile"):
                return True
    return False


def require_goods_card_enabled(db: Session, tenant_id: int) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise ValueError("企业不存在")
    if not bool(getattr(tenant, "goods_card_enabled", False)):
        raise PermissionError("该企业未开通商品卡分析")
    return tenant


def _brand_match_terms(db: Session, tenant_id: int, asset: BrandAsset | None) -> list[str]:
    terms: list[str] = []
    groups = [
        {
            "status": True,
            "exposure_terms": list(group.exposure_terms_json or []),
        }
        for group in db.scalars(
            select(BrandKeywordGroup).where(
                BrandKeywordGroup.tenant_id == tenant_id,
                BrandKeywordGroup.deleted.is_(False),
                BrandKeywordGroup.status.is_(True),
            )
        )
    ]
    terms.extend(collect_exposure_term_options(groups, asset=asset))
    if asset:
        for t in (asset.company_full_name, asset.brand_name):
            s = str(t or "").strip()
            if s:
                terms.append(s)
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        key = _norm(t)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def _competitor_map(competitors: list[BrandCompetitor]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for item in competitors:
        name = str(item.name or "").strip()
        if not name:
            continue
        terms = [name]
        short = str(item.short_name or "").strip()
        if short:
            terms.append(short)
        for alias in item.aliases_json or []:
            a = str(alias).strip()
            if a:
                terms.append(a)
        seen: set[str] = set()
        uniq: list[str] = []
        for t in terms:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        out[name] = uniq
    return out


def _load_completed_samples(
    db: Session,
    tenant_id: int,
    *,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """只取 purpose=geo 且完成的子任务；未完成不进样本。"""
    start_dt = datetime.combine(start_date, time.min)
    end_dt = datetime.combine(end_date, time.max)
    rows = db.execute(
        select(GeoMonitorSubtask, GeoMonitorTask)
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .where(
            GeoMonitorTask.tenant_id == tenant_id,
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.purpose == PURPOSE_GEO,
            GeoMonitorSubtask.status.in_(_COMPLETED),
            GeoMonitorSubtask.updated_at >= start_dt,
            GeoMonitorSubtask.updated_at <= end_dt,
        )
    ).all()

    asset = get_brand_asset(db, tenant_id)
    brand_terms = _brand_match_terms(db, tenant_id, asset)
    competitors = _competitor_map(list_competitors(db, tenant_id))

    samples: list[dict[str, Any]] = []
    for subtask, _task in rows:
        goods = extract_goods(subtask.raw_result_json)
        has_goods = len(goods) > 0
        brand_hits: list[dict[str, Any]] = []
        comp_hits: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for g in goods:
            title = str(g.get("title") or "")
            bt = hit_brand(title, brand_terms)
            item = {
                "term": bt,
                "title": title,
                "thumbnail": g.get("thumbnail"),
                "price": g.get("price"),
            }
            if bt:
                brand_hits.append({**item, "term": bt})
            for cname, terms in competitors.items():
                ct = hit_contains(title, terms)
                if ct:
                    comp_hits[cname].append({**item, "term": ct})
        samples.append(
            {
                "subtask_id": subtask.subtask_id,
                "platform": subtask.platform,
                "platform_cn": _platform_cn(subtask.platform),
                "prompt": subtask.prompt or "",
                "has_goods": has_goods,
                "goods_n": len(goods),
                "goods": goods,
                "brand_hits": brand_hits,
                "comp_hits": dict(comp_hits),
                "page_screenshot": public_screenshot_url(subtask.page_screenshot),
                "updated_at": subtask.updated_at.isoformat(sep=" ", timespec="seconds")
                if subtask.updated_at
                else None,
            }
        )
    return samples


def _build_diagnosis(
    *,
    brand_label: str,
    company_terms: list[str],
    category_hint: str,
    title_examples: list[str],
    by_plat: dict[str, dict[str, int]],
    by_prompt: dict[str, dict[str, int]],
    out_rate: float | None,
    brand_rate: float | None,
    unk_rate: float | None,
    top_comp: dict[str, Any] | None,
) -> dict[str, Any]:
    """规则诊断层（对齐桌面 _goods_card_diagnosis，返回纯文本 JSON）。"""
    brand_terms = [t for t in company_terms if str(t).strip()]
    generic_prompts: list[str] = []
    brand_prompts: list[str] = []
    for p in by_prompt:
        if is_brand_prompt(p, brand_terms):
            brand_prompts.append(p)
        else:
            generic_prompts.append(p)

    def _prompt_stats(prompt: str) -> dict[str, int]:
        return by_prompt.get(prompt) or {"total": 0, "goods": 0, "brand": 0}

    generic_totals = {"total": 0, "goods": 0, "brand": 0}
    brand_totals = {"total": 0, "goods": 0, "brand": 0}
    for p in generic_prompts:
        s = _prompt_stats(p)
        for k in generic_totals:
            generic_totals[k] += s[k]
    for p in brand_prompts:
        s = _prompt_stats(p)
        for k in brand_totals:
            brand_totals[k] += s[k]

    brand_word_rate = _pct(brand_totals["brand"], brand_totals["goods"])
    generic_brand_rate = _pct(generic_totals["brand"], generic_totals["goods"])
    loss_generics = [
        p for p in generic_prompts if _prompt_stats(p)["goods"] > 0 and _prompt_stats(p)["brand"] == 0
    ]
    loss_generic_label = loss_generics[0] if loss_generics else (
        generic_prompts[0] if generic_prompts else "通用推荐词"
    )
    brand_ok = (brand_word_rate or 0) > 0
    generic_miss = (generic_brand_rate or 0) == 0 and generic_totals["goods"] > 0
    comp_rate_v = float((top_comp or {}).get("rate") or 0) if top_comp else 0.0
    brand_v = float(brand_rate or 0)
    comp_leads = bool(
        top_comp and top_comp.get("rate") is not None and brand_rate is not None and comp_rate_v > brand_v
    )
    brand_leads = bool(
        top_comp and top_comp.get("rate") is not None and brand_rate is not None and brand_v >= comp_rate_v
    )

    if brand_ok and generic_miss:
        headline = (
            f"{brand_label}在品牌词问法下有一定商品卡承接，"
            f"但在「{loss_generic_label}」这类通用获客词中未进入商品卡，"
            f"当前主要损失发生在新客发现阶段。"
        )
    elif brand_ok:
        if brand_leads and top_comp:
            headline = (
                f"{brand_label}在已出卡样本中本品出卡率 {_fmt_rate(brand_rate)}，"
                f"高于最强竞品{top_comp.get('name')} {_fmt_rate(top_comp.get('rate'))}；"
                f"建议把优势继续扩到通用{category_hint}推荐词。"
            )
        else:
            headline = (
                f"{brand_label}在品牌词问法下商品卡承接较好；"
                f"建议继续把优势扩到通用{category_hint}推荐词。"
            )
    elif generic_miss:
        if brand_leads:
            headline = (
                f"{brand_label}整体本品出卡仍强于竞品，"
                f"但在通用推荐词「{loss_generic_label}」中缺位，新客发现词还有补强空间。"
            )
        else:
            headline = (
                f"{brand_label}在通用推荐词「{loss_generic_label}」中缺位，"
                f"竞品更容易先拿到商品卡货架，新客发现阶段损失明显。"
            )
    else:
        headline = (
            f"{brand_label}商品卡覆盖偏弱，需同时补强品牌词承接与通用{category_hint}获客词。"
        )

    opp_text = (
        f"AI 商品卡出卡率 {_fmt_rate(out_rate)}，说明{category_hint}品类在 AI 端有购物流量入口。"
        if (out_rate or 0) >= 50
        else f"部分问法/平台已出现商品卡，{category_hint}品类具备 AI 购物入口潜力。"
    )

    comp_name = str((top_comp or {}).get("name") or "竞品")
    brand_rate_s = _fmt_rate(brand_rate)
    comp_rate = _fmt_rate((top_comp or {}).get("rate"))
    if generic_miss and comp_leads:
        risk_title, risk_text = "风险", (
            f"通用推荐词{brand_label}缺位，{comp_name}出卡率 {comp_rate} 高于本品 {brand_rate_s}；竞品先占位推荐卡。"
        )
    elif generic_miss and brand_leads:
        risk_title, risk_text = "关注点", (
            f"通用词「{loss_generic_label}」上本品未出卡；整体本品出卡率 {brand_rate_s} 仍高于 {comp_name} {comp_rate}，"
            f"缺口在新客发现词，不是全面被抢货架。"
        )
    elif generic_miss:
        risk_title, risk_text = "风险", (
            f"通用推荐词「{loss_generic_label}」上本品缺位，新客发现阶段容易把货架让给其他品牌。"
        )
    elif comp_leads:
        risk_title, risk_text = "风险", f"{comp_name}出卡率 {comp_rate} 高于本品 {brand_rate_s}，货架被竞品挤压。"
    elif brand_leads:
        risk_title, risk_text = "关注点", (
            f"本品出卡率 {brand_rate_s} 高于最强竞品 {comp_name} {comp_rate}，短期被挤占风险不高；"
            f"优先把优势扩到通用获客词即可。"
        )
    else:
        risk_title, risk_text = "关注点", (
            f"竞品出卡尚少，暂未见明显挤压；仍建议盯紧通用获客词，避免后续被{comp_name}等品牌抢先占位。"
        )

    plat_scores: list[tuple[str, float, int]] = []
    for plat, b in by_plat.items():
        if b["total"] <= 0:
            continue
        br = _pct(b["brand"], b["goods"]) or 0.0
        plat_scores.append((plat, br, b["brand"]))
    plat_scores.sort(key=lambda x: (x[1], x[2]), reverse=True)
    strengthen: list[str] = []
    consolidate: list[str] = []
    overall_br = brand_rate or 0.0
    for plat, br, _ in plat_scores:
        label = _platform_cn(plat)
        if br < overall_br or br == 0:
            strengthen.append(label)
        elif br >= overall_br and br > 0:
            consolidate.append(label)
    if not strengthen and plat_scores:
        strengthen = [_platform_cn(plat_scores[-1][0])]
    if not consolidate and plat_scores:
        consolidate = [_platform_cn(plat_scores[0][0])]
    priority_text = (
        f"优先补强：{'、'.join(strengthen[:3]) or '—'}；继续巩固：{'、'.join(consolidate[:2]) or '—'}。"
    )

    title_ex = "」「".join(title_examples[:2]) if title_examples else brand_label
    generic_ex = " / ".join(generic_prompts[:2] or ["通用推荐词"])
    actions = [
        f"补齐商品标题里的品牌标准名、核心露出词，例如「{title_ex}」。",
        f"建立「{generic_ex}」这类非品牌词内容资产，覆盖通用获客场景。",
        f"优化官方旗舰店、商品详情页、百科/问答/测评内容，让 AI 更容易把{brand_label}识别成{category_hint}候选商品。",
    ]
    if (unk_rate or 0) >= 25:
        actions.append(f"扩充竞品和别名词库，降低「未识别商品 {_fmt_rate(unk_rate)}」。")
    else:
        actions.append("持续维护竞品与别名词库，减少商品卡标题未识别。")

    return {
        "headline": headline,
        "opportunity": opp_text,
        "risk_title": risk_title,
        "risk_text": risk_text,
        "priority_text": priority_text,
        "actions": actions,
    }


def build_goods_card_summary(
    db: Session,
    tenant_id: int,
    *,
    days: int = 7,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    """汇总 KPI + 诊断 + 三表 + 命中明细（一期单接口）。"""
    require_goods_card_enabled(db, tenant_id)
    today = date.today()
    end = end_date or today
    start = start_date or (end - timedelta(days=max(days, 1) - 1))
    if start > end:
        start, end = end, start

    has_mobile = tenant_has_mobile_monitor_platform(db, tenant_id)
    asset = get_brand_asset(db, tenant_id)
    brand_label = (
        str((asset.brand_name if asset else None) or (asset.company_full_name if asset else None) or "本品牌").strip()
        or "本品牌"
    )
    brand_terms = _brand_match_terms(db, tenant_id, asset)
    competitors = _competitor_map(list_competitors(db, tenant_id))
    category_hint = "本品类"
    if asset and asset.product_keywords_json:
        category_hint = str(asset.product_keywords_json[0] or category_hint)
    title_examples = [f"{brand_label}"]
    if brand_terms:
        title_examples = [brand_terms[0], *(brand_terms[1:2])]

    all_completed = _load_completed_samples(db, tenant_id, start_date=start, end_date=end)
    ever_platforms = sorted({s["platform"] for s in all_completed if s["has_goods"]})
    completed = [s for s in all_completed if s["platform"] in ever_platforms]
    n = len(completed)
    goods_n_tasks = sum(1 for s in completed if s["has_goods"])
    brand_n = sum(1 for s in completed if s["brand_hits"])
    out_rate = _pct(goods_n_tasks, n)
    brand_rate = _pct(brand_n, goods_n_tasks)

    brand_hit_row = {"name": brand_label, "is_brand": True, "hit": brand_n, "rate": brand_rate}
    comp_rows: list[dict[str, Any]] = []
    for cname in competitors:
        c_n = sum(1 for s in completed if s["comp_hits"].get(cname))
        comp_rows.append({"name": cname, "is_brand": False, "hit": c_n, "rate": _pct(c_n, goods_n_tasks)})
    comp_rows.sort(key=lambda r: (-(r["rate"] or -1), -r["hit"], r["name"]))
    top_comp = next((r for r in comp_rows if r["hit"] > 0), None)
    gap_value = None
    gap_note = "暂无竞品出卡"
    if top_comp and brand_rate is not None and top_comp.get("rate") is not None:
        gap_value = round(brand_rate - float(top_comp["rate"]), 1)
        gap_note = f"相对 {top_comp['name']}"

    by_plat: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "goods": 0, "brand": 0})
    by_prompt: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "goods": 0, "brand": 0})
    for s in completed:
        b = by_plat[s["platform"]]
        b["total"] += 1
        if s["has_goods"]:
            b["goods"] += 1
        if s["brand_hits"]:
            b["brand"] += 1
        p = str(s["prompt"] or "—")
        bp = by_prompt[p]
        bp["total"] += 1
        if s["has_goods"]:
            bp["goods"] += 1
        if s["brand_hits"]:
            bp["brand"] += 1

    prompt_rows = [
        {
            "prompt": prompt,
            "total": b["total"],
            "goods": b["goods"],
            "out_rate": _pct(b["goods"], b["total"]),
            "brand": b["brand"],
            "brand_rate": _pct(b["brand"], b["goods"]),
            "is_brand_prompt": is_brand_prompt(prompt, brand_terms),
        }
        for prompt, b in sorted(by_prompt.items(), key=lambda x: (-x[1]["goods"], -x[1]["total"], x[0]))
    ]
    platform_rows = [
        {
            "platform": plat,
            "platform_cn": _platform_cn(plat),
            "total": b["total"],
            "goods": b["goods"],
            "out_rate": _pct(b["goods"], b["total"]),
            "brand": b["brand"],
            "brand_rate": _pct(b["brand"], b["goods"]),
        }
        for plat, b in sorted(by_plat.items(), key=lambda x: (-x[1]["goods"], -x[1]["total"], x[0]))
    ]

    drill_goods: list[dict[str, Any]] = []
    for s in completed:
        if not s["has_goods"]:
            continue
        for g in s["goods"]:
            title = str(g.get("title") or "")
            brand_hit = hit_brand(title, brand_terms)
            comps: list[str] = []
            for cname, terms in competitors.items():
                ct = hit_contains(title, terms)
                if ct:
                    comps.append(cname if _norm(ct) == _norm(cname) else f"{cname}({ct})")
            href, link_kind = resolve_goods_web_url(g)
            drill_goods.append(
                {
                    "subtask_id": s["subtask_id"],
                    "platform": s["platform"],
                    "platform_cn": s["platform_cn"],
                    "prompt": s["prompt"],
                    "title": title or "—",
                    "thumbnail": g.get("thumbnail"),
                    "price": g.get("price"),
                    "mall": g.get("mall"),
                    "url": href,
                    "link_kind": link_kind,
                    "brand_hit": bool(brand_hit),
                    "brand_term": brand_hit,
                    "comp_hits": comps,
                    "page_screenshot": s["page_screenshot"],
                    "updated_at": s["updated_at"],
                }
            )

    unk_n = sum(1 for d in drill_goods if not d["brand_hit"] and not d["comp_hits"])
    unk_rate = _pct(unk_n, len(drill_goods))

    empty_reason = None
    if not all_completed:
        empty_reason = "no_completed_samples"
    elif not ever_platforms:
        # 无出卡：无手机端配置时优先提示开通手机端；有配置则提示暂无商品卡
        empty_reason = "no_mobile_platform" if not has_mobile else "no_goods"

    diagnosis = None
    if completed and ever_platforms:
        diagnosis = _build_diagnosis(
            brand_label=brand_label,
            company_terms=brand_terms or [brand_label],
            category_hint=category_hint,
            title_examples=title_examples,
            by_plat=dict(by_plat),
            by_prompt=dict(by_prompt),
            out_rate=out_rate,
            brand_rate=brand_rate,
            unk_rate=unk_rate,
            top_comp=top_comp,
        )

    return {
        "tenant_id": tenant_id,
        "brand_label": brand_label,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "has_mobile_platform": has_mobile,
        "empty_reason": empty_reason,
        "denominator_platforms": ever_platforms,
        "denominator_platform_labels": [_platform_cn(p) for p in ever_platforms],
        "sample_total": n,
        "goods_task_total": goods_n_tasks,
        "kpi": {
            "out_rate": out_rate,
            "out_note": f"{goods_n_tasks}/{n} 条含商品卡",
            "brand_rate": brand_rate,
            "brand_note": f"{brand_n}/{goods_n_tasks} · 已出卡中标题露出公司名/露出词",
            "gap_vs_top_comp": gap_value,
            "gap_note": gap_note,
            "unknown_rate": unk_rate,
            "unknown_note": f"{unk_n}/{len(drill_goods)} 条未命中本品牌/竞品",
        },
        "diagnosis": diagnosis,
        "brand_competitor_rows": [brand_hit_row, *comp_rows],
        "prompt_rows": prompt_rows,
        "platform_rows": platform_rows,
        "hits": drill_goods,
        "stats_note": (
            "出卡率 = 含非空 goods 的完成子任务 ÷ 分母平台上的完成子任务。"
            "分母仅含历史上曾出过卡的平台。本品/竞品出卡率 = 标题命中该品牌的出卡子任务 ÷ 已出卡子任务。"
            "仅统计日常监测（不含品牌词任务）。"
        ),
    }
