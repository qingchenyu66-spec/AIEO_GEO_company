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


def test_structured_rankings_fill_missing_rank_within_category():
    raw = [
        {"name": "A公司", "category": "电梯"},
        {"name": "艾迪亚", "category": "电梯"},
    ]
    entries = normalize_structured_rankings(raw)
    assert entries[0]["rank"] == 1
    assert entries[1]["rank"] == 2


def test_find_best_brand_rank_across_categories():
    entries = [
        {"name": "艾迪亚", "rank": 2, "category": "电梯"},
        {"name": "艾迪亚", "rank": 1, "category": "机场"},
    ]
    rank, matched = find_best_brand_rank(entries, lambda name: "艾迪亚" in name)
    assert matched is True
    assert rank == 1
