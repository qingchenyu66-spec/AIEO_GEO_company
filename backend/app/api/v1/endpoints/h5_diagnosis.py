"""9.9 元 H5 付费售前诊断（公开接口）。"""

from __future__ import annotations

import json
import secrets

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.schemas.common import ApiResponse
from app.schemas.h5_diagnosis import H5DiagnosisOrderCreateRequest
from app.services.h5_diagnosis_service import (
    _H5_OPENID_COOKIE,
    create_h5_diagnosis_order,
    fulfill_h5_order_paid,
    get_h5_diagnosis_public_config,
    get_h5_order_status,
    mark_h5_order_paid_dev,
    mask_openid,
)
from app.services.wechat_oauth_service import build_oauth_redirect_url, exchange_code_for_openid
from app.services.wechat_pay_service import decrypt_notify_resource

router = APIRouter(prefix="/h5/diagnosis")
wechat_pay_router = APIRouter(prefix="/wechat-pay")

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


def _h5_frontend_url(*, query: str = "") -> str:
    base = settings.wechat_h5_base_url.rstrip("/") + "/"
    return f"{base}{('?' + query.lstrip('?')) if query else ''}"


@router.get("/config", response_model=ApiResponse[dict])
def public_config(db: Session = Depends(get_db)) -> ApiResponse[dict]:
    data = get_h5_diagnosis_public_config(db)
    return ApiResponse(data=data)


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
def oauth_start(request: Request) -> RedirectResponse:
    if settings.wechat_pay_dev_mode:
        response = RedirectResponse(url=_h5_frontend_url(), status_code=302)
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
    response = RedirectResponse(url=_h5_frontend_url(), status_code=302)
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
            industry=payload.industry,
            product_focus=payload.product_focus,
            website_url=payload.website_url,
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
        payload = json.loads(body.decode("utf-8"))
        resource = payload.get("resource") or {}
        plain = decrypt_notify_resource(resource)
    except Exception:
        return Response(status_code=400, content="invalid notify")

    if plain.get("trade_state") != "SUCCESS":
        return Response(content=json.dumps({"code": "SUCCESS", "message": "ignored"}), media_type="application/json")

    out_trade_no = str(plain.get("out_trade_no") or "").strip()
    transaction_id = str(plain.get("transaction_id") or "").strip()
    if not out_trade_no:
        return Response(status_code=400, content="missing out_trade_no")

    try:
        fulfill_h5_order_paid(db, out_trade_no=out_trade_no, wx_transaction_id=transaction_id)
    except ValueError:
        return Response(status_code=404, content="order not found")

    return Response(content=json.dumps({"code": "SUCCESS", "message": "成功"}), media_type="application/json")
