"""DeepSeek account balance helpers for platform ops."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.deepseek_client import DeepseekApiError, DeepseekClient


def _parse_balance(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _pick_balance_info(items: list[Any]) -> dict[str, Any] | None:
    if not items:
        return None
    for preferred in ("CNY", "USD"):
        for item in items:
            if isinstance(item, dict) and item.get("currency") == preferred:
                return item
    first = items[0]
    return first if isinstance(first, dict) else None


def fetch_deepseek_balance() -> dict[str, Any]:
    """Return DeepSeek balance snapshot; never raise to callers."""
    from app.services.system_config_service import get_runtime_config

    fetched_at = datetime.now().isoformat(timespec="seconds")
    if not str(get_runtime_config("deepseek_api_key") or "").strip():
        return {
            "available": False,
            "current_balance": None,
            "current_balance_text": None,
            "currency": None,
            "is_available": None,
            "fetched_at": fetched_at,
            "error": "未配置 DEEPSEEK_API_KEY",
        }
    try:
        payload = DeepseekClient().get_account_balance()
        balance_info = _pick_balance_info(payload.get("balance_infos") or [])
        balance = _parse_balance(balance_info.get("total_balance") if balance_info else None)
        currency = str(balance_info.get("currency") or "CNY") if balance_info else "CNY"
        if balance is None:
            return {
                "available": False,
                "current_balance": None,
                "current_balance_text": None,
                "currency": currency,
                "is_available": payload.get("is_available"),
                "fetched_at": fetched_at,
                "error": "DeepSeek 余额接口未返回 total_balance",
            }
        symbol = "¥" if currency == "CNY" else "$" if currency == "USD" else ""
        return {
            "available": True,
            "current_balance": balance,
            "current_balance_text": f"{balance:.2f}",
            "currency": currency,
            "is_available": payload.get("is_available"),
            "fetched_at": fetched_at,
            "error": None,
            "display_value": f"{symbol} {balance:.2f}".strip(),
        }
    except DeepseekApiError as exc:
        return {
            "available": False,
            "current_balance": None,
            "current_balance_text": None,
            "currency": None,
            "is_available": None,
            "fetched_at": fetched_at,
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "available": False,
            "current_balance": None,
            "current_balance_text": None,
            "currency": None,
            "is_available": None,
            "fetched_at": fetched_at,
            "error": f"查询 DeepSeek 余额失败：{exc}",
        }
