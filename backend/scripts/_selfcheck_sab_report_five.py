# -*- coding: utf-8 -*-
"""ponytail: SAB 报告五条回归自检（空心点/无城市表/排名去重/点评无源码/拆页无孤 P0）。"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.services.lead_diagnosis_analytics import (
    _build_molizhishu_ranking_rows,
    compact_ranking_rows_for_deck,
)
from app.services.report_chart_service import (
    _collect_entity_series,
    build_entity_rank_trend_chart,
)
from app.services.report_molizhishu_context_service import build_molizhishu_report_context
from app.services.report_molizhishu_fragments import render_prompt_comment
from app.services.report_molizhishu_pdf_service import _pack_js

ROOT = Path(__file__).resolve().parents[1]


def _check_hollow_points() -> None:
    rows = [
        {
            "schedule_label": f"2026-08-0{d} 20:30",
            "avg_rank": 5.0 if d == 4 else None,
            "entities": {
                "SAB": 5.0 if d == 4 else None,
                "YKK": 5.0 if d == 4 else None,
                "SBS": None,
            },
        }
        for d in (4, 5, 6, 7)
    ]
    series, _labels, _max_rank = _collect_entity_series(
        rows, brand="SAB", entities=["SAB", "YKK", "SBS"]
    )
    by_name = {item["name"]: item for item in series}
    assert by_name["SAB"]["points"] and by_name["SAB"]["absent"], by_name["SAB"]
    assert len(by_name["SAB"]["absent"]) == 3
    png = build_entity_rank_trend_chart(
        rows, brand="SAB", tracked_entities=["SAB", "YKK", "SBS"], title=""
    )
    assert png and len(png) > 800, "chart png missing"


def _check_city_hidden() -> None:
    payload = {
        "title": "t",
        "report_type": "diagnosis",
        "brand_name": "SAB伟星拉链",
        "tenant_name": "SAB",
        "competitors": ["YKK"],
        "period_label": "p",
        "generated_at": "2026-08-10T15:00:00",
        "platform_stats": [],
        "rank_trend": [],
        "prompt_analytics": [],
        "kpis": {},
        "diagnosis": {},
        "top_sources": [],
        "matrix_rows": [],
        "brand_city_matrix": {
            "prompts": ["q1"],
            "rows": [{"label": "全部区域", "cells": [1.0]}],
        },
        "tracked_entities": ["SAB伟星拉链"],
    }
    ctx = build_molizhishu_report_context(payload, platform_names={})
    assert ctx.get("show_city_table") is False


def _check_ranking_dedupe() -> None:
    class Sub:
        def __init__(self) -> None:
            self.task_id = "t1"
            self.prompt = "服饰辅料供应商怎么选？"
            self.status = "completed"
            self.answer_content = "x"
            self.all_rankings_json = [
                {"name": "YKK（日本吉田拉链）", "rank": 2},
            ]
            self.mention_position = 2
            self.updated_at = datetime(2026, 8, 5, 14, 30)

    class Run:
        def __init__(self) -> None:
            self.schedule_key = "20260805-1430"
            self.schedule_label = "2026-08-05 14:30"
            self.task_id = "t1"

    rows = _build_molizhishu_ranking_rows(
        [Sub()],
        brand="SAB伟星拉链",
        competitors=["YKK（日本吉田拉链）"],
        task_run_map={"t1": Run()},
    )
    labels = [str(r.get("type_label")) for r in rows]
    assert labels.count("最差") == 0, labels
    assert "最优" in labels or "最近" in labels
    compacted = compact_ranking_rows_for_deck(rows)
    assert not any(str(r.get("type_label")) == "最差" for r in compacted)


def _check_comment_no_raw_html() -> None:
    raw = (
        "\u63d0\u53ca\u738722.2%\uff0c\u9700\u53d1\u5e03\u5185\u5bb9\uff0c"
        '<strong style="color:#ff6666;">\u76ee\u6807\u63d0\u5347\u63d0\u53ca\u7387\u81f350%</strong>\u3002'
    )
    html = render_prompt_comment(raw)
    plain = re.sub(r"<[^>]+>", "", html)
    assert "&lt;strong" not in html
    assert "&lt;/" not in html
    assert "\u76ee\u6807\u63d0\u5347\u63d0\u53ca\u7387\u81f350%" in plain
    assert "22.2%" in plain


def _check_pack_no_orphan_p0() -> None:
    cards = []
    for i in range(10):
        cards.append(f'<div class="pack-item analysis-card analysis-block" style="height:110px">结论{i}</div>')
    cards.append('<div class="pack-item analysis-card analysis-section-sub" style="height:48px"><h3>P0</h3></div>')
    for i in range(6):
        cards.append(f'<div class="pack-item analysis-card analysis-block" style="height:110px">P0正文{i}</div>')
    cards.append('<div class="pack-item analysis-card analysis-section-sub" style="height:48px"><h3>P1</h3></div>')
    for i in range(4):
        cards.append(f'<div class="pack-item analysis-card analysis-block" style="height:110px">P1正文{i}</div>')
    # tip empty card trap
    tips = "".join(
        [
            f'<div class="pack-item analysis-card tip-as-analysis" style="height:100px">'
            f'<p><span class="tip-card-index">{i:02d}</span>有内容{i}</p></div>'
            for i in range(1, 9)
        ]
        + [
            '<div class="pack-item analysis-card tip-as-analysis" style="height:40px"><p> </p></div>',
        ]
    )
    html = f"""<!DOCTYPE html><html><head><style>
    .slide{{width:2520px;height:1417px;position:relative;overflow:hidden}}
    .pack-body{{position:absolute;left:132px;top:210px;width:2260px;max-height:1000px;overflow:hidden}}
    .pack-item{{margin:0 0 12px;background:#eee}}
    .slide-title{{position:absolute;left:140px;top:118px}}
    </style></head><body><main class="deck">
    <section class="slide" data-pack="1" data-merge-group="source-tips">
      <h2 class="slide-title">信源优化建议</h2>
      <div class="pack-body dark-content tip-slide-body">{tips}</div>
    </section>
    <section class="slide" data-pack="1" data-merge-group="analysis">
      <h2 class="slide-title">数据分析与优化建议</h2>
      <div class="pack-body light-content analysis-slide-body">{''.join(cards)}</div>
    </section>
    <section class="slide slide--thanks"><h2 class="slide-title">感谢</h2></section>
    </main></body></html>"""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 2520, "height": 1417})
        page.set_content(html, wait_until="load")
        result = page.evaluate(_pack_js())
        titles = page.locator(".slide-title").all_text_contents()
        analysis_bodies = page.locator(".slide[data-merge-group='analysis'] .pack-body").all()
        orphans = []
        for body in analysis_bodies:
            text = re.sub(r"\s+", "", body.inner_text())
            if text in {"P0", "P1", "P2"} or re.fullmatch(r"P[012]", text):
                orphans.append(text)
        empty_tips = page.evaluate(
            """() => Array.from(document.querySelectorAll('.tip-as-analysis')).filter(el => {
              const t = (el.textContent || '').replace(/\\s+/g,'').trim();
              return t.length < 2;
            }).length"""
        )
        still = int(result.get("stillClipped") or 0)
        browser.close()
    assert still == 0, result
    assert not orphans, f"orphan priority slides: {orphans} titles={titles}"
    assert empty_tips == 0, f"empty tip cards left: {empty_tips}"
    assert any("数据分析" in t for t in titles)


def main() -> None:
    _check_hollow_points()
    print("ok hollow")
    _check_city_hidden()
    print("ok city hidden")
    _check_ranking_dedupe()
    print("ok ranking dedupe")
    _check_comment_no_raw_html()
    print("ok comment")
    _check_pack_no_orphan_p0()
    print("ok pack")
    print("ALL_OK")


if __name__ == "__main__":
    main()
