from types import SimpleNamespace

from app.services.monitor_service import (
    BrandRankResolution,
    fill_missing_subtask_ranks_for_task,
    _filter_matrix_columns_for_scope,
    _filter_subtasks_by_exposure_term,
    _keyword_groups_for_exposure_term,
    _prompt_keyword_match_score,
    _resolve_brand_rank,
    _resolve_brand_rank_detail,
    _resolve_prompt_monitor_keyword,
)
from app.services.rank_llm_service import should_trigger_llm_fallback


class _FakeRankBackfillSession:
    def __init__(self, subtasks):
        self._subtasks = subtasks

    def scalars(self, _stmt):
        return self._subtasks


def test_fill_subtask_ranks_only_fills_null_by_default() -> None:
    """2026-08-14 - 默认只补空，已有错误位次不覆盖（force 才重算）。"""
    task = SimpleNamespace(
        task_id="task-1",
        tenant_id=None,
        monitor_keywords="BrandCo",
        raw_request_json={},
    )
    dirty = SimpleNamespace(
        task_id="task-1",
        prompt="best vendor ranking",
        answer_content="1. CompetitorCo\n2. BrandCo\n3. OtherCo",
        mention_context=None,
        all_rankings_json=[],
        mention_position=8,
        raw_result_json={},
    )
    empty = SimpleNamespace(
        task_id="task-1",
        prompt="best vendor ranking",
        answer_content="1. CompetitorCo\n2. BrandCo\n3. OtherCo",
        mention_context=None,
        all_rankings_json=[],
        mention_position=None,
        raw_result_json={},
    )

    changed = fill_missing_subtask_ranks_for_task(_FakeRankBackfillSession([dirty, empty]), task)

    assert dirty.mention_position == 8
    assert empty.mention_position == 2
    assert changed == 1
    assert empty.raw_result_json["rank_resolution"]["source"] == "structured"
    assert "parsed_at" in empty.raw_result_json["rank_resolution"]


def test_fill_subtask_ranks_force_recomputes_existing() -> None:
    task = SimpleNamespace(
        task_id="task-1",
        tenant_id=None,
        monitor_keywords="BrandCo",
        raw_request_json={},
    )
    subtask = SimpleNamespace(
        task_id="task-1",
        prompt="best vendor ranking",
        answer_content="1. CompetitorCo\n2. BrandCo\n3. OtherCo",
        mention_context=None,
        all_rankings_json=[],
        mention_position=8,
        raw_result_json={},
    )

    changed = fill_missing_subtask_ranks_for_task(
        _FakeRankBackfillSession([subtask]),
        task,
        force_recompute=True,
    )

    assert changed == 1
    assert subtask.mention_position == 2


def test_filter_matrix_columns_for_scope_keeps_only_prompt_set() -> None:
    columns = [
        {"prompt": "LED广告公司推荐", "monitor_keyword": "LED广告公司推荐"},
        {"prompt": "地铁广告公司推荐", "monitor_keyword": "地铁广告公司推荐"},
    ]
    prompt_set = {"LED广告公司推荐": "词组A"}
    filtered = _filter_matrix_columns_for_scope(
        columns,
        prompt_set,
        keyword_group=None,
        monitor_keyword="LED广告公司推荐",
        exposure_term=None,
    )
    assert len(filtered) == 1
    assert filtered[0]["monitor_keyword"] == "LED广告公司推荐"


def test_filter_matrix_columns_for_scope_no_filter_keeps_all() -> None:
    columns = [{"prompt": "a"}, {"prompt": "b"}]
    assert _filter_matrix_columns_for_scope(columns, {"a": None}, keyword_group=None, monitor_keyword=None, exposure_term=None) == columns


