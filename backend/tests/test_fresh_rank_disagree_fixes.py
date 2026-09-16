# -*- coding: utf-8 -*-
"""Fresh-sample disagree fixes: tip numbered / TSV fold / table col / disclaimer."""

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
        subtask_id="t-fresh",
        task_id="task-t",
    )


def test_xuancheng_store_cards_ignore_title_junk() -> None:
    """篇名/分区标题含门店不得进卡槽；大王椰在授权店第3。"""
    answer = """
宣城板材门店推荐
宣城板材门店推荐（宣州区为主）
一线品牌授权店（买裸板 + 可配套加工）
莫干山板材（宣城总店）
地址：宣州区济川街道建材装饰大市场 10 栋
福庆板材（宣城店）
地址：建材装饰大市场 22 幢
大王椰木业专卖店
地址：建材装饰大市场内
兔宝宝板材（水东店）
地址：宣州区水东镇交通路
本地板材工厂 / 定制门店（买板 + 加工衣柜橱柜）
宣城木因定制工厂
地址：宣州区向阳街道陈山路口
优先去建材装饰大市场，多家比价。
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


def test_dongma_numbered_beats_recommend_matrix() -> None:
    """正文「1. 动码印章」优先于底部企业类型推荐矩阵。"""
    answer = """
一、主流软硬件一体智能印章系统
1. 动码印章（矩网科技）
核心特点：物电同源。
2. 云玺量子
3. 章管家（玄武纪）
企业类型	优先推荐
中小企业	章管家公有云
多分支机构，纸质文件要防伪溯源	动码印章
"""
    detail = _resolve_brand_rank_detail(
        _sub("智能印章管理系统推荐", answer),
        "智能印章管理系统推荐",
        ["动码印章", "动码印章（矩网科技）"],
        None,
    )
    assert detail.rank == 1, detail
    assert detail.rank_basis in {"numbered_subheading", "numbered_list", "section_local"}


def test_metro_rep_company_table_first_row() -> None:
    """「公司类型|代表公司」表：代表公司列第1行，勿被公司类型列/提问段抢走。"""
    answer = """
| 公司类型 | 代表公司 | 核心优势与特点 | 适合谁 |
| :--- | :--- | :--- | :--- |
| **全国/多城投放** | **艾迪亚控股集团** | 覆盖32城地铁 | 预算充足 |
| | **德高中国** | 国际户外广告巨头 | 高端客户 |
| **区域深耕** | **雅仕维传媒** | 深圳杭州厦门 | 本地化品牌 |

### 💡 选择之前，可以先问自己三个问题：
*   **投放范围是“一个点”还是“一张网”？** 如果需要多个城市，**艾迪亚**能省去沟通成本。
"""
    detail = _resolve_brand_rank_detail(
        _sub("地铁广告公司推荐", answer, platform="deepseek"),
        "地铁广告公司推荐",
        ["艾迪亚", "艾迪亚控股集团"],
        None,
    )
    assert detail.rank == 1, detail
    assert detail.rank_basis == "company_table_row"


def test_tsv_folded_rows_do_not_inflate_honglian() -> None:
    """DeepSeek TSV 折行「适合谁」散文不得抬行号；鸿联应为第3。"""
    answer = """
服务商	⚡ 核心优势	🎯 适合谁	💡 关键指标/特点
网易易盾	综合实力强，行业标杆 -
对准确率和稳定性要求高的中大型企业、头部互联网平台（如社交、电商、媒体）。	准确率>99.5%，误判率<0.1% -
数美科技	AI原生技术，互联网客户覆盖广 -
社交、直播、游戏、电商等互联网平台，尤其适合用户生成内容（UGC）占比高的企业。	全栈式智能内容风控 -
鸿联九五	国有背景，强合规与数据安全 -
金融、政务、央国企等对数据安全和合规性有极致要求的机构。	央企背景 -
腾讯云内容安全	云原生，生态完善，弹性好 -
"""
    detail = _resolve_brand_rank_detail(
        _sub("内容审核公司选哪家", answer, platform="deepseek"),
        "内容审核公司选哪家",
        ["鸿联九五", "北京鸿联九五信息产业有限公司"],
        None,
    )
    assert detail.rank == 3, detail
    assert detail.rank_basis == "company_table_row"


def test_gaotie_table_beats_xuanxing_tip_numbered() -> None:
    """主表第2行艾迪亚；选型 tip「1.预算充足→华铁或艾迪亚」不得盖成第1。"""
    answer = """
