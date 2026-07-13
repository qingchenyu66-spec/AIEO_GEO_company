from app.services.ranking_parser import find_best_brand_rank, normalize_structured_rankings, parse_answer_rankings


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


def test_parse_skips_markdown_table_rows():
    text = """
| 排名 | 公司 |
| --- | --- |
| 1 | 艾迪亚 |
| 2 | 分众传媒 |

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