def test_exposure_term_filter_matches_keyword_group_not_prompt_substring() -> None:
    from types import SimpleNamespace

    groups = [
        {
            "status": True,
            "monitor_keyword": "地铁广告公司推荐",
            "monitor_keywords": ["地铁广告公司推荐"],
            "exposure_terms": ["艾迪亚"],
        },
        {
            "status": True,
            "monitor_keyword": "LED广告公司推荐",
            "monitor_keywords": ["LED广告公司推荐"],
            "exposure_terms": ["另一品牌"],
        },
    ]
    matched = _keyword_groups_for_exposure_term("艾迪亚", groups)
    assert len(matched) == 1
    subtasks = [
        SimpleNamespace(prompt="地铁广告公司推荐"),
        SimpleNamespace(prompt="LED广告公司推荐"),
    ]
    filtered = _filter_subtasks_by_exposure_term(subtasks, "艾迪亚", groups)
    assert len(filtered) == 1
    assert filtered[0].prompt == "地铁广告公司推荐"


def test_resolve_brand_rank_blocks_api_when_prompt_is_scene_keyword() -> None:
    text = """
## 综合性/下沉市场运营商
- **华君传媒**：在二三线城市有优势。
- **艾迪亚控股 / 上海澜翼传媒**：侧重公交车身全场景整合。
"""
    asset = SimpleNamespace(
        brand_name="艾迪亚控股集团有限公司",
        brand_short_name="艾迪亚",
        company_full_name="艾迪亚控股集团有限公司",
    )
    subtask = SimpleNamespace(
        prompt="公交广告公司哪家好",
        answer_content=text,
        mention_context=None,
        all_rankings_json=[],
        mention_position=13,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        subtask,
        "艾迪亚控股集团有限公司",
        ["艾迪亚", "艾迪亚控股"],
        asset=asset,
    )
    assert detail.mentioned is True
    assert detail.source != "api"
    assert detail.rank == 2


def test_resolve_brand_rank_does_not_skip_company_names_ending_with_media() -> None:
    """「艾迪亚传媒」不得被当作行业词 skip，否则会落到「怎么选」第 7 条。"""
    text = """
## 三、全国整合投放代理公司（多城一站式，中小品牌省心）
1. **传播易**：线上户外广告投放平台
2. **艾迪亚传媒**：覆盖一二三线城市地铁/公交/高铁
# 怎么选公司？快速对照
7. **多城市同步批量投放、预算有限** → 传播易、艾迪亚整合代理
"""
    asset = SimpleNamespace(
        brand_name="艾迪亚控股集团有限公司",
        brand_short_name="艾迪亚",
        company_full_name="艾迪亚控股集团有限公司",
    )
    subtask = SimpleNamespace(
        prompt="地铁广告公司推荐",
        answer_content=text,
        mention_context=None,
        all_rankings_json=[],
        mention_position=7,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        subtask,
        "艾迪亚控股集团有限公司",
        ["艾迪亚", "艾迪亚控股", "艾迪亚传媒"],
        asset=asset,
    )
    assert detail.mentioned is True
    assert detail.rank == 2
    assert detail.source == "structured"

    resolution = BrandRankResolution(rank=13, mentioned=True, source="api", confidence=0.6)
    assert should_trigger_llm_fallback(resolution, is_industry_task=True) is True


def test_resolve_brand_rank_trusts_manual_snapshot_rank() -> None:
    subtask = SimpleNamespace(
        prompt="地铁广告公司推荐",
        answer_content="1. 某竞品\n2. 另一竞品",
        mention_context=None,
        all_rankings_json=[{"name": "某竞品", "rank": 1}],
        mention_position=1,
        raw_result_json={"source": "manual_snapshot"},
    )
    rank, mentioned = _resolve_brand_rank(subtask, "综合", ["艾迪亚"], asset=None)
    assert rank == 1
    assert mentioned is True


