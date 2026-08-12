# -*- coding: utf-8 -*-
"""HTML 导出指纹须含内联版本，避免复用外链旧包。"""

from datetime import datetime
from types import SimpleNamespace

from app.services.report_export_job_service import _report_fingerprint


def test_html_export_fingerprint_includes_embed_version(monkeypatch):
    row = SimpleNamespace(
        updated_at=datetime(2026, 8, 1, 12, 0, 0),
        status="published",
        report_type="monthly",
    )

    class _DB:
        def get(self, model, report_id):
            return row

    html_fp = _report_fingerprint(_DB(), 1, "html", "b")
    pdf_fp = _report_fingerprint(_DB(), 1, "pdf", "b")
    assert html_fp != pdf_fp

    # 去掉版本后应与旧算法不同（旧算法 html 的 asset 为空）
    import hashlib

    stamp = f"{row.updated_at}|{row.status}|{row.report_type}"
    old = hashlib.sha256(f"report|1|html|b|{stamp}|".encode("utf-8")).hexdigest()[:40]
    assert html_fp != old
