from __future__ import annotations

import json
import re
import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.lead_diagnosis_config import clamp_lead_schedule_days
from app.core.lead_diagnosis_prompts import normalize_lead_prompts
from app.core.masking import mask_phone
from app.models.h5_diagnosis_order import H5DiagnosisOrder
from app.schemas.lead_diagnosis import normalize_brand_aliases
from app.services.lead_diagnosis_service import create_lead_diagnosis_from_h5_order
from app.services.molizhishu_catalog_service import filter_submittable_platforms
from app.services.system_config_service import get_runtime_config
from app.services.wechat_pay_service import WechatPayError, build_jsapi_pay_params, create_jsapi_prepay

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


def get_h5_diagnosis_public_config(db: Session) -> dict[str, Any]:
    price_fen = int(get_runtime_config("h5_diagnosis_price_fen", db))
    schedule_days = clamp_lead_schedule_days(int(get_runtime_config("h5_diagnosis_schedule_days", db)))
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
        "schedule_slots_per_day": 3,
        "schedule_total": schedule_days * 3,
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
    wechat_id: str,
    contact_phone: str,
    brand_name: str,
    prompts: list[str],
    brand_aliases: str = "",
    industry: str = "",
    product_focus: str = "",
    website_url: str = "",
    competitors: str = "",
) -> dict[str, Any]:
    cfg = get_h5_diagnosis_public_config(db)
    if not cfg["enabled"]:
        raise ValueError("H5 付费诊断暂未开放")
    if not openid:
        raise ValueError("请在微信内打开并完成授权")
    normalized_prompts = normalize_lead_prompts(prompts)
    if not normalized_prompts:
        raise ValueError("请至少填写 1 条检测问题")

    brand = brand_name.strip()
    wx_id = wechat_id.strip()
    phone = contact_phone.strip()
    if not brand:
        raise ValueError("请填写品牌名称")
    if not wx_id:
        raise ValueError("请填写微信号")
    if not re.fullmatch(r"1\d{10}", phone):
        raise ValueError("请填写正确的手机号")

    alias_list = _split_csv_terms(brand_aliases, max_items=20)
    competitor_list = _split_csv_terms(competitors, max_items=10)

    out_trade_no = _gen_out_trade_no()
    order = H5DiagnosisOrder(
        out_trade_no=out_trade_no,
        openid=openid,
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

    try:
        prepay_id = create_jsapi_prepay(
            out_trade_no=out_trade_no,
            openid=openid,
            amount_fen=order.amount_fen,
            description="艾迪亚GEO售前诊断",
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