def test_resolve_brand_rank_ignores_industry_list_without_brand() -> None:
    text = """
### 主要地铁广告运营商

1. 分众传媒
- 中国最大的楼宇媒体和户外视频广告运营商之一

2. 华视传媒
- 专注于地铁、公交移动电视广告

3. 雅仕维
4. 德高中国
5. 百灵时代
6. 各城市地铁集团自有广告公司
"""
    subtask = SimpleNamespace(
        prompt="地铁广告公司哪家好",
        answer_content=text,
        mention_context=None,
        all_rankings_json=[],
        mention_position=2,
        raw_result_json={},
    )
    brand_terms = ["艾迪亚控股集团有限公司", "艾迪亚", "艾迪亚集团"]

    rank, mentioned = _resolve_brand_rank(subtask, "电梯广告", brand_terms, asset=None)
    assert rank is None
    assert mentioned is False


def test_prompt_keyword_match_score_accepts_industry_variant_suffix() -> None:
    assert _prompt_keyword_match_score("公交广告公司推荐", "公交广告公司哪家好") >= 500
    assert _prompt_keyword_match_score("地铁广告公司哪家好", "地铁广告公司推荐") >= 500


def test_find_brand_rank_prefers_category_local_over_api_flat() -> None:
    from types import SimpleNamespace

    subtask = SimpleNamespace(
        prompt="公交广告公司哪家好",
        answer_content="""
一、沧州本地推荐
1. 沧州市都市传媒公交广告有限公司
2. 沧州公共交通集团有限公司
二、全国性头部企业
1. 艾迪亚控股集团
2. 德高广告
""",
        mention_context=None,
        all_rankings_json=[
            {"name": "沧州市都市传媒公交广告有限公司", "rank": 1},
            {"name": "沧州公共交通集团有限公司", "rank": 2},
            {"name": "艾迪亚控股集团", "rank": 3},
        ],
        raw_result_json={},
        mention_position=3,
    )
    rank, mentioned = _resolve_brand_rank(subtask, "公交广告公司哪家好", ["艾迪亚"], asset=None)
    assert mentioned is True
    assert rank == 1


def test_resolve_prompt_monitor_keyword_maps_variant_prompt_to_configured_keyword() -> None:
    groups = [
        {
            "status": True,
            "monitor_keyword": "电梯广告公司推荐",
            "monitor_keywords": [
                "电梯广告公司推荐",
                "机场广告公司哪家好",
                "高铁广告公司哪家好",
                "公交广告公司哪家好",
                "地铁广告公司推荐",
                "LED广告公司推荐",
            ],
        }
    ]
    assert _resolve_prompt_monitor_keyword("公交广告公司推荐", groups) == "公交广告公司哪家好"
    assert _resolve_prompt_monitor_keyword("地铁广告公司哪家好", groups) == "地铁广告公司推荐"
    assert _resolve_prompt_monitor_keyword("LED广告公司推荐", groups) == "LED广告公司推荐"


