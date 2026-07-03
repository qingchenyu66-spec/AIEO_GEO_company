"""Sensitive field masking for API responses and audit logs."""

from __future__ import annotations

import re

_PHONE_DIGITS_RE = re.compile(r"\d+")


def mask_phone(phone: str | None) -> str | None:
    """Mask middle digits of a phone number; keep first 3 and last 4 when possible."""
    text = str(phone or "").strip()
    if not text:
        return phone
    digits = "".join(_PHONE_DIGITS_RE.findall(text))
    if len(digits) < 7:
        return text[:1] + "*" * max(len(text) - 2, 1) + text[-1:] if len(text) > 2 else "*"
    masked_digits = f"{digits[:3]}{'*' * (len(digits) - 7)}{digits[-4:]}"
    if digits == text:
        return masked_digits
    out: list[str] = []
    digit_index = 0
    for ch in text:
        if ch.isdigit():
            out.append(masked_digits[digit_index])
            digit_index += 1
        else:
            out.append(ch)
    return "".join(out)


def excerpt_sensitive_text(text: str | None, *, limit: int = 80) -> str:
    """Short preview for logs/audit without storing full answer bodies."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    compact = re.sub(r"\s+", " ", raw)
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}…"
