"""补录页对不上：礼叮当裸行 / Bio Island 空格名 / DHA 分型切段。"""

from types import SimpleNamespace

from app.services.monitor_service import _resolve_brand_rank_detail


def test_wenchuang_bare_company_line_is_section_local_first() -> None:
    """22186041：文创节裸行「礼叮当」须类内第1，勿并进员工福利 tip 成第7。"""
    text = """
以下按不同业务场景分类推荐国内主流礼品公司：

一、综合型头部礼品公司

元隆雅图
行业地位：国内礼品行业首家 A 股上市公司。

二、文创定制类礼品公司（主打文化创意与柔性定制）

礼叮当
行业地位：国家级高新技术企业、北京市专精特新企业。
核心优势：主打故事化礼品设计。

墨斗鱼礼品
行业地位：成立于 2003 年，深耕 B 端礼品定制。

三、员工福利与数字化采购类礼品公司

云中鹤
行业地位：国内领先的 S2B2C 数智化营销与采购平台。

瑞祥科技（桃红家）
行业地位：数字化福利平台。

大型品牌营销：优先选择元隆雅图。
企业文创定制：优先选择礼叮当，定制化创意能力强。
央国企员工福利：优先选择云中鹤或瑞祥科技。
"""
    subtask = SimpleNamespace(
        prompt="礼品公司推荐",
        answer_content=text,
        mention_context=None,
        all_rankings_json=[],
        mention_position=None,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(subtask, "礼叮当", ["礼叮当"], None)
    assert detail.mentioned is True
    assert detail.rank == 1
    assert detail.rank_basis == "section_local"
    assert detail.category and "文创" in str(detail.category)


def test_bio_island_spaced_latin_name_counts_before_baodecong() -> None:
    """23241356：Bio Island 带空格冒号卡须进槽，宝得聪为藻油名单第4。"""
    text = """
🏆主流儿童DHA品牌一览

纽曼思：经典单一藻油，配料表干净。
童年时光 (ChildLife)：有藻油滴剂和软胶囊。
Bio Island：小鱼造型可爱，官方标示折合DHA 100mg/粒。
宝得聪：润科藻油原料。基础款120mg/粒。
天然博士：汤臣倍健旗下。
"""
    subtask = SimpleNamespace(
        prompt="儿童DHA品牌推荐",
        answer_content=text,
        mention_context=None,
        all_rankings_json=[],
        mention_position=None,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(subtask, "宝得聪", ["宝得聪"], None)
    assert detail.mentioned is True
    assert detail.rank == 4
    assert detail.rank_basis == "section_local"


def test_dha_product_type_sections_keep_baodecong_in_fupei() -> None:
    """23196808：高纯度/复配型须切开，宝得聪在复配型类内第1，勿吞进综合实力型第5。"""
    text = """
给孩子选DHA，关键不是找最好的牌子。

👶 儿童DHA品牌速览

综合实力型（配方与科研并重）

植物诀：复合配方，每份DHA 365mg。
元素力：孕童专用，主打TG型蓝帽注册。

高纯度/高认证型（追求极致纯净）

童年故事倍启智：80%高纯度TG型配方。
奇鹤：国货中首个公开藻株号的品牌。

DHA+ARA复配型（模拟母乳比例）

宝得聪：DHA与ARA各120mg（1:1比例）。
卓岳：每粒约150mg DHA + 150mg ARA。

热门进口/口碑款

纽曼思：母婴渠道认知度高。
"""
    subtask = SimpleNamespace(
        prompt="儿童DHA品牌推荐",
        answer_content=text,
        mention_context=None,
        all_rankings_json=[],
        mention_position=None,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(subtask, "宝得聪", ["宝得聪"], None)
    assert detail.mentioned is True
    assert detail.rank == 1
    assert detail.rank_basis == "section_local"
    assert detail.category and "复配" in str(detail.category)