def test_china_bpo_leaders_not_global_appearance() -> None:
    """19244033：中国市场行业领导者迈睿①鸿联②，勿把全球表+全文出场计成第42。"""
    text = """
### 🌍 全球领先的BPO公司
| 公司 | 核心优势 | 适合场景 |
| :--- | :--- | :--- |
| **Concentrix** | 大规模CX | 客服 |
| **Teleperformance (TP)** | 多渠道 | 全球 |
| **Accenture** | 数字化转型 | 复杂项目 |
| **Capgemini** | 技术BPO | 高端 |
| **Tata Consultancy Services (TCS)** | IT+BPO | 大型企业 |
| **Genpact** | 数据驱动 | 流程 |
| **WNS** | 财务 | 财务外包 |
| **Infosys BPM** | 端到端 | 综合 |
| **TaskUs** | 数字服务 | 初创 |
| **Hugo** | 新兴 | 多渠道 |

### 🇨🇳 中国市场的主要BPO公司

除了上述国际巨头在中国设有分支机构外，本土也有一批实力强劲的玩家：

*   **行业领导者**：**迈睿中国**[citation:32]、**北京鸿联九五信息产业有限公司**[citation:34]、**泰盈科技**[citation:36]和**上海特朗思大宇宙信息技术服务有限公司(Transcosmos中国)**[citation:38]。这些公司在市场份额和行业影响力上处于领先地位。
*   **其他重要本土企业**：**北京九五太维资讯有限公司**、**诚联凯**、**上海赛科斯**。

### 总结
*   如果是在**中国市场**，**迈睿中国、鸿联九五**等本土领军企业值得重点关注。
"""
    subtask = SimpleNamespace(
        prompt="BPO公司推荐",
        answer_content=text,
        mention_context=None,
        all_rankings_json=[
            {"name": "Concentrix", "rank": 1, "category": "🌍 全球领先的BPO公司"},
            {"name": "TP", "rank": 2, "category": "🌍 全球领先的BPO公司"},
            {"name": "Accenture", "rank": 3, "category": "🌍 全球领先的BPO公司"},
            {"name": "Capgemini", "rank": 4, "category": "🌍 全球领先的BPO公司"},
            {"name": "TCS", "rank": 5, "category": "🌍 全球领先的BPO公司"},
            {"name": "Genpact", "rank": 6, "category": "🌍 全球领先的BPO公司"},
            {"name": "WNS", "rank": 7, "category": "🌍 全球领先的BPO公司"},
            {"name": "Infosys BPM", "rank": 8, "category": "🌍 全球领先的BPO公司"},
            {"name": "TaskUs", "rank": 9, "category": "🌍 全球领先的BPO公司"},
            {"name": "Hugo", "rank": 10, "category": "🌍 全球领先的BPO公司"},
            {"name": "🇨🇳 中国市场的主要BPO公司", "rank": 12},
        ],
        mention_position=42,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        subtask,
        "北京鸿联九五信息产业有限公司",
        ["北京鸿联九五信息产业有限公司", "鸿联九五"],
        None,
    )
    assert detail.mentioned is True
    assert detail.rank == 2
    assert detail.rank_basis in {"section_local", "line_enum_local"}


def test_national_team_labeling_section_first() -> None:
    """19244071：国家队与大型外包商里鸿联①电信星海②，勿全文出场第30。"""
    text = """
#### 🏛️ 综合型巨头
*   **云测数据**：市场份额高
*   **海天瑞声**：自动驾驶点云
*   **数据堂**：图像音频文本

#### 🎯 垂直领域专家
*   **标贝数据**：语音文本
*   **汇众天智**：自动驾驶与智慧医疗
*   **金智云**：地图数据

#### 🌐 全球化服务商
*   **澳鹏 (Appen)**：全球标注员网络

#### 🏗️ 国家队与大型外包商
这类公司以国企背景和庞大的人力资源网络为特点。

*   **鸿联九五**：中信国安控股的国企[citation:38]，拥有全国140+职场和5万+坐席。
*   **电信星海**：依托中国电信集团，在数据安全和基础设施方面有天然优势。

#### 🚀 创新技术派
*   **菲利信科技**：2024年全国排名第2
*   **景联文科技**：长三角
*   **百行数据**：私有化部署
"""
    subtask = SimpleNamespace(
        prompt="数据标注公司选哪家",
        answer_content=text,
        mention_context=None,
        all_rankings_json=[],
        mention_position=30,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        subtask,
        "北京鸿联九五信息产业有限公司",
        ["北京鸿联九五信息产业有限公司", "鸿联九五"],
        None,
    )
    assert detail.mentioned is True
    assert detail.rank == 1
    assert detail.rank_basis == "section_local"


