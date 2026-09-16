# -*- coding: utf-8 -*-
"""无编号门店卡片序：对齐人工锁金标准。"""

from types import SimpleNamespace

from app.services.monitor_service import BrandRankResolution, _resolve_brand_rank_detail


def _sub(prompt: str, answer: str):
    return SimpleNamespace(
        prompt=prompt,
        answer_content=answer,
        mention_context=None,
        all_rankings_json=[],
        mention_position=None,
        raw_result_json={},
        platform="doubao",
        status="completed",
        mode="standard",
        subtask_id="t-store",
        task_id="task-t",
    )


def test_jinhua_store_cards_rank_dawangye_third() -> None:
    """金华浙中：千年舟→韩宇来→大王椰；贴士并列不得虚成第2。"""
    answer = """
金华板材门店推荐
金华板材店主要集中在浙中建材市场、江南建材市场，下面是口碑稳定的品牌门店：
✅ 浙中建材市场（金东区南环城南路，板材店最集中）
千年舟（金华店）
地址：浙中建材市场板材区北 - 08
主营：ENF 锌效抗菌生态板、多层板
韩宇来板材（金华旗舰店）
地址：浙中建材市场板材区 B 座
主营：生态板、细木工板
大王椰板材（金华总代・聚锋建材）
主营：大王椰森芯板、ENF 生态板
✅ 江南建材市场（婺城区）
莫干山板材专卖店
地址：江南建材市场板材区 7 幢
主营：ENF 级生态板
优先去浙中建材市场，可以一次性对比千年舟 / 大王椰 / 韩宇来，节省时间
"""
    detail = _resolve_brand_rank_detail(
        _sub("金华板材门店推荐", answer),
        "金华板材门店推荐",
        ["大王椰", "大王椰板材"],
        None,
    )
    assert isinstance(detail, BrandRankResolution)
    assert detail.rank == 3, detail
    assert detail.rank_basis == "store_card_local"


def test_jinhua_store_cards_rank_dawangye_second() -> None:
    """金华另一篇：千年舟→大王椰→韩宇来 → 第2。"""
    answer = """
📍浙中建材市场｜金东区南环城南路（优先逛）
千年舟（金华店）
位置：浙中建材市场板材区北 - 08
主营：ENF 锌效抗菌生态板
大王椰板材（金华总代・聚锋建材）
位置：浙中建材市场 B 座地下商业街
主营：森芯板、ENF 生态板
韩宇来板材（金华旗舰店）
位置：浙中建材市场板材区 B 座
主营：生态板、细木工板
📍江南建材市场｜婺城区
莫干山板材专卖店
主营：ENF 生态板
✅ 金华探店避坑要点
浙中建材市场品牌扎堆，可以一次性对比千年舟、大王椰、韩宇来
"""
    detail = _resolve_brand_rank_detail(
        _sub("金华板材门店推荐", answer),
        "金华板材门店推荐",
        ["大王椰", "大王椰板材"],
        None,
    )
    assert detail.rank == 2, detail
    assert detail.rank_basis == "store_card_local"


def test_xian_store_cards_rank_dawangye_second() -> None:
    """西安无编号专卖店卡：兔宝宝→大王椰 → 第2（原先规则算空）。"""
    answer = """
西安板材门店 & 市场推荐
✅ 品牌授权专卖店（适合家装自住，看重环保、保真）
都在北三环大明宫板材区
兔宝宝健康饰材专卖店（阳光店）
位置：板材 C 区 12 排 20 号
主营：兔宝宝生态板、多层板、欧松板
适合：自住家装
大王椰板材（西安店）
主营：生态板、多层实木板、阻燃板
三千方家西北运营中心
主打 ENF 级，支持门墙柜同色
✅ 本地仓储批发门店（性价比高）
西安金秋板材
位置：北三环大明宫板材 A 区
泰山板材西安经销商，主营海洋板
"""
    detail = _resolve_brand_rank_detail(
        _sub("西安板材门店推荐", answer),
        "西安板材门店推荐",
        ["大王椰", "大王椰板材"],
        None,
    )
    assert detail.rank == 2, detail
    assert detail.rank_basis == "store_card_local"


