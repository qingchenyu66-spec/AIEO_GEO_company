from pathlib import Path

from app.services.ranking_parser import (
    appearance_order_rank_scoped,
    find_best_brand_rank,
    find_best_brand_rank_scoped,
    normalize_structured_rankings,
    parse_answer_rankings,
    ranking_category_scope_score,
)


def test_parse_holding_group_short_name_in_numbered_headers():
    """### 四、艾迪亚控股集团 — 无「有限公司」后缀也要进榜，不能当分类。"""
    text = """
结合2026年最新行业信息，为你推荐国内综合实力突出的优质LED广告相关企业：
### 一、深圳市布兰登光电科技有限公司
- **核心优势**：源头工厂
### 二、利亚德光电股份有限公司
- **核心优势**：上市
### 三、洲明科技集团股份有限公司
- **核心优势**：节能
### 四、艾迪亚控股集团
- **核心优势**：全链路LED大屏广告服务商
- **业务覆盖**：全场景
### 五、艾比森光电股份有限公司
- **核心优势**：户外
"""
    entries = parse_answer_rankings(text)
    names = [item["name"] for item in entries]
    assert "艾迪亚控股集团" in names
    assert "业务覆盖" not in names
    assert names.index("艾迪亚控股集团") == 3
    assert [item["rank"] for item in entries] == [1, 2, 3, 4, 5]
    rank, matched = find_best_brand_rank(entries, lambda name: "艾迪亚" in name)
    assert matched is True
    assert rank == 4


def test_company_detail_fields_do_not_inflate_section_rank():
    """高性价比档：联系方式/总部不当选手；艾迪亚档内第3不是第5。"""
    text = """
## 二、高性价比服务商推荐
### 6. **成都狼界广告传播有限公司**
- **成立时间**：2011年
- **联系方式**：15982158849，官网 www.langjiegg.com
### 7. **联岸传媒集团有限公司**
- **总部**：北京
- **核心优势**：运营北上广深电梯广告
### 8. **艾迪亚控股集团**
- **成立时间**：1998年
- **核心优势**：全国200+城市优质LED点位
"""
    entries = parse_answer_rankings(text)
    names = [item["name"] for item in entries]
    assert "联系方式" not in names
    assert "总部" not in names
    brand = next(item for item in entries if "艾迪亚" in item["name"])
    assert brand["rank"] == 3
    assert "高性价比" in str(brand["category"] or "")


def test_pipe_numbered_board_brands_keep_section_order():
    """### 7）大王椰｜… 挂在 ## 国产主流，档内第7；福人⭐加粗不被吞。"""
    text = """
## 国产主流品牌（性价比首选）
### 1）万华禾香板｜禾香板（秸秆基材）
### 2）鲁丽｜欧松板OSB/LSB
### 3）兔宝宝｜生态板、多层板、颗粒板、欧松板
### 4）千年舟｜颗粒板、多层板、LSB板
### 5）莫干山｜多层板见长
### 6）福人、红棉花｜颗粒板精板
### 7）大王椰、伟业
"""
    entries = parse_answer_rankings(text)
    brand = next(item for item in entries if "大王椰" in item["name"])
    assert brand["rank"] == 7
    assert "国产主流" in str(brand["category"] or "")
    assert not any(item["name"] in {"生态板", "多层板", "颗粒板"} for item in entries)


def test_scoped_rank_prefers_domestic_section_over_import_front_rank():
    """同品牌跨国产/进口分段时，按问题场景取国产段，不被进口第1抬高。"""
    entries = [
        {"name": "示例品牌", "rank": 1, "category": "进口高端品牌"},
        {"name": "示例品牌", "rank": 5, "category": "国产主流品牌"},
    ]
    rank, matched = find_best_brand_rank_scoped(
        entries,
        lambda name: name == "示例品牌",
        "国产板材品牌推荐",
    )
    assert matched is True
    assert rank == 5