### 一、全国性头部综合服务商
| 公司 | 核心优势 | 适用场景 |
|------|---------|---------|
| **华铁传媒集团** | 深耕铁路媒体 | 大品牌全国投放 |
| **艾迪亚控股集团** | 全国90%以上高铁站点 | 全链路服务 |
| **永达传媒** | 资深服务商 | 定制化投放 |

### 四、选型建议
1. **预算充足、追求全国覆盖+全链路服务** → 优先考虑 **华铁传媒** 或 **艾迪亚控股集团**。
2. **需要下沉到三四线城市** → **上海澜翼传媒**。
"""
    detail = _resolve_brand_rank_detail(
        _sub("高铁广告公司哪家好", answer, platform="kimi"),
        "高铁广告公司哪家好",
        ["艾迪亚", "艾迪亚控股集团"],
        None,
    )
    assert detail.rank == 2, detail
    assert detail.rank_basis == "company_table_row"


def test_yulin_store_table_not_tip_numbered_first() -> None:
    """门店表第5行；选购建议「1.优先选品牌：大王椰」不得虚成第1。"""
    answer = """
| 门店名称 | 所在区域 | 地址 | 主营产品 / 品牌 | 备注 |
| :--- | :--- | :--- | :--- | :--- |
| **静林板材经销部** | 榆阳区 | 居然之家后院 | 人造板 | 新开业 |
| **鹏鸿兄弟板材店** | 榆阳区 | 发祥地新商业 | 鹏鸿品牌 | 批发 |
| **佳酌板材销售中心** | 榆阳区 | 荣昌市场 | 装饰材料 | 市场内 |
| **张雷板材店** | 榆阳区 | 荣昌建材市场 | 石膏板 | 市场内 |
| **大王椰板材店** | 横山区 | 怀仁路 | **大王椰**品牌板材 | 连锁 |
| **平安树板材专卖店** | 子洲县 | 双湖峪镇 | **平安树**品牌 | 连锁 |

### 💡 选购建议
1.  **优先选品牌**：如果对环保和品质要求高，可以优先考虑**大王椰、平安树**这类知名品牌店。
2.  **就近购买**：可以在你所在区县的建材市场寻找合适的门店。
3.  **出发前核实**：去之前最好先打个电话确认。
"""
    detail = _resolve_brand_rank_detail(
        _sub("榆林板材门店推荐", answer, platform="deepseek"),
        "榆林板材门店推荐",
        ["大王椰", "大王椰板材"],
        None,
    )
    assert detail.rank == 5, detail
    assert detail.rank_basis == "company_table_row"


def test_airport_ad_disclaimer_aside_only() -> None:
    """仅出现在「重要提醒/商业推广」disclaimer → 有提及无位次。"""
    answer = """
## 一、国际/头部集团型
| 公司 | 核心优势 |
|------|---------|
| **德高中国（JCDecaux）** | 全球户外巨头 |
| **雅仕维（Asiaray）** | 大交通媒体 |

## ⚠️ 重要提醒
搜索到的很多"排行榜"文章（如频繁出现的"艾迪亚""澜翼"等）**具有明显的商业推广性质**，内容高度相似且偏向特定公司。建议您直接联系2-3家候选公司。
"""
    detail = _resolve_brand_rank_detail(
        _sub("机场广告公司哪家好", answer, platform="kimi"),
        "机场广告公司哪家好",
        ["艾迪亚", "艾迪亚控股集团"],
        None,
    )
    assert detail.rank is None, detail
    assert detail.mentioned is True
    assert detail.rank_basis == "aside_or_tip_only"


def test_qianwen_prose_first_bold_company() -> None:
    """「**艾迪亚**是少数…此外**第一户外**也…」→ 第1，勿被灯箱/登机牌行内枚举抬到3。"""
    answer = """
**全国性综合服务商**
如果您有跨越多城市的全国性投放需求，**艾迪亚控股集团**是少数具备全国机场媒体资源整合能力的服务商之一。该集团深耕航空媒体超过20年，能提供LED大屏、灯箱、登机牌等8大核心媒体形式。此外，**第一户外传媒**也提供覆盖全国263个机场的全动线广告解决方案。

