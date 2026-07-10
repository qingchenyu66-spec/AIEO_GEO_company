#!/usr/bin/env python3
"""生成 A/B 主题售前诊断 HTML 到桌面，便于浏览器对比。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.services.lead_diagnosis_service import get_lead_diagnosis
from app.services.report_export_service import _normalize_export_payload
from app.services.report_molizhishu_pdf_service import render_molizhishu_report_html
from app.services.report_molizhishu_theme import THEMES, theme_scope


def _lead_payload(lead_id: int) -> dict:
    db = SessionLocal()
    try:
        detail = get_lead_diagnosis(db, lead_id, current=None)
        if detail.get("status") != "ready":
            raise SystemExit(f"lead #{lead_id} status={detail.get('status')}，需 ready 才能导出")
        result = detail.get("diagnosis_result") or {}
        report = {
            "report_title": f"{detail['brand_name']} 售前品牌诊断报告",
            "report_type": "diagnosis",
            "report_type_label": "售前诊断",
            "status_label": "已完成",
            "tenant_name": detail["brand_name"],
            "data_summary": result.get("diagnosis", {}).get("sentiment_summary"),
            "created_at": detail.get("created_at"),
            "report_content": {
                **result,
                "contact_phone": detail.get("contact_phone"),
                "contact_name": detail.get("contact_name"),
                "competitors": detail.get("competitors") or [],
            },
        }
        return _normalize_export_payload(report)
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate diagnosis HTML theme previews on Desktop")
    parser.add_argument("--lead-id", type=int, default=2)
    parser.add_argument("--out-dir", type=Path, default=Path.home() / "Desktop")
    args = parser.parse_args()

    payload = _lead_payload(args.lead_id)
    brand = str(payload.get("brand_name") or "report").replace("/", "-")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for theme_id, theme in THEMES.items():
        if theme_id == "portal":
            continue
        with theme_scope(theme_id):
            html = render_molizhishu_report_html(payload, theme=theme_id)
        out = args.out_dir / f"lead{args.lead_id}_{brand}_theme_{theme_id}_{theme.label}.html"
        out.write_text(html, encoding="utf-8")
        written.append(out)
        print(out)

    index = args.out_dir / f"lead{args.lead_id}_theme_compare.html"
    links = "\n".join(
        f'<li><a href="{p.name}" target="_blank">{p.name}</a> — {THEMES["a" if "theme_a" in p.name else "b"].label}</li>'
        for p in written
    )
    index.write_text(
        f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>诊断报告主题对比</title>
<style>body{{font-family:"Microsoft YaHei",sans-serif;padding:40px;background:#edf3f9;color:#10233f}}
a{{color:#1677ff;font-size:18px}}</style></head><body>
<h1>Lead #{args.lead_id} 售前诊断 — 主题对比</h1>
<ul>{links}</ul>
<p style="color:#667c99;margin-top:24px">在浏览器中分别打开 A/B 两个 HTML 文件对比表格与图表配色。</p>
</body></html>""",
        encoding="utf-8",
    )
    print(index)
    print(f"DONE {len(written)} themes -> {args.out_dir}")


if __name__ == "__main__":
    main()