def test_scoped_rank_prefers_prompt_scene_over_other_category_front_rank():
    """问电梯广告时，不能用同品牌在LED大屏分段里的第1覆盖电梯分段第4。"""
    entries = [
        {"name": "艾迪亚控股集团", "rank": 1, "category": "全国LED大屏媒体运营商"},
        {"name": "艾迪亚控股集团", "rank": 4, "category": "电梯广告资源代理商"},
    ]
    rank, matched = find_best_brand_rank_scoped(
        entries,
        lambda name: "艾迪亚" in name,
        "电梯广告公司推荐",
    )
    assert matched is True
    assert rank == 4

    beauty = """
## 🇨🇳 国产高端｜颜值主力
1. **福人（福建国企）⭐国产颜值标杆**
2. **大王椰**
3. **华富立（华立股份）**
"""
    beauty_entries = parse_answer_rankings(beauty)
    names = [item["name"] for item in beauty_entries]
    assert "福人" in names
    assert next(item for item in beauty_entries if "大王椰" in item["name"])["rank"] == 2


def test_caution_bullet_does_not_inflate_mainstream_rank():
    """福人下「注意：区分…」不当选手，大王椰仍是国产主流第7。"""
    text = """
## 国产主流靠谱品牌
### 1）兔宝宝
### 2）莫干山
### 3）千年舟
### 4）万华
### 5）鲁丽
### 6）福人家居
- 注意：区分**福人家居（正品）**和福人木业
### 7）大王椰
"""
    entries = parse_answer_rankings(text)
    assert not any(item["name"] == "注意" for item in entries)
    brand = next(item for item in entries if "大王椰" in item["name"])
    assert brand["rank"] == 7


def test_geo_place_headers_do_not_steal_store_rank():
    """区县小标题不当选手；大王椰在区县列表里从第1计。"""
    text = """
## 二、分区域知名品牌授权门店
### 城关区（东岗）
1. 大王椰板材：大西北板材市场
2. 千年舟板材运营中心：大西北板材市场A105号
### 西固区
大王椰板材｜西固中路1288号
"""
    entries = parse_answer_rankings(text)
    assert not any(item["name"] in {"城关区", "西固区"} for item in entries)
    brand = next(item for item in entries if item["name"] == "大王椰板材" and item["rank"] == 1)
    assert brand["category"] and "城关" in brand["category"]


def test_flagship_store_brand_names_stay_in_numbered_list():
    """精材艺匠旗舰店是品牌名不是地址行，荔城区内排第1。"""
    text = """
## 荔城区
1. **精材艺匠黄浦木业旗舰店**
2. **大王椰板材（荔城店）**
"""
    entries = parse_answer_rankings(text)
    section = [item for item in entries if item.get("category") == "荔城区"]
    assert [item["name"] for item in section] == ["精材艺匠黄浦木业旗舰店", "大王椰板材"]
    assert section[1]["rank"] == 2


def test_authorized_store_brand_headers_not_store_lines():
    """### 品牌下挂门店；下一 ### 品牌继续同段计位，福庆不当 category。"""
    text = """
## 一、国产一线品牌授权门店（兔宝宝/莫干山/千年舟/福庆/大王椰）
### 兔宝宝（ENF生态板、多层板）[citation:9]
1. 秦淮卡子门京东MALL整家店
2. 建邺金盛国际全屋店
### 莫干山板材[citation:11]
1. 弘阳装饰城店｜雨花台区
### 千年舟板材
1. 长江装饰城同洲木业店
### 福庆板材（江苏本土品牌）[citation:10]
1. 桥北弘阳家居店
### 大王椰板材南京运营中心
"""
    entries = parse_answer_rankings(text)
    assert not any("整家店" in item["name"] or item["name"].endswith("家居店") for item in entries)
    brand = next(item for item in entries if "大王椰" in item["name"])
    assert brand["rank"] == 5
    assert "福庆" not in str(brand.get("category") or "")
    assert "国产一线" in str(brand.get("category") or "")


