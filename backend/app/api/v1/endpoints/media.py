"""媒体代理 API：快照图经自家域名输出，避免地址栏露出供应商 CDN。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, Response

from app.api.dependencies import CurrentSession, get_current_session
from app.services.media_proxy_service import fetch_shot_response, unseal_shot_token
from app.services.share_page_screenshot_service import resolve_backfill_shot_path

router = APIRouter(prefix="/media", tags=["Media"])


@router.get("/shot/{token}")
def media_shot(
    token: str,
    current: CurrentSession = Depends(get_current_session),
) -> Response:
    """登录用户打开快照：服务端拉取白名单 CDN，原图流式回写。"""
    _ = current  # 鉴权：须登录（Cookie / Bearer）；禁止匿名扫库
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
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/backfill-shot/{file_id}")
def media_backfill_shot(
    file_id: str,
    current: CurrentSession = Depends(get_current_session),
) -> FileResponse:
    """补录自截图：本地落盘 PNG，登录可看。"""
    _ = current
    try:
        path = resolve_backfill_shot_path(file_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type="image/png",
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )
