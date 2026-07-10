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
            "<h2>5. 采取措施建议</h2><ul><li>行动</li></ul>"
        ),
        priority_actions=[{"priority": "P0", "title": "优化电梯语义词", "timeline": "30天"}],
    )
    assert "analysis-block" in html
    assert "analysis-h2" in html
    assert "数据分析与优化建议" not in html
    assert "优先级行动清单" in html


def test_sanitize_source_title_prefers_domain_for_seo_spam() -> None:
    spam = "2025年精选十大" + "超长" * 40 + "公司选-百家好"
    assert sanitize_source_title(spam, url="https://www.zhihu.com/question/123") == "zhihu.com"