def test_nanchang_pin_and_check_main_attrs_rank_third() -> None:
    """南昌：店名 + 📍地址 + ✅主营，大王椰第3。"""
    answer = """
🪵 品牌裸板专卖店（买板材，木工现场打柜子）
千年舟板材
📍青山湖香江建材市场罗马广场 12-14 号
✅主营：ENF 生态板、欧松板
兔宝宝板材
📍香江建材市场、喜盈门建材广场
✅主营：实木芯生态板
大王椰板材
📍香江建材市场香江六街 23-24 号
✅主营：ENF 生态板、欧松板
莫干山板材
📍香江建材六街
✅实木生态板
🛋️ 板材 + 加工一站式
"""
    detail = _resolve_brand_rank_detail(
        _sub("南昌板材门店推荐", answer),
        "南昌板材门店推荐",
        ["大王椰", "大王椰板材"],
        None,
    )
    assert detail.rank == 3, detail
    assert detail.rank_basis == "store_card_local"


def test_xingtai_emoji_highlight_cards_rank_third() -> None:
    """邢台豆包：店名+📍+✅亮点+👉适合，莫干山→兔宝宝→大王椰=3；亮点行不得切段虚抬成1。"""
    answer = """
🏪主流品牌门店
莫干山板材
📍冀南装饰城北门旁；皓顺壹号院底商工厂店
✅亮点：邢台正规总代理，ENF 豆茵板齐全
👉适合：儿童房、母婴房，中高端自住
兔宝宝板材
📍冀南装饰城经销商门店；沙河机械零部件市场
✅亮点：官方授权门店，花色丰富
👉适合：认准大品牌做全屋衣柜
大王椰板材
📍信都区居然之家建材街旗舰店；润鹏家居建材市场
✅亮点：零售 + 批发，现货充足
👉适合：自装、批量采购，中等预算
千年舟板材
📍冀南装饰城、兴安装饰材料市场经销商门店
✅亮点：锌效抗菌 ENF 生态板
👉适合：一楼、阳台、厨房
高端板材经销商
📍冀南装饰城；冲锋木业（鲁丽、大王椰授权）
✅亮点：鲁丽欧松板、万华禾香板
👉适合：大平层、别墅
📍逛店路线
冀南装饰城｜襄都区新兴东大街 160 号
⚠️邢台本地选购避坑要点
一楼优先桉木芯多层板
✅快速选型参考
自装批量采购、性价比：大王椰、千山
"""
    detail = _resolve_brand_rank_detail(
        _sub("邢台板材门店推荐", answer),
        "邢台板材门店推荐",
        ["大王椰", "大王椰板材"],
        None,
    )
    assert detail.rank == 3, detail
    assert detail.rank_basis == "store_card_local"


def test_xingtai_advantage_emoji_variant_still_third() -> None:
    """同结构把亮点改成优势，仍须第3（防白名单只认亮点）。"""
    answer = """
🏪主流品牌门店
莫干山板材
📍冀南装饰城北门旁
✅优势：正规总代理
👉适合：儿童房
兔宝宝板材
📍冀南装饰城经销商门店
✅优势：官方授权
👉适合：全屋定制
大王椰板材
📍信都区居然之家
✅优势：零售批发
👉适合：自装
⚠️选购避坑要点
认准授权
"""
    detail = _resolve_brand_rank_detail(
        _sub("邢台板材门店推荐", answer),
        "邢台板材门店推荐",
        ["大王椰", "大王椰板材"],
        None,
    )
    assert detail.rank == 3, detail
    assert detail.rank_basis == "store_card_local"