def test_line_enum_kept_when_section_local_is_inflated() -> None:
    """客服BPO行内迈睿①鸿联②，宽节类内第9不得盖掉行内第2。"""
    from app.services.monitor_service import _drop_soft_ranks_beaten_by_structured

    kept = _drop_soft_ranks_beaten_by_structured(
        [
            BrandRankResolution(
                rank=9, mentioned=True, source="appearance", confidence=0.72, rank_basis="section_local"
            ),
            BrandRankResolution(
                rank=2, mentioned=True, source="appearance", confidence=0.7, rank_basis="line_enum_local"
            ),
        ]
    )
    assert min(item.rank for item in kept if item.rank is not None) == 2
    assert any(item.rank_basis == "line_enum_local" for item in kept)

    kept_six = _drop_soft_ranks_beaten_by_structured(
        [
            BrandRankResolution(
                rank=6, mentioned=True, source="appearance", confidence=0.72, rank_basis="section_local"
            ),
            BrandRankResolution(
                rank=2, mentioned=True, source="appearance", confidence=0.7, rank_basis="line_enum_local"
            ),
        ]
    )
    assert min(item.rank for item in kept_six if item.rank is not None) == 2


def test_line_enum_dropped_when_compact_section_is_slightly_behind() -> None:
    """紧凑类内第5被行内第4盖掉时，仍丢掉行内。"""
    from app.services.monitor_service import _drop_soft_ranks_beaten_by_structured

    kept = _drop_soft_ranks_beaten_by_structured(
        [
            BrandRankResolution(
                rank=5, mentioned=True, source="appearance", confidence=0.72, rank_basis="section_local"
            ),
            BrandRankResolution(
                rank=4, mentioned=True, source="appearance", confidence=0.7, rank_basis="line_enum_local"
            ),
        ]
    )
    assert [item.rank_basis for item in kept] == ["section_local"]


def test_representative_column_enum_first_not_empty() -> None:
    """19227911：代表企业格顿号鸿联九五为首，勿因场景列/跳过表格而空位次。"""
    text = """
### 第二步：认识市场上的主要玩家

| 公司类型 | 代表企业 | 核心优势 / 特点 | 适合场景 |
| :--- | :--- | :--- | :--- |
| **综合巨头与平台** | 百度智能云[citation:7]、Scale AI[citation:8]、Labelbox[citation:9] | 技术实力雄厚 | 大型企业 |
| **专业数据服务商** | 鸿联九五[citation:10]、澳鹏(Appen)[citation:11]、云测数据[citation:12]、海天瑞声[citation:13]、数据堂[citation:14]、菲利信科技[citation:15]、标贝数据[citation:16] | **行业主流选择** | 绝大多数有明确数据标注需求的企业 |
| **垂直领域专家** | 曼孚科技(自动驾驶)[citation:17]、中科江南(医疗)[citation:18] | 垂直场景 | 行业项目 |
"""
    subtask = SimpleNamespace(
        prompt="数据标注公司选哪家",
        answer_content=text,
        mention_context="鸿联九五",
        all_rankings_json=[
            {"name": "📝 第一步", "rank": 1},
            {"name": "百度智能云", "rank": 1, "category": "📊 第二步：认识市场上的主要玩家"},
            {"name": "Scale AI", "rank": 2, "category": "📊 第二步：认识市场上的主要玩家"},
        ],
        mention_position=None,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        subtask,
        "北京鸿联九五信息产业有限公司",
        ["北京鸿联九五信息产业有限公司", "鸿联九五"],
        None,
    )
    assert detail.mentioned is True
    assert detail.rank == 1
    assert detail.rank_basis == "rep_column"


def test_callcenter_domestic_head_table_second() -> None:
    """19147399：国内头部代表企业 泰盈、鸿联、维音 → 第2，勿全文16。"""
    text = """
### 第三步：三类主流供应商“画像”与对应场景

| 类型 | 代表企业（供检索参考） | 核心优势 | 最适合谁 |
| :--- | :--- | :--- | :--- |
| **国际巨头（高安全）** | Teleperformance（TP）、Concentrix（CNX） | 流程标准化 | 跨国企业 |
| **国内头部（高性价比）** | 泰盈科技、鸿联九五、维音（VXI） | 本土化灵活 | 互联网大厂 |
| **垂直专精（高转化）** | 区域性/行业性小巨人 | 行业话术库 | 汽车售后 |
"""
    subtask = SimpleNamespace(
        prompt="呼叫中心外包公司选哪家",
        answer_content=text,
        mention_context=None,
        all_rankings_json=[],
        mention_position=16,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        subtask,
        "北京鸿联九五信息产业有限公司",
        ["鸿联九五"],
        None,
    )
    assert detail.mentioned is True
    assert detail.rank == 2
    assert detail.rank_basis == "rep_column"


