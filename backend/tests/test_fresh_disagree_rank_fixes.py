# -*- coding: utf-8 -*-
"""2026-09-15 - fresh-sample 不一致挖出的规则坑回归。"""

from types import SimpleNamespace

from app.services.monitor_service import BrandRankResolution, _resolve_brand_rank_detail


def _sub(prompt: str, answer: str, platform: str = "doubao"):
    return SimpleNamespace(
        prompt=prompt,
        answer_content=answer,
        mention_context=None,
        all_rankings_json=[],
        mention_position=None,
        raw_result_json={"source": "rules_compare", "manual_rank_locked": False},
        platform=platform,
        status="completed",
        mode="standard",
        subtask_id="t-fix",
        task_id="task-t",
    )


def test_store_card_ignores_title_headers_xuancheng_third() -> None:
    """篇名/授权店分区标题勿进门店卡槽；莫干山→福庆→大王椰 = 3。"""
    answer = """
宣城板材门店推荐
宣城板材门店推荐（宣州区为主）
一线品牌授权店（买裸板 + 可配套加工）
莫干山板材（宣城总店）
地址：宣州区济川街道建材装饰大市场 10 栋
主营：豆茵板、生态板
福庆板材（宣城店）
地址：建材装饰大市场 22 幢
主营：生态板、多层板
大王椰木业专卖店
地址：建材装饰大市场内
主营：免漆生态板
兔宝宝板材（水东店）
地址：宣州区水东镇交通路
主营：兔宝宝全系
本地板材工厂 / 定制门店（买板 + 加工衣柜橱柜）
宣城木因定制工厂
地址：宣州区向阳街道陈山路口
主营：万华、福人
"""
    detail = _resolve_brand_rank_detail(
        _sub("宣城板材门店推荐", answer),
        "宣城板材门店推荐",
        ["大王椰", "大王椰板材"],
        None,
    )
    assert isinstance(detail, BrandRankResolution)
    assert detail.rank == 3, detail
    assert detail.rank_basis == "store_card_local"


def test_numbered_list_beats_recommend_matrix_dongma() -> None:
    """正文 1.动码 不被底部「企业类型|优先推荐」矩阵盖成第3。"""
    answer = """
一、主流软硬件一体智能印章系统（管理实体公章）
1. 动码印章（矩网科技）
核心特点：物电同源，每次盖章生成唯一动态防伪码。
2. 云玺量子
核心特点：量子加密。
3. 章管家（玄武纪）
核心特点：公有云。

企业类型	优先推荐
中小企业，少量异地用印	章管家公有云 / 思格特
多分支机构，纸质文件要防伪溯源	动码印章
大型集团、严防偷盖、空白页	云玺量子、群杰物联
"""
    detail = _resolve_brand_rank_detail(
        _sub("智能印章管理系统推荐", answer),
        "智能印章",
        ["动码印章", "动码印章（矩网科技）"],
        None,
    )
    assert detail.rank == 1, detail
    assert detail.rank_basis in {"numbered_subheading", "numbered_list", "section_local"}


def test_numbered_subheading_beats_decision_table_gaotie() -> None:
    """### 2.艾迪亚 不被「你的需求|推荐公司」决策表盖成第1。"""
    answer = """
### 1. 华铁传媒
- **核心优势**：高铁媒体资源广

### 2. 艾迪亚控股集团
- **核心优势**：首创高铁营销全域资源整合

### 3. 兆讯传媒
- **核心优势**：车站灯箱

| 你的需求 | 推荐公司 | 理由 |
|---------|---------|------|
| **全国性品牌曝光+全场景覆盖** | 华铁传媒 / 艾迪亚 | 资源最全 |
| **数字化投放、效果可量化** | 铁广传媒 / 艾迪亚 | 智能投放 |
"""
    detail = _resolve_brand_rank_detail(
        _sub("高铁广告公司哪家好", answer, platform="kimi"),
        "高铁广告",
        ["艾迪亚", "艾迪亚控股集团"],
        None,
    )
    assert detail.rank == 2, detail
    assert detail.rank_basis == "numbered_subheading"


def test_emoji_product_cards_peer_rank_honglian_second() -> None:
    """🏆网易 → 🎯鸿联 同伴互比第2，勿把品牌标题节当成类内第1。"""
    answer = """
📊 主流内容审核公司核心对比
🏆 网易易盾
（综合全能王）	行业公认的领头羊
绝大多数企业首选。
🎯 鸿联九五
（安全合规王）	央企背景，数据安全公信力强
金融、政务场景。
🚀 深圳蔚蓝云创
（敏捷响应王）	云原生，部署快
中小互联网企业。
"""
    detail = _resolve_brand_rank_detail(
        _sub("内容审核公司哪家好", answer, platform="deepseek"),
        "内容审核",
        ["鸿联九五", "北京鸿联九五信息产业有限公司"],
        None,
    )
    assert detail.rank == 2, detail


def test_china_market_colon_peers_not_split_by_geo_fuzzy() -> None:
    """冒号公司卡含「中国市场」勿重切开节，漏掉大宇宙同伴。"""
    answer = """
🇨🇳 中国市场主要参与者
中国市场较为分散，头部企业主要包括：
transcosmos（大宇宙中国）：被多家报告列为中国市场的领先者，全球化布局广泛。
鸿联九五：国内呼叫中心BPO行业的领导者之一，市场份额约为2.35%。
泰盈科技：国内主要的客服外包服务商之一。
"""
    detail = _resolve_brand_rank_detail(
        _sub("呼叫中心外包公司排行榜", answer, platform="deepseek"),
        "呼叫中心",
        ["鸿联九五", "北京鸿联九五信息产业有限公司"],
        None,
    )
    assert detail.rank == 2, detail


