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
