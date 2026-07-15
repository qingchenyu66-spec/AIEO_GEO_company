from pathlib import Path

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


def test_segment_local_rank_ignores_cross_section_numbering():
    """豆包式分段：中腰部接龙头继续标 3/4/5，段内应重排为 1/2/3。"""
    text = """
## 一、全国两大绝对龙头
1. 分众传媒
2. 新潮传媒

## 二、全国性中腰部专业梯媒公司
3. 城市纵横 CityMedia
4. 梯影传媒 TikinMedia
5. 艾迪亚传媒
6. 淘屏新媒体 / 喜屏传媒
"""
    entries = parse_answer_rankings(text)
    mid = [item for item in entries if item["category"] and "中腰部" in str(item["category"])]
    assert len(mid) >= 3
    aidiya = next(item for item in mid if "艾迪亚" in item["name"])
    assert aidiya["rank"] == 3
    assert mid[0]["rank"] == 1
    assert mid[1]["rank"] == 2
    rank, matched = find_best_brand_rank_scoped(
        entries,
        lambda name: "艾迪亚" in name,
        "电梯广告公司推荐",
    )
    assert matched is True
    assert rank == 3


def test_structured_rankings_rerank_within_category():
    raw = [
        {"name": "城市纵横", "rank": 3, "category": "中腰部"},
        {"name": "梯影传媒", "rank": 4, "category": "中腰部"},
        {"name": "艾迪亚传媒", "rank": 5, "category": "中腰部"},
    ]
    entries = normalize_structured_rankings(raw)
    assert [item["rank"] for item in entries] == [1, 2, 3]
    assert entries[2]["name"] == "艾迪亚传媒"


def test_airport_scoped_prefers_first_section_not_later_regional():
    """机场广告：整合代理无「传媒」二字时，不能被区域段后文同品牌第 9 抢走。"""
    text = Path(__file__).resolve().parents[1].joinpath("scripts/_airport_fixture.md").read_text(encoding="utf-8")
    entries = parse_answer_rankings(text)
    aidya = [item for item in entries if "艾迪亚" in item["name"]]
    assert len(aidya) >= 2
    assert aidya[0]["rank"] == 1
    assert "整合" in str(aidya[0]["category"])
    rank, matched = find_best_brand_rank_scoped(
        entries,
        lambda name: "艾迪亚" in name,
        "机场广告公司哪家好",
    )
    assert matched is True
    assert rank == 1


def test_normalize_structured_drops_subsection_labels():
    raw = [
        {"name": "华铁传媒集团", "rank": 1, "category": "全国性头部综合服务商"},
        {"name": "核心优势", "rank": 2, "category": "全国性头部综合服务商"},
        {"name": "服务能力", "rank": 3, "category": "全国性头部综合服务商"},
        {"name": "资质层面", "rank": 4, "category": "全国性头部综合服务商"},
        {"name": "规模体量", "rank": 5, "category": "全国性头部综合服务商"},
        {"name": "兆讯传媒", "rank": 2, "category": "全国性头部综合服务商"},
        {"name": "核心优势", "rank": 4, "category": "全国性头部综合服务商"},
        {"name": "服务能力", "rank": 5, "category": "全国性头部综合服务商"},
        {"name": "艾迪亚控股集团", "rank": 3, "category": "全国性头部综合服务商"},
    ]
    entries = normalize_structured_rankings(raw)
    assert [e["name"] for e in entries] == ["华铁传媒集团", "兆讯传媒", "艾迪亚控股集团"]
    assert entries[2]["rank"] == 3
    assert not any(e["name"] in {"资质层面", "规模体量", "核心亮点"} for e in entries)
    entries2 = normalize_structured_rankings(
        [{"name": "核心亮点", "rank": 2, "category": "头部"}, {"name": "艾迪亚", "rank": 1, "category": "头部"}]
    )
    assert [e["name"] for e in entries2] == ["艾迪亚"]
    assert entries2[0]["rank"] == 1


def test_hsr_parse_rejects_field_bullets_under_company():
    """百度高铁文：公司下的「核心优势/服务能力」bullet 不得占位，艾迪亚应为头部段第 3。"""
    text = Path(__file__).resolve().parents[1].joinpath("scripts/_hsr_5786.txt").read_text(encoding="utf-8")
    entries = parse_answer_rankings(text)
    assert not any(item["name"] in {"核心优势", "服务能力"} for item in entries)
    head = [item for item in entries if item["category"] == "全国性头部综合服务商"]
    assert [item["name"] for item in head] == ["华铁传媒集团", "兆讯传媒", "艾迪亚控股集团"]
    assert head[2]["rank"] == 3
    rank, matched = find_best_brand_rank_scoped(
        entries,
        lambda name: "艾迪亚" in name,
        "高铁广告公司哪家好",
    )
    assert matched is True
    assert rank == 3


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


