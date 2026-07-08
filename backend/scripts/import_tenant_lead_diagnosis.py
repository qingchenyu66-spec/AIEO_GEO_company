"""从企业已完成的定时监测任务生成售前诊断报告并导出 PDF。

Run from backend:
    $env:PYTHONPATH='D:\\py代码\\GEO优化\\backend'
    .\\.venv\\Scripts\\python.exe scripts\\import_tenant_lead_diagnosis.py --tenant-code AIDIYA_REAL
    .\\.venv\\Scripts\\python.exe scripts\\import_tenant_lead_diagnosis.py --tenant-id 6 --output "..\\docs\\艾迪亚控股_售前诊断报告.pdf"
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.tenant import Tenant
from app.models.user import User
from app.services.lead_diagnosis_service import build_lead_diagnosis_export, import_tenant_lead_diagnosis


def _pick_platform_user_id(db) -> int | None:
    user = db.scalar(select(User).where(User.username == "demo", User.deleted.is_(False)))
    return user.id if user else None


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

        lead = import_tenant_lead_diagnosis(
            db,
            tenant_id=tenant.id,
            contact_note=args.note,
            created_by_user_id=_pick_platform_user_id(db),
        )
        pdf_bytes, filename, _ = build_lead_diagnosis_export(db, lead.id, export_format="pdf")

        output_path = Path(args.output) if args.output else Path("..") / "docs" / f"{lead.brand_name}_售前诊断报告.pdf"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(pdf_bytes)
        print(f"已生成售前诊断 lead_id={lead.id} -> {output_path} ({filename})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