def test_soe_section_single_brand_is_rank_one():
    """### 国企背景 下唯一 * **金隅** → 档内第1，不被国际段吞。"""
    text = """
### 🌍 国际一线品牌：技术引领，高端优选
*   **西卡 (Sika)**：环氧
*   **亚地斯 (Ardex)**：快干
### 🏛️ 国企背景品牌：安全合规，大型公建首选
这类品牌在防火、环保等硬性指标上具有天然优势。
*   **金隅涂料**：A级防火
### 🇨🇳 国内市场化品牌：灵活高效，性价比高
*   **秀珀 (Supe)**：性价比
"""
    entries = parse_answer_rankings(text)
    brand = next(item for item in entries if "金隅" in item["name"])
    assert brand["rank"] == 1
    assert "国企" in str(brand.get("category") or "")


def test_parse_numbered_category_heading_keeps_local_bullets():
    """### 3. 中国本土市场活跃榜单 开新段；鸿联是该类 bullet 第2，标题不当选手。"""
    text = """
### 1. 全球综合实力“四大巨头”（规模与全流程能力）
-   **Concentrix**：全球营收最高。
-   **Teleperformance（TP）**：欧洲老牌。

### 3. 中国本土市场活跃榜单（国内靠谱选择）
-   **泰盈科技（CCC）**：呼叫中心龙头。
-   **鸿联九五**：中信集团旗下。
-   **维音（VXI）**：汽车客服。
"""
    entries = parse_answer_rankings(text)
    names = [item["name"] for item in entries]
    assert "中国本土市场活跃榜单" not in names
    assert "全球综合实力“四大巨头”" not in names
    assert "鸿联九五" in names
    hl = next(item for item in entries if item["name"] == "鸿联九五")
    assert hl["rank"] == 2
    assert "本土" in str(hl.get("category") or "")


def test_normalize_collapses_all_rank_one_api_payload():
    """模力 allRankings 全员 rank=1 时按出场序重排。"""
    raw = [
        {"name": "深圳市布兰登光电科技有限公司", "rank": 1},
        {"name": "利亚德光电股份有限公司", "rank": 1},
        {"name": "洲明科技集团股份有限公司", "rank": 1},
        {"name": "艾迪亚控股集团有限公司", "rank": 1},
        {"name": "艾比森光电股份有限公司", "rank": 1},
    ]
    entries = normalize_structured_rankings(raw)
    assert [item["rank"] for item in entries] == [1, 2, 3, 4, 5]
    assert entries[3]["name"] == "艾迪亚控股集团有限公司"


def test_parse_roman_style_company_headers_not_field_labels():
    """### 一、XX有限公司 + 成立时间字段 → 5 家公司，不当字段当选手。"""
    text = """
以下是广州地区**5家优质LED广告公司推荐**。

### 一、广州伟源光电科技有限公司（全链路LED显示服务商）
- **成立时间**：2004年
- **核心优势**：
  - 一站式服务：方案设计
  - 标杆项目：白云国际会议中心
- **适用场景**：商业综合体

### 二、广州市夜空彩虹光电科技有限公司（户外灯光装饰专家）
- **成立时间**：1997年

### 三、广州普锐电子有限公司（LED大屏显示系统专家）
- **成立时间**：2007年

### 四、广州圣彩广告有限公司（一站式广告生态服务商）
- **成立时间**：20年行业沉淀

### 五、广州市佳拍档装饰工程有限公司（户外高空广告专家）
- **成立时间**：2012年

### 选择建议
- **按需求类型选**：户外大屏优先选伟源光电
- **选择要点**：核实资质

### 补充推荐
- 媒体资源型：艾迪亚传媒（全国户外LED大屏资源）、广州地铁传媒
"""
    entries = parse_answer_rankings(text)
    names = [item["name"] for item in entries]
    assert names == [
        "广州伟源光电科技有限公司",
        "广州市夜空彩虹光电科技有限公司",
        "广州普锐电子有限公司",
        "广州圣彩广告有限公司",
        "广州市佳拍档装饰工程有限公司",
    ]
    assert [item["rank"] for item in entries] == [1, 2, 3, 4, 5]
    assert not any(item["name"] in {"成立时间", "一站式服务", "标杆项目", "选择建议"} for item in entries)
    rank, matched = find_best_brand_rank(
        entries,
        lambda name: "艾迪亚" in name,
    )
    assert matched is False
    assert rank is None


