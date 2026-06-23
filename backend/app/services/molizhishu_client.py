import logging
import time
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class MolizhishuApiError(RuntimeError):
    """模力指数远端业务或网络异常。"""

    def __init__(self, message: str, *, code: int | None = None, response: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.response = response or {}


class MolizhishuClient:
    """模力指数监控 API 客户端，统一处理鉴权、超时、错误和日志。"""

    def __init__(self) -> None:
        self.base_url = settings.molizhishu_base_url.rstrip("/")
        self.token = settings.molizhishu_token.strip()
        self.timeout = settings.molizhishu_timeout_seconds

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise MolizhishuApiError("未配置 MOLIZHISHU_TOKEN，无法调用模力指数接口")
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, *, json_body: dict[str, Any] | None = None, source: str) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        started = time.perf_counter()
        http_status: int | None = None
        payload: dict[str, Any] | None = None
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(method, url, headers=self._headers(), json=json_body)
            http_status = response.status_code
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:1000]
            raise MolizhishuApiError(f"模力指数 HTTP 错误：{exc.response.status_code} {body}") from exc
        except httpx.HTTPError as exc:
            raise MolizhishuApiError(f"模力指数网络错误：{exc}") from exc
        except ValueError as exc:
            raise MolizhishuApiError("模力指数响应不是合法 JSON") from exc
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "[molizhishu] source=%s method=%s url=%s http_status=%s duration=%sms",
                source,
                method,
                url,
                http_status,
                duration_ms,
            )
        success = bool(payload.get("success"))
        code = payload.get("code")
        message = payload.get("message") or "模力指数接口返回失败"
        if not success:
            raise MolizhishuApiError(message, code=code, response=payload)
        return payload

    def submit_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/task/batch/shared", json_body=payload, source="local-api:submit-task")

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        return self._request("GET", f"/task/status/{task_id}", source="local-api:manual-sync:status")

    def get_task_result(self, task_id: str) -> dict[str, Any]:
        return self._request("GET", f"/task/result/{task_id}", source="local-api:manual-sync:result")
