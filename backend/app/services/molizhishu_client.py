import json
import logging
import platform
import shutil
import subprocess
import time
from typing import Any

from app.core.config import settings
from app.core.rate_limiter import acquire_molizhishu_rate_limit

logger = logging.getLogger(__name__)


class MolizhishuApiError(RuntimeError):
    """模力指数远端业务或网络异常。"""

    def __init__(self, message: str, *, code: int | None = None, response: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.response = response or {}


def _curl_exe_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict[str, Any] | None,
    timeout: float,
) -> tuple[int, str]:
    curl_bin = shutil.which("curl") or shutil.which("curl.exe")
    if not curl_bin:
        raise MolizhishuApiError("未找到 curl，可安装 curl 或 curl_cffi 以调用监测 API")
    cmd = [curl_bin, "-sS", "-m", str(max(1, int(timeout))), "-X", method.upper(), "-w", "\n__HTTP_CODE__:%{http_code}"]
    for key, value in headers.items():
        cmd.extend(["-H", f"{key}: {value}"])
    if json_body is not None:
        cmd.extend(["-H", "Content-Type: application/json", "-d", json.dumps(json_body, ensure_ascii=False)])
    cmd.append(url)
    completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "curl failed").strip()
        raise MolizhishuApiError(f"监测服务网络错误：{detail[:500]}")
    body = completed.stdout
    marker = "\n__HTTP_CODE__:"
    if marker in body:
        text, _, code_text = body.rpartition(marker)
        return int(code_text.strip() or "0"), text
    return 200, body


def _http_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict[str, Any] | None,
    timeout: float,
) -> tuple[int, str]:
    """Windows 优先 curl.exe（Schannel）；其他环境优先 curl_cffi，再 httpx。"""
    if platform.system().lower() == "windows":
        return _curl_exe_request(method, url, headers=headers, json_body=json_body, timeout=timeout)

    try:
        from curl_cffi import requests as curl_requests

        response = curl_requests.request(
            method,
            url,
            headers=headers,
            json=json_body,
            timeout=timeout,
            impersonate="chrome",
        )
        return response.status_code, response.text
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("curl_cffi request failed, fallback to httpx: %s", exc)

    import httpx

    with httpx.Client(timeout=timeout) as client:
        response = client.request(method, url, headers=headers, json=json_body)
    return response.status_code, response.text


class MolizhishuClient:
    """模力指数监控 API 客户端，统一处理鉴权、超时、错误和日志。"""

    def __init__(self) -> None:
        self.base_url = settings.molizhishu_base_url.rstrip("/")
        self.token = settings.molizhishu_token.strip()
        self.timeout = settings.molizhishu_timeout_seconds

    @property
    def api_root(self) -> str:
        marker = "/api/business/monitor"
        if marker in self.base_url:
            return self.base_url.split(marker, 1)[0].rstrip("/")
        return self.base_url.rsplit("/api", 1)[0].rstrip("/")

    def _headers(self) -> dict[str, str]:
        from app.services.system_config_service import get_runtime_config

        token = str(get_runtime_config("molizhishu_token") or "").strip()
        if not token:
            raise MolizhishuApiError("未配置 MOLIZHISHU_TOKEN，无法调用监测接口")
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        source: str,
        base_url: str | None = None,
        rate_category: str = "default",
    ) -> dict[str, Any]:
        try:
            acquire_molizhishu_rate_limit(rate_category)  # type: ignore[arg-type]
        except TimeoutError as exc:
            raise MolizhishuApiError(str(exc)) from exc

        root = (base_url or self.base_url).rstrip("/")
        url = path if path.startswith("http") else f"{root}{path if path.startswith('/') else f'/{path}'}"
        started = time.perf_counter()
        http_status: int | None = None
        payload: dict[str, Any] | None = None
        try:
            http_status, body_text = _http_request(
                method,
                url,
                headers=self._headers(),
                json_body=json_body,
                timeout=self.timeout,
            )
            if http_status >= 400:
                raise MolizhishuApiError(f"监测服务 HTTP 错误：{http_status} {body_text[:1000]}")
            payload = json.loads(body_text)
        except MolizhishuApiError:
            raise
        except ValueError as exc:
            raise MolizhishuApiError("监测服务响应不是合法 JSON") from exc
        except Exception as exc:
            raise MolizhishuApiError(f"监测服务网络错误：{exc}") from exc
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
        message = payload.get("message") or "监测接口返回失败"
        if not success:
            raise MolizhishuApiError(message, code=code, response=payload)
        return payload

    def submit_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/task/batch/shared", json_body=payload, source="local-api:submit-task", rate_category="submit")

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        return self._request("GET", f"/task/status/{task_id}", source="local-api:manual-sync:status", rate_category="sync")

    def get_task_result(self, task_id: str) -> dict[str, Any]:
        return self._request("GET", f"/task/result/{task_id}", source="local-api:manual-sync:result", rate_category="sync")

    def get_account_balance(self) -> dict[str, Any]:
        """Query current Molizhishu account balance."""
        return self._request(
            "GET",
            "/api/reconciliation/balance",
            source="local-api:molizhishu-balance",
            base_url=self.api_root,
        )

    def ping(self) -> dict[str, Any]:
        """连通性探测：查询账户余额。"""
        return self.get_account_balance()
