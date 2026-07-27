"""模力指数风格售前诊断报告模板测试。"""

from datetime import datetime

from app.services.lead_diagnosis_analytics import _build_molizhishu_ranking_rows
from app.services.report_molizhishu_context_service import build_molizhishu_report_context
from app.services.report_molizhishu_fragments import (
    render_competitor_landscape_table,
    render_matrix_table,
    render_mention_table,
    render_prompt_platform_matrix,
)
from app.services.report_molizhishu_pdf_service import pdf_from_slide_pngs, render_molizhishu_report_html


class _SubtaskStub:
    def __init__(self, *, task_id: str, prompt: str, rankings: list, updated_at: datetime) -> None:
        self.task_id = task_id
        self.prompt = prompt
        self.status = "completed"
        self.answer_content = "ok"
        self.all_rankings_json = rankings
        self.mention_position = None
        self.updated_at = updated_at


class _RunStub:
    def __init__(self, schedule_key: str, schedule_label: str, task_id: str) -> None:
        self.schedule_key = schedule_key
        self.schedule_label = schedule_label
        self.task_id = task_id


def _demo_payload() -> dict:
    return {
        "title": "春全合珠宝 售前品牌诊断报告",
        "report_type": "diagnosis",
        "brand_name": "春全合珠宝",
        "tenant_name": "春全合珠宝",
        "contact_phone": "13031099925",
        "competitors": [],
        "period_label": "2026-07-02 至 2026-07-09 · 三天九次均值",
        "generated_at": "2026-07-09T14:58:05",
        "platform_stats": [{"platform": "deepseek", "mention_rate": 60.0, "completed": 9, "total": 9}],
        "rank_trend": [
            {
                "schedule_key": "r1",
                "schedule_label": "2026-07-03 09:30",
                "avg_rank": 2.0,
                "entities": {"春全合珠宝": 2.0},
            }
        ],
        "tracked_entities": ["春全合珠宝"],
        "health_score": 72,
        "mention_rate": 36.9,
        "avg_rank": 4.2,
        "top3_rate": 19.2,
        "completed_count": 120,
        "source_count": 48,
        "executive_summary": "监测期内品牌在部分语义词表现稳定，但分平台差异显著。",
        "highlights": [
            "高铁广告推荐语义词平均排名第 3.8，为当前最优场景",
            "微博智搜提及率显著高于夸克与 DeepSeek",
        ],
        "platform_stats": [
            {"platform": "deepseek", "completed": 40, "mention_rate": 6.2, "avg_rank": 5.1},
            {"platform": "weibo_zhisou", "completed": 40, "mention_rate": 82.5, "avg_rank": 3.2},
        ],
        "matrix_rows": [
            {"prompt": "北京冰种翡翠手镯品牌哪家好", "platform": "deepseek", "mention_rate": 10.0, "avg_rank": 4.0},
        ],
        "sentiment_counts": {"positive": 90, "neutral": 8, "negative": 2},
        "positive_rate": 98.0,
        "diagnosis": {
            "strength_points": "口碑与提及率表现稳定",
            "weakness_points": "部分语义词未进 Top3",
            "recommendation": "补充垂直内容并强化引用布局",
        },
        "brand_date_matrix": {
            "prompts": ["北京冰种翡翠手镯品牌哪家好"],
            "rows": [{"label": "2026-07-09", "cells": [1.0]}],
        },
        "brand_city_matrix": {
            "prompts": ["北京冰种翡翠手镯品牌哪家好"],
            "rows": [{"label": "上海", "cells": [1.3]}],
        },
        "prompt_analytics": [
            {
                "prompt": "北京冰种翡翠手镯品牌哪家好",
                "sample_count": 16,
                "brand_mention_rate": 93.8,
                "brand_avg_rank": 1.0,
                "round_trend": [{"schedule_label": "2026-07-09 14:00", "avg_rank": 1.0}],
                "molizhishu_ranking_rows": [
                    {
                        "name": "春全合珠宝",
                        "type_label": "最近",
                        "type_muted": False,
                        "category": "性价比与专业度",
                        "rank_display": "1",
                        "collected_at": "26-07-09 13:40",
                        "is_brand": True,
                        "is_competitor": False,
                    }
                ],
                "mention_table": [
                    {
                        "name": "春全合珠宝",
                        "mention_count": 15,
                        "sample_count": 16,
                        "mention_rate": 93.8,
                        "is_brand": True,
                    }
                ],
            }
        ],
        "top_sources": [{"title": "知乎", "count": 3}],
        "source_analysis": {"domain_stats": [{"domain": "zhihu.com", "count": 3, "brand_related_count": 1}]},
        "report_sections": {
            "industry_analysis": "<p>行业聚焦<strong style=\"color:#ff6666;\">翡翠手镯</strong>。</p>",
            "ranking_analysis": "<p>排名分析</p>",
            "mention_analysis": "<p>提及率分析</p>",
            "source_analysis": "<p>引用网站分析</p>",
            "action_recommendations": "<p>采取措施建议</p>",
        },
    }


