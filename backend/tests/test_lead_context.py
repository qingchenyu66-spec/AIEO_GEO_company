"""售前 lead_context：schema 清洗 → 序列化 → 报告/cockpit 透传。"""

from __future__ import annotations

import json
from datetime import date, datetime
from unittest.mock import patch

from app.core.lead_diagnosis_config import DEFAULT_LEAD_SCHEDULE_TIMES
from app.models.lead_diagnosis import LeadDiagnosis
from app.schemas.lead_diagnosis import LeadDiagnosisCreateRequest, normalize_lead_context
from app.services.lead_diagnosis_service import _serialize_lead
from app.services.report_diagnosis_cockpit_service import build_diagnosis_cockpit_context
from app.services.report_export_service import _normalize_export_payload


def test_normalize_lead_context_url_and_lengths() -> None:
    out = normalize_lead_context(
        {
            "website_url": "www.example.com/path",
            "industry": "拉链",
            "product_focus": "工业拉链",
            "purchase_scenario": "",
            "source": "lead_diagnosis_create",
        }
    )
    assert out["website_url"] == "https://www.example.com/path"
    assert out["industry"] == "拉链"
    assert out["product_focus"] == "工业拉链"
    assert out["purchase_scenario"] == ""
    assert out["source"] == "lead_diagnosis_create"
    assert normalize_lead_context({"website_url": "javascript:alert(1)"})["website_url"] == ""
    assert normalize_lead_context(None)["source"] == "lead_diagnosis_create"


def test_create_request_accepts_lead_context() -> None:
    with patch(
        "app.services.molizhishu_catalog_service.filter_submittable_platforms",
        return_value=["doubao"],
    ):
        req = LeadDiagnosisCreateRequest.model_validate(
            {
                "brand_name": "测试品牌",
                "prompts": ["拉链品牌推荐", "伟星怎么样"],
                "platforms": ["doubao"],
                "contact_note": "仅销售备注",
                "lead_context": {
                    "website_url": "https://www.weixing.com",
                    "industry": "拉链",
                    "product_focus": "尼龙拉链",
                    "source": "lead_diagnosis_create",
                },
            }
        )
    assert req.contact_note == "仅销售备注"
    ctx = req.lead_context_dict()
    assert ctx["website_url"] == "https://www.weixing.com"
    assert ctx["industry"] == "拉链"
    assert "官网" not in (req.contact_note or "")


def test_serialize_lead_exposes_lead_context() -> None:
    lead = LeadDiagnosis(
        id=1,
        brand_name="测试品牌",
        contact_note="销售备注",
        lead_context_json={
            "website_url": "https://a.example",
            "industry": "户外",
            "product_focus": "电梯",
            "purchase_scenario": "",
            "source": "lead_diagnosis_create",
        },
        prompts_json=["问法1"],
        competitors_json=[],
        platforms_json=["doubao"],
        region_codes_json=[],
        schedule_times_json=list(DEFAULT_LEAD_SCHEDULE_TIMES),
        schedule_days=3,
        diagnosis_date=date(2026, 8, 13),
        status="pending",
        created_at=datetime(2026, 8, 13, 10, 0, 0),
        updated_at=datetime(2026, 8, 13, 10, 0, 0),
        runs=[],
    )
    payload = _serialize_lead(lead)
    assert payload["contact_note"] == "销售备注"
    assert payload["lead_context"]["website_url"] == "https://a.example"
    assert payload["lead_context"]["industry"] == "户外"


def test_report_and_cockpit_carry_lead_context() -> None:
    lead_ctx = {
        "website_url": "https://brand.example",
        "industry": "拉链",
        "product_focus": "金属拉链",
        "purchase_scenario": "",
        "source": "lead_diagnosis_create",
    }
    report = {
        "report_title": "测试",
        "report_type": "diagnosis",
        "tenant_name": "测试品牌",
        "report_content": {
            "brand_name": "测试品牌",
            "kpis": {},
            "prompt_analytics": [],
            "platform_stats": [],
            "diagnosis": {},
            "lead_context": lead_ctx,
            "input_context": lead_ctx,
            "competitors": [],
        },
    }
    export_payload = _normalize_export_payload(report)
    assert export_payload["lead_context"]["industry"] == "拉链"
    assert export_payload["input_context"]["product_focus"] == "金属拉链"

    ctx = build_diagnosis_cockpit_context(export_payload)
    assert ctx["lead_context"]["website_url"] == "https://brand.example"
    assert ctx["input_context"]["industry"] == "拉链"
    cockpit = json.loads(ctx["cockpit_json"])
    assert cockpit["lead_context"]["product_focus"] == "金属拉链"
    assert cockpit["input_context"]["source"] == "lead_diagnosis_create"
