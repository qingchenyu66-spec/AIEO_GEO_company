"""监控词里非排名问法（如「做什么的」）不记位次。"""

from types import SimpleNamespace

from app.services.monitor_service import _resolve_brand_rank_detail
from app.services.schedule_context import prompt_monitor_intent


def test_what_does_it_do_monitor_prompt_is_non_ranking() -> None:
    assert prompt_monitor_intent("艾迪亚传媒做什么的") == "exposure"
    assert prompt_monitor_intent("户外广告公司哪家好") == "ranking"


def test_non_ranking_monitor_prompt_resolves_to_no_rank() -> None:
    subtask = SimpleNamespace(
        prompt="艾迪亚传媒做什么的",
        answer_content="艾迪亚是一家户外广告公司，主要做电梯与高铁媒体。",
        mention_context=None,
        all_rankings_json=[],
        mention_position=1,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(
        subtask,
        "艾迪亚控股集团有限公司",
        ["艾迪亚", "艾迪亚传媒", "艾迪亚控股集团有限公司"],
        None,
    )
    assert detail.rank is None
    assert detail.mentioned is True
    assert detail.source == "exposure"