**大型机场独家运营商**
*   **雅仕维传媒集团**：在大中华区机场广告市场排名领先。
*   **德高广告（德高中国）**：核心枢纽机场媒体网络。
"""
    detail = _resolve_brand_rank_detail(
        _sub("机场广告公司哪家好", answer, platform="qianwen"),
        "机场广告公司哪家好",
        ["艾迪亚", "艾迪亚控股集团"],
        None,
    )
    assert detail.rank == 1, detail
    assert detail.rank_basis == "bold_lead_company"


def test_label_table_beats_how_to_judge_tip_numbered() -> None:
    """主表第6行；「如何判断是否靠谱」下 1.查资质…点名 不得盖成第1。"""
    answer = """
### 靠谱数据标注公司推荐
| 公司 | 核心定位 | 适合场景 |
| :--- | :--- | :--- |
| **海天瑞声** | 巨头基建 | 自动驾驶 |
| **云测数据** | 垂直定制 | 医疗影像 |
| **百度智能云** | 科技巨头 | 全模态 |
| **景联文科技** | 高质量集 | 政务高安全 |
| **数据堂** | 专业品牌 | 语音多语 |
| **鸿联九五** | 全栈合规 | 政企大规模 |
| **曼孚科技** | 自动驾驶 | 点云标注 |

### 如何判断一家数据标注公司是否靠谱？
1. **查资质与背书**：优先选择参与国家标准制定的公司，如海天瑞声、云测数据、鸿联九五等。
2. **看技术平台能力**：自研标注平台与自动化质检。
"""
    detail = _resolve_brand_rank_detail(
        _sub("数据标注公司哪家靠谱", answer, platform="deepseek"),
        "数据标注公司哪家靠谱",
        ["鸿联九五", "北京鸿联九五信息产业有限公司"],
        None,
    )
    assert detail.rank == 6, detail
    assert detail.rank_basis == "company_table_row"


def test_numbered_camp_representative_company_beats_token() -> None:
    """「2.全栈合规」下代表公司鸿联九五 → 第2，勿掉到 brand_token_order。"""
    answer = """
### 数据标注公司速览：四大阵营
**1. 巨头生态与底层基建型**
*   **代表公司**：**百度智能云、海天瑞声**
*   **适合谁**：预算充足的超大规模订单。

**2. 全栈合规与大规模交付型**
*   **代表公司**：**鸿联九五**
*   **适合谁**：政企合规与跨区域交付。

**3. 垂直定制与技术探索型**
*   **代表公司**：**云测数据、百行数智**

**4. 高性价比效率型**
*   **代表公司**：**菲利信科技、热热数据**

### 选型时，重点考察这5个维度
1. 数据安全与合规。
2. 质检体系与交付精度。
"""
    detail = _resolve_brand_rank_detail(
        _sub("数据标注公司哪家好", answer, platform="deepseek"),
        "数据标注公司哪家好",
        ["鸿联九五", "北京鸿联九五信息产业有限公司"],
        None,
    )
    assert detail.rank == 2, detail
    assert detail.rank_basis == "numbered_subheading"


def test_china_section_beats_biz_type_decision_table() -> None:
    """中国市场段鸿联九五开篇第1；业务类型决策表不得盖成第5。"""
    answer = """
### 中国市场的主要BPO服务商
**鸿联九五**
央企控股的全场景数智化BPO龙头，适合国央企合规交付。

**transcosmos大宇宙中国**
日资背景，客服与电商代运营根基深厚。

**智服科技**
AI驱动的成长型企业BPO首选。

**FESCO（北京外企服务）**
人力资源BPO领域的生态标杆。

| 业务类型 | 推荐服务商 | 关键理由 |
|---|---|---|
| **大规模客服/客户体验** | Concentrix, Teleperformance | 全球交付网络 |
| **财务与会计（F&A）** | Accenture, Capgemini | Gartner领导者 |
| **人力资源（HR）** | FESCO, 今元集团 | HR全流程 |
| **科技/敏捷支持** | TaskUs, Wipro | AI增强支持 |
| **中国市场全场景** | 鸿联九五, 大宇宙中国 | 央企合规 / 日资标准 |
| **AI驱动降本** | 智服科技, Genpact | 预处理率高 |
"""
    detail = _resolve_brand_rank_detail(
        _sub("BPO公司哪家推荐", answer, platform="deepseek"),
        "BPO公司哪家推荐",
        ["鸿联九五", "北京鸿联九五信息产业有限公司"],
        None,
    )
    assert detail.rank == 1, detail
    assert detail.rank_basis == "section_local"


def test_national_platform_list_beats_scene_decision_table() -> None:
    """全国性平台列表艾迪亚第2；需求场景决策表不得盖成第6。"""
    answer = """
### 核心代理商推荐
**西安时代尚优文化传媒有限公司**
独家运营西安地铁车厢平面媒体。