def test_appearance_ignores_field_bullets_and_advice_mention():
    """品牌只在补充推荐出现时，appearance 不计字段行，不给出虚高名次。"""
    text = """
### 一、广州伟源光电科技有限公司（全链路）
- **成立时间**：2004年
- **核心优势**：一站式服务
### 二、广州普锐电子有限公司
- **成立时间**：2007年
### 补充推荐
- 媒体资源型：艾迪亚传媒（全国户外LED大屏资源）
"""
    rank = appearance_order_rank_scoped(
        text,
        lambda line: "艾迪亚" in line,
        "LED广告公司推荐",
    )
    assert rank is None


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


def test_glued_markdown_headers_reset_category_rank():
    """元宝导出常见：上一 bullet 末尾直接粘 ##二、 / ##户外…，必须拆行后段内重计。"""
    subway = """
##一、 北京地区主要运营商（核心资源方）
- **北京地下铁道通成广告股份有限公司**：覆盖约80%。
- **北青传媒股份有限公司**：独家运营4号线。
- **北京三木国际文化传播有限公司**：独家运营14号线。
- **亚瑞科尔国际广告传媒(北京)有限公司**：扶梯面板。[citation:8]##二、 全国性/跨区域知名地铁广告公司
- **德高中国 (JCDecaux)**：全球户外广告巨头。
- **雅仕维传媒 (Asiaray)**：大中华区交通媒体。
- **华铁传媒**：高铁+地铁联动。
- **艾迪亚控股集团**：覆盖全国30+核心城市。
- **博视得 (Posterscope)**：第三方策划购买。
## 三、 其他重点城市官方运营代表
- **上海**：上海地铁通成广告。
"""
    entries = parse_answer_rankings(subway)
    brand = next(item for item in entries if "艾迪亚" in item["name"])
    assert brand["rank"] == 4
    assert "全国" in str(brand["category"] or "")

    led = """
## 硬件制作与工程安装（买屏/门店/楼体）
- **北京飓风伟业广告制作有限公司**：灯箱招牌。
- **北京天一联创广告**：发光字。
- **文彩新艺广告**：牌匾。
- **北京中康鼎辉智能科技**：LED集成。[citation:10]##户外大屏广告投放（租媒体位）
- **天雅飞腾**：楼体全彩LED。
- **励唐永智**：全国网络。
- **艾迪亚传媒**：一站式策略定制。
- **寰球博瑞林特**：本土全场景。
- **北京北斗丽天广告**：候车亭地铁。[citation:14]##高端显示与知名厂商（大型项目/上市级）
- **利亚德光电股份有限公司**：上市公司。
"""
    led_entries = parse_answer_rankings(led)
    led_brand = next(item for item in led_entries if "艾迪亚" in item["name"])
    assert led_brand["rank"] == 3
    assert "户外" in str(led_brand["category"] or "") or "投放" in str(led_brand["category"] or "")


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


