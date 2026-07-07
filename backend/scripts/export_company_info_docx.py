"""Export tenant company information to a Word document.

Run from backend:
    $env:PYTHONPATH='D:\\py代码\\GEO优化\\backend'
    .\\.venv\\Scripts\\python.exe scripts\\export_company_info_docx.py
    .\\.venv\\Scripts\\python.exe scripts\\export_company_info_docx.py --tenant-id 6
    .\\.venv\\Scripts\\python.exe scripts\\export_company_info_docx.py --output "D:\\exports\\企业信息汇总.docx"
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.brand import BrandAsset, BrandCompetitor, BrandKeywordGroup
from app.models.knowledge import KnowledgeFile
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.services.brand_service import asset_to_dict, competitor_to_dict, list_keyword_groups
from app.core.region_catalog import region_display_labels
from app.api.v1.endpoints.management import tenant_service_state

PLATFORM_LABELS: dict[str, str] = {
    "deepseek": "DeepSeek",
    "deepseek_mobile": "DeepSeek（移动端）",
    "doubao": "豆包",
    "doubao_mobile": "豆包（移动端）",
    "yuanbao": "元宝",
    "kimi": "Kimi",
    "qianwen": "通义千问",
    "quark": "夸克",
    "baiduai": "百度 AI+",
    "weibo_zhisou": "微博智搜",
    "wenxinyiyan": "文心一言",
}

SERVICE_STATE_LABELS = {
    "active": "服务中",
    "pending": "未开始",
    "expired": "已到期",
    "manual_stopped": "人工停服",
    "canceled": "已取消",
    "stopped": "已停止",
}

SCHEDULE_TYPE_LABELS = {
    "daily_times": "每日定时",
    "weekly": "每周",
    "monthly": "每月",
}


def platform_label(code: str) -> str:
    return PLATFORM_LABELS.get(code, code)


def service_state_label(tenant: Tenant) -> str:
    return SERVICE_STATE_LABELS.get(tenant_service_state(tenant), tenant_service_state(tenant))


def fmt_date(value: date | None) -> str:
    return value.isoformat() if value else "未设置"


def fmt_datetime(value: datetime | None) -> str:
    if value is None:
        return "未设置"
    return value.strftime("%Y-%m-%d %H:%M")


def fmt_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.2f} MB"


def add_heading(doc: Document, text: str, level: int = 1) -> None:
    doc.add_heading(text, level=level)


def add_kv_table(doc: Document, rows: list[tuple[str, str]]) -> None:
    table = doc.add_table(rows=len(rows), cols=2)
    table.style = "Table Grid"
    for index, (key, value) in enumerate(rows):
        table.rows[index].cells[0].text = key
        table.rows[index].cells[1].text = value or "-"
    doc.add_paragraph("")


def add_bullet_list(doc: Document, items: list[str], empty_text: str = "暂无") -> None:
    if not items:
        doc.add_paragraph(empty_text)
        return
    for item in items:
        doc.add_paragraph(str(item), style="List Bullet")


def set_document_style(doc: Document) -> None:
    normal = doc.styles["Normal"]
    normal.font.name = "Microsoft YaHei"
    normal.font.size = Pt(11)


def collect_tenant_users(db, tenant_id: int) -> list[dict]:
    identities = db.scalars(
        select(UserIdentity).where(
            UserIdentity.tenant_id == tenant_id,
            UserIdentity.deleted.is_(False),
        )
    ).all()
    rows: list[dict] = []
    for identity in identities:
        user = db.get(User, identity.user_id)
        if user is None or user.deleted:
            continue
        rows.append(
            {
                "username": user.username,
                "display_name": user.display_name,
                "identity_name": identity.identity_name,
                "role_code": identity.role_code,
                "status": "启用" if user.status else "禁用",
            }
        )
    return rows


def build_company_doc(db, tenant: Tenant) -> Document:
    asset = db.scalar(
        select(BrandAsset).where(BrandAsset.tenant_id == tenant.id, BrandAsset.deleted.is_(False))
    )
    keyword_groups = list_keyword_groups(db, tenant.id) if asset else []
    asset_data = asset_to_dict(asset, keyword_groups)
    competitors = [
        competitor_to_dict(item)
        for item in db.scalars(
            select(BrandCompetitor).where(
                BrandCompetitor.tenant_id == tenant.id,
                BrandCompetitor.deleted.is_(False),
            ).order_by(BrandCompetitor.id)
        ).all()
    ]
    knowledge_files = db.scalars(
        select(KnowledgeFile).where(
            KnowledgeFile.tenant_id == tenant.id,
            KnowledgeFile.deleted.is_(False),
        ).order_by(KnowledgeFile.id)
    ).all()
    users = collect_tenant_users(db, tenant.id)

    doc = Document()
    set_document_style(doc)

    title = doc.add_heading(f"{tenant.name} — 企业信息汇总", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    doc.add_paragraph("")

    add_heading(doc, "一、企业基本信息", level=1)
    add_kv_table(
        doc,
        [
            ("企业名称", tenant.name),
            ("企业编码", tenant.code),
            ("服务状态", service_state_label(tenant)),
            ("服务开始日期", fmt_date(tenant.service_start_date)),
            ("服务结束日期", fmt_date(tenant.service_end_date)),
            ("停服原因", tenant.stop_reason or "无"),
            ("停服时间", fmt_datetime(tenant.stopped_at)),
            ("创建时间", fmt_datetime(tenant.created_at)),
            ("最后更新", fmt_datetime(tenant.updated_at)),
        ],
    )

    add_heading(doc, "二、品牌资产", level=1)
    if asset_data:
        add_kv_table(
            doc,
            [
                ("企业全称", asset_data["company_full_name"]),
                ("品牌主词", asset_data["brand_name"]),
                ("品牌简称", asset_data["brand_short_name"] or "未设置"),
                ("官网 / 主站", asset_data["official_url"] or "未设置"),
                ("监测地区", region_display_labels(asset_data.get("region_codes") or []) or "全部区域"),
                ("品牌说明", asset_data["description"] or "未填写"),
            ],
        )
    else:
        doc.add_paragraph("尚未配置品牌资产。")
        doc.add_paragraph("")

    add_heading(doc, "三、监测关键词", level=1)
    add_heading(doc, "3.1 监测词列表", level=2)
    add_bullet_list(doc, asset_data["monitor_keywords"] if asset_data else [])

    add_heading(doc, "3.2 露出词（别名）", level=2)
    add_bullet_list(doc, asset_data["aliases"] if asset_data else [])

    add_heading(doc, "3.3 产品 / 业务词", level=2)
    add_bullet_list(doc, asset_data["product_keywords"] if asset_data else [])

    add_heading(doc, "3.4 监测词组配置", level=2)
    groups = asset_data["keyword_groups"] if asset_data else []
    if not groups:
        doc.add_paragraph("暂无词组配置。")
    else:
        for group in groups:
            monitor_terms = group.get("monitor_keywords") or [group.get("monitor_keyword")]
            monitor_terms = [str(item).strip() for item in monitor_terms if str(item or "").strip()]
            exposure_terms = [str(item).strip() for item in (group.get("exposure_terms") or []) if str(item or "").strip()]
            doc.add_paragraph(f"词组：{group.get('name') or '未命名'}")
            doc.add_paragraph(f"  监测词：{'、'.join(monitor_terms) or '无'}")
            doc.add_paragraph(f"  露出词：{'、'.join(exposure_terms) or '无'}")
    doc.add_paragraph("")

    add_heading(doc, "四、监测平台", level=1)
    platforms = asset_data["monitored_platforms"] if asset_data else []
    if platforms:
        add_bullet_list(doc, [f"{platform_label(code)}（{code}）" for code in platforms])
    else:
        doc.add_paragraph("尚未购买或配置监测平台。")
    doc.add_paragraph("")

    add_heading(doc, "五、监测计划", level=1)
    if asset_data:
        schedule_type = SCHEDULE_TYPE_LABELS.get(asset_data["schedule_type"], asset_data["schedule_type"])
        add_kv_table(
            doc,
            [
                ("计划类型", schedule_type),
                ("每日执行次数", str(asset_data["schedule_frequency"])),
                ("执行时刻", "、".join(asset_data["schedule_times"]) or "未配置"),
                ("执行星期", "、".join(str(item) for item in asset_data["schedule_weekdays"]) or "不限"),
                ("执行日期", "、".join(str(item) for item in asset_data["schedule_month_days"]) or "不限"),
            ],
        )
    else:
        doc.add_paragraph("尚未配置监测计划。")
        doc.add_paragraph("")

    add_heading(doc, "六、竞品监控", level=1)
    if not competitors:
        doc.add_paragraph("尚未配置竞品。")
    else:
        for index, item in enumerate(competitors, start=1):
            doc.add_paragraph(f"{index}. {item['name']}")
            doc.add_paragraph(f"   简称：{item.get('short_name') or '无'}")
            doc.add_paragraph(f"   类型：{item.get('category') or '未分类'}")
            doc.add_paragraph(f"   官网：{item.get('website_url') or '未填写'}")
            aliases = item.get("aliases") or []
            doc.add_paragraph(f"   别名：{'、'.join(aliases) if aliases else '无'}")
    doc.add_paragraph("")

    add_heading(doc, "七、企业账号", level=1)
    if not users:
        doc.add_paragraph("暂无绑定该企业的用户账号。")
    else:
        table = doc.add_table(rows=1, cols=5)
        table.style = "Table Grid"
        headers = ["登录账号", "显示名称", "身份名称", "角色", "状态"]
        for cell, text in zip(table.rows[0].cells, headers):
            cell.text = text
        for user in users:
            row = table.add_row().cells
            row[0].text = user["username"]
            row[1].text = user["display_name"] or "-"
            row[2].text = user["identity_name"] or "-"
            row[3].text = user["role_code"] or "-"
            row[4].text = user["status"]
    doc.add_paragraph("")

    add_heading(doc, "八、企业知识库文件", level=1)
    if not knowledge_files:
        doc.add_paragraph("知识库暂无上传文件。")
    else:
        table = doc.add_table(rows=1, cols=4)
        table.style = "Table Grid"
        headers = ["文件名", "类型", "大小", "上传时间"]
        for cell, text in zip(table.rows[0].cells, headers):
            cell.text = text
        for item in knowledge_files:
            row = table.add_row().cells
            row[0].text = item.original_name
            row[1].text = item.file_ext
            row[2].text = fmt_size(item.file_size)
            row[3].text = fmt_datetime(item.created_at)

    return doc


def resolve_tenants(db, tenant_id: int | None) -> list[Tenant]:
    stmt = select(Tenant).where(Tenant.deleted.is_(False)).order_by(Tenant.id)
    if tenant_id is not None:
        stmt = stmt.where(Tenant.id == tenant_id)
    tenants = list(db.scalars(stmt).all())
    if tenant_id is not None and not tenants:
        raise SystemExit(f"未找到企业 ID={tenant_id}")
    if not tenants:
        raise SystemExit("数据库中暂无有效企业。")
    return tenants


def default_output_path(tenants: list[Tenant]) -> Path:
    root = Path(__file__).resolve().parents[2]
    if len(tenants) == 1:
        safe_name = tenants[0].name.replace("/", "_").replace("\\", "_")
        return root / "docs" / f"{safe_name}_企业信息汇总.docx"
    return root / "docs" / "全部企业信息汇总.docx"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export company information to Word.")
    parser.add_argument("--tenant-id", type=int, default=None, help="Only export one tenant.")
    parser.add_argument("--output", type=str, default=None, help="Output .docx path.")
    args = parser.parse_args()

    with SessionLocal() as db:
        tenants = resolve_tenants(db, args.tenant_id)
        output_path = Path(args.output) if args.output else default_output_path(tenants)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if len(tenants) == 1:
            doc = build_company_doc(db, tenants[0])
        else:
            doc = Document()
            set_document_style(doc)
            doc.add_heading("全部企业信息汇总", level=0)
            doc.add_paragraph(f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            doc.add_paragraph(f"企业数量：{len(tenants)}")
            doc.add_paragraph("")
            for index, tenant in enumerate(tenants, start=1):
                if index > 1:
                    doc.add_page_break()
                section_doc = build_company_doc(db, tenant)
                for element in section_doc.element.body:
                    doc.element.body.append(element)

        doc.save(output_path)
        print(str(output_path.resolve()))


if __name__ == "__main__":
    main()