def test_hr_vertical_expert_fourth_not_seven() -> None:
    """19227921：垂直行业专家华兴①卡思②华路③鸿联④，勿被总结顿号抬成第7。"""
    text = """
### 🏢 全国性综合服务商
*   **中智集团 (CIIC)**：央企背景
*   **北京外企 (FESCO)**：老牌
*   **万宝盛华 (ManpowerGroup)**：全球
*   **蚂蚁HR**：72小时到岗
*   **科锐国际**：高端寻访
*   **上海外服**：华东巨头

### 🎯 垂直行业专家
*   **华兴人力资源**：国央企岗位外包
*   **卡思优派**：高端制造
*   **北京华路时代**：IT和技术岗位
*   **鸿联九五**：金融、通信等合规敏感型行业的标杆

### ✅ 如何选择一家靠谱的外包公司？

1.  **核查“硬资质”**：确认许可证。
2.  **评估“软实力”**：行业经验与服务网络。
3.  **匹配核心需求**：明确痛点。
4.  **验证市场口碑**：续约率。

总的来说，可以优先考察**中智、FESCO、万宝盛华**等综合型巨头；如果你身处**高端制造、IT互联网、金融**等专业性强的行业，那么**卡思优派、华路时代、鸿联九五**这类垂直专家可能是更能解决实际问题的选择。
"""
    subtask = SimpleNamespace(
        prompt="人力资源外包公司推荐",
        answer_content=text,
        mention_context=None,
        all_rankings_json=[],
        mention_position=7,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        subtask,
        "北京鸿联九五信息产业有限公司",
        ["鸿联九五"],
        None,
    )
    assert detail.mentioned is True
    assert detail.rank == 4
    assert detail.rank_basis == "section_local"


def test_strength_type_colon_card_first_not_empty() -> None:
    """19244073：综合实力型下「鸿联九五：」为首张卡，勿空位次。"""
    text = """
📊 主流数据标注公司推荐
🏢 综合实力型：全栈式服务，安全合规

这类公司通常规模大、资质全。

鸿联九五：中信集团旗下国企。拥有覆盖全国50+城市的140+职场。

百度智能云：依托其文心大模型。

云测数据 (Testin)：全流程闭环服务。
"""
    subtask = SimpleNamespace(
        prompt="数据标注公司推荐",
        answer_content=text,
        mention_context=None,
        all_rankings_json=[],
        mention_position=None,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        subtask,
        "北京鸿联九五信息产业有限公司",
        ["鸿联九五"],
        None,
    )
    assert detail.mentioned is True
    assert detail.rank == 1
    assert detail.rank_basis == "section_local"


def test_high_compliance_scene_first_not_token_fourteen() -> None:
    """19244037：高合规场景首卡鸿联九五，勿全文出场第14。"""
    text = """
选择哪家内容审核公司，关键在于适合自己的。

🏢 大型、全球化及高合规要求场景

如果你的业务涉及金融、政务，可以重点考虑以下服务商。

鸿联九五：作为中信集团控股的央企，它在安全合规方面具有天然优势。

网易智企·易盾：国内内容风控市场的领跑者。

⚡️ 高并发、互联网及出海业务场景

深圳蔚蓝云创：以高并发著称。
"""
    subtask = SimpleNamespace(
        prompt="内容审核公司哪家好",
        answer_content=text,
        mention_context=None,
        all_rankings_json=[],
        mention_position=14,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        subtask,
        "北京鸿联九五信息产业有限公司",
        ["鸿联九五"],
        None,
    )
    assert detail.mentioned is True
    assert detail.rank == 1
    assert detail.rank_basis == "section_local"