def test_parse_table_multi_company_cell_uses_in_cell_order():
    """方案 B：格内「A、B、C」按出现顺序记 1/2/3，展示仍是普通名次。"""
    text = """
| 梯队 | 代表公司 | 核心能力 |
| --- | --- | --- |
| 国内头部 | **泰盈科技**、**维音（VXI）**、**鸿联九五** | 本土化运营 |
| 互联网专家 | **鸿联九五**（中信系）、**河北博岳** | 高并发 |
"""
    entries = parse_answer_rankings(text)
    by_name = {}
    for item in entries:
        name = item["name"]
        rank = item["rank"]
        if name not in by_name or rank < by_name[name]:
            by_name[name] = rank
    assert by_name["泰盈科技"] == 1
    assert by_name["维音"] == 2
    assert by_name["鸿联九五"] == 1
    assert by_name["河北博岳"] == 2
    rank, matched = find_best_brand_rank_scoped(
        entries,
        lambda name: "鸿联九五" in name,
        "呼叫中心外包公司选哪家",
    )
    assert matched is True
    assert rank == 1


def test_parse_table_vendor_column_header():
    text = """
| 梯队 | 代表厂商 | 核心标签 |
| --- | --- | --- |
| 互联网专家 | **鸿联九五**（中信系）、**河北博岳** | 高并发 |
"""
    entries = parse_answer_rankings(text)
    by_name = {item["name"]: item["rank"] for item in entries}
    assert by_name["鸿联九五"] == 1
    assert by_name["河北博岳"] == 2


def test_parse_table_supplier_column_with_like_examples():
    text = """
| 你的核心诉求 | 推荐关注的供应商梯队 | 选型红线 |
| --- | --- | --- |
| 性价比优先 | **国内头部人力型BPO**（如**泰盈科技**、**鸿联九五**）。它们人力储备极深。 | 弹性坐席 |
"""
    entries = parse_answer_rankings(text)
    names = [item["name"] for item in entries]
    assert "国内头部人力型BPO" not in names
    assert "泰盈科技" in names
    assert "鸿联九五" in names
    by_name = {item["name"]: item["rank"] for item in entries}
    assert by_name["泰盈科技"] == 1
    assert by_name["鸿联九五"] == 2


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


def test_parse_yuanbao_share_lone_bullet_colon_lines():
    """元宝分享页：孤立 • 行 +「公司名：说明」应能出场序计位。"""
    text = """
商圈/地标/户外大屏（A 类头部）
•
•
A 类：媒体运营商（买屏上曝光）
•
•
凤凰都市传媒：全国性户外 LED 大屏网络。
•
•
郁金香传媒：华东核心商圈老牌玩家。
•
•
分众传媒（含晶视）：写字楼集群联播网。
•
•
华视传媒：华南及大湾区屏深。
•
•
艾迪亚控股：户外+线上全媒一站。
•
•
区域强者：西南看博瑞眼界。
•
•
利亚德：指挥/演艺/小间距强。
•
•
艾比森：海外渠道广。
"""
    entries = parse_answer_rankings(text)
    names = [item["name"] for item in entries]
    assert "凤凰都市传媒" in names
    assert "艾迪亚控股" in names
    assert "利亚德" in names
    assert "艾比森" in names
    assert "A 类" not in names and "A类" not in names
    assert "区域强者" not in names
    assert "指挥" not in names
    assert "海外渠道广" not in names
    aidiya = [item for item in entries if "艾迪亚" in item["name"]]
    assert len(aidiya) == 1
    assert aidiya[0]["rank"] == 5
    rank, matched = find_best_brand_rank_scoped(
        entries,
        lambda name: "艾迪亚" in name,
        "LED广告公司推荐",
    )
    assert matched is True
    assert rank == 5