def test_numbered_store_list_beats_store_card_jiujiang_fourth() -> None:
    """1.2.3.4. 编号门店榜优先于无编号卡碎片；大王椰第4，勿被尾部碎卡虚成第2。"""
    answer = """
# 九江板材门店推荐（市区主流品牌店）
## 濂溪区（主流建材市场，优先逛）
1. 兔宝宝板材（宏大五金城店）
地址：宏大五金城A区1113‑1117
主营：ENF生态板、多层板
2. 莫干山板材（华东市场专卖店）
地址：华东市场二期C2栋
主营：莫干山全系列板材
3. 千年舟板材（华东市场店）
地址：华东市场三期B7栋
主营：ENF级板材、LSB板
4. 大王椰板材（新三鼎市场店）
地址：新三鼎市场B11栋1‑8号
主营：免漆生态板、五金配套
香港九岗山板材批发（天马建材城）
地址：长虹北路天马建材家具城北区G栋109
大王椰板材（现代综合大市场店）
地址：经开区现代综合大市场57栋114
"""
    detail = _resolve_brand_rank_detail(
        _sub("九江板材门店推荐", answer),
        "九江板材门店推荐",
        ["大王椰", "大王椰板材"],
        None,
    )
    assert detail.rank == 4, detail
    assert detail.rank_basis in {"numbered_list", "numbered_subheading"}


def test_markdown_numbered_heading_beats_store_card_yulin_second() -> None:
    """## 1.莫干山 ## 2.大王椰 优先于门店卡；勿因 ✅主打 碎卡虚抬。"""
    answer = """
## 1. 莫干山板材（门店多，适合普通家装）
📍门店：发祥地建材市场、麻地湾
✅主打：ENF豆茵板、生态板
👉适合：自住衣柜、橱柜
## 2. 大王椰板材（麻地湾总仓，批发零售均可）
📍地址：麻地湾建材市场（仓储运营中心）
✅主打：ENF生态板、欧松板
👉适合：木工自购板材
## 3. 兔宝宝板材
📍地址：麻地湾建材市场
✅主打：兔宝宝生态板、多层板
👉适合：注重品牌
"""
    detail = _resolve_brand_rank_detail(
        _sub("榆林板材门店推荐", answer),
        "榆林板材门店推荐",
        ["大王椰", "大王椰板材"],
        None,
    )
    assert detail.rank == 2, detail
    assert detail.rank_basis in {"numbered_list", "numbered_subheading"}


def test_market_title_with_brand_mention_not_numbered_hit() -> None:
    """市场标题顺带「大王椰运营中心」不得当本品编号位；专卖店段第2才算。"""
    answer = """
## 一、大型板材建材市场
### 1. 喜盈门建材家具广场（八里湖）
- 兔宝宝、千年舟专柜
### 2. 华东市场（濂溪十里）
门店：兔宝宝易装华东店
### 3. 天马21世纪建材家居城
### 4. 新三鼎建材市场
### 5. 宏大五金城（濂溪，大王椰运营中心）
**大王椰板材（宏大店）**
## 二、一线环保品牌专卖店
1. **兔宝宝板材**
- 华东店：濂溪长虹西大道
2. **大王椰板材（九江运营中心）**
3. **福湘板材（九江总经销）**
4. **莫干山板材**
"""
    detail = _resolve_brand_rank_detail(
        _sub("九江板材门店推荐", answer),
        "九江板材门店推荐",
        ["大王椰", "大王椰板材"],
        None,
    )
    assert detail.rank == 2, detail
    assert detail.rank_basis in {"numbered_list", "numbered_subheading"}
    assert detail.rank != 5


def test_positive_recommend_line_with_avoid_counterfeit_keeps_rank() -> None:
    """「千山、大王椰：…避开贴牌货」不得因贴牌整行作废。"""
    answer = """
## 国产主流ENF级板材
### 高性价比
1. **兔宝宝**
产品线最全。
2. **千山、水性科天、大王椰**：全系有ENF，价格友好，适合预算有限，认准原厂精板，避开贴牌货。
"""
    detail = _resolve_brand_rank_detail(
        _sub("环保板材品牌哪个好", answer),
        "环保板材品牌哪个好",
        ["大王椰", "大王椰板材"],
        None,
    )
    assert detail.rank is not None, detail
    assert detail.rank_basis != "negative_context_skip"


def test_pipe_enum_line_ranks_third() -> None:
    answer = """
✅ 国民一线高端
兔宝宝、千年舟、大王椰｜国民一线高端，产品线全，门店多，售后方便
爱格、可丽芙｜进口饰面板
"""
    detail = _resolve_brand_rank_detail(
        _sub("高端板材品牌有哪些", answer),
        "高端板材品牌有哪些",
        ["大王椰"],
        None,
    )
    assert detail.rank == 3, detail
