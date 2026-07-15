"""多样例：分段回答里取最靠前名次（方案 2 产品口径）。"""

from __future__ import annotations

from app.services.ranking_parser import (
    find_best_brand_entry_scoped,
    find_best_brand_rank_scoped,
    parse_answer_rankings,
)


def _honglian(name: str) -> bool:
    return "鸿联" in name


SAMPLE_INTL_THEN_CN = """
## 一、国际知名外包公司
| 公司 | 特点 |
|------|------|
| Teleperformance | 全球规模大 |
| Concentrix | 技术驱动 |
| Sitel Group | 全流程 |
| TTEC | 体验设计 |
| Alorica | 北美灵活 |
| Webhelp | 欧洲 |
| Infosys BPM | 印度成本优 |

## 二、中国本土/亚太区主要外包商
- **大宇宙（transcosmos）**：电商客服
- Teleperformance 中国：本地化
- Sykes：已并入 Sitel
- **鸿联九五**：金融/运营商客户多
- **九五太维**：北京系 BPO
- **华道数据**：金融后台
- **京北方科技**：银行 IT
- **软通动力**：IT 与客服

## 三、选择外包公司的关键考量
1. 行业经验
2. 语种能力
3. 技术能力
"""


SAMPLE_BY_NEED = """
按需求类型选择：

**大型企业/全渠道需求**
- Teleperformance：全球化多语种
- Concentrix：数字化转型
- 泰盈科技：大型交付
- 智齿科技：全渠道客服

**国内主流/性价比**
- 鸿联九五：国内老牌网点广
- 九五太维：综合 BPO
- 二六三通信：云通话
- 赛福特：中小批量灵活

**技术驱动/云呼叫中心**
- 容联七陌：云呼叫
- Udesk：工单一体化

## 建议的决策路径
1. 需求定义
2. RFP 招标
3. 实地考察
4. 试点验证
"""


SAMPLE_CN_ONLY_NUMBERED = """
### 一、国内呼叫中心外包推荐
1. 鸿联九五
2. 九五太维
3. 华道数据
"""


SAMPLE_DUPLICATE_WORSE_LATER = """
## 一、整合服务商
1. 鸿联九五
2. 九五太维

## 二、区域补充
1. 某某本地商
…
9. 鸿联九五（区域提及）
"""


SAMPLE_TABLE_THEN_BULLETS = """
二、中国本土主要厂商

| 公司 | 说明 |
|------|------|
| 大宇宙 | 日系 |
| 鸿联九五 | 老牌 |

- 九五太维：北京系
"""


def test_intl_then_cn_prefers_cn_local_rank_not_global_11():
    entries = parse_answer_rankings(SAMPLE_INTL_THEN_CN)
    hit = next(item for item in entries if _honglian(item["name"]))
    assert hit["rank"] == 3
    assert "中国" in str(hit["category"]) or "本土" in str(hit["category"])
    # 关键考量不得当选手段抬分抢段
    assert not any("考量" in str(item.get("category") or "") and _honglian(item["name"]) for item in entries)
    rank, matched = find_best_brand_rank_scoped(entries, _honglian, "呼叫中心外包公司推荐")
    assert matched and rank == 3
    entry = find_best_brand_entry_scoped(entries, _honglian, "呼叫中心外包公司推荐")
    assert entry is not None
    assert entry["rank"] == 3


def test_by_need_prefers_domestic_first_not_global_5():
    entries = parse_answer_rankings(SAMPLE_BY_NEED)
    hit = next(item for item in entries if _honglian(item["name"]))
    assert hit["rank"] == 1
    assert "国内" in str(hit["category"]) or "性价比" in str(hit["category"])
    rank, matched = find_best_brand_rank_scoped(entries, _honglian, "呼叫中心外包公司选哪家")
    assert matched and rank == 1
    # 决策路径编号不能吞成选手
    assert not any(item["name"] in {"需求定义", "实地考察", "试点验证"} for item in entries)


def test_cn_only_numbered_is_first():
    entries = parse_answer_rankings(SAMPLE_CN_ONLY_NUMBERED)
    rank, matched = find_best_brand_rank_scoped(entries, _honglian, "呼叫中心外包公司推荐")
    assert matched and rank == 1


def test_duplicate_later_worse_rank_keeps_frontmost():
    entries = parse_answer_rankings(SAMPLE_DUPLICATE_WORSE_LATER)
    ranks = [item["rank"] for item in entries if _honglian(item["name"])]
    assert 1 in ranks
    rank, matched = find_best_brand_rank_scoped(entries, _honglian, "呼叫中心外包公司推荐")
    assert matched and rank == 1


def test_min_across_intl_json_and_cn_section():
    """正文段内第 3 + JSON 全文第 11 → 取 3。"""
    text_entries = parse_answer_rankings(SAMPLE_INTL_THEN_CN)
    merged = [
        *text_entries,
        {"name": "鸿联九五", "rank": 11, "category": None},
    ]
    rank, matched = find_best_brand_rank_scoped(merged, _honglian, "呼叫中心外包公司推荐")
    assert matched and rank == 3


def test_table_and_bullets_honglian_front_in_cn_block():
    entries = parse_answer_rankings(SAMPLE_TABLE_THEN_BULLETS)
    hit = next(item for item in entries if _honglian(item["name"]))
    assert hit["rank"] in {1, 2}  # 表内第 2 或段内重排
    rank, matched = find_best_brand_rank_scoped(entries, _honglian, "呼叫中心外包")
    assert matched and rank is not None and rank <= 2