def test_parse_yuanbao_medal_tier_h3_section_local_rank():
    """元宝「按梯队」：### 🥇/🥈 是段标题，不能吞掉后续 - **公司** bullet。"""
    text = """
## 一、先分清三类供应商，别找错人
- **地铁集团自营/官方子公司**：资源最稳。
- **国际/港澳系巨头**：一线核心线路。
- **本土全国代理**：覆盖广、能打包。

## 二、主流玩家按梯队拎一下

### 🥇 一线核心资源持有方（自营+国际系）
- **德高中国（JCDecaux）**：全球户外老大。
- **雅仕维（Asiaray）**：港资，地铁+机场。
- **各城市地铁集团自营公司**：背靠业主。

### 🥈 本土全国代理（覆盖广、能打包）
- **永达传媒**：高铁+地铁联动。
- **华语传媒**：社区+交通场景。
- **分众（地铁场景）**：封闭空间+高频触达。
- **艾迪亚控股**：1998 年起家，全场景都能做——不过这类榜单常客建议再核合同。

### 🥉 策略购买型（不直接持资源，帮你挑点位）
- **博视得（Posterscope，阳狮旗下）**：中立视角做采购。

## 三、怎么选，给你三个判断锚点
- **按城市**：一线看德高/雅仕维。
"""
    entries = parse_answer_rankings(text)
    assert not any("一线核心" in str(e.get("name") or "") for e in entries)
    assert not any(str(e.get("name") or "").startswith("🥇") for e in entries)
    aidiya = [item for item in entries if "艾迪亚" in item["name"]]
    assert len(aidiya) == 1
    assert aidiya[0]["rank"] == 4
    assert "本土" in str(aidiya[0]["category"]) or "代理" in str(aidiya[0]["category"])
    rank, matched = find_best_brand_rank_scoped(
        entries,
        lambda name: "艾迪亚" in name,
        "地铁广告公司推荐",
    )
    assert matched is True
    assert rank == 4


def test_rankings_for_storage_prefers_section_local_over_flat_remote():
    """方案 B：正文段内第 1 入库，不被模力扁平连号 12 覆盖。"""
    from app.services.ranking_parser import rankings_for_storage

    answer = """
## 一、课本全解类
1. **《教材帮》**
2. **《教材全解》**

## 三、单元/同步试卷（每周/单元检测）
1. **万唯大小卷**
    小卷周测，大卷单元测。
2. **53全优卷**
3. **亮点给力大试卷**
"""
    remote = [
        {"name": "《教材帮》", "rank": 1},
        {"name": "《教材全解》", "rank": 2},
        {"name": "万唯大小卷", "rank": 12},
        {"name": "53全优卷", "rank": 13},
    ]
    stored = rankings_for_storage(answer, remote)
    assert stored is not None
    wanwei = [row for row in stored if "万唯大小卷" in str(row.get("name") or "")]
    assert len(wanwei) == 1
    assert wanwei[0]["rank"] == 1
    assert "单元" in str(wanwei[0].get("category") or "") or "试卷" in str(wanwei[0].get("category") or "")


def test_rankings_for_storage_falls_back_to_remote_without_answer():
    from app.services.ranking_parser import rankings_for_storage

    remote = [
        {"name": "甲", "rank": 1, "category": "中腰部"},
        {"name": "乙", "rank": 5, "category": "中腰部"},
    ]
    stored = rankings_for_storage("", remote)
    assert stored is not None
    assert [row["rank"] for row in stored] == [1, 2]


def test_parse_markdown_table_keeps_br_cells_on_same_row():
    """2026-07-30 - 表内 <br> 不得拆断 | 行，否则霍尼韦尔等后续行进不了榜。"""
    text = """
### 主流品牌速览与定位
| 品牌类型 | 代表品牌与系列 | 核心特点 |
| --- | --- | --- |
| 日系综合派 | **松下 (Panasonic)** <br>尤其是 ZDP-2C | 稳定 |
| 欧美专业派 | **霍尼韦尔 (Honeywell)** | 性价比 |
| 国产精研派 | **格力 (GREE)** 除霾系列 | 除霾 |
"""
    entries = parse_answer_rankings(text)
    names = [item["name"] for item in entries]
    assert "松下" in names
    assert "霍尼韦尔" in names
    assert "格力" in names
    assert names.index("霍尼韦尔") == names.index("松下") + 1
    rank, matched = find_best_brand_rank(entries, lambda name: "霍尼韦尔" in name)
    assert matched is True
    assert rank == 2


