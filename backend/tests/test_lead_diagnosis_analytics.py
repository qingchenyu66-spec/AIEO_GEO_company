"""Unit tests for lead diagnosis extended analytics."""

from datetime import datetime

from app.services.lead_diagnosis_analytics import build_lead_diagnosis_analytics, names_match


class _SubtaskStub:
    def __init__(
        self,
        *,
        prompt: str,
        task_id: str,
        platform: str = "deepseek",
        mention_position: int | None = None,
        all_rankings: list | None = None,
        references: list | None = None,
    ) -> None:
        self.prompt = prompt
        self.task_id = task_id
        self.platform = platform
        self.status = "completed"
        self.answer_content = "ok"
        self.mention_position = mention_position
        self.all_rankings_json = all_rankings or []
        self.reference_list_json = references or []
        self.updated_at = None


class _RunStub:
    def __init__(self, schedule_key: str, schedule_label: str, task_id: str) -> None:
        self.schedule_key = schedule_key
        self.schedule_label = schedule_label
        self.task_id = task_id


class _LeadStub:
    brand_name = "儒思HR"
    region_codes_json: list[str] = []
    prompts_json = ["HR课程性价比高的品牌推荐", "HR培训机构品牌排名"]
    competitors_json = ["北森", "光华赋能"]


def test_execution_key_falls_back_to_schedule_key_then_updated_at() -> None:
    from app.services.lead_diagnosis_analytics import _execution_key_from_run

    run_without_label = _RunStub("202607031430", "", "task-1")
    run_without_schedule = _RunStub("", "", "task-2")

    assert _execution_key_from_run(run_without_label) == "2026-07-03 14:30"
    assert _execution_key_from_run(
        run_without_schedule,
        updated_at=datetime(2026, 7, 3, 19, 42),
    ) == "2026-07-03 19:42"
    assert _execution_key_from_run(None) == "时间数据缺失"


def test_names_match_supports_partial_brand() -> None:
    assert names_match("儒思HR", "儒思")
    assert names_match("儒思", "儒思HR App")


def test_build_prompt_analytics_groups_by_prompt() -> None:
    lead = _LeadStub()
    runs = [_RunStub("202607030930", "2026-07-03 09:30", "task-1")]
    subtasks = [
        _SubtaskStub(
            prompt="HR课程性价比高的品牌推荐",
            task_id="task-1",
            mention_position=4,
            all_rankings=[
                {"brandName": "光华赋能", "rank": 1},
                {"brandName": "儒思HR", "rank": 4},
            ],
            references=[{"url": "https://www.zhihu.com/question/1", "title": "知乎"}],
        ),
        _SubtaskStub(
            prompt="HR培训机构品牌排名",
            task_id="task-1",
            all_rankings=[{"brandName": "量子教育", "rank": 1}],
        ),
    ]
    result = build_lead_diagnosis_analytics(lead, subtasks, runs)
    assert len(result["prompt_analytics"]) == 2
    first = result["prompt_analytics"][0]
    assert first["brand_mention_rate"] == 100.0
    assert first["brand_avg_rank"] == 4.0
    assert result["source_analysis"]["total_references"] == 1


def test_build_rank_trend_across_runs() -> None:
    lead = _LeadStub()
    runs = [
        _RunStub("202607030930", "2026-07-03 09:30", "task-1"),
        _RunStub("202607031400", "2026-07-03 14:00", "task-2"),
        _RunStub("202607031930", "2026-07-03 19:30", "task-3"),
    ]
    subtasks = [
        _SubtaskStub(
            prompt="HR课程性价比高的品牌推荐",
            task_id="task-1",
            mention_position=4,
            all_rankings=[
                {"brandName": "儒思HR", "rank": 4},
                {"brandName": "北森", "rank": 1},
            ],
        ),
        _SubtaskStub(
            prompt="HR课程性价比高的品牌推荐",
            task_id="task-2",
            mention_position=2,
            all_rankings=[
                {"brandName": "儒思HR", "rank": 2},
                {"brandName": "北森", "rank": 3},
            ],
        ),
        _SubtaskStub(
            prompt="HR课程性价比高的品牌推荐",
            task_id="task-3",
            mention_position=5,
            all_rankings=[
                {"brandName": "儒思HR", "rank": 5},
                {"brandName": "北森", "rank": 2},
            ],
        ),
    ]
    result = build_lead_diagnosis_analytics(lead, subtasks, runs)
    assert len(result["rank_trend"]) == 3
    assert [row["schedule_label"] for row in result["rank_trend"]] == [
        "2026-07-03 09:30",
        "2026-07-03 14:00",
        "2026-07-03 19:30",
    ]
    assert [row["avg_rank"] for row in result["rank_trend"]] == [4.0, 2.0, 5.0]
    assert "北森" in result["rank_trend"][0]["entities"]
    assert result["tracked_entities"][0] == "儒思HR"


