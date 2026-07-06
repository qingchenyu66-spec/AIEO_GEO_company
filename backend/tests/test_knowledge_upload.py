"""Knowledge upload signature validation."""

from __future__ import annotations

import pytest

from app.services.knowledge_service import _validate_file_signature


def test_pdf_signature_ok():
    _validate_file_signature(".pdf", b"%PDF-1.7 sample")


def test_pdf_signature_rejects_fake():
    with pytest.raises(ValueError, match="不匹配"):
        _validate_file_signature(".pdf", b"not-a-pdf")


def test_txt_skips_signature():
    _validate_file_signature(".txt", b"plain text")