def test_molizhishu_ranking_rows_aggregates_same_day_to_daily_mean() -> None:
    """同日多时段必须合成日均，禁止按 09:30/14:30 分行。"""
    from datetime import datetime

    from app.services.lead_diagnosis_analytics import _build_molizhishu_ranking_rows

    runs = {
        "t1": _RunStub("202607020930", "2026-07-02 09:30", "t1"),
        "t2": _RunStub("202607021430", "2026-07-02 14:30", "t2"),
    }
    subtasks = [
        _SubtaskStub(
            task_id="t1",
            prompt="p",
            rankings=[{"name": "春全合珠宝", "rank": 4, "category": "默认分类"}],
            updated_at=datetime(2026, 7, 2, 9, 40),
        ),
        _SubtaskStub(
            task_id="t2",
            prompt="p",
            rankings=[{"name": "春全合珠宝", "rank": 2, "category": "默认分类"}],
            updated_at=datetime(2026, 7, 2, 14, 40),
        ),
    ]
    rows = _build_molizhishu_ranking_rows(
        subtasks,
        brand="春全合珠宝",
        competitors=[],
        task_run_map=runs,
    )
    brand_rows = [row for row in rows if row["is_brand"] and row["type_label"] == "最近"]
    assert len(brand_rows) == 1
    assert brand_rows[0]["rank_display"] == "3"
    assert brand_rows[0]["collected_at"] == "2026-07-02"
    assert ":" not in brand_rows[0]["collected_at"]


def test_molizhishu_ranking_rows_labels_recent_best_worst() -> None:
    runs = {
        "t1": _RunStub("202607020930", "2026-07-02 09:30", "t1"),
        "t2": _RunStub("202607090930", "2026-07-09 09:30", "t2"),
    }
    subtasks = [
        _SubtaskStub(
            task_id="t1",
            prompt="p",
            rankings=[{"name": "春全合珠宝", "rank": 5, "category": "默认分类"}],
            updated_at=datetime(2026, 7, 2, 9, 40),
        ),
        _SubtaskStub(
            task_id="t2",
            prompt="p",
            rankings=[{"name": "春全合珠宝", "rank": 1, "category": "默认分类"}],
            updated_at=datetime(2026, 7, 9, 9, 40),
        ),
    ]
    rows = _build_molizhishu_ranking_rows(
        subtasks,
        brand="春全合珠宝",
        competitors=[],
        task_run_map=runs,
    )
    labels = {row["type_label"] for row in rows if row["is_brand"]}
    assert "最近" in labels
    assert "最优" in labels
    assert "最差" in labels


def test_prompt_chart_kpis_span() -> None:
    from app.services.report_molizhishu_context_service import _prompt_chart_kpis

    kpis = _prompt_chart_kpis(
        {
            "sample_count": 80,
            "brand_mention_rate": 8.8,
            "brand_avg_rank": 2.6,
            "round_trend": [{"avg_rank": 2.5}, {"avg_rank": 3.0}],
        }
    )
    by_label = {row["label"]: row["value"] for row in kpis}
    assert by_label["监测样本"] == "80"
    assert by_label["品牌提及率"] == "8.8%"
    assert by_label["平均排名"] == "2.6"
    assert by_label["均排走势"] == "2.5 → 3"


def test_ranking_detail_table_ab_layout() -> None:
    """A+B：无分类列、类型标签、本品牌行、日期 MM-DD。"""
    from app.services.report_molizhishu_fragments import render_ranking_table

    html = render_ranking_table(
        "rank-demo",
        [
            {
                "name": "分众传媒",
                "type_label": "最近",
                "rank_display": "1.2",
                "collected_at": "2026-07-02",
                "is_brand": False,
            },
            {
                "name": "艾迪亚控股集团有限公司",
                "type_label": "最优",
                "rank_display": "1.1",
                "collected_at": "2026-06-30",
                "is_brand": True,
            },
        ],
    )
    assert "ranking-detail-table" in html
    assert "ranking-detail-wrap" in html
    assert ">分类<" not in html
    assert "默认分类" not in html
    assert "rank-type-tag--recent" in html
    assert "rank-type-tag--best" in html
    assert "rank-row--brand" in html
    assert ">07-02<" in html
    assert ">06-30<" in html