def test_build_rank_trend_spans_multiple_days() -> None:
    lead = _LeadStub()
    runs = [
        _RunStub("202607030930", "2026-07-03 09:30", "task-1"),
        _RunStub("202607040930", "2026-07-04 09:30", "task-2"),
    ]
    subtasks = [
        _SubtaskStub(
            prompt="HR课程性价比高的品牌推荐",
            task_id="task-1",
            mention_position=4,
            all_rankings=[{"brandName": "儒思HR", "rank": 4}],
        ),
        _SubtaskStub(
            prompt="HR课程性价比高的品牌推荐",
            task_id="task-2",
            mention_position=2,
            all_rankings=[{"brandName": "儒思HR", "rank": 2}],
        ),
    ]
    result = build_lead_diagnosis_analytics(lead, subtasks, runs)
    assert len(result["rank_trend"]) == 2
    assert [row["schedule_label"] for row in result["rank_trend"]] == [
        "2026-07-03 09:30",
        "2026-07-04 09:30",
    ]
    assert result["rank_trend"][0]["avg_rank"] == 4.0
    assert result["rank_trend"][1]["avg_rank"] == 2.0


def test_molizhishu_ranking_rows_only_include_tracked_entities() -> None:
    from datetime import datetime

    from app.services.lead_diagnosis_analytics import _build_molizhishu_ranking_rows

    class _Run:
        schedule_key = "202607021634"
        schedule_label = "2026-07-02 16:34"
        task_id = "task-1"

    class _Sub:
        task_id = "task-1"
        all_rankings_json = [
            {"brandName": "分众传媒", "rank": 1},
            {"brandName": "新潮传媒", "rank": 2},
            {"brandName": "儒思HR", "rank": 3},
        ]
        updated_at = datetime(2026, 7, 2, 16, 34)

    rows = _build_molizhishu_ranking_rows(
        [_Sub()],
        brand="儒思HR",
        competitors=["北森"],
        task_run_map={"task-1": _Run()},
    )
    names = {row["name"] for row in rows}
    assert "儒思HR" in names
    assert "新潮传媒" not in names


def test_strict_entity_match_avoids_two_char_false_positive() -> None:
    from app.services.lead_diagnosis_analytics import _is_tracked_entity

    brand = "艾迪亚控股集团有限公司"
    competitors = ["分众传媒", "白马户外媒体", "华铁传媒", "德高中国", "北京优视传媒"]
    assert _is_tracked_entity("新潮传媒（已被分众收购）", brand, competitors) is False
    assert _is_tracked_entity("北京信时光传媒", brand, competitors) is False
    assert _is_tracked_entity("分众传媒（Focus Media）", brand, competitors) is True
    assert _is_tracked_entity("艾迪亚传媒", brand, competitors) is True


def test_build_brand_city_rankings_groups_by_region() -> None:
    lead = _LeadStub()
    lead.region_codes_json = ["110000"]
    runs = [_RunStub("202607030930", "2026-07-03 09:30", "task-1")]
    subtasks = [
        _SubtaskStub(
            prompt="HR课程性价比高的品牌推荐",
            task_id="task-1",
            mention_position=2,
            all_rankings=[
                {"brandName": "儒思HR", "rank": 2},
                {"brandName": "北森", "rank": 1},
            ],
        ),
    ]
    result = build_lead_diagnosis_analytics(
        lead,
        subtasks,
        runs,
        task_region_map={"task-1": ["110000"]},
    )
    blocks = result["brand_city_rankings"]
    assert len(blocks) == 1
    assert blocks[0]["region_name"] == "北京"
    brand_row = next(row for row in blocks[0]["rows"] if row["is_brand"])
    assert brand_row["mention_rate"] == 100.0
    assert brand_row["avg_rank"] == 2.0
