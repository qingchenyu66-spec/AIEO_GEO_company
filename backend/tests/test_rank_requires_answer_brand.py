"""正文未提品牌不得有位次；正文有顿号并列仍可有位次。"""
from types import SimpleNamespace

from app.services.monitor_service import _resolve_brand_rank_detail, _read_display_brand_rank


def _sub(**kwargs):
    defaults = {
        "prompt": "板材品牌哪个好",
        "answer_content": "",
        "mention_context": None,
        "all_rankings_json": [],
        "mention_position": None,
        "raw_result_json": {},
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_context_only_brand_gets_no_rank():
    """mention_context 有品牌、answer 没有 → 不得写位次。"""
    item = _sub(
        answer_content="天津板材市场集中在北辰和东丽，建议去大型批发市场比价。",
        mention_context="里面聚集了大量兔宝宝、千年舟、鹏鸿、大王椰等一线品牌的总代",
        mention_position=4,
        raw_result_json={
            "rank_resolution": {
                "rank": 4,
                "source": "llm",
                "mentioned": True,
                "confidence": 0.92,
                "evidence": "里面聚集了大量兔宝宝、千年舟、鹏鸿、大王椰等一线品牌的总代",
            }
        },
    )
    detail = _resolve_brand_rank_detail(item, "板材品牌哪个好", ["大王椰", "大王椰板材"], None)
    assert detail.rank is None
    assert detail.mentioned is False


def test_answer_enumeration_still_ranks():
    """正文含品牌列表 → 仍可有位次（顿号/编号均走既有解析，不因收紧正文门槛丢掉）。"""
    item = _sub(
        answer_content="1. 兔宝宝\n2. 莫干山\n3. 千年舟\n4. 大王椰",
        mention_context=None,
        mention_position=None,
    )
    detail = _resolve_brand_rank_detail(item, "板材品牌哪个好", ["大王椰"], None)
    assert detail.rank == 4
    assert detail.mentioned is True
    assert detail.source in {"appearance", "structured"}


def test_store_guide_uses_brand_appearance_order_not_location_number():
    """门店题：地点「2.白马商城」下出现品牌 → 按正文品牌出场序第4，而非地点第2。"""
    answer = """
**1. 首选地标：宿州木材建材市场（港口路附近）**
- **特点**：从高端的**兔宝宝、莫干山、千年舟**，到本地通货都有。

**2. 综合卖场：白马商城**
- **推荐**：里面设有**大王椰**、**鹏鸿**等品牌的直营或经销点。

**3. 本地实力派：东昌建材市场**
"""
    item = _sub(
        prompt="宿州板材门店推荐",
        answer_content=answer,
        mention_context="大王椰（宿州总代理）",
        mention_position=2,  # 旧脏位次：地点序
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "宿州板材门店推荐", ["大王椰", "大王椰板材"], None
    )
    assert detail.rank == 4
    assert detail.source == "appearance"
    assert detail.rank_basis == "brand_token_order"


def test_midcentury_answer_ignores_sku_and_material_bold_tokens():
    """中古风长文：色号/材质加粗不计入出场；露出词「大王椰」命中后位次应为品牌序而非33。"""
    answer = """
### 1. **爱格** (奥地利)
- 花色：**H1379**、**H1714**；卖点：**ENF高环保**、**肤感/同步对纹质感高级**
### 2. **福人**
- **L8021逐影胡桃**、**北美黑胡桃**、**实木多层板**
### 选购建议
- 木工现场打柜：**莫干山、大王椰**
"""
    item = _sub(
        prompt="中古风板材品牌哪个好",
        answer_content=answer,
        mention_position=33,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "中古风板材品牌哪个好", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 4  # 爱格、福人、莫干山、大王椰
    assert detail.rank_basis == "brand_token_order"


def test_rank_match_requires_configured_exposure_term_not_generic_fragment():
    """仅有「板材」等泛词、没有配置露出词 → 匹配失败、无位次。"""
    item = _sub(
        prompt="板材品牌哪个好",
        answer_content="家里装修优先选环保板材，注意看ENF标识。",
        mention_position=2,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "板材品牌哪个好", ["大王椰", "大王椰板材"], None
    )
    assert detail.rank is None
    assert detail.mentioned is False


def test_solid_wood_answer_ignores_category_and_species_bold_tokens():
    """实木板长文：方案C按「高性价比」小类内点名，大王椰为第1并带类名。"""
    answer = """
选实木板，**木种**和**等级**比品牌名字更重要。
### 一、 **高端顶配（预算无上限，追求极致）**
**丹麦的Pine**（高端定制线）、意大利的**Riva 1920**。
### 二、 **中高端主流（最推荐）**
- **北美品牌**：**Advantage**、**Columbia**、**Weyerhaeuser**
- **欧洲品牌**：**芬兰的UPM**、**瑞典的Setra**
- **国产一线**：**兔宝宝**、**千年舟**、**莫干山**（**杉木芯**）
### 三、 **高性价比（预算有限）**
**大王椰**、**鹏鸿**、**福庆**。
"""
    item = _sub(
        prompt="实木板品牌哪个好",
        answer_content=answer,
        mention_position=17,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "实木板品牌哪个好", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 1
    assert detail.rank_basis == "secondary_section_local"
    assert detail.category == "高性价比"


def test_station_section_local_rank_not_global_appearance():
    """S1b：第二站内大王椰、福庆 → 类内第1（第二站），不是全文出场第7。"""
    answer = """
按优先级排序：
### 第一站（最推荐）：十里河板材市场（于洪区）
- **有什么**：**鹏鸿、千年舟、兔宝宝、百的宝**等一线品牌。
### 第二站：张士板材市场（铁西区/经济技术开发区）
- **有什么**：**大王椰、福庆**在这里有较大仓库。
### 第三站：红星美凯龙/居然之家内的板材专卖店
- **爱格**、**可丽芙**。
"""
    item = _sub(
        prompt="沈阳板材门店推荐",
        answer_content=answer,
        mention_position=7,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "沈阳板材门店推荐", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 1
    assert detail.rank_basis == "section_local"
    assert detail.category == "第二站"


def test_chapter_market_section_local_not_global_seventh():
    """莆田：一、专卖店已列其它品牌；二、市场句兔宝宝/千年舟/莫干山/大王椰 → 类内第4。"""
    answer = """
# 莆田板材门店&建材市场推荐
## 一、品牌授权专卖店（买板材+可对接加工/全屋定制）
### 涵江区（板材店集中，性价比高）
1. **千年舟（国林装潢店）**
2. **莫干山板材（高林街店）**
3. **精材艺匠**
4. **兔宝宝**
### 城厢区
1. **金利源板材专卖店**
特点：大型仓储批发商，兔宝宝、福人等现货量大。
## 二、大型建材市场（可以多家比价，一站式逛）
1. **喜盈门建材家具广场（城厢区）**
高端商场，兔宝宝、千年舟、莫干山、大王椰等品牌入驻，明码标价。
2. **涵江商业城**
## 三、本地源头工厂（板材+加工一体）
1. **远东木业**
"""
    item = _sub(
        prompt="莆田板材门店推荐",
        answer_content=answer,
        mention_position=7,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "莆田板材门店推荐", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 4
    assert detail.rank_basis == "section_local"
    assert detail.category == "大型建材市场"


def test_bullet_tier_section_local_fourth_not_structured_ninth():
    """环保板：- **兼顾品质与性价比** 下莫干山/千年舟/兔宝宝/大王椰 → 类内第4，不是全文/结构化第9。"""
    answer = """
根据市场工艺，主流品牌分成三个梯队：

- **预算充足、追求极致环保（首选进口高端）**
  - **爱格 (EGGER)**：硬通货。
  - **可丽芙 (Cleaf)**：意大利。
  - **芬萨 (Finsa)**：西班牙。

- **兼顾品质与性价比（国产一线大牌）**
  - **莫干山**：老牌，主打**大豆基无醛胶**，ENF级。
  - **千年舟**：优势在**难燃板**，握钉力强。
  - **兔宝宝**：认知度高，**顺芯板**。
  - **大王椰**：以实木芯为特色。

- **互联网爆款、设计感强（新兴势力）**
  - **万华禾香板**：MDI。
  - **福人**：国企。
"""
    item = _sub(
        prompt="环保板材品牌哪个好",
        answer_content=answer,
        mention_position=9,
        all_rankings_json=[
            {"name": "爱格", "rank": 1},
            {"name": "可丽芙", "rank": 2},
            {"name": "芬萨", "rank": 3},
            {"name": "莫干山", "rank": 4},
            {"name": "千年舟", "rank": 5},
            {"name": "兔宝宝", "rank": 6},
            {"name": "大王椰", "rank": 9},
        ],
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "环保板材品牌哪个好", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 4
    assert detail.rank_basis == "section_local"
    assert "性价比" in (detail.category or "")


def test_store_brand_list_ignores_place_name_bold_tokens():
    """门店题：地名/卖场加粗不计入；兔宝宝/千年舟/莫干山/大王椰 → 第4。"""
    answer = """
### 第一步：锁定核心采购区域
- **主要集群地**：**驿城区**、**中华大道西段**、**天中山大道**
- **新兴商圈**：**置地大道**与**乐山大道**交叉口、**红星美凯龙**
### 第二步：根据品牌类型筛选
- **知名品牌专卖店（品质首选）：** 地图搜索 **“兔宝宝”、“千年舟”、“莫干山”、“大王椰”** 等品牌。
- 买前务必**查防伪**、看**防伪二维码**。
"""
    item = _sub(
        prompt="驻马店板材门店推荐",
        answer_content=answer,
        mention_position=12,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "驻马店板材门店推荐", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 4
    assert detail.rank_basis in {"brand_token_order", "line_enum_local"}


def test_plain_brand_enumeration_ranks_without_bold():
    """方案A：未加粗顿号列表也算出场序。"""
    item = _sub(
        prompt="设计师推荐的板材品牌有哪些",
        answer_content="- 福汉木业、千山、大王椰，这三个品牌木工师傅认可度高。",
        mention_position=None,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "设计师推荐的板材品牌有哪些", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 3
    assert detail.rank_basis in {"brand_token_order", "line_enum_local"}


def test_hefei_plain_list_not_inflated_by_other_bolds():
    """合肥：推荐句未加粗四大牌 → 第4，不被其它卖点加粗虚抬。"""
    answer = """
- **华东建材中心**：最大，可**砍价**。
- **推荐**：兔宝宝、千年舟、莫干山、大王椰的**华东旗舰店**。
- **别只问单价**，还要问**辅材**、**封边**。
"""
    item = _sub(
        prompt="合肥板材门店推荐",
        answer_content=answer,
        mention_position=17,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "合肥板材门店推荐", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 4
    assert detail.rank_basis in {"brand_token_order", "line_enum_local"}
    """莆田避坑句含福人/吉荣/大王椰（≥3）→ P1 同行局部第3，优于全文第7。"""
    answer = """
这是莆田板材性价比最高的地方，因为很多本地知名的木业工厂（如**福人**、**华名华居**等周边供应链）就设在涵江。
- **重点看什么**：这里主要卖**多层实木（生态板）**和**颗粒板**。
- **推荐去处**：商场内的**千年舟**、**莫干山**或**兔宝宝**专卖店。
- **避坑指南**：如果您去这里，**只认福建本地大牌**（如**“福人”**、**“吉荣”**），或者全国连锁的**“大王椰”**。
- **全包价**、**农村自建房**另说。
"""
    item = _sub(
        prompt="莆田板材门店推荐",
        answer_content=answer,
        mention_position=16,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "莆田板材门店推荐", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 3
    assert detail.rank_basis == "line_enum_local"


def test_line_enum_local_beats_inflated_global_token_order():
    """P1：同行≥3品牌列表进池；徐州国民大牌五品牌 → 第4，不是全文 junk 第10。"""
    answer = """
### 首选核心卖场
- **最合适**、**徐州最大**、**最集中**的批发区有**千年舟**、**莫干山**。
### 给您的关键选购建议
- **国民大牌**：**兔宝宝**、**千年舟**、**莫干山**、**大王椰**、**鹏鸿**。
"""
    item = _sub(
        prompt="徐州板材门店推荐",
        answer_content=answer,
        mention_position=10,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "徐州板材门店推荐", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 4
    assert detail.rank_basis == "line_enum_local"


def test_two_brand_line_does_not_override_store_guide_global_fourth():
    """宿州：仅「大王椰、鹏鸿」两品牌行不触发 line_enum；仍全文第4。"""
    answer = """
**1. 首选地标：宿州木材建材市场（港口路附近）**
- **特点**：从高端的**兔宝宝、莫干山、千年舟**，到本地通货都有。

**2. 综合卖场：白马商城**
- **推荐**：里面设有**大王椰**、**鹏鸿**等品牌的直营或经销点。
"""
    item = _sub(
        prompt="宿州板材门店推荐",
        answer_content=answer,
        mention_position=2,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "宿州板材门店推荐", ["大王椰", "大王椰板材"], None
    )
    assert detail.rank == 4
    assert detail.rank_basis == "brand_token_order"


def test_counterfeit_warning_mention_gets_no_rank():
    """假货/贴牌负面点名：只记提及，不进推荐位次。"""
    answer = """
### 1. 批发量大、价格低（源头仓库）
- **居然之家**：**鹏鸿**、**露水河**
### 2. 零售服务好
- **铁西**：**千年舟**、**莫干山**
### 3. 2026年特别避坑提示
- **假货重灾区**：**“兔宝宝”**和**“大王椰”**在沈阳有贴牌加工现象。务必写明**“假一赔十”**。
"""
    item = _sub(
        prompt="沈阳板材门店推荐",
        answer_content=answer,
        mention_position=10,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "沈阳板材门店推荐", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank is None
    assert detail.rank_basis == "negative_context_skip"


def test_store_suffix_plain_list_still_ranks():
    """正面句「兔宝宝…、大王椰板材专卖店」应能坍缩露出词并计位次。"""
    answer = """
红旗建材市场板材一条街：兔宝宝红旗总店、大王椰板材专卖店，ENF级生态板现货充足。
"""
    item = _sub(
        prompt="合肥板材门店推荐",
        answer_content=answer,
        mention_position=None,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "合肥板材门店推荐", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 2
    assert detail.rank_basis == "brand_token_order"


def test_positive_mention_keeps_rank_when_also_in_counterfeit_line():
    """正面推荐与假货警告同时出现时，仍按正面出场计位次。"""
    answer = """
- **推荐门店**：**鹏鸿**、**大王椰**
- **假货重灾区**：**兔宝宝**和**大王椰**有贴牌风险。
"""
    item = _sub(
        prompt="沈阳板材门店推荐",
        answer_content=answer,
        mention_position=10,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "沈阳板材门店推荐", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 2
    assert detail.rank_basis == "brand_token_order"


def test_display_hides_rank_when_answer_loaded_without_brand():
    item = _sub(
        answer_content="完全没有品牌名的一段回答。",
        mention_context="兔宝宝、千年舟、莫干山、大王椰",
        mention_position=4,
        raw_result_json={},
    )
    detail = _read_display_brand_rank(
        item,
        "板材品牌哪个好",
        ["大王椰"],
        None,
        allow_full_parse=False,
    )
    assert detail.rank is None
    assert detail.mentioned is False


def test_display_keeps_manual_rank_without_answer_brand():
    item = _sub(
        answer_content="完全没有品牌名。",
        mention_position=2,
        raw_result_json={"source": "manual_snapshot", "manual_rank_locked": True},
    )
    detail = _read_display_brand_rank(
        item,
        "板材品牌哪个好",
        ["大王椰"],
        None,
        allow_full_parse=False,
    )
    assert detail.rank == 2
    assert detail.source == "manual"


def test_paren_bold_enum_ranks_brand_third():
    """A：加粗括号内顿号（兔宝宝、千年舟、大王椰）→ 第3，不能 mentioned 却无位次。"""
    answer = """
根据装修阶段这样选：
- **追求极致环保和品牌（兔宝宝、千年舟、大王椰）**：去红星美凯龙官方授权专卖店。
- **追求性价比（鹏鸿、福湘）**：看批发市场。
"""
    item = _sub(
        prompt="漳州板材门店推荐",
        answer_content=answer,
        mention_position=None,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "漳州板材门店推荐", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 3
    assert detail.source == "appearance"


def test_quoted_plain_enum_ranks_brand_first():
    """A：未加粗中文引号并列 “大王椰”、“千年舟” → 第1。"""
    answer = """
找门头写“大王椰”、“千年舟”、“鹏鸿”或“鲁丽”的专卖店，散户价格透明。
"""
    item = _sub(
        prompt="天津板材门店推荐",
        answer_content=answer,
        mention_position=None,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "天津板材门店推荐", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 1
    assert detail.source == "appearance"


def test_dha_sell_points_do_not_inflate_appearance_rank():
    """B：卖点句不得进出场池；宝得聪在「纽曼思、健敏思、宝得聪」应为第3而非十几。"""
    answer = """
海藻原味、部分宝宝嫌腥、易过敏宝宝也要注意。
开封尽快吃完，几乎无腥味，孩子接受度高。
推荐顺序：纽曼思、健敏思、宝得聪
"""
    item = _sub(
        prompt="儿童DHA品牌推荐",
        answer_content=answer,
        mention_position=14,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "儿童DHA品牌推荐", ["宝得聪"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 3
    assert detail.rank_basis in {"brand_token_order", "line_enum_local"}


def test_prose_product_title_mentioned_without_rank():
    """B：仅「万唯新初一分班考」散文露出 → 提及但无合格枚举则空位次。"""
    answer = """
三、分班考专用（有分班考试必买）
万唯新初一分班考
小学知识 80%+ 初一预科 20%，真题卷。
"""
    item = _sub(
        prompt="新初一暑假自学教辅书",
        answer_content=answer,
        mention_position=1,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "新初一暑假自学教辅书", ["万唯", "小白鸥", "腾远"], None
    )
    assert detail.mentioned is True
    assert detail.rank is None


def test_tsv_share_table_gives_structured_rank():
    """2026-08-12 - 分享页 TSV 品牌表：伊盾第3，不得空位次。"""
    answer = """
📊 2025-2026年主流门窗品牌榜单概览
品牌名称	核心特点/定位	主要上榜榜单及荣誉
派雅门窗	深舒适
皇派门窗	高端隔音
伊盾门窗	安全系统门窗开创者
新豪轩门窗	全自主生产
"""
    from app.services.ranking_parser import parse_answer_rankings

    rankings = parse_answer_rankings(answer)
    item = _sub(
        prompt="中国十大门窗品牌",
        answer_content=answer,
        mention_position=None,
        all_rankings_json=rankings,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(item, "中国十大门窗品牌", ["伊盾门窗"], None)
    assert detail.mentioned is True
    assert detail.rank == 3
    assert detail.source == "structured"


def test_edu_sell_points_do_not_inflate_to_28():
    """C1：教辅卖点句不得虚高；万唯大小卷/同步听力坍缩后应靠前。"""
    answer = """
分课本讲解类、同步课时练习、单元试卷、知识点超细致、课文逐句拆解。
万唯大小卷：中考教研团队出题，题型新颖。
文言文：万唯《文言文完全解读》。
四、分科目专项：万唯同步听力。
"""
    item = _sub(
        prompt="初一同步辅导书推荐",
        answer_content=answer,
        mention_position=28,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "初一同步辅导书推荐", ["万唯", "小白鸥", "腾远"], None
    )
    assert detail.mentioned is True
    assert detail.rank is not None
    assert float(detail.rank) < 10


def test_edu_book_title_preferred_mentions_brand():
    """C1：统一首选《万唯初中基础知识七年级》→ 至少提及并可定位位次。"""
    answer = """
小四门统一首选：《万唯初中基础知识七年级》
整本书浓缩四科知识点，思维导图、考点总结。
"""
    item = _sub(
        prompt="初一同步辅导书推荐",
        answer_content=answer,
        mention_position=None,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "初一同步辅导书推荐", ["万唯", "小白鸥", "腾远"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 1


def test_edu_numbered_section_not_inflated_by_structured_headers():
    """语法&阅读下 3.万唯听力：类内第3，不被「词汇/语法&阅读」标题抬成第7。"""
    answer = """
📕英语（词汇是核心）
### 词汇
1. **闪过·预备新初一**：小初衔接。
2. **蝶变初中词汇+默写本**：背核心词。

### 语法&阅读
1. **星火英语 小升初衔接语法**：梳理语法。
2. **快捷英语时文阅读（小升初/七年级）**：每天1篇。
3. **万唯听力**：基础听力训练。
"""
    item = _sub(
        prompt="小升初暑假衔接必备教辅",
        answer_content=answer,
        mention_position=7,
        all_rankings_json=[
            {"name": "词汇", "rank": 1, "category": "📕英语"},
            {"name": "闪过·预备新初一", "rank": 2, "category": "📕英语"},
            {"name": "蝶变初中词汇+默写本", "rank": 3, "category": "📕英语"},
            {"name": "语法&阅读", "rank": 4, "category": "📕英语"},
            {"name": "星火英语 小升初衔接语法", "rank": 5, "category": "📕英语"},
            {"name": "快捷英语时文阅读", "rank": 6, "category": "📕英语"},
            {"name": "万唯听力", "rank": 7, "category": "📕英语"},
        ],
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "小升初暑假衔接必备教辅", ["万唯", "小白鸥", "腾远"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 3
    assert detail.rank_basis == "section_local"


def test_edu_subject_section_not_inflated_by_chapter_numbering():
    """分学科教辅下 ### 英语 内 3.万唯：类内第3，不被跨科连号抬到第5+。"""
    answer = """
## 二、分学科教辅
### 📖语文
1. **教材帮七上**：划重点。
2. **必刷题语文**：衔接练习。
3. **文言文完全解读**：预习。

### 📐数学
1. **必刷题预备新初一**：计算。
2. **教材划重点数学**：概念。

### 🗣️英语
1. **蝶变初中英语词汇**：单词。
2. **星火英语 小升初衔接语法**：语法。
3. **万唯听力**：基础听力训练。
"""
    item = _sub(
        prompt="小升初暑假衔接必备教辅",
        answer_content=answer,
        mention_position=7,
        all_rankings_json=[
            {"name": "教材帮七上", "rank": 1, "category": "分学科教辅"},
            {"name": "必刷题语文", "rank": 2, "category": "分学科教辅"},
            {"name": "文言文完全解读", "rank": 3, "category": "分学科教辅"},
            {"name": "必刷题预备新初一", "rank": 4, "category": "分学科教辅"},
            {"name": "教材划重点数学", "rank": 5, "category": "分学科教辅"},
            {"name": "蝶变初中英语词汇", "rank": 6, "category": "分学科教辅"},
            {"name": "星火英语 小升初衔接语法", "rank": 7, "category": "分学科教辅"},
            {"name": "万唯听力", "rank": 8, "category": "分学科教辅"},
        ],
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "小升初暑假衔接必备教辅", ["万唯", "小白鸥", "腾远"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 3
    assert detail.rank_basis == "section_local"
    assert detail.category == "英语"


def test_edu_chapter_paper_section_first_not_global_fifth():
    """四、试卷类仅《万唯大小卷》→ 类内第1，不被刷题卖点词抬成全文第5。"""
    answer = """
一、同步讲解类（预习 + 吃透课本）
1. 《教材帮》（首选）
2. 《中学教材全解》
二、同步刷题类（课后巩固，分难度）
✅ 基础中等：《5 年中考 3 年模拟》
特点：答案解析详细，日常作业首选。
✅ 稳步提分：《一遍过》
特点：学练测三合一，梯度清晰。
✅ 培优拔高：《典中点》
特点：创新题多。
三、3 套最优搭配（直接照抄）
基础薄弱：教材帮 + 5・3
四、试卷类（单元检测）
《万唯大小卷》：小卷周测、大卷单元考，用来阶段性查漏补缺。
五、选购提醒
只买 1 讲 + 1 练，避免做不完。
"""
    item = _sub(
        prompt="初一同步辅导书推荐",
        answer_content=answer,
        mention_position=5,
        all_rankings_json=[
            {"name": "《教材帮》", "rank": 1, "category": "同步讲解类"},
            {"name": "《中学教材全解》", "rank": 2, "category": "同步讲解类"},
        ],
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "万唯", ["万唯", "万唯大小卷"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 1
    assert detail.rank_basis == "section_local"
    assert detail.category == "试卷类"


def test_edu_numbered_subheading_second_not_token_fifth():
    """### 2. 下《万唯初升高衔接》→ 第2，不被节内卖点 token 抬成第5。"""
    answer = """
## 一、全科通用·初升高衔接用书（暑假开篇必用）
### 1. 基础薄弱、自律一般（稳妥过渡）
**《预备新高一》**
- 适用：初中中下游、害怕高中难度、自学容易走神的同学。

### 2. 中等生、冲刺分班考（高效提速）
**《万唯初升高衔接》**
- 适用：初中成绩中等，想开学领先。

### 3. 尖子生、理科思维拔高
**《更高更妙·初升高衔接手册》**
- 适用：中考高分、想超前学。
"""
    item = _sub(
        prompt="新高一暑假预习教辅推荐",
        answer_content=answer,
        mention_position=5,
        all_rankings_json=[],
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "万唯", ["万唯", "万唯初升高衔接"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 2
    assert detail.rank_basis == "section_local"


def test_merged_duplicate_rankings_do_not_inflate_structured_rank():
    """2026-08-12 - parse 与 all_rankings 双份同名时，主流产品第6不可抬成第11。"""
    from app.services.monitor_service import _find_brand_in_rankings

    rankings = [
        {"name": "章管家", "rank": 1, "category": "主流产品推荐"},
        {"name": "金蝶妙想智能印控仪", "rank": 2, "category": "主流产品推荐"},
        {"name": "思格特·印章卫士6.0", "rank": 3, "category": "主流产品推荐"},
        {"name": "云玺量子 AI智能印章", "rank": 4, "category": "主流产品推荐"},
        {"name": "御鑫箱智能印章柜", "rank": 5, "category": "主流产品推荐"},
        {"name": "动码印章", "rank": 6, "category": "主流产品推荐"},
        {"name": "泛微印控解决方案", "rank": 7, "category": "主流产品推荐"},
    ]
    answer = """
## 主流产品推荐
### 1.章管家
### 2.金蝶妙想智能印控仪
### 3.思格特·印章卫士6.0
### 4.云玺量子 AI智能印章
### 5.御鑫箱智能印章柜
### 6.动码印章（物电同源）
### 7.泛微印控解决方案
"""
    item = _sub(
        prompt="智能印章管理系统推荐",
        answer_content=answer,
        all_rankings_json=rankings,
        mention_position=None,
    )
    rank, matched, category = _find_brand_in_rankings(
        item, ["动码印章"], None, monitor_keywords="动码印章"
    )
    assert matched is True
    assert rank == 6
    assert category == "主流产品推荐"
    detail = _resolve_brand_rank_detail(item, "动码印章", ["动码印章"], None)
    assert detail.rank == 6
    assert detail.source == "structured"


def test_secondary_mention_section_gets_local_rank():
    """2026-08-12 - 「其他值得关注」点名算小节内排名，勿清空、勿抬成全文 10/18。"""
    answer = """
### 🥇 品牌速览与推荐
| 品牌 | 定位 |
| 云玺量子 | 全栈安全 |
| 群杰 | 集团管控 |
| 思格特 | 便携 |

### 🔍 其他值得关注的品牌
*   **动码印章**：物电同源、一章一码防伪。
*   **爱国小男孩（云章）**：物联网+印章。
"""
    item = _sub(
        prompt="智能印章品牌推荐",
        answer_content=answer,
        mention_position=18,
        all_rankings_json=[
            {"name": "云玺量子", "rank": 1, "category": "品牌速览与推荐"},
            {"name": "群杰", "rank": 2, "category": "品牌速览与推荐"},
            {"name": "思格特", "rank": 3, "category": "品牌速览与推荐"},
        ],
    )
    detail = _resolve_brand_rank_detail(item, "动码印章", ["动码印章"], None)
    assert detail.mentioned is True
    assert detail.rank == 1
    assert detail.rank_basis == "secondary_section_local"

    detail2 = _resolve_brand_rank_detail(item, "爱国小男孩", ["爱国小男孩"], None)
    assert detail2.rank == 2
    assert detail2.rank_basis == "secondary_section_local"


def test_secondary_reference_section_local_rank():
    """2026-08-12 - 「其他实力品牌参考」里第二位应为 2，不是全文出场 10。"""
    answer = """
### 主流品牌对比
| 品牌 | 特点 |
| 云玺量子 | A |
| 群杰 | B |

### 其他实力品牌参考
*   **爱国小男孩**：物联网。
*   **动码印章**：物电同源。
*   **云之印**：云端管控。
"""
    item = _sub(
        prompt="智能印章品牌推荐",
        answer_content=answer,
        mention_position=10,
        all_rankings_json=[
            {"name": "云玺量子", "rank": 1, "category": "主流品牌对比"},
            {"name": "群杰", "rank": 2, "category": "主流品牌对比"},
        ],
    )
    detail = _resolve_brand_rank_detail(item, "动码印章", ["动码印章"], None)
    assert detail.mentioned is True
    assert detail.rank == 2
    assert detail.rank_basis == "secondary_section_local"


def test_structured_table_beats_advice_line_enum():
    """2026-08-12 - 主表第4不应被「可以关注动码」建议句盖成第1。"""
    answer = """
### 🏆 重点智能印章品牌速览
1. 云玺量子
2. 群杰
3. 思格特
4. 动码印章
5. 爱国小男孩

### 🤔 如何根据你的需求选择？
*   **如果你的痛点在于文件防伪**：可以关注**动码印章**。
"""
    rankings = [
        {"name": "云玺量子", "rank": 1},
        {"name": "群杰", "rank": 2},
        {"name": "思格特", "rank": 3},
        {"name": "动码印章", "rank": 4},
        {"name": "爱国小男孩", "rank": 5},
    ]
    item = _sub(
        prompt="智能印章品牌推荐",
        answer_content=answer,
        all_rankings_json=rankings,
        mention_position=1,
    )
    detail = _resolve_brand_rank_detail(item, "动码印章", ["动码印章"], None)
    assert detail.rank == 4
    assert detail.rank_basis in {"structured", "numbered_subheading", "section", "table"}


def test_subject_section_branded_book_is_local_first():
    """语文下「专项：万唯《…》」→ 类内第1；方案A/名著书名号不得抬位。"""
    answer = """
## 📘语文（七上）
自学重点：古诗文预习、生字词、现代文梳理、名著《朝花夕拾》《西游记》
**方案A（稳妥通用）**
讲解：教材划重点 / 涂重点
练习：5·3七上语文
专项：万唯《初中文言文完全解读》（课内古文长期使用）
拓展：《一本 七年级阅读五合一》

## 📗数学（七上）
练习：5·3七上数学
"""
    item = _sub(
        prompt="新初一暑假自学教辅书",
        answer_content=answer,
        mention_position=None,
        all_rankings_json=[],
    )
    detail = _resolve_brand_rank_detail(
        item, "万唯", ["万唯", "小白鸥", "腾远"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 1
    assert detail.rank_basis == "section_local"
    assert detail.category == "语文"


def test_geo_brand_section_choose_is_local_first():
    """全国性品牌下「可选择艾迪亚」→ 类内第1。"""
    answer = """
### 全国性品牌
可选择艾迪亚这类代理商网络较完善的品牌。
"""
    item = _sub(
        prompt="短剧投放平台",
        answer_content=answer,
        mention_position=None,
        all_rankings_json=[],
    )
    detail = _resolve_brand_rank_detail(item, "艾迪亚", ["艾迪亚"], None)
    assert detail.mentioned is True
    assert detail.rank == 1
    assert detail.rank_basis == "section_local"
    assert detail.category == "全国性品牌"


def test_tool_platform_anishort_lead_is_local_first():
    """短剧工具平台下 AniShort：为首条 → 类内第1。"""
    answer = """
## 二、短剧拍摄 & AI 制作工具平台
1. **AniShort**：AI短剧制作。
2. **FooBar**：其它工具。
"""
    item = _sub(
        prompt="短剧拍摄工具",
        answer_content=answer,
        mention_position=None,
        all_rankings_json=[],
    )
    detail = _resolve_brand_rank_detail(item, "AniShort", ["AniShort"], None)
    assert detail.mentioned is True
    assert detail.rank == 1
    assert detail.rank_basis in {"section_local", "section"}
    assert detail.source in {"appearance", "structured"}


def test_arrow_find_two_brands_line_enum_second():
    """「→ 找天赐、艾迪亚」→ 行内第2。"""
    answer = "预算有限时 → 找天赐、艾迪亚"
    item = _sub(
        prompt="短剧投放",
        answer_content=answer,
        mention_position=None,
        all_rankings_json=[],
    )
    detail = _resolve_brand_rank_detail(item, "艾迪亚", ["艾迪亚"], None)
    assert detail.mentioned is True
    assert detail.rank == 2
    assert detail.rank_basis == "line_enum_local"


def test_three_brand_slash_line_enum_third():
    """「澜翼、云翼、艾迪亚/亦智」→ 行内第3。"""
    answer = "同类还有澜翼、云翼、艾迪亚/亦智等可对比。"
    item = _sub(
        prompt="短剧投放",
        answer_content=answer,
        mention_position=None,
        all_rankings_json=[],
    )
    detail = _resolve_brand_rank_detail(item, "艾迪亚", ["艾迪亚", "亦智"], None)
    assert detail.mentioned is True
    assert detail.rank == 3
    assert detail.rank_basis == "line_enum_local"


def test_system_name_table_beats_row_sellpoint_line_enum():
    """系统名称表第5行动码；表行「物电同源」不得 line_enum 成第2。"""
    answer = """
### 两种主流思路：先看你要管什么
| 对比维度 | **方案一：管实体印章** | **方案二：用电子印章** |
| --- | --- | --- |
| **核心目标** | 追溯谁盖了什么 | 线上自动化 |

### 几款有代表性的系统
| 系统名称 | 核心特点 | 适合谁 | 粗略价格参考 |
| --- | --- | --- | --- |
| **章管家** | **实体章管控老牌厂商** | 中大型 | 年费 |
| **契约锁** | **电子签章一体化** | 央国企 | **定制报价** |
| **爱国小男孩（云章）** | **物联网印章先行者** | 企业 | **定制报价** |
| **云玺量子（钉钉生态）** | **与钉钉深度融合** | 中小 | **定制报价** |
| **动码印章** | **物电同源，强防伪溯源** | 高要求 | **定制报价** |
"""
    item = _sub(
        prompt="智能印章管理系统推荐",
        answer_content=answer,
        mention_position=2,
        all_rankings_json=[
            {"name": "两种主流思路", "rank": 1},
            {"name": "几款有代表性的系统", "rank": 2},
        ],
    )
    detail = _resolve_brand_rank_detail(item, "动码印章", ["动码印章", "动码"], None)
    assert detail.mentioned is True
    assert detail.rank == 5
    assert detail.source == "structured"


def test_supplement_two_bold_brands_line_enum_second():
    """补充句「还有像爱国小男孩和动码」→ 行内第2；物电同源引号不得抬成第3。"""
    answer = """
| 推荐品牌 | 核心优势 |
| :--- | :--- |
| **云玺量子** | 全栈 |

> 补充一点：还有像**爱国小男孩**（侧重“物联网+印章”）和**动码印章**（主打“物电同源”）等特色品牌，也各有侧重。
"""
    item = _sub(
        prompt="智能印章管理系统推荐",
        answer_content=answer,
        mention_position=3,
        all_rankings_json=[],
    )
    detail = _resolve_brand_rank_detail(item, "动码印章", ["动码印章", "动码"], None)
    assert detail.mentioned is True
    assert detail.rank == 2
    assert detail.rank_basis == "line_enum_local"


def test_unordered_ten_brands_table_uses_frequent_line_enum_second():
    """「排名不分先后」长榜勿虚抬；频繁出现句按格：派雅第2。"""
    answer = """
### 📊 2025-2026年主流门窗品牌榜单对比
| 评选机构/来源 | 品牌名单（排名不分先后） | 评选侧重 |
| --- | --- | --- |
| **华夏门窗网** | 亿合门窗、欧哲门窗、富轩门窗、墨瑟门窗、皇派门窗、良木道门窗、飞宇门窗、新豪轩门窗、森鹰窗业、派雅门窗 | 综合 |
| **品牌网** | 皇派门窗、轩尼斯门窗、欧铂尼、龙树、派雅门窗、旭格、金大田、亿合门窗、富轩门窗、博仕门窗 | 销量 |

### 💡 如何看懂这些榜单？
可以看到，在不同榜单中频繁出现的品牌（如**皇派门窗、派雅门窗、新豪轩门窗、亿合门窗、富轩门窗**等），说明它们在多个维度都得到了认可，是市场公认的头部选择。
"""
    dirty_stored = [
        {"name": "派雅门窗", "rank": 10, "category": "📊 2025-2026年主流门窗品牌榜单对比"},
        {"name": "皇派门窗", "rank": 1, "category": "📊 2025-2026年主流门窗品牌榜单对比"},
    ]
    item = _sub(
        prompt="中国十大门窗品牌",
        answer_content=answer,
        mention_position=10,
        all_rankings_json=dirty_stored,
    )
    detail = _resolve_brand_rank_detail(item, "派雅门窗", ["派雅门窗", "派雅"], None)
    assert detail.mentioned is True
    assert detail.rank == 2
    assert detail.rank_basis == "line_enum_local"


def test_numbered_subheading_without_space_after_dot():
    """### 7.大王椰 无空格：S1 标题序=7，勿吃扁平 structured 子项脏榜。"""
    answer = """## 国产主流ENF环保板材（家装首选）
### 1.万华禾香板
- 基材：秸秆刨花板
- 优点：环保表现优秀
- 缺点：防潮一般
### 2.鲁丽欧松板
- 优点：稳定性好
### 3.兔宝宝
- 优点：门店多
### 4.千年舟
### 5.莫干山
### 6.福人竹香板
### 7.大王椰
- 生态板、多层板见长
"""
    item = _sub(
        prompt="环保板材品牌哪个好",
        answer_content=answer,
        mention_position=10,
        all_rankings_json=[
            {"name": "万华禾香板", "rank": 1, "category": "国产主流ENF环保板材"},
            {"name": "基材", "rank": 2, "category": "国产主流ENF环保板材"},
            {"name": "大王椰", "rank": 13, "category": "国产主流ENF环保板材"},
        ],
    )
    detail = _resolve_brand_rank_detail(
        item, "杭州大王椰装饰新材料有限公司", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 7
    assert detail.rank_basis in {"numbered_subheading", "section_local", "numbered_list"}


def test_nested_tier_continued_numbering_rebases_to_subtier_rank():
    """## 国产下 ###第一梯队 1-4 + ###国民头部 5-8 续号 → 大王椰子档内第4，非总榜8。"""
    answer = """
# 高端板材品牌（全屋定制常用）
## 一、进口高端板材（预算高，门板首选）
1. **爱格EGGER｜奥地利**
2. **可丽芙CLEAF｜意大利**
3. **克诺斯邦Kronospan｜德国**
4. **芬萨Finsa｜西班牙**
5. **博耐克Berneck｜巴西**
6. **飞德莱Pfleiderer｜德国**

## 二、国产高端板材（ENF级，性价比高）
### 国产第一梯队（环保&品控顶尖）
1. **万华·禾香板**
2. **福人FUREN（福建）**
3. **红棉花（广东）**
4. **鲁丽**

### 国民头部高端线
5. **兔宝宝**
6. **千年舟**
7. **莫干山**
8. **大王椰**
饰面工艺好，线下渠道强，高端系列定位高。
"""
    item = _sub(
        prompt="高端板材品牌有哪些",
        answer_content=answer,
        mention_position=8,
        raw_result_json={
            "rank_resolution": {
                "rank": 8,
                "source": "llm",
                "rank_basis": "numbered_subheading",
            }
        },
    )
    detail = _resolve_brand_rank_detail(
        item, "高端板材品牌有哪些", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 4
    assert detail.rank_basis in {"numbered_subheading", "section_local", "numbered_list"}


def test_child_room_supplemental_tier_section_local_rank():
    """儿童房：主榜 ###1-6 无大王椰，高性价比备选 bullet → 类内第1（非全文7）。"""
    answer = """
## 一、国产一线（儿童房主流首选，ENF级齐全）
### 1. 兔宝宝
### 2. 千年舟
### 3. 莫干山
### 4. 万华·禾香板
### 5. 鲁丽欧松板（OSB）
### 6. 雪宝板材

## 二、高性价比备选品牌（ENF可选，预算友好）
- **大王椰**：杉木芯生态板口碑好
- **伟业**：ENF-OSB欧松板
- **露水河（吉林森工）**：松木基材颗粒板
"""
    item = _sub(
        prompt="儿童房环保板材品牌哪个好",
        answer_content=answer,
        mention_position=7,
        raw_result_json={
            "rank_resolution": {
                "rank": 7,
                "source": "llm",
                "rank_basis": "section_bullet",
            }
        },
    )
    detail = _resolve_brand_rank_detail(
        item, "儿童房环保板材品牌哪个好", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 1
    assert detail.rank_basis == "secondary_section_local"
    assert detail.category and "高性价比" in detail.category


def test_home_decor_regional_supplemental_section_local_rank():
    """家装：全国一线 1-6 主榜无大王椰，区域强势 bullet → 类内第3（非全文11）。"""
    answer = """
## 国产主流靠谱品牌（家装常用）
### 全国一线（门店多，品控稳定）
1. **兔宝宝（浙江）**
2. **千年舟（浙江）**
3. **莫干山（浙江）**
4. **万华（山东）**
5. **鲁丽（山东）**
6. **福人（福建）**

### 区域强势好品牌
- 广东：**红棉花、伟业**
- 湖南：**雪宝、万象**
- 大王椰：生态板、多层板国标起草单位
"""
    item = _sub(
        prompt="家装板材品牌质量哪个好",
        answer_content=answer,
        mention_position=11,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "家装板材品牌质量哪个好", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 3
    assert detail.rank_basis == "secondary_section_local"
    assert detail.category and "区域" in detail.category


def test_negative_news_case_gets_no_rank():
    """家装避坑「新闻报道选购大王椰后爆裂」→ 只记提及，无推荐位次。"""
    answer = """
| 品牌 | 核心优势 | 适合场景 |
| 兔宝宝 | ENF+ | 儿童房 |
| 千年舟 | 防潮 | 厨房 |
| 莫干山 | 大豆胶 | 卧室 |
| 鹏鸿 | 握钉力 | 北方 |
| 福庆 | 绿色采购 | 华东 |

### 怎么才能选对、不踩坑？
1. 看环保检测报告
2. 认准自有工厂
3. **警惕负面案例**：曾有新闻报道，选购了「大王椰」的板材，使用不到一年表面爆裂，赔偿陷入僵局。
"""
    item = _sub(
        prompt="家装板材品牌质量哪个好",
        answer_content=answer,
        mention_position=8,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "家装板材品牌质量哪个好", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank is None
    assert detail.rank_basis == "negative_context_skip"


def test_high_end_table_trailing_prose_rank_four():
    """高端：主表4品牌无大王椰，段尾「万象/福湘/鹏鸿/大王椰」→ 行内第4非12。"""
    answer = """
### 国内一线高端品牌
| 品牌 | 核心优势 | 环保亮点 |
| 兔宝宝 | 上市公司 | ENF+ |
| 千年舟 | 亚运供应商 | HENF |
| 莫干山 | CNAS实验室 | ENF |
| 大亚圣象 | 供应链 | 无醛添加 |

此外，国内一线高端品牌中，还有**万象**、**福湘**、**鹏鸿**、**大王椰**等其他口碑较好的品牌值得关注。

### 国际高端品牌
- 克诺斯邦
"""
    item = _sub(
        prompt="高端板材品牌有哪些",
        answer_content=answer,
        mention_position=12,
        raw_result_json={
            "rank_resolution": {
                "rank": 12,
                "source": "llm",
                "rank_basis": "section_local",
            }
        },
    )
    detail = _resolve_brand_rank_detail(
        item, "高端板材品牌有哪些", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 4
    assert detail.rank_basis == "line_enum_local"


def test_ecological_board_regional_tier_section_local_rank():
    """生态板：一线头部无大王椰，区域代表性段 → 类内第3（非全文10）。"""
    answer = """
### 一线头部品牌：行业标杆
*   **兔宝宝**：产品线全
*   **千年舟**：绿色健康
*   **莫干山**：华东认知高

### 实力特色品牌：性价比高
*   **万象板材**：性价比高
*   **鹏鸿板材**：东北市场
*   **福湘板材**：中南地区

### 区域代表性品牌：深耕本地
*   **伟业板材**：华南份额高
*   **露水河**：北方成本优
*   **大王椰**：定位为中高端市场的性价比之选
"""
    item = _sub(
        prompt="生态板品牌哪个好",
        answer_content=answer,
        mention_position=10,
        raw_result_json={
            "rank_resolution": {"rank": 10, "source": "llm", "rank_basis": "section"},
        },
    )
    detail = _resolve_brand_rank_detail(
        item, "生态板品牌哪个好", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 3
    assert detail.rank_basis == "secondary_section_local"
    assert detail.category and "区域" in detail.category


def test_shared_conversation_pollution_stripped_for_store_rank():
    """南昌门店：Shared Conversation/思考区污染勿抬出场序；正文列表大王椰第2。"""
    answer = """
Shared Conversation Instant
This shared conversation is generated by AI, for reference only.
Thought for 3 seconds
用户需要南昌板材门店推荐，我将搜索并整理市场与品牌门店。
Found 65 web pages

### 主要品牌门店
| 品牌 | 门店名称 | 所在区域 | 地址 |
| 兔宝宝 | 兔宝宝专卖店 | 青山湖区 | 香江家居 |
| 千年舟 | 千年舟展示中心 | 南昌县 | 华南城 |
| 大王椰 | 大王椰板材 | 西湖区 | 司马庙建材城 |
"""
    item = _sub(
        prompt="南昌板材门店推荐",
        answer_content=answer,
        mention_position=9,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "南昌板材门店推荐", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 3
    assert float(detail.rank) < 9


def test_tianjin_other_region_store_cell_enum_rank():
    """天津门店：「其他区域门店」格内多商家 → 大王椰第2非9。"""
    answer = """
| 推荐市场/区域 | 主要特点 | 所在区域 | 代表商家/门店 |
| 潘庄木材市场 | 华北大型 | 宁河区 | 欣盛国际木业 |
| 环渤海装饰城 | 市区综合 | 河西区 | 莫干山、千年舟 |
| 其他区域门店 | 覆盖武清等 | 各区域 | 雪元板材、大王椰板材、周立强建材 |
"""
    item = _sub(
        prompt="天津板材门店推荐",
        answer_content=answer,
        mention_position=9,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "天津板材门店推荐", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 2
    assert detail.rank_basis == "rep_column"


def test_nanchang_store_table_brand_dedup_rank_third():
    """南昌门店：品牌|门店表多行兔宝宝/千年舟（含续行缺品牌列）→ 大王椰第3。"""
    answer = """
南昌的板材市场主要集中在青云谱区、青山湖区和红谷滩区。

品牌	门店名称	所在区域	地址	联系电话
兔宝宝	兔宝宝板材(喜盈门旗舰店)	西湖区	抚生南路9号	-
兔宝宝健康饰材易装馆	青山湖区	解放二街33号	13970972665
兔宝宝健康板材厨柜衣柜专卖店	新建区	长麦路38号	-
兔宝宝健康饰材专卖店	南昌县	澄湖中路37号	13177858696
兔宝宝板材	青山湖区	经开区枫庐新天地B5栋3号	13870957108
千年舟	千年舟板材专卖店	青山湖区	解放西路香江建材市场	18970067768
千年舟建材家居	新建区	长堎镇拓新路	-
千年舟饰材专卖	南昌县	莲塘中大道746号	13870082263
大王椰	大王椰木业(香江专卖店)	青山湖区	香江中路122号	13970800946
大王椰板材(高新专卖店)	南昌县	艾溪湖南路	18879138953
鹏鸿	鹏鸿板材定制家居	青云谱区	装潢建材市场12栋9号	13037221256
"""
    item = _sub(
        prompt="南昌板材门店推荐",
        answer_content=answer,
        mention_position=9,
        raw_result_json={
            "source": "manual_snapshot",
            "manual_rank_locked": False,
        },
    )
    detail = _resolve_brand_rank_detail(
        item, "南昌板材门店推荐", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 3
    assert detail.source == "structured"


def test_tianjin_numbered_section_other_region_rank_three():
    """天津22178：###3.其他区域门店 bullet 红桥大王椰 → 类内第3。"""
    answer = """
### 1. 河西区珠江装饰城及周边（零售首选）
*   **谢姐木材 & 百强/莫干山/千年舟等品牌店**
### 2. 宁河区潘庄名贵木材市场
*   **欣盛国际木业**
### 3. 其他区域门店备选
*   **滨海新区**：**吉安装饰板材总汇**
*   **西青区**：**宏坤宅配装饰材料经营店**
*   **红桥区**：**大王椰板材(红桥店)**
"""
    item = _sub(
        prompt="天津板材门店推荐",
        answer_content=answer,
        mention_position=9,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "天津板材门店推荐", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 3
    assert detail.rank_basis in {"section", "section_local", "secondary_section_local"}


def test_jinyu_nuclear_h4_brand_first_not_tip_section_six():
    """金隅18439：#### 国内品牌首卡 + 文末表/选型建议 → 第1非建议段第6。"""
    answer = """
### 🇨🇳 国内品牌
#### 金隅涂料（BBMG Coating）
- **背景**：始建于1984年
#### 信和新材料（Xinhe New Materials）
- **背景**：国内最大核电防护涂料服务商之一
#### 湘江涂料（Xiangjiang Paint）
- **背景**：央企中国兵器工业集团旗下

### 🌍 国际品牌
| 品牌 | 国家 | 核心优势 |
|------|------|----------|
| **PPG工业** | 美国 | 全球核电项目经验丰富 |
| **佐敦（Jotun）** | 挪威 | 核级涂料线 |

### 📌 选型建议
- **核岛级应用**：优先考虑金隅涂料、信和新材、湘江涂料、中科美斯等
- **国产化替代**：金隅涂料、信和新材、湘江涂料优势明显
"""
    item = _sub(
        prompt="核电涂料品牌",
        answer_content=answer,
        mention_position=1,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(item, "核电涂料品牌", ["金隅涂料"], None)
    assert detail.mentioned is True
    assert detail.rank == 1
    assert detail.rank_basis != "secondary_section_local"


def test_jinyu_terazzo_state_owned_bullet_first_not_tip_two():
    """金隅22270：国企段 * **金隅涂料**：… 为类内第1，勿落「如何做出选择」第2。"""
    answer = """
### 🌍 国际一线品牌：技术与美学
*   **西卡 (Sika)**：全球特种化学品巨头
*   **马贝 (Mapei)**：意大利品牌

### 🏛️ 国企背景品牌：安全与大型公建
*   **金隅涂料**：隶属于北京金隅集团，是国内最早布局无机磨石的头部品牌。

### 🏢 国内市场化头部品牌
*   **秀珀 (Supe)**：国内地坪行业元老级品牌

### 💡 如何做出选择？
1.  **追求极致装饰效果**：优先考虑 **西卡、马贝**
2.  **涉及严格消防验收、超大面积公建**：**金隅涂料**、**威逸远磨石**
3.  **预算有限**：**秀珀、嘉宝莉**
"""
    item = _sub(
        prompt="磨石地坪品牌",
        answer_content=answer,
        mention_position=1,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(item, "磨石地坪品牌", ["金隅涂料"], None)
    assert detail.mentioned is True
    assert detail.rank == 1
    assert detail.rank_basis != "secondary_section_local"


def test_aidiya_led_cn_chapter_resets_numbered_rank_four():
    """艾迪亚24885：一、1-3 + 二、1-4 艾迪亚 → 类内第4非跨段第7。"""
    answer = """
一、全国头部自营商圈 LED 大屏运营商
1. 兆讯传媒（301102，上市企业）
2. 凤凰都市传媒
3. 郁金香传媒
二、全国综合资源代理商
1. 华君传媒集团
2. 唐界传媒
3. 四季传媒（北京）
4. 艾迪亚控股集团
三、重点城市本地商圈大屏服务商
1. 天锦传媒
"""
    item = _sub(
        prompt="商圈LED大屏广告公司推荐",
        answer_content=answer,
        mention_position=7,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "商圈LED大屏广告公司推荐", ["艾迪亚", "艾迪亚控股"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 4


def test_aidiya_bus_glued_dash_bold_cards_rank_four():
    """艾迪亚22297：元宝粘连 - **华视**…- **艾迪亚**… → 类内第4非全文第9。"""
    answer = """
## 一、按“需求场景”对号入座
- **单城市深耕** → 当地公交集团
- **多城市全国统投（3城以上同步上刊）** → 选有跨城统筹能力的全国型运营商/代理：
  - **华视传媒**：覆盖30+城[citation:4]- **巴士在线（新动传媒）**：车身+车内屏[citation:4]- **分众传媒**：SmartBus试点[citation:4]- **艾迪亚控股、银马传媒、麦迪威**：42城统筹[citation:8]
"""
    item = _sub(
        prompt="公交广告公司哪家好",
        answer_content=answer,
        mention_position=9,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "公交广告公司哪家好", ["艾迪亚", "艾迪亚控股"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 4


def test_aidiya_airport_glued_cards_rank_three():
    """艾迪亚24900：垂直段粘连卡「益航、狼界、艾迪亚等」→ 第3卡非第8。"""
    answer = """
**🎯 垂直/区域型（特定场景或城市更深）**
- **华视传媒**：中西部枢纽[citation:4]- **分众传媒**：贵宾厅定向[citation:12]- **上海益航、狼界、艾迪亚等**：安检后交互屏[citation:6]
"""
    item = _sub(
        prompt="机场广告公司哪家好",
        answer_content=answer,
        mention_position=8,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "机场广告公司哪家好", ["艾迪亚", "艾迪亚控股"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 3


def test_child_room_board_dawangye_watchlist_is_section_second():
    """2026-09-03 - 儿童房截图：大王椰在「其他值得关注」小节第2，勿被同行顿号抬成第1。"""
    from app.services.ranking_parser import parse_answer_rankings

    answer = """
## 重点品牌推荐
1. **兔宝宝**
2. **雪宝**
3. **千年舟**
4. **索菲亚**
5. **鹏鸿**
6. **福人**

## 其他值得关注的品牌
- **小白兔**：专注儿童板材细分市场
- **大王椰、鲁丽、广林新材**：性价比高，渠道覆盖广

## 如何挑选？记住这几点
认准ENF级；看权威认证。
"""
    entries = parse_answer_rankings(answer)
    item = _sub(
        prompt="儿童房环保板材品牌哪个好",
        answer_content=answer,
        all_rankings_json=entries,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        item, "儿童房环保板材品牌哪个好", ["大王椰", "大王椰板材"], None
    )
    assert detail.mentioned is True
    assert detail.rank == 2
    assert detail.rank_basis in {"secondary_section_local", "section"}

    furen = _resolve_brand_rank_detail(
        item, "儿童房环保板材品牌哪个好", ["福人"], None
    )
    assert furen.rank == 6


def test_highspeed_rail_ad_main_catalog_beats_decision_table() -> None:
    """2026-09-03 - 主榜 5.艾迪亚控股｜全链路… 勿被决策表「华铁/艾迪亚」抬成第2。"""
    from types import SimpleNamespace

    from app.services.monitor_service import _resolve_brand_rank_detail

    answer = """
国内主流高铁广告头部公司对比（2026）
1. 华铁传媒｜列车媒体龙头（全国全域全场景）
适合：大品牌全国曝光
2. 兆讯传媒｜高铁数字屏上市公司（站内 LED / 刷屏机）
适合：动态广告
3. 路铁传媒｜高铁站静态灯箱头部
适合：品牌形象
4. 永达传媒｜高铁 + 高速双户外场景
适合：渠道下沉
5. 艾迪亚控股｜全链路整合服务商（车站 + 列车全触点）
适合：品牌事件营销
快速选型决策表
投放目标	优先选择
高铁列车冠名、品牌专列	华铁传媒 / 艾迪亚控股
高铁站 LED 视频、动态广告	兆讯传媒
"""
    ranks = [
        {"name": "华铁传媒｜列车媒体龙头", "rank": 1, "category": None},
        {"name": "兆讯传媒｜高铁数字屏上市公司", "rank": 2, "category": None},
        {"name": "路铁传媒｜高铁站静态灯箱头部", "rank": 3, "category": None},
        {"name": "永达传媒｜高铁 + 高速双户外场景", "rank": 4, "category": None},
        {"name": "艾迪亚控股｜全链路整合服务商", "rank": 5, "category": None},
    ]
    sub = SimpleNamespace(
        prompt="高铁广告公司哪家好",
        answer_content=answer,
        mention_position=None,
        mention_context=None,
        all_rankings_json=ranks,
        competitor_rankings_json=None,
        reference_list_json=None,
        citation_list_json=None,
        raw_result_json={"source": "manual_snapshot", "manual_rank_locked": False},
        page_screenshot=None,
    )
    detail = _resolve_brand_rank_detail(
        sub, "艾迪亚", ["艾迪亚", "艾迪亚控股", "AIDIYA"], None
    )
    assert detail.rank == 5
    assert detail.rank_basis in {"numbered_subheading", "numbered_list", "section", None}