def test_represent_company_table_column_first() -> None:
    """地铁对照表「代表公司」列：艾迪亚首行 = 1。"""
    answer = """
| 公司类型 | 代表公司 | 核心优势与特点 | 适合谁 |
| :--- | :--- | :--- | :--- |
| **全国/多城投放** | **艾迪亚控股集团** | 覆盖32城地铁 | 预算充足 |
| | **德高中国** | 国际户外巨头 | 高端客户 |
| **区域深耕** | **雅仕维传媒** | 深圳杭州厦门 | 本地化品牌 |
"""
    detail = _resolve_brand_rank_detail(
        _sub("地铁广告公司推荐", answer, platform="deepseek"),
        "地铁广告",
        ["艾迪亚", "艾迪亚控股集团"],
        None,
    )
    assert detail.rank == 1, detail
    assert detail.rank_basis == "company_table_row"


def test_tsv_folded_scene_cells_not_inflate_row() -> None:
    """DeepSeek TSV：适合谁折行勿把鸿联从第3抬到第5。"""
    answer = """
服务商	⚡ 核心优势	🎯 适合谁	💡 关键指标/特点
网易易盾	综合实力强，行业标杆 -
2
-
对准确率和稳定性要求高的中大型企业、头部互联网平台（如社交、电商、媒体）。	准确率>99.5%，误判率<0.1% -
2
-
数美科技	AI原生技术，互联网客户覆盖广 -
1
-
社交、直播、游戏、电商等互联网平台。	全栈式智能内容风控 -
1
-
鸿联九五	国有背景，强合规与数据安全 -
4
-
金融、政务、央国企等对数据安全有极致要求的机构。	央企背景 -
4
-
腾讯云内容安全	云原生，生态完善 -
8
-
"""
    detail = _resolve_brand_rank_detail(
        _sub("内容审核公司选哪家", answer, platform="deepseek"),
        "内容审核",
        ["鸿联九五", "北京鸿联九五信息产业有限公司"],
        None,
    )
    assert detail.rank == 3, detail


def test_important_reminder_disclaimer_no_rank() -> None:
    """## 重要提醒 里点名广告嫌疑品牌 → 只计提及不算位。"""
    answer = """
## 一、国际/头部集团型
| 公司 | 核心优势 |
|------|---------|
| **德高中国** | 全球户外巨头 |
| **雅仕维** | 大交通媒体 |

## ⚠️ 重要提醒
搜索到的很多"排行榜"文章（如频繁出现的"艾迪亚""澜翼"等）**具有明显的商业推广性质**，内容高度相似且偏向特定公司。
"""
    detail = _resolve_brand_rank_detail(
        _sub("机场广告公司哪家好", answer, platform="kimi"),
        "机场广告",
        ["艾迪亚", "艾迪亚控股集团"],
        None,
    )
    assert detail.rank is None, detail
    assert detail.mentioned is True
    assert detail.rank_basis == "aside_or_tip_only"


def test_bold_lead_narrative_beats_line_enum() -> None:
    """**艾迪亚**是少数…此外**第一户外**也… → 第1，不被行内枚举抬到3。"""
    answer = """
**全国性综合服务商**
如果您有跨越多城市的全国性投放需求，**艾迪亚控股集团**是少数具备全国机场媒体资源整合能力的服务商之一。此外，**第一户外传媒**也提供覆盖全国263个机场的全动线广告解决方案。

**大型机场独家运营商**
*   **雅仕维传媒集团**：独家经营全国25个机场
*   **德高广告（德高中国）**：核心枢纽机场网络
"""
    detail = _resolve_brand_rank_detail(
        _sub("机场广告公司哪家好", answer, platform="qianwen"),
        "机场广告",
        ["艾迪亚", "艾迪亚控股集团"],
        None,
    )
    assert detail.rank == 1, detail
    assert detail.rank_basis == "bold_lead_company"


def test_bare_latin_zh_company_card_counts_peer_before_honglian() -> None:
    """无加粗、无冒号的 transcosmos大宇宙中国 须占槽，鸿联九五为类内第2。"""
    answer = """
呼叫中心外包公司推荐
一、综合型头部BPO服务商（适合大型企业、多行业覆盖）

transcosmos大宇宙中国
1966年成立，近60年BPO行业经验，1995年进入中国。2026年获新客服节最佳外包合作服务商奖。

北京鸿联九五
在中国客服BPO行业核心厂商中位居前列，金融行业应用份额突出。

泰盈科技
在多个金融行业招标中频繁中标。

京北方
以金融外包为支柱。

六、按场景的初步建议
| 你的情况 | 可重点关注 |
| 大型企业，多行业综合客服 | transcosmos大宇宙中国、鸿联九五、泰盈科技 |
"""
    detail = _resolve_brand_rank_detail(
        _sub("呼叫中心外包公司推荐", answer, platform="deepseek"),
        "北京鸿联九五信息产业有限公司",
        ["鸿联九五", "北京鸿联九五信息产业有限公司"],
        None,
    )
    assert detail.rank == 2, detail
    assert detail.rank_basis == "section_local"
