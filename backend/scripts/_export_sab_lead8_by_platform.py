# 2026-08-10 - SAB lead#8 按平台拆导：豆包/ChatGPT 各一份，豆包版禁止出现 GPT
"""Re-aggregate SAB lead diagnosis per platform and export HTML to Desktop."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Allow local or prod paths
for root in (
    Path(__file__).resolve().parents[1],
    Path("/opt/geo/AIEO_GEO/backend"),
):
    if (root / "app").is_dir():
        sys.path.insert(0, str(root))
        os.chdir(root)
        break

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import SessionLocal
from app.models.lead_diagnosis import LeadDiagnosis
from app.services.lead_diagnosis_service import (
    _load_subtasks,
    _task_map,
    _task_region_map,
    aggregate_lead_diagnosis,
)
from app.services.report_export_service import build_report_export

LEAD_ID = 8
DESKTOP = Path.home() / "Desktop"
# On prod Linux, HOME may be /root — still write there then scp; also accept env override
OUT_DIR = Path(os.environ.get("SAB_EXPORT_OUT", str(DESKTOP)))

TARGETS = (
    ("doubao", "豆包", ("ChatGPT", "chatgpt", "GPT", "OpenAI", "openai")),
    ("chatgpt", "ChatGPT", ("豆包", "doubao", "doubao_mobile")),
)


def _scrub_text(text: str, forbid: tuple[str, ...]) -> str:
    out = text
    for token in sorted(forbid, key=len, reverse=True):
        if not token:
            continue
        # drop whole sentences/clauses that exist only to contrast the other platform
        out = re.sub(
            rf"[^。；;\n]*{re.escape(token)}[^。；;\n]*[。；;]?",
            "",
            out,
            flags=re.I,
        )
        out = re.sub(re.escape(token), "", out, flags=re.I)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def _scrub_obj(value: Any, forbid: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        return _scrub_text(value, forbid)
    if isinstance(value, list):
        return [_scrub_obj(item, forbid) for item in value]
    if isinstance(value, dict):
        return {k: _scrub_obj(v, forbid) for k, v in value.items()}
    return value


def _scrub_html(html: str, forbid: tuple[str, ...], keep_label: str) -> str:
    # title / chips
    html = re.sub(
        r"(GEO优化平台品牌分析报告_[^_<]*)_[^<]*(</title>)",
        rf"\1_{keep_label}\2",
        html,
        count=1,
    )
    for token in sorted(forbid, key=len, reverse=True):
        html = re.sub(
            rf'<span class="platform-chip">\s*{re.escape(token)}\s*</span>\s*',
            "",
            html,
            flags=re.I,
        )
    # table header cells / body cells that are only the other platform name
    for token in forbid:
        html = re.sub(
            rf"<th[^>]*>\s*{re.escape(token)}\s*</th>",
            "",
            html,
            flags=re.I,
        )
    # scrub visible text nodes roughly via paragraph-level replace
    def _repl_textish(m: re.Match[str]) -> str:
        return _scrub_text(m.group(0), forbid)

    # only scrub outside base64 to avoid corrupting images
    parts = re.split(r"(data:image/[^;]+;base64,[A-Za-z0-9+/=\n\r]+)", html)
    for i, part in enumerate(parts):
        if part.startswith("data:image/"):
            continue
        parts[i] = _scrub_obj(part, forbid) if False else _scrub_text_keep_tags(part, forbid)
    return "".join(parts)


def _scrub_text_keep_tags(chunk: str, forbid: tuple[str, ...]) -> str:
    """Scrub forbid tokens in HTML text without touching tags/attrs aggressively."""
    out = chunk
    for token in sorted(forbid, key=len, reverse=True):
        out = re.sub(re.escape(token), "", out, flags=re.I)
    # clean empty comparison leftovers
    out = re.sub(r"、{2,}", "、", out)
    out = re.sub(r"（\s*）", "", out)
    out = re.sub(r"\(\s*\)", "", out)
    return out


def export_one(db, lead: LeadDiagnosis, platform: str, label: str, forbid: tuple[str, ...]) -> Path:
    tasks = _task_map(db, lead)
    all_subtasks = _load_subtasks(db, lead)
    scoped = [item for item in all_subtasks if str(item.platform or "").strip() == platform]
    if not scoped:
        raise SystemExit(f"no subtasks for platform={platform}")

    # 2026-08-10 - 勿改 ORM platforms_json：聚合内 DP 补标会 commit，临时单平台会落库
    # 单平台范围已由 scoped 子任务保证；AI/KPI 按传入 subtasks 聚合
    result = aggregate_lead_diagnosis(
        lead,
        scoped,
        task_region_map=_task_region_map(tasks),
        db=db,
    )

    result = _scrub_obj(result, forbid)
    # ensure platform_stats only keep this platform
    snap = dict(result.get("monitor_snapshot") or {})
    stats = [
        row
        for row in (snap.get("platform_stats") or result.get("monitor_snapshot", {}).get("platform_stats") or [])
        if str((row or {}).get("platform") or "") == platform
    ]
    if "monitor_snapshot" in result:
        result["monitor_snapshot"] = {
            **result["monitor_snapshot"],
            "platform_stats": [
                row
                for row in (result["monitor_snapshot"].get("platform_stats") or [])
                if str(row.get("platform") or "") == platform
            ],
            "matrix_rows": [
                row
                for row in (result["monitor_snapshot"].get("matrix_rows") or [])
                if str(row.get("platform") or "") == platform
            ],
        }
    result["matrix_rows"] = [
        row for row in (result.get("matrix_rows") or []) if str(row.get("platform") or "") == platform
    ]

    report = {
        "report_title": f"{lead.brand_name} 售前品牌诊断报告（{label}）",
        "report_type": "diagnosis",
        "report_type_label": "售前诊断",
        "status_label": "已完成",
        "tenant_name": lead.brand_name,
        "data_summary": (result.get("diagnosis") or {}).get("sentiment_summary"),
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "report_content": {
            **result,
            "contact_phone": lead.contact_phone,
            "contact_name": lead.contact_name,
            "competitors": list(lead.competitors_json or []),
        },
    }
    data, _filename, _mime = build_report_export(report, "html", db=db)
    html = data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else str(data)
    html = _scrub_html(html, forbid, keep_label=label)

    # hard assert for doubao
    plain = re.sub(r"data:image/[^;]+;base64,[A-Za-z0-9+/=\n\r]+", "[IMG]", html)
    for token in forbid:
        if re.search(re.escape(token), plain, flags=re.I):
            # second pass
            html = _scrub_html(html, forbid, keep_label=label)
            plain = re.sub(r"data:image/[^;]+;base64,[A-Za-z0-9+/=\n\r]+", "[IMG]", html)
            if re.search(re.escape(token), plain, flags=re.I):
                raise SystemExit(f"{label} export still contains forbidden token: {token}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_brand = "".join(ch if ch not in '\\/:*?"<>|' else "_" for ch in str(lead.brand_name))
    out = OUT_DIR / f"{safe_brand}_售前品牌诊断报告_{label}.html"
    out.write_text(html, encoding="utf-8")
    # also dump result json for QA
    (OUT_DIR / f"{safe_brand}_diagnosis_{platform}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(
        "exported",
        out,
        "mb",
        round(out.stat().st_size / 1024 / 1024, 2),
        "subs",
        len(scoped),
        "kpi",
        (result.get("kpis") or {}),
    )
    return out


def main() -> None:
    db = SessionLocal()
    try:
        lead = db.scalar(
            select(LeadDiagnosis)
            .where(LeadDiagnosis.id == LEAD_ID, LeadDiagnosis.deleted.is_(False))
            .options(selectinload(LeadDiagnosis.runs))
        )
        if lead is None:
            raise SystemExit(f"lead {LEAD_ID} not found")
        if lead.status != "ready":
            raise SystemExit(f"lead {LEAD_ID} status={lead.status}")
        print("lead", lead.id, lead.brand_name, lead.platforms_json)
        paths = []
        for platform, label, forbid in TARGETS:
            paths.append(export_one(db, lead, platform, label, forbid))
        print("DONE", [str(p) for p in paths])
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    main()