def test_molizhishu_html_matches_reference_markers() -> None:
    html = render_molizhishu_report_html(_demo_payload())
    assert "master-bg" in html
    assert 'class="master-bg" src="data:image/jpeg;base64,' in html
    assert 'class="master-bg" src="data:image/png;base64,' not in html  # 0723 亮底改 JPG
    assert "idea-cover.jpg" not in html  # masters must be embedded, not file paths
    assert "idea-light.png" not in html
    assert "idea-light.jpg" not in html
    assert "核心指标与结论" in html
    assert "情感与口碑" in html
    assert "sentiment-kpi" in html
    assert "swot-stack" in html
    assert "优势 / 待改善 / 建议" not in html
    assert "竞品格局对比" in html
    assert "分平台表现" in html
    assert "语义词 × 平台矩阵" in html or "语义词平台矩阵" in html
    assert "语义词成绩单" in html
    assert "品牌用户专属报表分析" in html
    assert "竞品" in html
    assert "分析平台" in html
    assert "分析周期" in html
    assert "报告生成时间" in html
    assert "采信网站" in html or "domain_map" in html or "信源" in html
    assert 'id="t_divBrandRecent"' in html
    assert 'id="t_divBrandCityRank"' in html
    assert "分享链接导入" not in html
    assert "13031099925" in html
    assert "kpi-grid" in html
    assert "slide-title" in html
    assert "progress-container" in html
    assert "report-theme-b" in html
    assert "#1677ff" in html
    assert "background-color: #000000" not in html
    assert 'data-pack="1"' in html
    assert "pack-body" in html
    assert "chart-prompt-panel" in html
    assert "chart-kpi-strip" in html
    assert "北京冰种翡翠手镯品牌哪家好" in html

    ctx = build_molizhishu_report_context(_demo_payload())
    assert "domain_map_slides" in ctx
    assert "analysis_html" in ctx
    assert isinstance(ctx["domain_map_slides"], list)


def test_deck_pack_splits_overflow_and_merges_sparse() -> None:
    """量高拆页 + 同类短页合并（Playwright DOM）。"""
    from playwright.sync_api import sync_playwright

    from app.services.report_molizhishu_pdf_service import _pack_js

    pack_js = _pack_js()
    html = """<!DOCTYPE html><html><head><style>
    .slide{width:2520px;height:1417px;position:relative;overflow:hidden}
    .pack-body{position:absolute;left:132px;top:210px;width:2260px;max-height:1100px;overflow:hidden}
    .pack-item{margin:0 0 12px}
    .slide-title{position:absolute;left:140px;top:118px}
    .tall{height:700px;background:#ddd}
    .short{height:120px;background:#eee}
    .mid{height:960px;background:#ccc}
    table{width:100%;border-collapse:collapse}
    td,th{padding:10px;border:1px solid #ccc}
    </style></head><body><main class="deck">
    <section class="slide" data-pack="1" data-merge-group="analysis">
      <h2 class="slide-title">数据分析与优化建议</h2>
      <div class="pack-body">
        <div class="pack-item tall">A1</div>
        <div class="pack-item tall">A2</div>
        <div class="pack-item short">A3</div>
      </div>
    </section>
    <section class="slide" data-pack="1" data-merge-group="source">
      <h2 class="slide-title">采信网站概览</h2>
      <div class="pack-body"><div class="pack-item short">S1</div></div>
    </section>
    <section class="slide" data-pack="1" data-merge-group="source">
      <h2 class="slide-title">信源优化建议</h2>
      <div class="pack-body"><div class="pack-item short">S2</div></div>
    </section>
    <section class="slide" data-pack="1" data-merge-group="domain">
      <h2 class="slide-title">品牌平均排名与引用网站映射关系 (1/2)</h2>
      <div class="pack-body"><div class="pack-item mid"><table><thead><tr><th>域名</th></tr></thead>
      <tbody><tr><td>a.com</td></tr><tr><td>b.com</td></tr>
      <tr><td>c.com</td></tr><tr><td>d.com</td></tr><tr><td>e.com</td></tr>
      <tr><td>f.com</td></tr><tr><td>g.com</td></tr><tr><td>h.com</td></tr>
      </tbody></table></div></div>
    </section>
    <section class="slide" data-pack="1" data-merge-group="domain">
      <h2 class="slide-title">品牌平均排名与引用网站映射关系 (2/2)</h2>
      <div class="pack-body"><div class="pack-item short"><table><thead><tr><th>域名</th></tr></thead>
      <tbody><tr><td>jobui.com</td></tr></tbody></table></div></div>
    </section>
    </main></body></html>"""

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 2520, "height": 1417}, device_scale_factor=1)
            page.set_content(html, wait_until="load")
            result = page.evaluate(pack_js)
            titles = page.locator(".slide-title").all_text_contents()
            domain_titles = [t for t in titles if "映射关系" in t]
            jobui_pages = page.locator(".slide:has-text('jobui.com')").count()
        finally:
            browser.close()

    assert any("(1/" in t for t in titles)
    assert any("(2/" in t for t in titles)
    assert sum(1 for t in titles if "采信网站概览" in t) == 1
    assert not any(t.strip() == "信源优化建议" for t in titles)
    # 域名尾页并回上一页：只剩一页映射，且含 jobui
    assert len(domain_titles) == 1
    assert "(2/2)" not in domain_titles[0]
    assert jobui_pages == 1
    assert result["slides"] >= 3