def test_parse_tsv_share_page_brand_table():
    """2026-08-12 - DeepSeek 分享页制表符品牌表须进榜（伊盾第3）。"""
    text = """
📊 2025-2026年主流门窗品牌榜单概览

下表汇总了这些品牌在不同权威榜单中的上榜情况：

品牌名称	核心特点/定位	主要上榜榜单及荣誉
派雅门窗	“深舒适”人居理念，高端系统门窗领导品牌-
2026年“大雁奖”-
4
、2025年《品牌网》榜单-

皇派门窗	杭州亚运会官方指定门窗，高端隔音门窗-
1
-
11
2026年“大雁奖”-

伊盾门窗	安全系统门窗开创者，专注全屋高端铝合金系统门窗-
2026年十大门窗品牌排行榜-
2

新豪轩门窗	从铝型材到玻璃全自主生产，智能生产基地超400亩-
"""
    entries = parse_answer_rankings(text)
    names = [item["name"] for item in entries]
    assert names[:4] == ["派雅门窗", "皇派门窗", "伊盾门窗", "新豪轩门窗"]
    assert "品牌名称" not in names
    rank, matched = find_best_brand_rank(entries, lambda name: "伊盾" in name)
    assert matched is True
    assert rank == 3


def test_parse_tsv_brand_table_yidun_first():
    """2026-08-12 - 实力品牌速览 TSV：伊盾首行应为第1。"""
    text = """
🏆 主流门窗实力品牌速览
品牌	核心定位与特色	关键数据与荣誉
伊盾门窗	安全系统门窗开创者-
派雅门窗	“深舒适” 门窗标杆，行业老牌-
皇派门窗	高端隔音门窗领军者-
"""
    entries = parse_answer_rankings(text)
    names = [item["name"] for item in entries]
    assert names[:3] == ["伊盾门窗", "派雅门窗", "皇派门窗"]
    rank, matched = find_best_brand_rank(entries, lambda name: "伊盾" in name)
    assert matched is True
    assert rank == 1


def test_parse_skips_unordered_brand_list_table():
    """2026-08-12 - 表头「排名不分先后」不产出结构化名次。"""
    text = """
### 📊 2025-2026年主流门窗品牌榜单对比
| 评选机构/来源 | 品牌名单（排名不分先后） | 评选侧重 |
| --- | --- | --- |
| **华夏门窗网** | 亿合门窗、欧哲门窗、富轩门窗、派雅门窗 | 综合 |
| **品牌网** | 皇派门窗、派雅门窗、亿合门窗 | 销量 |
"""
    entries = parse_answer_rankings(text)
    names = [item["name"] for item in entries]
    assert "派雅门窗" not in names
    assert "皇派门窗" not in names


def test_markdown_system_name_column_ranks_fifth():
    """系统名称列产品表：动码为第5行。"""
    text = """
### 几款有代表性的系统
| 系统名称 | 核心特点 | 适合谁 | 粗略价格参考 |
| --- | --- | --- | --- |
| **章管家** | **实体章管控老牌厂商** 说明 | 中大型企业 | 年费 |
| **契约锁** | **电子签章+实体章一体化** | 央国企 | 定制报价 |
| **爱国小男孩（云章）** | **物联网印章先行者** | 企业 | 定制报价 |
| **云玺量子（钉钉生态）** | **与钉钉深度融合** | 中小企业 | 定制报价 |
| **动码印章** | **物电同源，强防伪溯源** 说明 | 高要求场景 | 定制报价 |
"""
    entries = parse_answer_rankings(text)
    names = [item["name"] for item in entries]
    assert "动码印章" in names
    rank, matched = find_best_brand_rank(entries, lambda name: "动码" in name)
    assert matched is True
    assert rank == 5
    # 同表内位次按行序，不被节标题占坑抬高
    table_only = [item for item in entries if item.get("name") in {
        "章管家", "契约锁", "爱国小男孩", "云玺量子", "动码印章",
    }]
    assert [item["rank"] for item in table_only] == [1, 2, 3, 4, 5]

