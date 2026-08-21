"""方案 C：计位前裁思考/搜索区；ordered_brands 校对 LLM 口算。"""

from app.services.rank_llm_service import (
    parse_llm_rank_payload,
    strip_pre_answer_noise_for_rank,
)


def test_strip_pre_answer_noise_drops_search_brands_before_formal_answer() -> None:
    # 2026-08-21 - 分享页「浏览网页」里的倍启智/奇鹤会污染表序
    raw = """
儿童DHA品牌推荐
Thought for 3 seconds

用户想了解儿童DHA品牌推荐。我将同时进行多项搜索。

Found 27 web pages
Read 7 pages
倍启智
奇鹤
儿童dha什么牌子最好
View All

这些搜索结果提供了许多品牌。现在开始组织回答。

给孩子选DHA，整理了品牌清单。

品牌\t核心特点
植物诀\t纯度高
YesNow\t复合配方
宝得聪\t性价比高
倍启智\tIFOS认证
"""
    cleaned = strip_pre_answer_noise_for_rank(raw)
    assert "现在开始组织回答" not in cleaned
    assert cleaned.index("植物诀") < cleaned.index("宝得聪")
    # 正式表里仍有倍启智，但搜索区里靠前的倍启智/奇鹤不应再单独出现在表前
    assert not cleaned.lstrip().startswith("倍启智")
    assert "奇鹤" not in cleaned.split("植物诀", 1)[0]


def test_strip_search_chrome_without_organize_marker() -> None:
    raw = """
前言
搜索到 12 个网页
某某品牌官网
查看全部
正式推荐：
1. 甲
2. 乙
"""
    cleaned = strip_pre_answer_noise_for_rank(raw)
    assert "搜索到" not in cleaned
    assert "查看全部" not in cleaned
    assert "正式推荐" in cleaned


def test_parse_ordered_brands_corrects_off_by_one_rank() -> None:
    """LLM 报 4，但 ordered_brands 里宝得聪是第 3 → 校正为 3。"""
    result = parse_llm_rank_payload(
        {
            "brand_mentioned": True,
            "rank": 4,
            "ordered_brands": ["植物诀", "YesNow", "宝得聪", "倍启智", "奇鹤"],
            "category": "热门儿童DHA品牌速览",
            "rank_basis": "markdown_table",
            "confidence": 0.95,
            "evidence": "宝得聪\t全产业链",
        },
        brand_terms=["宝得聪"],
    )
    assert result.rank == 3
    assert result.rank_basis == "ordered_brands_check"
    assert result.mentioned is True


def test_parse_ordered_brands_keeps_rank_when_already_consistent() -> None:
    result = parse_llm_rank_payload(
        {
            "brand_mentioned": True,
            "rank": 3,
            "ordered_brands": ["植物诀", "YesNow", "宝得聪"],
            "rank_basis": "markdown_table",
            "confidence": 0.9,
        },
        brand_terms=["宝得聪"],
    )
    assert result.rank == 3
    assert result.rank_basis == "markdown_table"


def test_parse_primary_frontmost_beats_preferred_worse_primary() -> None:
    """2026-08-21 - 主表多段时取最靠前，不锁 LLM preferred 的较差段。"""
    result = parse_llm_rank_payload(
        {
            "brand_mentioned": True,
            "overall_rank": 7,
            "category_ranks": [
                {"category": "全科通用（优先入手）", "rank": 6},
                {"category": "分科精选（精准突破）", "rank": 2},
            ],
            "category": "全科通用（优先入手）",
            "confidence": 0.95,
        }
    )
    assert result.rank == 2
    assert result.category == "分科精选（精准突破）"


def test_parse_secondary_specialty_section_yields_to_primary() -> None:
    """2026-08-21 - 「特色视角/单科专项」视为次要，不能压过主表。"""
    result = parse_llm_rank_payload(
        {
            "brand_mentioned": True,
            "category_ranks": [
                {"category": "主流门窗实力品牌速览", "rank": 1},
                {"category": "特色视角：技术领先与差异化品牌", "rank": 4},
            ],
            "category": "特色视角：技术领先与差异化品牌",
            "confidence": 0.95,
        }
    )
    assert result.rank == 1
    assert result.category == "主流门窗实力品牌速览"


def test_parse_secondary_xiaosimen_yields_to_primary() -> None:
    result = parse_llm_rank_payload(
        {
            "brand_mentioned": True,
            "category_ranks": [
                {"category": "全套自学套装（首选）", "rank": 1},
                {"category": "小四门精简选择", "rank": 4},
            ],
            "category": "小四门精简选择",
            "confidence": 0.95,
        }
    )
    assert result.rank == 1
    assert "小四门" not in str(result.category)
