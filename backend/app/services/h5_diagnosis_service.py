from __future__ import annotations

import json
import re
import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.lead_diagnosis_config import (
    H5_SCHEDULE_SLOTS_PER_DAY,
    clamp_h5_schedule_runs,
    h5_runs_to_schedule_days,
)
from app.core.lead_diagnosis_prompts import normalize_lead_prompts
from app.core.masking import mask_phone
from app.models.h5_diagnosis_order import H5DiagnosisOrder
from app.schemas.lead_diagnosis import normalize_brand_aliases
from app.services.lead_diagnosis_service import create_lead_diagnosis_from_h5_order
from app.services.molizhishu_catalog_service import filter_submittable_platforms
from app.services.system_config_service import get_runtime_config
from app.services.wechat_pay_service import WechatPayError, build_jsapi_pay_params, create_jsapi_prepay, create_native_code_url

_H5_OPENID_COOKIE = "geo_h5_wx_openid"
_DEFAULT_PLATFORMS = ["doubao", "deepseek"]


def _split_csv_terms(raw: str, *, max_items: int = 10) -> list[str]:
    return normalize_brand_aliases(raw, max_items=max_items)


def parse_platform_list(raw: Any) -> list[str]:
    if isinstance(raw, list):
        text_items = [str(item).strip() for item in raw]
    else:
        text = str(raw or "").strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                text_items = [str(item).strip() for item in parsed]
            else:
                text_items = re.split(r"[,，;；\s]+", text)
        except json.JSONDecodeError:
            text_items = re.split(r"[,，;；\s]+", text)
    return filter_submittable_platforms([item for item in text_items if item])


def _resolve_h5_schedule_runs(db: Session) -> int:
    # 2026-08-31 - 优先读监测次数；旧库仅有天数时回落 days×3
    raw_runs = get_runtime_config("h5_diagnosis_schedule_runs", db)
    if raw_runs not in (None, ""):
        try:
            return clamp_h5_schedule_runs(int(raw_runs))
        except (TypeError, ValueError):
            pass
    try:
        days = int(get_runtime_config("h5_diagnosis_schedule_days", db))
    except (TypeError, ValueError):
        days = 3
    return clamp_h5_schedule_runs(max(1, days) * H5_SCHEDULE_SLOTS_PER_DAY)


def get_h5_diagnosis_public_config(db: Session) -> dict[str, Any]:
    price_fen = int(get_runtime_config("h5_diagnosis_price_fen", db))
    schedule_runs = _resolve_h5_schedule_runs(db)
    schedule_days = h5_runs_to_schedule_days(schedule_runs)
    platforms = parse_platform_list(get_runtime_config("h5_diagnosis_platforms", db))
    if not platforms:
        platforms = list(_DEFAULT_PLATFORMS)
    enabled_raw = get_runtime_config("h5_diagnosis_enabled", db)
    enabled = bool(enabled_raw) if not isinstance(enabled_raw, str) else enabled_raw.lower() not in {"0", "false", "no", "off"}
    return {
        "enabled": enabled,
        "price_fen": price_fen,
        "price_yuan": round(price_fen / 100, 2),
        "schedule_days": schedule_days,
        "schedule_runs": schedule_runs,
        "schedule_slots_per_day": H5_SCHEDULE_SLOTS_PER_DAY,
        "schedule_total": schedule_runs,
        "platforms": platforms,
        "max_prompts": 5,
        "min_prompts": 1,
        "oauth_required": not settings.wechat_pay_dev_mode,
        "dev_mode": settings.wechat_pay_dev_mode,
    }


def _gen_out_trade_no() -> str:
    return f"H5{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{secrets.token_hex(4).upper()}"[:32]


