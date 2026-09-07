"""媒体代理 API：快照图经自家域名输出，避免地址栏露出供应商 CDN。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, Response

from app.services.media_proxy_service import fetch_shot_response, unseal_shot_token
from app.services.share_page_screenshot_service import resolve_backfill_shot_path

router = APIRouter(prefix="/media", tags=["Media"])


@router.get("/shot/{token}")
def media_shot(token: str) -> Response:
    """凭密封 token 取快照图。

    2026-09-07 - 诊断 HTML 下载/转发后无登录 Cookie - token 即能力凭证（含过期+白名单），不再强制会话
    """
    try:
        url = unseal_shot_token(token)
        body, content_type = fetch_shot_response(url)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="快照拉取失败",
        ) from exc
    return Response(
        content=body,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/backfill-shot/{file_id}")
def media_backfill_shot(file_id: str) -> FileResponse:
    """补录自截图：本地落盘 PNG；file_id 不透明，与 shot token 同理可免登录转发。"""
    try:
        path = resolve_backfill_shot_path(file_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )
