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
