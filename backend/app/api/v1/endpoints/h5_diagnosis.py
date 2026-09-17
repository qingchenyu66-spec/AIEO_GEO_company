"""9.9 元 H5 付费售前诊断（公开接口）。"""

from __future__ import annotations

import json
import secrets

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession, get_current_session
from app.core.config import settings
from app.core.database import get_db
from app.schemas.common import ApiResponse
from app.schemas.h5_diagnosis import (
    H5DiagnosisOrderCreateRequest,
    H5ResultUnlockByPhoneRequest,
    H5ResultUnlockRequest,
)
from app.services.h5_diagnosis_service import (
    _H5_OPENID_COOKIE,
    create_h5_diagnosis_order,
    get_h5_diagnosis_public_config,
    get_h5_order_status,
    list_h5_diagnosis_orders,
    mark_h5_order_paid_dev,
    mask_openid,
    require_h5_order_admin_access,
)
from app.services.payment_notify_guard import PaymentNotifyReject, process_alipay_notify, process_wechat_pay_notify
from app.services.h5_result_service import (
    build_h5_result_report_html,
    get_h5_diagnosis_result,
    result_cookie_name,
    unlock_h5_result_by_phone,
    unlock_h5_result_by_phone_tail,
)
from app.services.alipay_pay_service import verify_notify_signature
from app.services.wechat_oauth_service import build_oauth_redirect_url, exchange_code_for_openid

router = APIRouter(prefix="/h5/diagnosis")
wechat_pay_router = APIRouter(prefix="/wechat-pay")
alipay_router = APIRouter(prefix="/alipay")

_OAUTH_STATE_COOKIE = "geo_h5_oauth_state"


