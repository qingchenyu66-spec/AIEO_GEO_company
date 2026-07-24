"""收录明细关键词：勿把同组问法塌缩成词组主标签。"""

from app.models.brand import BrandKeywordGroup
from app.services.monitor_service import _prompt_monitor_keyword, _resolve_prompt_monitor_keyword

ELEVATOR = "\u7535\u68af\u5e7f\u544a\u516c\u53f8\u63a8\u8350"  # 电梯广告公司推荐
SUBWAY = "\u5730\u94c1\u5e7f\u544a\u516c\u53f8\u63a8\u8350"  # 地铁广告公司推荐


def test_resolve_prompt_keeps_subway_distinct_from_elevator_group_label() -> None:
    group = BrandKeywordGroup(
        tenant_id=1,
        brand_asset_id=1,
        monitor_keyword=ELEVATOR,
        monitor_keywords_json=[
            ELEVATOR,
            "\u673a\u573a\u5e7f\u544a\u516c\u53f8\u54ea\u5bb6\u597d",
            "\u9ad8\u94c1\u5e7f\u544a\u516c\u53f8\u54ea\u5bb6\u597d",
            "\u516c\u4ea4\u5e7f\u544a\u516c\u53f8\u54ea\u5bb6\u597d",
            SUBWAY,
            "LED\u5e7f\u544a\u516c\u53f8\u63a8\u8350",
        ],
        exposure_terms_json=[],
        platforms_json=[],
        status=True,
        deleted=False,
    )
    groups = [group]
    # 旧逻辑：同组一律显示主标签「电梯…」→ 点开快照却是地铁回答
    assert _prompt_monitor_keyword(SUBWAY, groups) == ELEVATOR
    assert _resolve_prompt_monitor_keyword(SUBWAY, groups) == SUBWAY
    assert _resolve_prompt_monitor_keyword(ELEVATOR, groups) == ELEVATOR
