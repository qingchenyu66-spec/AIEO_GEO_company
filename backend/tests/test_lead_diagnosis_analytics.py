"""Unit tests for lead diagnosis extended analytics."""

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
        _RunStub("202607031430", "2026-07-03 14:30", "task-2"),
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
    ]
    result = build_lead_diagnosis_analytics(lead, subtasks, runs)
    assert len(result["rank_trend"]) == 2
    assert result["rank_trend"][0]["avg_rank"] == 4.0
    assert result["rank_trend"][1]["avg_rank"] == 2.0
    assert "北森" in result["rank_trend"][0]["entities"]
    assert result["tracked_entities"][0] == "儒思HR"


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
