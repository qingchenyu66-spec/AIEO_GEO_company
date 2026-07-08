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