def test_deck_pack_peel_overflow_no_clip() -> None:
    """估算装页偏满时，收尾 peel 必须以 scrollHeight 为准，不留下裁切。"""
    from playwright.sync_api import sync_playwright

    from app.services.report_molizhishu_pdf_service import _pack_js

    # 固定块高合计 > max-height，且拆页后仍可能因 margin 实测溢出 → peel 兜底
    html = """<!DOCTYPE html><html><head><style>
    .slide{width:2520px;height:1417px;position:relative;overflow:hidden}
    .pack-body{position:absolute;left:132px;top:210px;width:2260px;max-height:300px;overflow:hidden}
    .pack-item{margin:0 0 20px;height:140px;box-sizing:border-box;background:#eee;border:1px solid #ccc}
    .slide-title{position:absolute;left:140px;top:118px}
    </style></head><body><main class="deck">
    <section class="slide" data-pack="1" data-merge-group="analysis">
      <h2 class="slide-title">数据分析与优化建议</h2>
      <div class="pack-body">
        <div class="pack-item">A1</div>
        <div class="pack-item">A2</div>
        <div class="pack-item">A3 底行若被裁只露一半</div>
      </div>
    </section>
    </main></body></html>"""

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 2520, "height": 1417}, device_scale_factor=1)
            page.set_content(html, wait_until="load")
            result = page.evaluate(_pack_js())
            clipped = page.evaluate(
                """() => [...document.querySelectorAll('.pack-body')].filter(
                  (b) => b.scrollHeight > b.clientHeight + 2
                ).length"""
            )
        finally:
            browser.close()

    assert result.get("stillClipped", 0) == 0, result
    assert clipped == 0, result
    assert result["slides"] >= 2, result


def test_deck_pack_domain_explode_avoids_one_row_tail() -> None:
    """B：超高映射表拆页后，不应留下仅 1 行的（续）页。"""
    from playwright.sync_api import sync_playwright

    from app.services.report_molizhishu_pdf_service import _pack_js

    rows_html = "".join(f"<tr><td>d{i}.com</td><td>站{i}</td><td>{i}</td><td>{i}</td></tr>" for i in range(1, 16))
    html = f"""<!DOCTYPE html><html><head><style>
    .slide{{width:2520px;height:1417px;position:relative;overflow:hidden}}
    .pack-body{{position:absolute;left:132px;top:210px;width:2260px;max-height:1000px;overflow:hidden}}
    .pack-item{{margin:0 0 12px}}
    .slide-title{{position:absolute;left:140px;top:118px}}
    table{{width:100%;border-collapse:collapse;font-size:32px}}
    td,th{{padding:18px 16px;border:1px solid #ccc;height:56px}}
    </style></head><body><main class="deck">
    <section class="slide" data-pack="1" data-merge-group="domain">
      <h2 class="slide-title">品牌平均排名与引用网站映射关系</h2>
      <div class="pack-body"><div class="pack-item">
        <table class="domain-map-table"><thead><tr><th>域名</th><th>网站</th><th>总引用</th><th>品牌</th></tr></thead>
        <tbody>{rows_html}</tbody></table>
      </div></div>
    </section>
    </main></body></html>"""

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 2520, "height": 1417}, device_scale_factor=1)
            page.set_content(html, wait_until="load")
            page.evaluate(_pack_js())
            info = page.evaluate(
                """() => [...document.querySelectorAll('.slide[data-merge-group="domain"]')].map((s) => ({
                  title: (s.querySelector('.slide-title')||{}).innerText || '',
                  rows: s.querySelectorAll('tbody tr').length,
                  cont: !!(s.querySelector('.block-title') && /续/.test(s.querySelector('.block-title').textContent||'')),
                }))"""
            )
        finally:
            browser.close()

    assert info, info
    # 不应出现「只有 1 行」的映射尾页
    assert all(row["rows"] != 1 for row in info), info
    assert all(row["rows"] >= 4 or len(info) == 1 for row in info), info