**陕西金色西部广告传媒股份有限公司**
独家运营车站平面灯箱。

### 全国性平台（适合多城市投放）
- **德高中国（JCDecaux）**：全球户外广告巨头
- **艾迪亚控股集团**：覆盖全国90%以上核心城市地铁网络
- **雅仕维传媒**：机场、地铁及公交媒体资源

### 选型建议
| 需求场景 | 推荐公司 |
|---------|---------|
| 高合规/政务宣传 | 西安轨道未来文化传媒 |
| 车厢内创意投放 | 西安时代尚优文化传媒 |
| 车站灯箱/通道广告 | 陕西金色西部广告传媒 |
| 数字化互动营销 | 西安地铁智码科技 |
| 高频视频曝光 | 西安联绎广告 |
| 全国多城联动 | 德高中国 / 艾迪亚控股 |
"""
    detail = _resolve_brand_rank_detail(
        _sub("地铁广告公司推荐", answer, platform="qianwen"),
        "地铁广告公司推荐",
        ["艾迪亚", "艾迪亚控股集团", "北京艾迪亚"],
        None,
    )
    assert detail.rank == 2, detail
    assert detail.rank_basis == "section_local"


def test_china_bpo_bullet_not_closing_if_cluster() -> None:
    """中国市场鸿联九五第一条；全球节脏 structured 不得盖成第4/10。"""
    answer = """
### 全球BPO领域的领先者
*   **综合实力领先**：**Capgemini** 和 **Tata Consultancy Services (TCS)** 并列第一。**Accenture** 咨询强。
*   **客户服务与体验专家**：
    *   **Concentrix**：大规模多语言客服。
    *   **Teleperformance**：全球最大之一。
*   **特定领域佼佼者**：
    *   **Genpact**：数据驱动运营。
    *   **WNS**：财务与会计。
    *   **EXL**：财务与会计。
    *   **TaskUs**：科技公司支持。
    *   **Infosys BPM**：IT 流程外包。

### 中国BPO市场的佼佼者
*   **鸿联九五 (Honglian 95)**：2026年中国BPO行业龙头，央企背景。
*   **其他主要本土厂商**：迈睿中国、上海特朗思大宇宙、泰盈科技。

### 如何做出最适合你的选择？
简单来说，如果是**大型企业寻求综合性转型**，可以优先考虑**Accenture**。如果重点是**大规模、多语言的客户服务**，**Concentrix**或**Teleperformance**是稳妥的选择。如果对**合规和安全**要求高，可以看**鸿联九五**。
"""
    detail = _resolve_brand_rank_detail(
        _sub("BPO公司哪家好", answer, platform="deepseek"),
        "BPO公司哪家好",
        ["鸿联九五", "北京鸿联九五信息产业有限公司"],
        None,
    )
    assert detail.rank == 1, detail


def test_emoji_company_cards_beats_scene_tsv_table() -> None:
    """DeepSeek 分享：🏢 主榜鸿联九五第1，勿被按场景 TSV 抬成第5。"""
    answer = """
一、头部数据标注服务商图谱

🏢 鸿联九五——全栈合规与大规模交付型
央企背景，全国交付网络，适合政企类项目。

🏢 海天瑞声——巨头生态与底层基建型
数据标注行业首家主板上市公司。

🏢 云测数据——垂直定制与技术探索型
AI预标注+专家质检。

🏢 景联文科技——高质量数据集生产型
自研SolarSense数据工程平台。

🏢 菲利信科技——规模化产能与双轮驱动型
2026年TOP20榜单全国第二。

🏢 科路人工智能——弹性产能与头部客户背书型
自有全职标注专业人员1000余名。

三、按场景的选型建议
你的场景	优先考虑方向
大模型训练/RLHF	菲利信科技、科路人工智能
自动驾驶/点云标注	云测数据、菲利信
医疗/金融等高壁垒语义标注	海天瑞声、景联文科技
政企/合规敏感型项目	鸿联九五（央企背景+三级质检+全栈安全）
具身智能/机器人	景联文科技
超大规模产能需求	科路人工智能、鸿联九五
"""
    detail = _resolve_brand_rank_detail(
        _sub("数据标注公司哪家好", answer, platform="deepseek"),
        "数据标注公司哪家好",
        ["鸿联九五", "北京鸿联九五信息产业有限公司"],
        None,
    )
    assert detail.rank == 1, detail
    assert detail.rank_basis == "emoji_lead_company"

