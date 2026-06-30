"""Molizhishu account balance helpers for platform ops."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.molizhishu_client import MolizhishuApiError, MolizhishuClient


def _parse_balance(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        return None


def fetch_molizhishu_balance() -> dict[str, Any]:
    """Return balance snapshot; never raise to callers."""
    fetched_at = datetime.now().isoformat(timespec="seconds")
    try:
        response = MolizhishuClient().get_account_balance()
        data = response.get("data") or {}
        balance = _parse_balance(data.get("currentBalance"))
        if balance is None:
            return {
                "available": False,
                "current_balance": None,
                "current_balance_text": None,
                "fetched_at": fetched_at,
                "error": "模力余额接口未返回 currentBalance",
            }
        return {
            "available": True,
            "current_balance": balance,
            "current_balance_text": f"{balance:.2f}",
            "fetched_at": fetched_at,
            "error": None,
        }
    except MolizhishuApiError as exc:
        return {
            "available": False,
            "current_balance": None,
            "current_balance_text": None,
            "fetched_at": fetched_at,
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "available": False,
            "current_balance": None,
            "current_balance_text": None,
            "fetched_at": fetched_at,
            "error": f"查询模力余额失败：{exc}",
        }
