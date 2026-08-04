from app.services.report_text_sanitize import consolidate_top_sources, sanitize_source_title


def test_sanitize_source_title_strips_js_snippet() -> None:
    raw = "1摩洛哥点球大战淘汰荷兰window._q_wl_sc_1_1 = Date.now();新"
    result = sanitize_source_title(raw, url="https://news.example.com/a")
    assert "window." not in result
    assert "Date.now" not in result
    assert "摩洛哥" not in result
    assert result == "news.example.com"


def test_sanitize_source_title_drops_irrelevant_without_domain() -> None:
    assert sanitize_source_title("1摩洛哥点球大战淘汰荷兰 新", url=None) == ""


def test_consolidate_top_sources_merges_and_filters() -> None:
    rows = consolidate_top_sources(
        [
            {"title": "1摩洛哥点球大战淘汰荷兰 新", "url": "http://spam/a", "count": 730, "platforms": ["a"]},
            {"title": "电梯广告投放公司", "url": "http://b", "count": 85, "platforms": ["b"]},
            {"title": "电梯广告投放公司", "url": "http://b2", "count": 15, "platforms": ["c"]},
        ],
        limit=5,
    )
    titles = [row["title"] for row in rows]
    assert "摩洛哥" not in " ".join(titles)
    assert "电梯广告投放公司" in titles
    elevator = next(row for row in rows if row["title"] == "电梯广告投放公司")
    assert elevator["count"] == 100


def test_sanitize_analysis_html_strips_garbage() -> None:
    from app.services.report_text_sanitize import sanitize_analysis_html

    raw = "<p>引用<strong>1摩洛哥点球大战淘汰荷兰window._q=1;</strong>出现730次</p>"
    cleaned = sanitize_analysis_html(raw)
    assert "摩洛哥" not in cleaned
    assert "window." not in cleaned


def test_render_analysis_html_wraps_sections() -> None:
    from app.services.report_molizhishu_fragments import render_analysis_html

    html = render_analysis_html(
        {},
        analysis_html=(
            "<h2>数据分析与优化建议</h2>"
            "<h2>1. 行业分析</h2><p>行业段落</p>"
            "<h2>5. 采取措施建议</h2><ul><li>行动甲独有建议</li><li>优化电梯语义词</li></ul>"
        ),
        priority_actions=[{"priority": "P0", "title": "优化电梯语义词", "timeline": "30天"}],
    )
    assert "analysis-block" in html
    assert "analysis-card" in html
    assert html.count("analysis-card") >= 2
    assert "行业段落" in html
    assert "数据分析与优化建议" not in html
    # 2026-08-04 - 节标题保留为 analysis-section-head（旧逻辑丢弃 h2，新三块结构依赖可见标题）
    assert "1. 行业分析" in html
    assert "analysis-section-head" in html
    # 行动项：与分析同流白卡，禁止优先级/建议周期表格
    assert "优化电梯语义词" in html
    assert "优先级" not in html
    assert "建议周期" not in html
    assert "priority-action-table" not in html
    assert html.index("优化电梯语义词") < html.index("行业段落")
    # 4A：ul/li 拆成独立卡；与 priority 近重复的 li 去掉
    assert "<ul>" not in html
    assert "行动甲独有建议" in html
    assert html.count("优化电梯语义词") == 1


def test_render_analysis_html_keeps_v2_section_heads() -> None:
    from app.services.report_molizhishu_fragments import render_analysis_html

    html = render_analysis_html(
        {},
        analysis_html=(
            "<h2>分析结论</h2><p>发现一。</p>"
            "<h2>攻坚优先级</h2><h3>P0</h3><ul><li>优先补短板</li></ul>"
            "<h2>渠道路径</h2><p>问答平台补内容。</p>"
        ),
        priority_actions=[{"priority": "P0", "title": "短标题行动", "timeline": "30天"}],
    )
    assert "分析结论" in html
    assert "攻坚优先级" in html
    assert "渠道路径" in html
    assert "analysis-section-head" in html
    assert "analysis-section-sub" in html
    # v2：攻坚已在正文，不再前置短标题行动卡
    assert "短标题行动" not in html
    assert "优先补短板" in html


def test_render_tip_list_no_indent_class() -> None:
    from app.services.report_molizhishu_fragments import render_tip_list

    html = render_tip_list(
        ["在知乎补电梯广告问答，提升品牌在对比问法中的露出机会，覆盖行业报告与百科类信源缺口"]
    )
    assert "para--short" in html
    assert "para--indent" not in html
    assert "tip-card-index" in html


def test_render_priority_actions_highlights_quotes_and_platforms() -> None:
    from app.services.report_molizhishu_fragments import render_priority_actions

    html = render_priority_actions(
        [
            {
                "priority": "P0",
                "title": "在知乎、百度知道创建「电梯广告公司推荐」相关问答，嵌入品牌案例",
                "timeline": "30天",
            }
        ]
    )
    assert "analysis-card" in html
    assert 'style="color:#ff6666;"' in html
    assert "电梯广告公司推荐" in html
    assert 'style="color:#66ccff;"' in html
    assert "知乎" in html
    assert "优先级" not in html
    assert "建议周期" not in html


def test_sanitize_source_title_prefers_domain_for_seo_spam() -> None:
    spam = "2025年精选十大" + "超长" * 40 + "公司选-百家好"
    assert sanitize_source_title(spam, url="https://www.zhihu.com/question/123") == "zhihu.com"
