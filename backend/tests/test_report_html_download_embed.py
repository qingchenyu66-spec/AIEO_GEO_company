# -*- coding: utf-8 -*-
"""HTML 下载须内联资源；预览仍外链。"""

from app.services.report_export_service import build_report_html_download, build_report_html_preview


def test_html_download_embeds_period_assets(monkeypatch):
    calls: list[bool] = []

    def fake_period(db, payload, *, tenant_id, embed_assets):
        calls.append(bool(embed_assets))
        return f"period-embed={embed_assets}"

    monkeypatch.setattr(
        "app.services.report_period_deck_pdf_service.build_period_deck_html",
        fake_period,
    )
    report = {
        "tenant_id": 15,
        "report_type": "monthly",
        "period_start": "2026-07-01",
        "period_end": "2026-07-31",
        "report_content": {"brand_name": "测试"},
    }
    preview = build_report_html_preview(None, report)
    download = build_report_html_download(None, report)
    assert preview == "period-embed=False"
    assert download == "period-embed=True"
    assert calls == [False, True]


def test_html_download_embeds_completion_assets(monkeypatch):
    calls: list[bool] = []

    def fake_completion(payload, platform_names, *, embed_assets):
        calls.append(bool(embed_assets))
        return f"completion-embed={embed_assets}"

    monkeypatch.setattr(
        "app.services.report_period_deck_pdf_service.build_completion_deck_html",
        fake_completion,
    )
    report = {
        "tenant_id": 15,
        "report_type": "completion",
        "report_content": {"brand_name": "测试"},
    }
    preview = build_report_html_preview(None, report)
    download = build_report_html_download(None, report)
    assert preview == "completion-embed=False"
    assert download == "completion-embed=True"
    assert calls == [False, True]
