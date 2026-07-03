"""从企业已完成的定时监测任务生成售前诊断报告并导出 PDF。

Run from backend:
    $env:PYTHONPATH='D:\\py代码\\GEO优化\\backend'
    .\\.venv\\Scripts\\python.exe scripts\\import_tenant_lead_diagnosis.py --tenant-code AIDIYA_REAL
    .\\.venv\\Scripts\\python.exe scripts\\import_tenant_lead_diagnosis.py --tenant-id 6 --output "..\\docs\\艾迪亚控股_售前诊断报告.pdf"
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.database import SessionLocal
from app.models.brand import BrandAsset, BrandCompetitor
from app.models.lead_diagnosis import LeadDiagnosis, LeadDiagnosisRun
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.models.tenant import Tenant
from app.models.user import User
from app.services.lead_diagnosis_service import (
    aggregate_lead_diagnosis,
    build_lead_diagnosis_export,
    _load_subtasks,
)


def _pick_platform_user_id(db) -> int | None:
    user = db.scalar(select(User).where(User.username == "demo", User.deleted.is_(False)))
    return user.id if user else None


def _completed_tasks(db, tenant_id: int) -> list[GeoMonitorTask]:
    tasks = list(
        db.scalars(
            select(GeoMonitorTask)
            .where(
                GeoMonitorTask.tenant_id == tenant_id,
                GeoMonitorTask.deleted.is_(False),
                GeoMonitorTask.status == "completed",
            )
            .order_by(GeoMonitorTask.created_at.asc())
        )
    )
    ready: list[GeoMonitorTask] = []
    for task in tasks:
        total = db.scalar(
            select(func.count())
            .select_from(GeoMonitorSubtask)
            .where(GeoMonitorSubtask.task_id == task.task_id)
        ) or 0
        completed = db.scalar(
            select(func.count())
            .select_from(GeoMonitorSubtask)
            .where(
                GeoMonitorSubtask.task_id == task.task_id,
                GeoMonitorSubtask.status == "completed",
            )
        ) or 0
        if total > 0 and completed == total:
            ready.append(task)
    return ready


def _schedule_from_task(task: GeoMonitorTask) -> tuple[str, str]:
    moment = task.created_at or datetime.now()
    return (
        moment.strftime("%Y%m%d-%H%M"),
        moment.strftime("%Y-%m-%d %H:%M"),
    )


def import_tenant_lead_diagnosis(
    db,
    *,
    tenant_id: int,
    contact_note: str | None = None,
    max_rounds: int = 9,
) -> LeadDiagnosis:
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise ValueError(f"企业不存在: tenant_id={tenant_id}")

    asset = db.scalar(select(BrandAsset).where(BrandAsset.tenant_id == tenant_id, BrandAsset.deleted.is_(False)))
    if asset is None:
        raise ValueError(f"企业 {tenant.name} 尚未配置品牌资产")

    tasks = _completed_tasks(db, tenant_id)
    if not tasks:
        raise ValueError(f"企业 {tenant.name} 没有全部完成的监测任务，无法生成诊断")

    tasks = tasks[-max_rounds:]
    prompts = list(dict.fromkeys(item for task in reversed(tasks) for item in (task.prompts_json or []) if str(item).strip()))[:5]
    if not prompts:
        raise ValueError("已完成监测任务中未找到检测问题")

    competitors = [
        row.name
        for row in db.scalars(
            select(BrandCompetitor).where(
                BrandCompetitor.tenant_id == tenant_id,
                BrandCompetitor.deleted.is_(False),
                BrandCompetitor.status.is_(True),
            )
        )
    ]

    lead = LeadDiagnosis(
        brand_name=(asset.brand_name or asset.company_full_name or tenant.name).strip(),
        contact_note=contact_note or f"基于 {tenant.name} 历史监测数据（{len(tasks)} 轮已完成任务）自动生成",
        prompts_json=prompts,
        competitors_json=competitors[:10],
        region_code=asset.region_code,
        schedule_times_json=list(asset.schedule_times_json or ["09:30", "14:30", "20:30"]),
        diagnosis_date=tasks[0].created_at.date(),
        status="collecting",
        created_by_user_id=_pick_platform_user_id(db),
    )
    db.add(lead)
    db.flush()

    for task in tasks:
        schedule_key, schedule_label = _schedule_from_task(task)
        db.add(
            LeadDiagnosisRun(
                lead_diagnosis_id=lead.id,
                schedule_key=schedule_key,
                schedule_label=schedule_label,
                task_id=task.task_id,
                status="completed",
                prompt_count=len(task.prompts_json or []),
                platform_count=len(task.platforms_json or []),
            )
        )

    db.commit()
    db.refresh(lead)

    lead = db.scalar(
        select(LeadDiagnosis)
        .where(LeadDiagnosis.id == lead.id)
        .options(selectinload(LeadDiagnosis.runs))
    )
    subtasks = _load_subtasks(db, lead)
    if not subtasks:
        lead.status = "failed"
        db.commit()
        raise ValueError("关联监测子任务为空，无法汇总")

    result = aggregate_lead_diagnosis(lead, subtasks)
    lead.diagnosis_result_json = result
    lead.health_score = result.get("diagnosis", {}).get("health_score") or result.get("kpis", {}).get("health_score")
    lead.status = "ready"
    db.commit()
    db.refresh(lead)
    return lead


def main() -> None:
    parser = argparse.ArgumentParser(description="从企业已完成监测数据生成售前诊断 PDF")
    parser.add_argument("--tenant-id", type=int, help="企业 ID")
    parser.add_argument("--tenant-code", default="AIDIYA_REAL", help="企业编码，默认 AIDIYA_REAL")
    parser.add_argument("--output", help="PDF 输出路径，默认 docs/{品牌名}_售前诊断报告.pdf")
    parser.add_argument("--note", help="销售备注")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.tenant_id:
            tenant = db.scalar(select(Tenant).where(Tenant.id == args.tenant_id, Tenant.deleted.is_(False)))
        else:
            tenant = db.scalar(select(Tenant).where(Tenant.code == args.tenant_code, Tenant.deleted.is_(False)))
        if tenant is None:
            raise SystemExit("未找到目标企业")

        lead = import_tenant_lead_diagnosis(db, tenant_id=tenant.id, contact_note=args.note)
        pdf_bytes, filename, _mime = build_lead_diagnosis_export(db, lead.id, export_format="pdf")

        if args.output:
            output_path = Path(args.output)
        else:
            repo_root = Path(__file__).resolve().parents[2]
            safe_name = lead.brand_name.replace("/", "_").replace("\\", "_")
            output_path = repo_root / "docs" / f"{safe_name}_售前诊断报告.pdf"

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(pdf_bytes)

        kpis = (lead.diagnosis_result_json or {}).get("kpis") or {}
        print(f"诊断 ID: {lead.id}")
        print(f"品牌: {lead.brand_name}")
        print(f"状态: {lead.status}")
        print(f"健康分: {lead.health_score}")
        print(f"提及率: {kpis.get('mention_rate')}%")
        print(f"平均排名: {kpis.get('avg_rank')}")
        print(f"抓取轮次: {kpis.get('schedule_round_count')}")
        print(f"PDF: {output_path}")
        print(f"文件名: {filename}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
