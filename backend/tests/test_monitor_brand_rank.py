from types import SimpleNamespace

from app.services.monitor_service import _resolve_brand_rank


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
    )
    brand_terms = ["艾迪亚控股集团有限公司", "艾迪亚", "艾迪亚集团"]

    rank, mentioned = _resolve_brand_rank(subtask, "电梯广告", brand_terms, asset=None)
    assert rank is None
    assert mentioned is False
