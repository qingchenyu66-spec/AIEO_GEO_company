"""用公司监测数据 + DeepSeek 生成模力风格售前诊断 HTML/PDF。"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import SessionLocal
from app.models.lead_diagnosis import LeadDiagnosis
from app.models.tenant import Tenant
from app.services.lead_diagnosis_service import (
    aggregate_lead_diagnosis,
    build_lead_diagnosis_export,
    get_lead_diagnosis,
    import_tenant_lead_diagnosis,
)
from app.services.report_export_service import _normalize_export_payload
from app.services.report_molizhishu_pdf_service import build_molizhishu_pdf, render_molizhishu_report_html


def _resolve_lead(db, *, lead_id: int | None, tenant_id: int | None, tenant_code: str | None, refresh: bool) -> LeadDiagnosis:
    if lead_id:
        lead = db.scalar(
            select(LeadDiagnosis)
            .where(LeadDiagnosis.id == lead_id, LeadDiagnosis.deleted.is_(False))
            .options(selectinload(LeadDiagnosis.runs))
        )
        if lead is None:
            raise SystemExit(f"售前诊断不存在: {lead_id}")
        if refresh:
            from app.services.lead_diagnosis_service import _load_subtasks, _task_region_map_for_task_ids

            subtasks = _load_subtasks(db, lead)
            task_ids = [run.task_id for run in (lead.runs or []) if run.task_id]
            result = aggregate_lead_diagnosis(
                lead,
                subtasks,
                task_region_map=_task_region_map_for_task_ids(db, task_ids),
                db=db,
            )
            lead.diagnosis_result_json = result
            lead.health_score = result.get("diagnosis", {}).get("health_score") or result.get("kpis", {}).get("health_score")
            lead.status = "ready"
            db.commit()
            db.refresh(lead)
        return lead

    if tenant_id:
        tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    elif tenant_code:
        tenant = db.scalar(select(Tenant).where(Tenant.code == tenant_code, Tenant.deleted.is_(False)))
    else:
        raise SystemExit("请指定 --lead-id 或 --tenant-id / --tenant-code")
    if tenant is None:
        raise SystemExit("未找到企业")
    return import_tenant_lead_diagnosis(db, tenant_id=tenant.id)


def main() -> None:
    parser = argparse.ArgumentParser(description="DeepSeek + 公司数据生成售前诊断报告")
    parser.add_argument("--lead-id", type=int, help="已有售前诊断 ID")
    parser.add_argument("--tenant-id", type=int, help="企业 ID，从监测数据新建诊断")
    parser.add_argument("--tenant-code", default="AIDIYA_REAL", help="企业编码")
    parser.add_argument("--refresh", action="store_true", help="对已有 lead 重新汇总并调用 DeepSeek")
    parser.add_argument("--output-dir", default=str(Path.home() / "Desktop"), help="输出目录")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        lead = _resolve_lead(
            db,
            lead_id=args.lead_id,
            tenant_id=args.tenant_id,
            tenant_code=None if args.tenant_id or args.lead_id else args.tenant_code,
            refresh=bool(args.refresh or args.lead_id),
        )
        detail = get_lead_diagnosis(db, lead.id)
        result = detail.get("diagnosis_result") or {}
        brand = detail["brand_name"]
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in brand)[:40]

        report = {
            "report_title": f"{brand} 售前品牌诊断报告",
            "report_type": "diagnosis",
            "report_type_label": "售前诊断",
            "status_label": "已完成",
            "tenant_name": brand,
            "created_at": detail.get("created_at"),
            "report_content": {
                **result,
                "contact_phone": detail.get("contact_phone"),
                "contact_name": detail.get("contact_name"),
                "competitors": detail.get("competitors") or [],
            },
        }
        payload = _normalize_export_payload(report)

        html_path = out_dir / f"{safe}_售前诊断报告_DeepSeek.html"
        pdf_path = out_dir / f"{safe}_售前诊断报告_DeepSeek.pdf"
        html_path.write_text(render_molizhishu_report_html(payload), encoding="utf-8")
        pdf_path.write_bytes(build_molizhishu_pdf(payload))

        sections = result.get("report_sections") or {}
        print(f"lead_id={lead.id} brand={brand}")
        print(f"DeepSeek analysis_html={'yes' if result.get('analysis_html') else 'no'} sections={list(sections.keys())}")
        print(f"HTML -> {html_path}")
        print(f"PDF  -> {pdf_path}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
