"""H5 付费诊断：用户自助结果页（进度 / 报告摘要 / token / ready 短信）。

2026-09-01 - 方案 A：结果页 + 阿里云短信短链
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.masking import mask_phone
from app.models.h5_diagnosis_order import H5DiagnosisOrder
from app.models.lead_diagnosis import LeadDiagnosis
from app.services.lead_diagnosis_service import (
    _completed_planned_run_count,
    _schedule_total_count,
)

logger = logging.getLogger(__name__)

_RESULT_COOKIE = "geo_h5_result_token"


def result_cookie_name() -> str:
    return _RESULT_COOKIE


def _h5_public_origin() -> str:
    base = str(settings.wechat_h5_base_url or "https://www.aieokj.com/h5/diagnosis/").strip()
    if "/h5/diagnosis" in base:
        return base.split("/h5/diagnosis")[0].rstrip("/") or "https://www.aieokj.com"
    return base.rstrip("/") or "https://www.aieokj.com"


def build_h5_result_page_url(*, out_trade_no: str, token: str) -> str:
    origin = _h5_public_origin()
    return f"{origin}/h5/diagnosis/result?out_trade_no={out_trade_no}&t={token}"


def ensure_h5_result_access_token(db: Session, order: H5DiagnosisOrder, *, force_new: bool = False) -> str:
    """保证订单有可用结果 token；返回明文 token。"""
    now = datetime.utcnow()
    days = max(1, int(settings.h5_result_token_days or 30))
    if (
        not force_new
        and order.result_access_token
        and order.result_token_expires_at
        and order.result_token_expires_at > now
    ):
        return str(order.result_access_token)
    token = secrets.token_urlsafe(24)[:48]
    order.result_access_token = token
    order.result_token_expires_at = now + timedelta(days=days)
    db.add(order)
    db.commit()
    db.refresh(order)
    return token


def _order_by_out_trade_no(db: Session, out_trade_no: str) -> H5DiagnosisOrder:
    order = db.scalar(
        select(H5DiagnosisOrder).where(H5DiagnosisOrder.out_trade_no == str(out_trade_no or "").strip())
    )
    if order is None:
        raise ValueError("订单不存在")
    return order


def assert_h5_result_access(
    db: Session,
    order: H5DiagnosisOrder,
    *,
    token: str | None = None,
    openid: str | None = None,
    phone_tail: str | None = None,
) -> None:
    """结果页鉴权：短链 token / 下单 openid / 手机号后四位（仅已支付）。"""
    if order.status != "paid":
        raise PermissionError("订单未支付，暂无结果可查看")

    token_text = str(token or "").strip()
    if token_text and order.result_access_token and token_text == order.result_access_token:
        if order.result_token_expires_at and order.result_token_expires_at < datetime.utcnow():
            raise PermissionError("查看链接已过期，请用手机号后四位重新获取")
        return

    openid_text = str(openid or "").strip()
    if openid_text and openid_text == str(order.openid or "").strip() and not str(order.openid).startswith("native_"):
        return

    tail = str(phone_tail or "").strip()
    phone = str(order.contact_phone or "").strip()
    if len(tail) == 4 and phone.endswith(tail):
        return

    raise PermissionError("无权查看该诊断结果，请使用下单手机号验证")


def unlock_h5_result_by_phone_tail(
    db: Session,
    *,
    out_trade_no: str,
    phone_tail: str,
) -> dict[str, Any]:
    order = _order_by_out_trade_no(db, out_trade_no)
    assert_h5_result_access(db, order, phone_tail=phone_tail)
    token = ensure_h5_result_access_token(db, order)
    return {
        "out_trade_no": order.out_trade_no,
        "access_token": token,
        "result_url": build_h5_result_page_url(out_trade_no=order.out_trade_no, token=token),
        "expires_at": order.result_token_expires_at.isoformat(sep=" ", timespec="seconds")
        if order.result_token_expires_at
        else None,
    }


def unlock_h5_result_by_phone(db: Session, *, contact_phone: str) -> dict[str, Any]:
    """用完整下单手机号解锁：取该号最近一笔已支付订单。"""
    phone = str(contact_phone or "").strip()
    if not re.fullmatch(r"1\d{10}", phone):
        raise ValueError("请填写正确的11位手机号")
    order = db.scalar(
        select(H5DiagnosisOrder)
        .where(
            H5DiagnosisOrder.contact_phone == phone,
            H5DiagnosisOrder.status == "paid",
        )
        .order_by(H5DiagnosisOrder.id.desc())
    )
    if order is None:
        raise ValueError("未找到该手机号的已支付诊断订单")
    token = ensure_h5_result_access_token(db, order)
    return {
        "out_trade_no": order.out_trade_no,
        "access_token": token,
        "result_url": build_h5_result_page_url(out_trade_no=order.out_trade_no, token=token),
        "expires_at": order.result_token_expires_at.isoformat(sep=" ", timespec="seconds")
        if order.result_token_expires_at
        else None,
    }


def get_h5_diagnosis_result(
    db: Session,
    *,
    out_trade_no: str,
    token: str | None = None,
    openid: str | None = None,
    phone_tail: str | None = None,
) -> dict[str, Any]:
    order = _order_by_out_trade_no(db, out_trade_no)
    assert_h5_result_access(db, order, token=token, openid=openid, phone_tail=phone_tail)

    lead: LeadDiagnosis | None = None
    if order.lead_diagnosis_id:
        lead = db.scalar(
            select(LeadDiagnosis)
            .where(LeadDiagnosis.id == int(order.lead_diagnosis_id), LeadDiagnosis.deleted.is_(False))
            .options(selectinload(LeadDiagnosis.runs))
        )

    total = int(_schedule_total_count(lead)) if lead is not None else int(
        (order.form_json or {}).get("schedule_runs") or order.schedule_days * 3 or 9
    )
    completed = int(_completed_planned_run_count(lead)) if lead is not None else 0
    lead_status = str(lead.status) if lead is not None else ("pending" if order.status == "paid" else order.status)
    ready = lead_status == "ready"

    summary: dict[str, Any] | None = None
    if ready and lead is not None:
        # 直接读聚合 JSON，避免再走 get_lead_diagnosis（可能触发同步副作用）
        result = lead.diagnosis_result_json if isinstance(lead.diagnosis_result_json, dict) else {}
        diagnosis = result.get("diagnosis") if isinstance(result.get("diagnosis"), dict) else {}
        kpis = result.get("kpis") if isinstance(result.get("kpis"), dict) else {}
        platforms = result.get("platforms") if isinstance(result.get("platforms"), list) else []
        summary = {
            "health_score": lead.health_score or diagnosis.get("health_score") or kpis.get("health_score"),
            "mention_rate": kpis.get("mention_rate"),
            "avg_rank": kpis.get("avg_rank"),
            "headline": diagnosis.get("headline") or diagnosis.get("summary") or diagnosis.get("title"),
            "bullets": list(diagnosis.get("bullets") or diagnosis.get("points") or [])[:6],
            "platforms": [
                {
                    "platform": row.get("platform"),
                    "mention_rate": row.get("mention_rate"),
                    "avg_rank": row.get("avg_rank"),
                    "sample_count": row.get("completed") or row.get("sample_count"),
                }
                for row in platforms
                if isinstance(row, dict)
            ][:12],
            "prompts": list(lead.prompts_json or order.prompts_json or [])[:8],
        }

    token_out = None
    if token and order.result_access_token and token == order.result_access_token:
        token_out = order.result_access_token
    elif openid or phone_tail:
        token_out = ensure_h5_result_access_token(db, order)

    return {
        "out_trade_no": order.out_trade_no,
        "order_status": order.status,
        "brand_name": order.brand_name,
        "contact_phone_masked": mask_phone(order.contact_phone),
        "platforms": list(order.platforms_json or []),
        "schedule_runs": total,
        "lead_diagnosis_id": order.lead_diagnosis_id,
        "lead_status": lead_status,
        "ready": ready,
        "progress": {
            "completed_runs": completed,
            "total_runs": total,
            "percent": int(round(completed / total * 100)) if total else 0,
        },
        "plan_hint": f"计划约 {total} 次监测，完成后可在本页查看报告",
        "summary": summary,
        "access_token": token_out,
        "sms_ready_sent": bool(order.sms_ready_sent_at),
    }


def build_h5_result_report_html(db: Session, *, out_trade_no: str, token: str | None = None, openid: str | None = None) -> str:
    from app.services.lead_diagnosis_service import build_lead_diagnosis_preview_html

    order = _order_by_out_trade_no(db, out_trade_no)
    assert_h5_result_access(db, order, token=token, openid=openid)
    if not order.lead_diagnosis_id:
        raise ValueError("诊断尚未创建")
    return build_lead_diagnosis_preview_html(db, int(order.lead_diagnosis_id), current=None)


def notify_h5_order_ready_sms(db: Session, lead_id: int) -> dict[str, Any]:
    """诊断 ready 后：确保 token 并发短信（幂等）。"""
    order = db.scalar(
        select(H5DiagnosisOrder).where(H5DiagnosisOrder.lead_diagnosis_id == int(lead_id))
    )
    if order is None:
        return {"status": "skip", "reason": "not_h5_order"}
    if order.status != "paid":
        return {"status": "skip", "reason": "not_paid"}
    if order.sms_ready_sent_at:
        return {"status": "skip", "reason": "already_sent"}

    token = ensure_h5_result_access_token(db, order)
    # 结果短链仅供站内/日志；短信模板禁止变量传链，正文写死结果页 URL
    link = build_h5_result_page_url(out_trade_no=order.out_trade_no, token=token)
    if not settings.aliyun_sms_enabled:
        order.sms_ready_last_error = "sms_disabled"
        db.commit()
        return {"status": "skip", "reason": "sms_disabled", "result_url": link}

    template = str(settings.aliyun_sms_template_code_h5_ready or "").strip()
    if not template:
        order.sms_ready_last_error = "template_missing"
        db.commit()
        return {"status": "skip", "reason": "template_missing", "result_url": link}

    # 2026-09-01 - 阿里云拒审「变量内传入链接」- 改传 brand/order，链接固定在模板
    try:
        from app.services.aliyun_sms_service import send_sms

        send_sms(
            phone=order.contact_phone,
            template_code=template,
            template_param={
                "brand": str(order.brand_name or "")[:20],
                "order": str(order.out_trade_no or "")[:32],
            },
        )
        order.sms_ready_sent_at = datetime.utcnow()
        order.sms_ready_last_error = None
        db.commit()
        return {"status": "sent", "result_url": link}
    except Exception as exc:
        order.sms_ready_last_error = str(exc)[:240]
        db.commit()
        logger.warning(
            "h5 ready sms failed out_trade_no=%s err=%s",
            order.out_trade_no,
            exc,
        )
        return {"status": "error", "error": str(exc), "result_url": link}
