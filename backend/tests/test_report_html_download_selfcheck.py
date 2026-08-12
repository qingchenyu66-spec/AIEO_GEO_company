# -*- coding: utf-8 -*-
"""导出 HTML 自检：缺模块/外链复现要在上线前失败。"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.report import GeoReport
from app.services.report_custom_optimization_service import optimization_parts_from_modules
from app.services.report_export_job_service import _load_report_payload
from app.services.report_export_service import build_report_html_download, build_report_html_preview


def test_custom_optimization_module_importable():
    assert optimization_parts_from_modules({}) == []
    assert optimization_parts_from_modules(None) == []


def test_monthly_html_download_embeds_assets_not_portal_paths():
    """对本地库中一份月报做真实下载渲染，确认内联且无 /report-assets 外链。"""
    db = SessionLocal()
    try:
        row = db.scalars(
            select(GeoReport)
            .where(
                GeoReport.deleted.is_(False),
                GeoReport.report_type == "monthly",
                GeoReport.status == "published",
            )
            .order_by(GeoReport.id.desc())
            .limit(1)
        ).first()
        if row is None:
            return
        report = _load_report_payload(db, int(row.id))
        html = build_report_html_download(db, report)
        assert "/report-assets/echarts.min.js" not in html
        assert not re.search(r'src=["\']/report-assets/', html)
        assert "data:image" in html
        assert "<script>" in html and "echarts" in html.lower()
        preview = build_report_html_preview(db, report)
        assert len(html) > len(preview)
        assert "/report-assets/" in preview
        out = Path("storage") / "_selfcheck_monthly_download.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        assert out.stat().st_size > 500_000
    finally:
        db.close()
