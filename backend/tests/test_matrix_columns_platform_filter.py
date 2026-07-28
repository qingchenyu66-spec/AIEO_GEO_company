"""词组未配置的平台不应出现在该平台矩阵列中。"""

from unittest.mock import patch

from app.services.monitor_service import _build_matrix_columns


class _Group:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_build_matrix_columns_filters_by_platform() -> None:
    groups = [
        _Group(
            id=1,
            name="核电涂料品牌",
            monitor_keyword="核电涂料品牌",
            monitor_keywords_json=["核电涂料品牌"],
            platforms_json=["qianwen", "doubao"],
            sort_order=0,
            status=True,
            deleted=False,
        ),
        _Group(
            id=2,
            name="无机涂料品牌",
            monitor_keyword="无机涂料品牌",
            monitor_keywords_json=["无机涂料品牌"],
            platforms_json=["doubao"],
            sort_order=1,
            status=True,
            deleted=False,
        ),
    ]
    prompt_set = {
        "核电涂料品牌": "核电涂料品牌",
        "无机涂料品牌": "无机涂料品牌",
    }

    def fake_platforms(group, asset=None):
        del asset
        return list(group.platforms_json or [])

    with patch("app.services.monitor_service.keyword_group_platforms", side_effect=fake_platforms):
        with patch("app.services.monitor_service.keyword_group_monitor_keywords", side_effect=lambda g: list(g.monitor_keywords_json)):
            with patch("app.services.monitor_service.keyword_group_display_label", side_effect=lambda g: g.name):
                with patch(
                    "app.services.monitor_service._prompt_key_for_monitor_keyword",
                    side_effect=lambda group, text, *_a, **_k: text,
                ):
                    qianwen_cols = _build_matrix_columns(groups, prompt_set, platform="qianwen")
                    doubao_cols = _build_matrix_columns(groups, prompt_set, platform="doubao")

    assert [c["monitor_keyword"] for c in qianwen_cols] == ["核电涂料品牌"]
    assert set(qianwen_cols[0]["platforms"]) == {"qianwen", "doubao"}
    assert {c["monitor_keyword"] for c in doubao_cols} == {"核电涂料品牌", "无机涂料品牌"}
