"""Celery 任务返回值脱敏：避免 Worker 日志 / result backend 泄露回调凭据。"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# 查询参数名（大小写不敏感）视为凭据，统一打码
_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "token",
        "access_token",
        "api_key",
        "apikey",
        "key",
        "secret",
        "password",
        "passwd",
        "authorization",
        "auth",
        "sign",
        "signature",
    }
)

_URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_SENSITIVE_ASSIGNMENT_IN_TEXT = re.compile(
    rf"(?P<prefix>\b(?:{'|'.join(sorted(map(re.escape, _SENSITIVE_QUERY_KEYS), key=len, reverse=True))})\s*=\s*)"
    r"(?P<value>[^&\s,;\"'<>]+)",
    re.IGNORECASE,
)

# 调度提交结果里允许出现的顶层字段（不含嵌套 task 对象）
_SCHEDULE_TOP_KEYS = ("tenant_id", "schedule_key", "status", "keyword", "message")


def redact_url_query_secrets(url: str) -> str:
    """保留 URL 结构，敏感查询参数值替换为 ***。"""
    text = str(url or "").strip()
    if not text:
        return text
    try:
        parts = urlsplit(text)
    except ValueError:
        return "***"
    if not parts.query:
        return text
    redacted = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in _SENSITIVE_QUERY_KEYS:
            redacted.append((key, "***"))
        else:
            redacted.append((key, value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(redacted), parts.fragment))


def redact_secrets_in_text(value: str, *, max_len: int = 240) -> str:
    """字符串内 URL 整段替换为占位（Celery 返回禁止残留 URL / query）；截断长度。"""
    text = str(value or "")
    if not text:
        return text
    cleaned = _URL_IN_TEXT.sub("[redacted-url]", text)
    cleaned = _SENSITIVE_ASSIGNMENT_IN_TEXT.sub(r"\g<prefix>***", cleaned)
    if len(cleaned) > max_len:
        return cleaned[: max_len - 1] + "…"
    return cleaned


def summarize_schedule_submit_for_celery(result: dict[str, Any] | None) -> dict[str, Any]:
    """调度提交 Celery 返回摘要：仅 ID / 状态 / 计数，不含 callback_url 等完整任务序列化。"""
    if not isinstance(result, dict):
        return {"status": "unknown"}

    out: dict[str, Any] = {}
    for key in _SCHEDULE_TOP_KEYS:
        if key not in result:
            continue
        value = result[key]
        if key == "message":
            out[key] = redact_secrets_in_text(str(value or ""))
        else:
            out[key] = value

    task = result.get("task")
    if isinstance(task, dict):
        out["task_id"] = task.get("task_id")
        out["task_status"] = task.get("status")
        out["total_items"] = task.get("total_items")
        out["completed_items"] = task.get("completed_items")
        out["failed_items"] = task.get("failed_items")
    elif result.get("task_id") is not None:
        out["task_id"] = result.get("task_id")
        if result.get("task_status") is not None:
            out["task_status"] = result.get("task_status")

    return out


def celery_result_contains_secrets(payload: Any) -> bool:
    """检测返回值是否仍含 URL、token= 类查询或敏感键名（供测试与自检）。"""
    if payload is None:
        return False
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_l = str(key).lower()
            if key_l in {"callback_url", "poll_url"} or key_l in _SENSITIVE_QUERY_KEYS:
                if value not in (None, "", "***"):
                    return True
            if celery_result_contains_secrets(value):
                return True
        return False
    if isinstance(payload, (list, tuple)):
        return any(celery_result_contains_secrets(item) for item in payload)
    if isinstance(payload, str):
        text = payload
        if any(match.group("value") != "***" for match in _SENSITIVE_ASSIGNMENT_IN_TEXT.finditer(text)):
            return True
        if _URL_IN_TEXT.search(text):
            return True
        return False
    # 兜底：JSON 化后再扫
    try:
        dumped = json.dumps(payload, ensure_ascii=False, default=str)
    except TypeError:
        dumped = str(payload)
    return celery_result_contains_secrets(dumped)
