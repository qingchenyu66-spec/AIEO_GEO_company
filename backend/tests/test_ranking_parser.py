from app.services.ranking_parser import (
    appearance_order_rank_scoped,
    find_best_brand_rank,
    find_best_brand_rank_scoped,
    normalize_structured_rankings,
    parse_answer_rankings,
    ranking_category_scope_score,
)


def test_parse_categorized_numbered_lists():
    text = """
### 一、电梯广告公司
1. 分众传媒
2. 艾迪亚
3. 新潮传媒

### 二、机场广告
1. 华视传媒
2. 艾迪亚集团
"""
    entries = parse_answer_rankings(text)
    elevator = [item for item in entries if item["category"] == "电梯广告公司"]
    assert [item["name"] for item in elevator] == ["分众传媒", "艾迪亚", "新潮传媒"]
    assert elevator[1]["rank"] == 2


def test_parse_bullet_list_uses_appearance_order():
    text = """
推荐公司：
- 分众传媒
- 艾迪亚
- 新潮传媒
"""
    entries = parse_answer_rankings(text)
    assert entries[1]["name"] == "艾迪亚"
    assert entries[1]["rank"] == 2


def test_parse_markdown_company_table_under_section():
    text = """
二、特色优势服务商
| 企业名称 | 核心特色 | 适配场景 |
| --- | --- | --- |
| 雅仕维 | 香港1993年成立 | 机场+户外 |
| 中视博弈 | 170+机场 | 多机场 |
| 艾迪亚控股 | 综合媒体集团 | 全链路方案 |
"""
    entries = parse_answer_rankings(text)
    section = [item for item in entries if item["category"] == "特色优势服务商"]
    assert [item["name"] for item in section] == ["雅仕维", "中视博弈", "艾迪亚控股"]
    aidiya = [item for item in entries if "艾迪亚" in item["name"]][0]
    assert aidiya["rank"] == 3
    rank, matched = find_best_brand_rank_scoped(
        entries,
        lambda name: "艾迪亚" in name,
        "机场广告公司哪家好",
    )
    assert matched is True
    assert rank == 3


def test_parse_rank_company_table_uses_explicit_rank_column():
    text = """
| 排名 | 公司 |
| --- | --- |
| 1 | 艾迪亚 |
| 2 | 分众传媒 |
"""
    entries = parse_answer_rankings(text)
    assert [item["name"] for item in entries] == ["艾迪亚", "分众传媒"]
    assert entries[0]["rank"] == 1


def test_parse_ignores_table_without_company_header():
    text = """
| 指标 | 数值 |
| --- | --- |
| 曝光 | 100万 |

1. 真正第一名
2. 真正第二名
"""
    entries = parse_answer_rankings(text)
    assert [item["name"] for item in entries] == ["真正第一名", "真正第二名"]


def test_structured_rankings_fill_missing_rank_within_category():
    raw = [
        {"name": "A公司", "category": "电梯"},
        {"name": "艾迪亚", "category": "电梯"},
    ]
    entries = normalize_structured_rankings(raw)
    assert entries[0]["rank"] == 1
    assert entries[1]["rank"] == 2


def test_parse_circled_number_list_marker():
    text = "① 艾迪亚控股集团有限公司\n② 分众传媒"
    entries = parse_answer_rankings(text)
    assert entries[0]["rank"] == 1
    assert "艾迪亚" in entries[0]["name"]


def test_structured_rankings_accept_circled_rank_token():
    entries = normalize_structured_rankings([{"name": "品牌A", "rank": "①"}])
    assert entries[0]["rank"] == 1


def test_find_best_brand_rank_across_categories():
    entries = [
        {"name": "艾迪亚", "rank": 2, "category": "电梯"},
        {"name": "艾迪亚", "rank": 1, "category": "机场"},
    ]
    rank, matched = find_best_brand_rank(entries, lambda name: "艾迪亚" in name)
    assert matched is True
    assert rank == 1


def test_find_best_brand_rank_prefers_category_over_flat_global():
    entries = [
        {"name": "艾迪亚控股集团", "rank": 3, "category": None},
        {"name": "艾迪亚控股集团", "rank": 1, "category": "全国性头部企业"},
    ]
    rank, matched = find_best_brand_rank(entries, lambda name: "艾迪亚" in name)
    assert matched is True
    assert rank == 1


