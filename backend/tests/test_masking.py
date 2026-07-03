"""Tests for masking helpers."""

from app.core.masking import excerpt_sensitive_text, mask_phone


def test_mask_phone_hides_middle_digits() -> None:
    assert mask_phone("13812345678") == "138****5678"
    assert mask_phone("010-8888-6666") == "010-****-6666"


def test_mask_phone_short_number() -> None:
    masked = mask_phone("12345")
    assert masked is not None
    assert "*" in masked


def test_excerpt_sensitive_text_truncates() -> None:
    text = "a" * 200
    excerpt = excerpt_sensitive_text(text, limit=80)
    assert len(excerpt) <= 81
    assert excerpt.endswith("…")