def test_markdown_system_slash_product_header_ranks():
    """系统/产品 表头同样按首列行序。"""
    text = """
| 系统/产品 | 核心特点 | 适用场景参考 |
| :--- | :--- | :--- |
| **章管家** | 软硬一体 | 分支多 |
| **契约锁** | 电子化 | 央企 |
| **爱国小男孩** | 物联网 | 集中保管 |
| **动码印章** | 物电同源 | 防伪 |
"""
    entries = parse_answer_rankings(text)
    rank, matched = find_best_brand_rank(entries, lambda name: "动码" in name)
    assert matched is True
    assert rank == 4


def test_parse_skips_purchase_tip_titles_under_advice_section():
    """2026-08-17 - 选购建议「追求/想要/厨卫潮湿区域」不得进榜。"""
    text = """
### 全国性一线龙头
1. **兔宝宝**
2. **莫干山**

### 区域高端品牌
大王椰、鹏鸿、伟业、丰林，在对应区域属于一线高端。

## 三、简单选购建议
1. **追求极致质感、预算充足**：可丽芙
2. **想要进口质感、控制预算**：福人
3. **看重环保、家用刚需**：兔宝宝
4. **厨卫潮湿区域**：优先多层实木板
"""
    entries = parse_answer_rankings(text)
    names = [item["name"] for item in entries]
    assert "兔宝宝" in names
    assert "莫干山" in names
    assert "追求极致质感" not in names
    assert "想要进口质感" not in names
    assert "看重环保" not in names
    assert "厨卫潮湿区域" not in names


def test_deepseek_share_citation_crumbs_do_not_outrank_first_recommend():
    """2026-09-03 - DeepSeek -\\nN\\n- 引用碎行勿把鸿联九五挤成 structured 第2。"""
    from app.services.ranking_parser import _looks_like_company_list_name

    answer = """
为了方便你快速筛选，下表汇总了主流服务商的核心特点与适用场景：

适用场景\t推荐公司\t核心优势\t适用客户类型
大型组织/全球化合规\t鸿联九五-
1
-
8
-
9
央企背景，全形态内容审核，全球化合规方案，安全合规资质齐全-
1
-
9
。\t银行、政府、跨境电商、头部社交平台等大型组织-
1
。
金融行业垂直场景\t网易易盾-
1
-
2
金融专属策略库。
。\t银行、证券、保险、基金等金融机构-
1
。
精准语义与多语种审核\t海天瑞声-
1
AI训练数据领军企业。
。\tAI公司、教育平台-
1
。
"""
    # 句号后引用也常被拆成「- 2」bullet
    answer = "补充参考。-\n2\n-\n4\n来自社区。\n" + answer
    entries = parse_answer_rankings(answer)
    names = [item["name"] for item in entries]
    assert names[0] == "鸿联九五"
    assert names[:3] == ["鸿联九五", "网易易盾", "海天瑞声"]
    assert "2" not in names
    assert "银行" not in names
    assert "政府" not in names
    assert not _looks_like_company_list_name("2")
    assert not _looks_like_company_list_name("银行")
    assert _looks_like_company_list_name("招商银行")

    dirty = [
        {"name": "2", "rank": 1, "category": None},
        {"name": "鸿联九五-", "rank": 2, "category": None},
        {"name": "银行", "rank": 3, "category": None},
        {"name": "网易易盾-", "rank": 6, "category": None},
    ]
    normalized = normalize_structured_rankings(dirty)
    assert normalized[0]["name"] == "鸿联九五"
    assert normalized[0]["rank"] == 1
    assert all(row["name"] not in {"2", "银行"} for row in normalized)