def test_parse_elevator_markdown_sections_use_category_local_rank():
    text = """
## 一、行业双寡头
### 1. 分众传媒
- 商务楼宇资源垄断
### 2. 新潮传媒
## 二、中腰部全国梯媒
### 3. 喜屏传媒
### 4. 城市纵横
## 三、全域整合型传媒
### 艾迪亚控股集团
全国90%核心城市布局
"""
    entries = parse_answer_rankings(text)
    aidiya = [item for item in entries if "艾迪亚" in item["name"]]
    assert len(aidiya) == 1
    assert aidiya[0]["rank"] == 1
    assert "全域整合" in str(aidiya[0]["category"])
    focus = [item for item in entries if "分众" in item["name"]]
    assert focus and focus[0]["rank"] == 1
    assert "双寡头" in str(focus[0]["category"])
    rank, matched = find_best_brand_rank(
        [{"name": "艾迪亚控股集团", "rank": 7, "category": None}, *aidiya],
        lambda name: "艾迪亚" in name,
    )
    assert matched is True
    assert rank == 1
    text = """
## 三、全案整合代理商（中小品牌）
### 艾迪亚控股、澜翼传媒、麦迪威广告
- 不独占核心一手资源
"""
    entries = parse_answer_rankings(text)
    aidiya = [item for item in entries if "艾迪亚" in item["name"]]
    assert aidiya
    assert aidiya[0]["rank"] == 1
    assert "全案整合" in str(aidiya[0]["category"])


def test_parse_bold_subsection_headers_as_categories():
    text = """
一、LED 显示屏生产 / 工程厂家
**头部上市大厂**
1. 利亚德 LEYARD
2. 洲明科技 Unilumin
**高性价比量产大厂**
1. 强力巨彩
2. 元亨光电

二、全国 LED 大屏媒体运营商
1. 郁金香传媒
2. 艾迪亚控股
"""
    entries = parse_answer_rankings(text)
    assert not any("头部上市" in item["name"] for item in entries)
    head = [item for item in entries if item["category"] == "头部上市大厂"]
    assert [item["name"] for item in head] == ["利亚德 LEYARD", "洲明科技 Unilumin"]
    media = [item for item in entries if "艾迪亚" in item["name"]]
    assert media[0]["rank"] == 2
    assert media[0]["category"] == "全国 LED 大屏媒体运营商"


def test_scoped_rank_prefers_monitor_keyword_section():
    text = """
一、LED 显示屏生产 / 工程厂家
1. 利亚德
2. 洲明

二、全国 LED 大屏媒体运营商
1. 郁金香传媒
2. 艾迪亚控股
"""
    entries = parse_answer_rankings(text)
    scope = "LED广告公司推荐"
    assert ranking_category_scope_score("全国 LED 大屏媒体运营商", scope) > ranking_category_scope_score(
        "LED 显示屏生产 / 工程厂家", scope
    )
    rank, matched = find_best_brand_rank_scoped(
        entries,
        lambda name: "艾迪亚" in name,
        scope,
    )
    assert matched is True
    assert rank == 2


def test_scoped_appearance_order_uses_matching_section():
    text = """
一、LED 显示屏生产 / 工程厂家
1. 利亚德
2. 洲明
3. 艾比森

二、全国 LED 大屏媒体运营商
1. 郁金香传媒
2. 艾迪亚控股
"""
    rank = appearance_order_rank_scoped(
        text,
        lambda line: "艾迪亚" in line,
        "LED广告公司推荐",
    )
    assert rank == 2


def test_scoped_rank_uses_brand_category_when_not_in_top_section():
    text = """
一、LED 显示屏生产 / 工程厂家
**区域优质工程商**
- 华东：杭州必见科技
- 西南：艾迪亚控股

二、全国 LED 大屏媒体运营商
1. 郁金香传媒
2. 联屏传媒
"""
    entries = parse_answer_rankings(text)
    aidiya = [item for item in entries if "艾迪亚" in item["name"]]
    assert aidiya and aidiya[0]["name"] == "艾迪亚控股"
    assert aidiya[0]["rank"] == 2
    rank, matched = find_best_brand_rank_scoped(
        entries,
        lambda name: "艾迪亚" in name,
        "LED广告公司推荐",
    )
    assert matched is True
    assert rank == 2


def test_parse_markdown_h3_subcategory_then_region_bullets():
    text = """
## 一、LED显示屏生产/工程厂家
### 头部上市大厂（大型地标）
1. 利亚德 LEYARD
2. 洲明科技 Unilumin
### 区域优质工程商（本地落地、售后响应快）
- 华东：杭州华见科技
- 西南：艾迪亚控股（利亚德/洲明双一级代理，重庆、贵州商圈大屏）

## 二、全国LED大屏媒体运营商
1. 郁金香传媒
2. 联屏传媒
"""
    entries = parse_answer_rankings(text)
    aidiya = [item for item in entries if "艾迪亚" in item["name"]]
    assert len(aidiya) == 1
    assert aidiya[0]["name"] == "艾迪亚控股"
    assert aidiya[0]["rank"] == 2
    assert "区域优质工程商" in str(aidiya[0]["category"])