def test_parse_rejects_nested_numbered_details_under_company():
    """### 1. 公司 下「优势：1/2/3」嵌套编号不得占位（生产 5959）。"""
    text = """
## 全国全域投放首选
### 1. 华铁传媒（行业绝对龙头）
- 优势：
  1. 一手铁路局授权，无多层转包，审批、上刊、运维统一落地；
  2. 擅长长线品牌冠名、大型整合营销，汽车、白酒、家电头部品牌案例极多；
  3. 全国同步监测，漏刊快速补刊，售后体系完善。
- 适合：全国连锁、上市品牌。
### 2. 艾迪亚控股集团（全场景全覆盖）
- 优势：方案定制化极强
"""
    entries = parse_answer_rankings(text)
    sec = [e for e in entries if e.get("category") == "全国全域投放首选"]
    assert [e["name"] for e in sec] == ["华铁传媒", "艾迪亚控股集团"]
    assert sec[1]["rank"] == 2
    rank, matched = find_best_brand_rank_scoped(
        entries, lambda name: "艾迪亚" in name, "高铁广告公司哪家好",
    )
    assert matched is True
    assert rank == 2


def test_parse_rejects_long_description_bullets_as_companies():
    """公司下的长描述 bullet 不得占位。"""
    text = """
## 全国全域投放首选
1. 华铁传媒
- 一手铁路局授权，无多层转包，审批、上刊、运维统一落地
- 擅长长线品牌冠名、大型整合营销，汽车、白酒、家电头部品牌案例极多
- 全国同步监测，漏刊快速补刊，售后体系完善
2. 艾迪亚控股集团
"""
    entries = parse_answer_rankings(text)
    sec = [e for e in entries if e.get("category") == "全国全域投放首选"]
    assert [e["name"] for e in sec] == ["华铁传媒", "艾迪亚控股集团"]
    assert sec[1]["rank"] == 2


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
    # 同品牌多次出现：优先更靠前名次（方案 2）
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


def test_parse_yuanbao_crushed_bus_bullets_section_local_rank():
    text = """
## 全国性/跨国头部集团（适合全国联投、高端品牌）
- **德高中国 (JCDecaux)**：全球户外广告巨头。[citation:1]
- **白马户外媒体**：国内老牌。[citation:8]
- **华视传媒 / 世通华纳**：早期专注公交。[citation:5]## 重点城市公交集团直属公司（适合单城深耕、本地化投放）
-**北京**：北京巴士传媒股份有限公司[citation:2][citation:9]
- **上海**：上海公共交通广告有限公司[citation:2][citation:9]
- **其他强市**：西安振兴公交广告、济南公共交通集团文化传媒。[citation:2]## 综合性/下沉市场运营商（适合性价比、二三线城市渗透）
- **华君传媒**：在二三线城市及县域市场的公交媒体资源整合有优势。[citation:3]
- **艾迪亚控股 / 上海澜翼传媒**：侧重公交车身全场景整合。[citation:7]
- **省广集团 / 引力传媒**：以整合营销见长。[citation:5]## 挑选时的核心判断标准
- **看资源权属**：优先问是不是公交集团直营。
"""
    entries = parse_answer_rankings(text)
    aidiya = [item for item in entries if "艾迪亚" in item["name"]]
    assert len(aidiya) == 1
    assert aidiya[0]["name"] == "艾迪亚控股"
    assert aidiya[0]["rank"] == 2
    assert "下沉" in str(aidiya[0]["category"]) or "综合" in str(aidiya[0]["category"])
    # 标准小节不应计入公司列表
    assert not any("看资源" in str(e.get("name") or "") for e in entries)
    rank, matched = find_best_brand_rank_scoped(
        entries,
        lambda name: "艾迪亚" in name,
        "公交广告公司哪家好",
    )
    assert matched is True
    assert rank == 2


def test_first_appearance_wins_when_brand_listed_twice():
    text = """
## 全国推荐
1. 分众传媒
2. 艾迪亚控股
3. 新潮传媒
## 区域推荐
1. 华君传媒
2. 省广集团
3. 艾迪亚控股
"""
    entries = parse_answer_rankings(text)
    rank, matched = find_best_brand_rank_scoped(
        entries,
        lambda name: "艾迪亚" in name,
        "广告公司推荐",
    )
    assert matched is True
    assert rank == 2


def test_metro_howto_section_does_not_steal_rank():
    text = """
## 一、全国头部独家地铁媒体运营商（一手资源，大品牌首选）
### 1. 德高中国 JCDecaux（全球户外龙头）
- 覆盖城市：北京、上海
### 2. 北京地铁通成（北京地铁官方合资运营商）
- 资质：北京地铁控股
## 二、区域本土专业地铁传媒（单城深耕，本地性价比高）
1. **西安时代尚优**：西安、天津地铁独家运营
2. **深圳市城市轨道广告**：深圳地铁全线路一手资源
3. **胜智广告**：上海、杭州多城整合
## 三、全国整合投放代理公司（多城一站式，中小品牌省心）
1. **传播易**：线上户外广告投放平台
2. **艾迪亚传媒**：覆盖一二三线城市地铁/公交/高铁
# 怎么选公司？快速对照
1. **只投北京** → 北京地铁通成（官方一手）
7. **多城市同步批量投放、预算有限** → 传播易、艾迪亚整合代理
"""
    entries = parse_answer_rankings(text)
    aidiya = [item for item in entries if "艾迪亚" in item["name"]]
    assert len(aidiya) == 1
    assert aidiya[0]["name"] == "艾迪亚传媒"
    assert aidiya[0]["rank"] == 2
    assert "整合投放" in str(aidiya[0]["category"])
    assert not any(item.get("rank") == 7 and "艾迪亚" in str(item.get("name") or "") for item in entries)
    rank, matched = find_best_brand_rank_scoped(
        entries,
        lambda name: "艾迪亚" in name,
        "地铁广告公司推荐",
    )
    assert matched is True
    assert rank == 2
