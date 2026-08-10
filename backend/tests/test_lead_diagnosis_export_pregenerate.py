"""售前诊断导出预生成入口自检。"""

from app.services.report_export_job_service import pregenerate_lead_diagnosis_exports


def test_pregenerate_lead_diagnosis_exports_missing_returns_empty():
    assert pregenerate_lead_diagnosis_exports(-1) == []