def create_h5_diagnosis_order(
    db: Session,
    *,
    openid: str,
    wechat_id: str = "",
    contact_phone: str,
    brand_name: str,
    prompts: list[str],
    brand_aliases: str = "",
    industry: str = "",
    product_focus: str = "",
    website_url: str = "",
    competitors: str = "",
    pay_trade_type: str = "jsapi",
    pay_channel: str = "wechat",
) -> dict[str, Any]:
    cfg = get_h5_diagnosis_public_config(db)
    if not cfg["enabled"]:
        raise ValueError("H5 付费诊断暂未开放")
    trade_type = str(pay_trade_type or "jsapi").strip().lower() or "jsapi"
    channel = str(pay_channel or "wechat").strip().lower() or "wechat"
    if channel != "wechat":
        raise ValueError("暂仅支持微信支付")
    if trade_type not in {"jsapi", "native"}:
        raise ValueError("不支持的支付方式")
    # 2026-08-31 - B3：Native 扫码无需 openid；JSAPI 仍必须微信授权
    if trade_type == "jsapi" and not openid:
        raise ValueError("请在微信内打开并完成授权")
    normalized_prompts = normalize_lead_prompts(prompts)
    if not normalized_prompts:
        raise ValueError("请至少填写 1 条检测问题")

    brand = brand_name.strip()
    phone = contact_phone.strip()
    # 2026-08-31 - H5 不再收集微信号，库字段仍非空，落空串
    wx_id = (wechat_id or "").strip()
    if not brand:
        raise ValueError("请填写品牌名称")
    if not re.fullmatch(r"1\d{10}", phone):
        raise ValueError("请填写正确的手机号")

    alias_list = _split_csv_terms(brand_aliases, max_items=20)
    competitor_list = _split_csv_terms(competitors, max_items=10)

    out_trade_no = _gen_out_trade_no()
    order_openid = openid if trade_type == "jsapi" else (openid or "native_pc")
    order = H5DiagnosisOrder(
        out_trade_no=out_trade_no,
        openid=order_openid,
        wechat_id=wx_id,
        contact_phone=phone,
        brand_name=brand,
        form_json={
            # 2026-08-31 - H5 对齐 PC 品牌字段：别名/竞品写入 form_json，履约时落 lead
            "industry": industry.strip(),
            "product_focus": product_focus.strip(),
            "website_url": website_url.strip(),
            "brand_aliases": alias_list,
            "competitors": competitor_list,
            "schedule_runs": int(cfg["schedule_runs"]),
            "pay_channel": channel,
            "pay_trade_type": trade_type,
        },
        prompts_json=normalized_prompts,
        platforms_json=list(cfg["platforms"]),
        schedule_days=int(cfg["schedule_days"]),
        amount_fen=int(cfg["price_fen"]),
        status="pending",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    description = "GEO售前诊断"
    try:
        if trade_type == "native":
            code_url = create_native_code_url(
                out_trade_no=out_trade_no,
                amount_fen=order.amount_fen,
                description=description,
            )
            order.prepay_id = code_url[:64]
            db.commit()
            result: dict[str, Any] = {
                "out_trade_no": out_trade_no,
                "amount_fen": order.amount_fen,
                "pay_channel": channel,
                "pay_trade_type": trade_type,
                "code_url": code_url,
                "pay_params": None,
            }
            if settings.wechat_pay_dev_mode:
                result["dev_auto_paid"] = True
            return result

        prepay_id = create_jsapi_prepay(
            out_trade_no=out_trade_no,
            openid=openid,
            amount_fen=order.amount_fen,
            description=description,
        )
    except WechatPayError as exc:
        order.status = "failed"
        db.commit()
        raise ValueError(str(exc)) from exc

    order.prepay_id = prepay_id
    db.commit()

    pay_params = build_jsapi_pay_params(prepay_id)
    if settings.wechat_pay_dev_mode:
        pay_params["devAutoPaid"] = True

    return {
        "out_trade_no": out_trade_no,
        "amount_fen": order.amount_fen,
        "pay_channel": channel,
        "pay_trade_type": trade_type,
        "code_url": None,
        "pay_params": pay_params,
    }


def mark_h5_order_paid_dev(db: Session, out_trade_no: str) -> dict[str, Any]:
    if not settings.wechat_pay_dev_mode:
        raise ValueError("仅开发模式可用")
    return fulfill_h5_order_paid(db, out_trade_no=out_trade_no, wx_transaction_id=f"DEV-{out_trade_no}")


def fulfill_h5_order_paid(
    db: Session,
    *,
    out_trade_no: str,
    wx_transaction_id: str,
) -> dict[str, Any]:
    order = db.scalar(select(H5DiagnosisOrder).where(H5DiagnosisOrder.out_trade_no == out_trade_no))
    if order is None:
        raise ValueError("订单不存在")
    if order.status == "paid" and order.lead_diagnosis_id:
        return get_h5_order_status(db, out_trade_no)

    order.status = "paid"
    order.wx_transaction_id = wx_transaction_id
    order.paid_at = datetime.utcnow()

    if not order.lead_diagnosis_id:
        lead_id = create_lead_diagnosis_from_h5_order(db, order)
        order.lead_diagnosis_id = lead_id

    db.commit()
    return get_h5_order_status(db, out_trade_no)


def get_h5_order_status(db: Session, out_trade_no: str) -> dict[str, Any]:
    order = db.scalar(select(H5DiagnosisOrder).where(H5DiagnosisOrder.out_trade_no == out_trade_no))
    if order is None:
        raise ValueError("订单不存在")
    return {
        "out_trade_no": order.out_trade_no,
        "status": order.status,
        "brand_name": order.brand_name,
        "amount_fen": order.amount_fen,
        "lead_diagnosis_id": order.lead_diagnosis_id,
        "paid_at": order.paid_at.isoformat(sep=" ", timespec="seconds") if order.paid_at else None,
        "contact_phone_masked": mask_phone(order.contact_phone),
    }


def mask_openid(openid: str) -> str:
    text = str(openid or "").strip()
    if len(text) <= 8:
        return "***"
    return f"{text[:4]}***{text[-4:]}"


def require_h5_order_admin_access(db: Session, current, action: str = "can_export") -> None:
    from app.services.menu_permission_service import has_identity_menu_permission

    if current.identity.identity_type != "PLATFORM":
        raise PermissionError("仅平台运营端可查看 H5 订单")
    if not has_identity_menu_permission(db, current.identity.id, "platform.h5_diagnosis_orders", action):
        raise PermissionError("当前身份无 H5 订单权限")


def list_h5_diagnosis_orders(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    keyword: str | None = None,
) -> dict[str, Any]:
    """平台后台：H5 付费订单列表。"""
    page = max(1, int(page or 1))
    page_size = max(1, min(100, int(page_size or 20)))
    stmt = select(H5DiagnosisOrder)
    status_text = str(status or "").strip().lower()
    if status_text:
        stmt = stmt.where(H5DiagnosisOrder.status == status_text)
    kw = str(keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        stmt = stmt.where(
            (H5DiagnosisOrder.brand_name.like(like))
            | (H5DiagnosisOrder.contact_phone.like(like))
            | (H5DiagnosisOrder.out_trade_no.like(like))
        )
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(
        stmt.order_by(H5DiagnosisOrder.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    items = []
    for order in rows:
        form = order.form_json if isinstance(order.form_json, dict) else {}
        prompts = order.prompts_json if isinstance(order.prompts_json, list) else []
        platforms = order.platforms_json if isinstance(order.platforms_json, list) else []
        aliases = form.get("brand_aliases") if isinstance(form.get("brand_aliases"), list) else []
        competitors = form.get("competitors") if isinstance(form.get("competitors"), list) else []
        items.append(
            {
                "id": order.id,
                "out_trade_no": order.out_trade_no,
                "brand_name": order.brand_name,
                # 2026-08-31 - 运营后台点名要明文手机号；masked 字段保留兼容
                "contact_phone": order.contact_phone,
                "contact_phone_masked": mask_phone(order.contact_phone),
                "wechat_id": order.wechat_id or "",
                "amount_fen": order.amount_fen,
                "amount_yuan": round(int(order.amount_fen or 0) / 100, 2),
                "status": order.status,
                "pay_channel": str(form.get("pay_channel") or "wechat"),
                "pay_trade_type": str(form.get("pay_trade_type") or ("jsapi" if order.openid and order.openid != "native_pc" else "native")),
                "openid_masked": mask_openid(order.openid),
                "wx_transaction_id": order.wx_transaction_id,
                "lead_diagnosis_id": order.lead_diagnosis_id,
                "paid_at": order.paid_at.isoformat(sep=" ", timespec="seconds") if order.paid_at else None,
                "created_at": order.created_at.isoformat(sep=" ", timespec="seconds") if order.created_at else None,
                # 2026-08-31 - 抽屉看填报：列表一次带齐，避免再开详情接口
                "industry": str(form.get("industry") or ""),
                "product_focus": str(form.get("product_focus") or ""),
                "website_url": str(form.get("website_url") or ""),
                "brand_aliases": aliases,
                "competitors": competitors,
                "schedule_runs": int(form.get("schedule_runs") or 0) or None,
                "schedule_days": int(order.schedule_days or 0),
                "platforms": platforms,
                "prompts": [str(p) for p in prompts],
            }
        )
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }
