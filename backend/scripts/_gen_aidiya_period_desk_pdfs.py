"""生产机：艾迪亚周/月/季/年 PDF（真实数拼本期/上期）→ 桌面「周期报告」。

用法（生产）::

  cd /opt/geo/AIEO_GEO/backend
  PYTHONPATH=. .venv/bin/python /tmp/_gen_aidiya_period_desk_pdfs.py
"""

from __future__ import annotations

import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TENANT_ID = 6
OUT_DIR = Path("/tmp/周期报告")
# 2026-07-29 - 桌面验收：用现有真实监测日对半/自然周拼本期上期，不改库


def _list_stat_days(db, tenant_id: int) -> list[date]:
    from sqlalchemy import select

    from app.models.monitor import GeoMonitorDailyStat

    rows = db.scalars(
        select(GeoMonitorDailyStat.stat_date)
        .where(GeoMonitorDailyStat.tenant_id == tenant_id)
        .distinct()
        .order_by(GeoMonitorDailyStat.stat_date.asc())
    ).all()
    return [d for d in rows if d is not None]


def _split_halves(days: list[date]) -> tuple[tuple[date, date], tuple[date, date]]:
    if len(days) < 2:
        raise RuntimeError(f"可用监测日不足：{days}")
    mid = max(1, len(days) // 2)
    prev_days = days[:mid]
    cur_days = days[mid:]
    if not cur_days:
        cur_days = [days[-1]]
        prev_days = days[:-1]
    return (prev_days[0], prev_days[-1]), (cur_days[0], cur_days[-1])


def _windows(today: date, days: list[date], report_type: str):
    """返回 (label_cur, label_prev, data_cur, data_prev)。"""
    from app.services.report_period_comparison_service import (
        previous_period_bounds,
        schedule_trigger_for_sample,
    )
    from app.services.report_period_service import period_bounds

    if report_type == "weekly":
        # 自然上周完整周 vs 再上一周；库内 7/14–7/27 有数
        trigger = schedule_trigger_for_sample("weekly", today)
        cur = period_bounds("weekly", trigger)
        prev = previous_period_bounds("weekly", cur[0], cur[1])
        return cur, prev, cur, prev

    # 月/季/年：封面按自然本期/上期标注，数据用现有监测日对半
    if report_type == "monthly":
        label_cur = (date(today.year, today.month, 1), today)
    elif report_type == "quarterly":
        q_month = ((today.month - 1) // 3) * 3 + 1
        label_cur = (date(today.year, q_month, 1), today)
    elif report_type == "annual":
        label_cur = (date(today.year, 1, 1), today)
    else:
        raise ValueError(report_type)
    label_prev = previous_period_bounds(report_type, label_cur[0], label_cur[1])
    data_prev, data_cur = _split_halves(days)
    return label_cur, label_prev, data_cur, data_prev


def _assemble(
    db,
    *,
    tenant_id: int,
    report_type: str,
    label_cur: tuple[date, date],
    label_prev: tuple[date, date],
    data_cur: tuple[date, date],
    data_prev: tuple[date, date],
    generated: date,
) -> dict:
    from app.services.brand_service import list_competitors
    from app.services.report_period_comparison_service import (
        _resolve_platform_codes,
        build_comparison,
        build_competitor_analytics_from_periods,
        build_keyword_analytics,
        build_period_trend,
        build_preface,
        build_sample_content_modules,
        collect_tenant_monitor_keywords,
        polish_content_modules_for_client_v2,
        polish_preface_for_client_v2,
    )
    from app.services.report_period_service import period_label
    from app.services.report_service import build_tenant_monitor_snapshot

    lbl = period_label(report_type, label_cur[0], label_cur[1])
    prev_lbl = period_label(report_type, label_prev[0], label_prev[1])
    current = build_tenant_monitor_snapshot(db, tenant_id, start_date=data_cur[0], end_date=data_cur[1])
    previous = build_tenant_monitor_snapshot(db, tenant_id, start_date=data_prev[0], end_date=data_prev[1])
    brand_name = str(current.get("brand_name") or "")
    all_keywords = collect_tenant_monitor_keywords(db, tenant_id)
    platform_codes = _resolve_platform_codes(current)
    comparison = build_comparison(
        report_type,
        current,
        previous,
        prev_lbl,
        used_demo_previous=False,
        allow_demo_fallback=False,
    )
    competitors = [item.name for item in list_competitors(db, tenant_id) if item.name]
    keyword_analytics = build_keyword_analytics(
        db,
        tenant_id,
        start=data_cur[0],
        end=data_cur[1],
        prev_start=data_prev[0],
        prev_end=data_prev[1],
    )
    content_modules = build_sample_content_modules(
        brand_name=brand_name,
        snapshot=current,
        report_type=report_type,
        period_lbl=lbl,
        period_start=label_cur[0],
        period_end=label_cur[1],
        competitor_names=competitors,
        v2=True,
    )
    preface = polish_preface_for_client_v2(
        build_preface(
            modules=content_modules,
            report_type=report_type,
            previous_period_label=prev_lbl,
            monitor_keywords=all_keywords,
        ),
        brand_name=brand_name,
    )
    content_modules = polish_content_modules_for_client_v2(
        content_modules,
        brand_name=brand_name,
        report_type=report_type,
        period_range=str(preface.get("period_range") or lbl),
        completed=int((current.get("kpis") or {}).get("completed_count") or 0),
        platform_count=int(current.get("platform_count") or len(platform_codes)),
    )
    trend = build_period_trend(db, tenant_id, report_type, data_cur[0], data_cur[1])
    competitor_analytics = build_competitor_analytics_from_periods(
        db,
        tenant_id=tenant_id,
        brand_name=brand_name,
        competitor_names=competitors,
        report_type=report_type,
        trend=trend,
        cur_start=data_cur[0],
        cur_end=data_cur[1],
        prev_start=data_prev[0],
        prev_end=data_prev[1],
    )
    return {
        "brand_name": brand_name,
        "report_type": report_type,
        "period_lbl": lbl,
        "comparison": comparison,
        "snapshot": current,
        "preface": preface,
        "content_modules": content_modules,
        "trend": trend,
        "keyword_analytics": keyword_analytics,
        "competitor_analytics": competitor_analytics,
        "competitors": competitors,
        "platform_codes": platform_codes,
        "generated": generated,
    }


def _pdf_from_html(html: str) -> bytes:
    from playwright.sync_api import sync_playwright

    from app.services.report_period_deck_pdf_service import (
        _ECHARTS_READY_TIMEOUT_MS,
        _SLIDE_HEIGHT_PX,
        _SLIDE_WIDTH_PX,
        _ensure_chromium,
        _inject_pdf_base_href,
        _install_report_asset_routes,
        _merge_slide_pdfs,
        _pack_js,
    )

    html = _inject_pdf_base_href(html)
    browser = _ensure_chromium(sync_playwright)
    page = browser.new_page(
        viewport={"width": _SLIDE_WIDTH_PX, "height": _SLIDE_HEIGHT_PX},
        device_scale_factor=1,
    )
    page_pdfs: list[bytes] = []
    try:
        _install_report_asset_routes(page)
        page.emulate_media(media="screen")
        page.set_content(html, wait_until="domcontentloaded", timeout=180_000)
        page.evaluate(
            """() => new Promise((resolve) => {
                if (window.echarts) { resolve(); return; }
                const start = Date.now();
                const tick = () => {
                    if (window.echarts || Date.now() - start > 8000) resolve();
                    else requestAnimationFrame(tick);
                };
                tick();
            })"""
        )
        page.evaluate(
            """() => Promise.race([
                Promise.all([
                    document.fonts.ready,
                    ...[...document.images].map((img) =>
                        img.complete
                            ? Promise.resolve()
                            : new Promise((resolve) => {
                                img.addEventListener('load', resolve, { once: true });
                                img.addEventListener('error', resolve, { once: true });
                              })
                    ),
                ]),
                new Promise((resolve) => setTimeout(resolve, 8000)),
            ])"""
        )
        page.evaluate(
            f"""() => new Promise((resolve) => {{
                const nodes = [...document.querySelectorAll('.echart-canvas')];
                if (!nodes.length) {{ resolve(); return; }}
                const start = Date.now();
                const tick = () => {{
                    const ready = nodes.every((el) => el.querySelector('canvas'));
                    if (ready || Date.now() - start > {_ECHARTS_READY_TIMEOUT_MS}) resolve();
                    else requestAnimationFrame(tick);
                }};
                tick();
            }})"""
        )
        page.evaluate(_pack_js())
        page.evaluate(
            f"""() => {{
                if (document.getElementById('geo-pdf-page-mode')) return;
                const style = document.createElement('style');
                style.id = 'geo-pdf-page-mode';
                style.textContent = `
                  html, body {{
                    margin: 0 !important; padding: 0 !important; overflow: hidden !important;
                    width: {_SLIDE_WIDTH_PX}px !important; height: {_SLIDE_HEIGHT_PX}px !important;
                  }}
                  main.deck {{
                    margin: 0 !important; padding: 0 !important; gap: 0 !important;
                    width: {_SLIDE_WIDTH_PX}px !important;
                  }}
                `;
                document.head.appendChild(style);
            }}"""
        )
        slides = page.locator("main.deck > section.slide")
        n = slides.count()
        for i in range(n):
            page.evaluate(
                """(idx) => {
                    document.querySelectorAll('main.deck > section.slide').forEach((el, j) => {
                        el.style.display = j === idx ? 'block' : 'none';
                    });
                }""",
                i,
            )
            page_pdfs.append(
                page.pdf(
                    width=f"{_SLIDE_WIDTH_PX}px",
                    height=f"{_SLIDE_HEIGHT_PX}px",
                    print_background=True,
                    margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                )
            )
        return _merge_slide_pdfs(page_pdfs)
    finally:
        page.close()


def main() -> None:
    from app.core.database import SessionLocal
    from app.services.report_period_deck_pdf_service import render_period_deck_html_from_bundle

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today()
    jobs = [
        ("weekly", "周报"),
        ("monthly", "月报"),
        ("quarterly", "季报"),
        ("annual", "年报"),
    ]
    db = SessionLocal()
    try:
        days = _list_stat_days(db, TENANT_ID)
        print("stat_days", len(days), days[0] if days else None, days[-1] if days else None, flush=True)
        for rtype, cn in jobs:
            label_cur, label_prev, data_cur, data_prev = _windows(today, days, rtype)
            print(
                f"== {rtype} label {label_cur[0]}~{label_cur[1]} / {label_prev[0]}~{label_prev[1]} "
                f"data {data_cur[0]}~{data_cur[1]} / {data_prev[0]}~{data_prev[1]}",
                flush=True,
            )
            t0 = time.time()
            bundle = _assemble(
                db,
                tenant_id=TENANT_ID,
                report_type=rtype,
                label_cur=label_cur,
                label_prev=label_prev,
                data_cur=data_cur,
                data_prev=data_prev,
                generated=today,
            )
            html = render_period_deck_html_from_bundle(bundle, embed_assets=True)
            pdf = _pdf_from_html(html)
            name = f"艾迪亚_{cn}_{label_cur[0].isoformat()}_{label_cur[1].isoformat()}.pdf"
            path = OUT_DIR / name
            path.write_bytes(pdf)
            kpis = (bundle.get("snapshot") or {}).get("kpis") or {}
            print(
                f"OK {name} bytes={len(pdf)} completed={kpis.get('completed_count')} "
                f"{time.time()-t0:.1f}s",
                flush=True,
            )
    finally:
        db.close()
    print("DONE", OUT_DIR, flush=True)


if __name__ == "__main__":
    main()