def _oauth_callback_url() -> str:
    parsed = urlparse(settings.wechat_h5_base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return f"{origin}{settings.api_v1_prefix}/h5/diagnosis/oauth/callback"


def _resolve_openid(request: Request) -> str:
    if settings.wechat_pay_dev_mode:
        cookie = request.cookies.get(_H5_OPENID_COOKIE)
        if cookie:
            return cookie
        return settings.wechat_pay_dev_openid
    openid = request.cookies.get(_H5_OPENID_COOKIE)
    return str(openid or "").strip()


def _h5_landing_url(*, query: str = "") -> str:
    base = settings.wechat_h5_base_url.rstrip("/") + "/"
    return f"{base}{('?' + query.lstrip('?')) if query else ''}"


def _h5_apply_url(*, query: str = "") -> str:
    parsed = urlparse(settings.wechat_h5_base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    base = f"{origin}/h5/diagnosis/apply"
    return f"{base}{('?' + query.lstrip('?')) if query else ''}"


def _oauth_return_url(target: str | None) -> str:
    if str(target or "").strip().lower() == "landing":
        return _h5_landing_url()
    return _h5_apply_url()


@router.get("/config", response_model=ApiResponse[dict])
def public_config(db: Session = Depends(get_db)) -> ApiResponse[dict]:
    data = get_h5_diagnosis_public_config(db)
    return ApiResponse(data=data)


@router.get("/admin/orders", response_model=ApiResponse[dict])
def admin_list_orders(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current: CurrentSession = Depends(get_current_session),
) -> ApiResponse[dict]:
    # 2026-08-31 - 平台后台 H5 付费订单列表（独立菜单权限）
    try:
        require_h5_order_admin_access(db, current, "can_export")
        return ApiResponse(data=list_h5_diagnosis_orders(db, page=page, page_size=page_size, status=status, keyword=keyword))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/session", response_model=ApiResponse[dict])
def public_session(request: Request) -> ApiResponse[dict]:
    openid = _resolve_openid(request)
    return ApiResponse(
        data={
            "ready": bool(openid),
            "openid_masked": mask_openid(openid) if openid else "",
            "dev_mode": settings.wechat_pay_dev_mode,
        }
    )


@router.get("/oauth/start")
def oauth_start(
    request: Request,
    target: str | None = Query(default="apply", description="apply | landing"),
) -> RedirectResponse:
    return_url = _oauth_return_url(target)
    if settings.wechat_pay_dev_mode:
        response = RedirectResponse(url=return_url, status_code=302)
        response.set_cookie(
            _H5_OPENID_COOKIE,
            settings.wechat_pay_dev_openid,
            httponly=True,
            secure=settings.auth_cookie_secure,
            samesite=settings.auth_cookie_samesite,
            max_age=86400 * 7,
        )
        return response
    state = secrets.token_urlsafe(16)
    callback = _oauth_callback_url()
    url = build_oauth_redirect_url(redirect_uri=callback, state=state)
    response = RedirectResponse(url=url, status_code=302)
    response.set_cookie(
        _OAUTH_STATE_COOKIE,
        state,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        max_age=600,
    )
    return response


@router.get("/oauth/callback", name="h5_oauth_callback")
def oauth_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
) -> RedirectResponse:
    expected = request.cookies.get(_OAUTH_STATE_COOKIE)
    if not code or not state or not expected or state != expected:
        raise HTTPException(status_code=400, detail="微信授权无效，请重试")
    try:
        openid = exchange_code_for_openid(code)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response = RedirectResponse(url=_h5_apply_url(), status_code=302)
    response.delete_cookie(_OAUTH_STATE_COOKIE)
    response.set_cookie(
        _H5_OPENID_COOKIE,
        openid,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        max_age=86400 * 7,
    )
    return response


@router.post("/orders", response_model=ApiResponse[dict])
def create_order(
    payload: H5DiagnosisOrderCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    openid = _resolve_openid(request)
    try:
        data = create_h5_diagnosis_order(
            db,
            openid=openid,
            wechat_id=payload.wechat_id,
            contact_phone=payload.contact_phone,
            brand_name=payload.brand_name,
            prompts=payload.prompts,
            brand_aliases=payload.brand_aliases,
            industry=payload.industry,
            product_focus=payload.product_focus,
            website_url=payload.website_url,
            competitors=payload.competitors,
            pay_trade_type=payload.pay_trade_type,
            pay_channel=payload.pay_channel,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.get("/orders/{out_trade_no}", response_model=ApiResponse[dict])
def order_status(out_trade_no: str, db: Session = Depends(get_db)) -> ApiResponse[dict]:
    try:
        return ApiResponse(data=get_h5_order_status(db, out_trade_no))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/orders/{out_trade_no}/result", response_model=ApiResponse[dict])
def order_result(
    out_trade_no: str,
    request: Request,
    t: str | None = Query(default=None, description="短信短链 token"),
    phone_tail: str | None = Query(default=None, description="手机号后四位"),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    # 2026-09-01 - H5 自助结果页：token / openid cookie / 手机后四位
    token = str(t or request.cookies.get(result_cookie_name()) or "").strip() or None
    openid = _resolve_openid(request) or None
    try:
        data = get_h5_diagnosis_result(
            db,
            out_trade_no=out_trade_no,
            token=token,
            openid=openid,
            phone_tail=phone_tail,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.post("/result/unlock", response_model=ApiResponse[dict])
def unlock_result_by_phone(
    payload: H5ResultUnlockByPhoneRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """结果页主路径：完整下单手机号 → 最近一笔已支付订单 token。"""
    try:
        data = unlock_h5_result_by_phone(db, contact_phone=payload.contact_phone)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    token = str(data.get("access_token") or "")
    if token:
        response.set_cookie(
            result_cookie_name(),
            token,
            httponly=True,
            secure=settings.auth_cookie_secure,
            samesite=settings.auth_cookie_samesite,
            max_age=86400 * max(1, int(settings.h5_result_token_days or 30)),
        )
    return ApiResponse(data=data)


@router.post("/orders/{out_trade_no}/result/unlock", response_model=ApiResponse[dict])
def unlock_order_result(
    out_trade_no: str,
    payload: H5ResultUnlockRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        data = unlock_h5_result_by_phone_tail(
            db,
            out_trade_no=out_trade_no,
            phone_tail=payload.phone_tail,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    token = str(data.get("access_token") or "")
    if token:
        response.set_cookie(
            result_cookie_name(),
            token,
            httponly=True,
            secure=settings.auth_cookie_secure,
            samesite=settings.auth_cookie_samesite,
            max_age=86400 * max(1, int(settings.h5_result_token_days or 30)),
        )
    return ApiResponse(data=data)


@router.get("/orders/{out_trade_no}/report.html")
def order_result_report_html(
    out_trade_no: str,
    request: Request,
    t: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Response:
    token = str(t or request.cookies.get(result_cookie_name()) or "").strip() or None
    openid = _resolve_openid(request) or None
    try:
        html = build_h5_result_report_html(db, out_trade_no=out_trade_no, token=token, openid=openid)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=html, media_type="text/html; charset=utf-8")


@router.post("/orders/{out_trade_no}/dev-paid", response_model=ApiResponse[dict])
def dev_mark_paid(out_trade_no: str, db: Session = Depends(get_db)) -> ApiResponse[dict]:
    try:
        return ApiResponse(data=mark_h5_order_paid_dev(db, out_trade_no))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@wechat_pay_router.post("/notify")
async def wechat_pay_notify(request: Request, db: Session = Depends(get_db)) -> Response:
    body = await request.body()
    try:
        result = process_wechat_pay_notify(db, body=body, headers=request.headers)
    except PaymentNotifyReject:
        return Response(
            status_code=400,
            content=json.dumps({"code": "FAIL", "message": "失败"}),
            media_type="application/json",
        )
    except Exception:
        return Response(status_code=400, content="invalid notify")

    if result is None:
        return Response(
            content=json.dumps({"code": "SUCCESS", "message": "ignored"}),
            media_type="application/json",
        )
    return Response(
        content=json.dumps({"code": "SUCCESS", "message": "成功"}),
        media_type="application/json",
    )


@alipay_router.post("/notify")
async def alipay_notify(request: Request, db: Session = Depends(get_db)) -> Response:
    # 2026-09-01 - 支付宝异步通知：form 字段 + RSA2 验签 + 业务对账
    form = await request.form()
    params = {str(k): str(v) for k, v in form.items()}
    try:
        result = process_alipay_notify(db, params=params)
    except PaymentNotifyReject:
        return Response(content="fail", media_type="text/plain")
    except Exception:
        return Response(content="fail", media_type="text/plain")
    if result is None:
        return Response(content="success", media_type="text/plain")
    return Response(content="success", media_type="text/plain")


@alipay_router.get("/return")
async def alipay_return(request: Request) -> RedirectResponse:
    """同步回跳：验签后带回申请页轮询。"""
    params = {str(k): str(v) for k, v in request.query_params.items()}
    out_trade_no = str(params.get("out_trade_no") or "").strip()
    parsed = urlparse(settings.alipay_return_url or settings.wechat_h5_base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    target = f"{origin}/h5/diagnosis/apply"
    if out_trade_no and (not params.get("sign") or verify_notify_signature(params)):
        target = f"{target}?out_trade_no={out_trade_no}&from=alipay"
    return RedirectResponse(url=target, status_code=302)