def test_matrix_and_mention_fragment_markup() -> None:
    matrix = render_matrix_table("t_divBrandRecent", "日期", ["语义词A"], [{"label": "2026-07-09", "cells": [2]}])
    assert 'style="background-color:hsl(' in matrix
    mention = render_mention_table("report-list2-x", [{"name": "品牌", "sample_count": 16, "mention_count": 15, "mention_rate": 93.8, "is_brand": True}])
    assert "93.8%" in mention
    assert "brand-row-outline" in mention

    ctx = build_molizhishu_report_context(
        _demo_payload(),
        platform_names={"deepseek": "DeepSeek", "weibo_zhisou": "微博智搜"},
    )
    assert ctx["competitor_text"] == "未指定竞品"
    assert ctx["platform_label"] == "DeepSeek、微博智搜"
    assert ctx["show_contact_meta"] is True

    no_contact = build_molizhishu_report_context(
        {**_demo_payload(), "contact_phone": "", "contact_name": ""},
        platform_names={"deepseek": "DeepSeek", "weibo_zhisou": "微博智搜"},
    )
    assert no_contact["show_contact_meta"] is False

    matrix_html = render_prompt_platform_matrix(
        {
            "platforms": ["DeepSeek"],
            "rows": [{"prompt": "测试词", "cells": [{"mention_rate": 38, "avg_rank": 6.0}]}],
        }
    )
    assert "#6" not in matrix_html
    assert "38%" in matrix_html
    assert "6" in matrix_html


def test_competitor_landscape_has_entity_colors_without_rank_risk() -> None:
    html = render_competitor_landscape_table(
        [
            {"name": "艾迪亚控股集团有限公司", "mention_rate": 8.8, "avg_rank": 4.2, "is_brand": True},
            {"name": "分众传媒", "mention_rate": 93.8, "avg_rank": 1.2},
            {"name": "白马户外媒体", "mention_rate": 3.8, "avg_rank": 6.1},
        ]
    )

    assert 'data-entity-color="#0057D9"' in html
    assert 'data-entity-color="#F28E2B"' in html
    assert 'data-entity-color="#009E73"' in html
    assert "rank-risk-good" not in html
    assert "达标（前三）" not in html
    assert "排名风险说明" not in html
    assert "4.2" in html
    assert "1.2" in html


def test_mention_table_uses_company_color_for_each_progress_bar() -> None:
    html = render_mention_table(
        "competitor-bars",
        [
            {"name": "艾迪亚控股集团有限公司", "sample_count": 80, "mention_count": 7, "mention_rate": 8.8, "is_brand": True},
            {"name": "分众传媒", "sample_count": 80, "mention_count": 75, "mention_rate": 93.8, "is_competitor": True},
        ],
    )

    assert "--entity-color: #0057D9" in html
    assert "--entity-color: #F28E2B" in html


def test_report_adds_competitor_strategy_and_removes_answer_excerpts() -> None:
    payload = _demo_payload()
    payload["competitors"] = ["分众传媒", "白马户外媒体"]
    payload["report_enrichment"] = {
        "competitor_landscape": [
            {"name": "春全合珠宝", "avg_rank": 4.2, "mention_rate": 8.8, "is_brand": True},
            {"name": "分众传媒", "avg_rank": 1.4, "mention_rate": 93.8},
            {"name": "白马户外媒体", "avg_rank": 5.1, "mention_rate": 2.5},
        ],
        "answer_excerpts": [
            {"prompt": "测试问题", "platform": "deepseek", "rank": 4, "excerpt": "不应出现在报告中"},
        ],
    }

    html = render_molizhishu_report_html(payload)

    assert "竞争格局摘要" in html
    assert "运营建议动作" in html
    assert "排名风险说明" not in html
    assert "验收口径" not in html
    assert "AI 回答摘录" not in html
    assert "不应出现在报告中" not in html
    assert "excerpt-card" not in html


def test_pdf_from_slide_pngs_uses_flate_not_jpeg() -> None:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (80, 45), (252, 253, 254)).save(buf, format="PNG")
    pdf = pdf_from_slide_pngs([buf.getvalue()])
    assert pdf.startswith(b"%PDF")
    assert pdf.count(b"/DCTDecode") == 0
    assert pdf.count(b"/FlateDecode") >= 1
