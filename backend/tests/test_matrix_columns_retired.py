"""已下线监测词列追加逻辑。"""

from unittest.mock import patch

from app.services.monitor_service import _append_retired_matrix_columns, _build_matrix_columns


class _Group:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_append_retired_matrix_columns_appends_historical_prompts() -> None:
    groups = [
        _Group(
            id=1,
            name="当前词组",
            monitor_keyword="仍在监测",
            monitor_keywords_json=["仍在监测"],
            platforms_json=["doubao"],
            sort_order=0,
            status=True,
            deleted=False,
        ),
    ]
    active_columns = [
        {
            "prompt": "仍在监测",
            "group_name": "当前词组",
            "monitor_keyword": "仍在监测",
            "group_id": 1,
            "platforms": ["doubao"],
        },
    ]
    prompt_set = {
        "仍在监测": "当前词组",
        "旧监测词A": "已删词组",
    }

    with patch("app.services.monitor_service.keyword_group_platforms", return_value=[]):
        with patch("app.services.monitor_service._resolve_prompt_keyword_group", return_value=None):
            merged = _append_retired_matrix_columns(active_columns, prompt_set, groups)

    assert [c["prompt"] for c in merged] == ["仍在监测", "旧监测词A"]
    assert merged[1]["retired"] is True
    assert merged[1]["group_name"] == "已删词组"


def test_build_matrix_columns_include_retired() -> None:
    groups = [
        _Group(
            id=1,
            name="当前词组",
            monitor_keyword="仍在监测",
            monitor_keywords_json=["仍在监测"],
            platforms_json=["doubao"],
            sort_order=0,
            status=True,
            deleted=False,
        ),
    ]
    prompt_set = {
        "仍在监测": "当前词组",
        "旧监测词A": "已删词组",
    }

    with patch("app.services.monitor_service.keyword_group_platforms", return_value=["doubao"]):
        with patch("app.services.monitor_service.keyword_group_monitor_keywords", side_effect=lambda g: list(g.monitor_keywords_json)):
            with patch("app.services.monitor_service.keyword_group_display_label", side_effect=lambda g: g.name):
                with patch(
                    "app.services.monitor_service._prompt_key_for_monitor_keyword",
                    side_effect=lambda group, text, *_a, **_k: text,
                ):
                    with patch("app.services.monitor_service._resolve_prompt_keyword_group", return_value=None):
                        cols = _build_matrix_columns(
                            groups,
                            prompt_set,
                            include_retired=True,
                        )

    assert [c["prompt"] for c in cols] == ["仍在监测", "旧监测词A"]
    assert cols[1].get("retired") is True


def test_build_matrix_columns_include_retired_when_active_unmapped() -> None:
    """当前配置词在窗内对不上任何历史 prompt 时, 仍应输出已下线列并打 retired."""
    groups = [
        _Group(
            id=1,
            name="当前词组",
            monitor_keyword="新配置词",
            monitor_keywords_json=["新配置词"],
            platforms_json=["doubao"],
            sort_order=0,
            status=True,
            deleted=False,
        ),
    ]
    prompt_set = {
        "旧监测词A": "已删词组",
        "旧监测词B": "已删词组",
    }

    with patch("app.services.monitor_service.keyword_group_platforms", return_value=["doubao"]):
        with patch(
            "app.services.monitor_service.keyword_group_monitor_keywords",
            side_effect=lambda g: list(g.monitor_keywords_json),
        ):
            with patch("app.services.monitor_service.keyword_group_display_label", side_effect=lambda g: g.name):
                # 当前词对不上窗内数据 → 建不出 active 列
                with patch(
                    "app.services.monitor_service._prompt_key_for_monitor_keyword",
                    return_value="",
                ):
                    with patch("app.services.monitor_service._resolve_prompt_keyword_group", return_value=None):
                        cols = _build_matrix_columns(
                            groups,
                            prompt_set,
                            include_retired=True,
                        )

    assert [c["prompt"] for c in cols] == ["旧监测词A", "旧监测词B"]
    assert all(c.get("retired") is True for c in cols)