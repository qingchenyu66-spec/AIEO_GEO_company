# -*- coding: utf-8 -*-
"""2026-08-13 - 售前可选露出词/别名入口。"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from app.models.lead_diagnosis import LeadDiagnosis
from app.schemas.lead_diagnosis import LeadDiagnosisCreateRequest, normalize_brand_aliases
from app.services.lead_diagnosis_service import _lead_brand_terms


def test_normalize_brand_aliases_split_and_dedupe() -> None:
    assert normalize_brand_aliases("艾迪亚, 艾迪亚传媒，艾迪亚") == ["艾迪亚", "艾迪亚传媒"]
    assert normalize_brand_aliases([" 艾迪亚传媒 ", "", "艾迪亚传媒"]) == ["艾迪亚传媒"]
    assert normalize_brand_aliases(None) == []


def test_create_request_accepts_brand_aliases() -> None:
    with patch(
        "app.services.molizhishu_catalog_service.filter_submittable_platforms",
        return_value=["doubao"],
    ):
        req = LeadDiagnosisCreateRequest.model_validate(
            {
                "brand_name": "艾迪亚控股集团有限公司",
                "prompts": ["地铁广告投放服务商哪家比较靠谱？", "艾迪亚靠谱吗"],
                "platforms": ["doubao"],
                "brand_aliases": "艾迪亚, 艾迪亚传媒",
            }
        )
    assert req.brand_aliases == ["艾迪亚", "艾迪亚传媒"]


def test_lead_brand_terms_prefer_stored_aliases() -> None:
    lead = LeadDiagnosis(
        brand_name="艾迪亚控股集团有限公司",
        brand_aliases_json=["艾迪亚传媒", "艾迪亚"],
        lead_context_json={},
        prompts_json=["问法1"],
        competitors_json=[],
        platforms_json=["doubao"],
        region_codes_json=[],
        schedule_times_json=["09:30"],
        schedule_days=3,
        diagnosis_date=date(2026, 8, 13),
        status="pending",
    )
    terms = _lead_brand_terms(lead)
    assert "艾迪亚传媒" in terms
    assert "艾迪亚控股集团有限公司" in terms
    assert terms.index("艾迪亚控股集团有限公司") == 0
