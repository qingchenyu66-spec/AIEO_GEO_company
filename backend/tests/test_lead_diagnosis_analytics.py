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
    run_dashed = _RunStub("20260630-1449", "", "task-3")
    run_without_schedule = _RunStub("", "", "task-2")

    assert _execution_key_from_run(run_without_label) == "2026-07-03 14:30"
    assert _execution_key_from_run(run_dashed) == "2026-06-30 14:49"
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


def test_molizhishu_best_day_not_worse_than_latest_brand_rank() -> None:
    """选日与展表同口径后：最新日品牌均位更好时，最优日不得落在更差的旧日。"""
    from datetime import datetime

    from app.services.lead_diagnosis_analytics import _build_molizhishu_ranking_rows

    class _RunEarly:
        schedule_key = "202608111000"
        schedule_label = "2026-08-11 10:00"
        task_id = "task-early"

    class _RunLate:
        schedule_key = "202608141000"
        schedule_label = "2026-08-14 10:00"
        task_id = "task-late"

    class _SubEarly:
        task_id = "task-early"
        mention_position = 1.5
        all_rankings_json = [{"brandName": "SAB伟星拉链", "rank": 1.5}]
        updated_at = datetime(2026, 8, 11, 10, 0)

    class _SubLate:
        task_id = "task-late"
        mention_position = 1
        all_rankings_json = [
            {"brandName": "SAB伟星拉链", "rank": 1},
            {"brandName": "YKK", "rank": 1},
        ]
        updated_at = datetime(2026, 8, 14, 10, 0)

    rows = _build_molizhishu_ranking_rows(
        [_SubEarly(), _SubLate()],
        brand="SAB伟星拉链",
        competitors=["YKK"],
        task_run_map={"task-early": _RunEarly(), "task-late": _RunLate()},
    )
    brand_rows = [r for r in rows if r.get("is_brand")]
    by_type = {r["type_label"]: r for r in brand_rows}
    assert "最近/最优" in by_type
    assert "最优" not in by_type
    assert by_type["最近/最优"]["rank_display"] == "1"
    assert by_type["最近/最优"]["collected_at"].startswith("2026-08-14")
    assert float(by_type["最差"]["rank_display"]) == 1.5
    assert by_type["最差"]["collected_at"].startswith("2026-08-11")
    # 竞品仍保留；最优/最差按自身日均，不得出现「最差位次好于最优」
    ykk = [r for r in rows if r["name"] == "YKK"]
    assert any(r["type_label"] in {"最近", "最近/最优"} for r in ykk)


def test_molizhishu_best_worst_per_entity_not_brand_day() -> None:
    """竞品最优/最差按自身日均；不得挂在本品牌选日上写反。"""
    from datetime import datetime

    from app.services.lead_diagnosis_analytics import _build_molizhishu_ranking_rows

    class _Run11:
        schedule_key = "202608111000"
        schedule_label = "2026-08-11 10:00"
        task_id = "t11"

    class _Run12:
        schedule_key = "202608121000"
        schedule_label = "2026-08-12 10:00"
        task_id = "t12"

    class _Run14:
        schedule_key = "202608141000"
        schedule_label = "2026-08-14 10:00"
        task_id = "t14"

    class _Sub11:
        task_id = "t11"
        mention_position = 2.7
        all_rankings_json = [
            {"brandName": "SAB伟星拉链", "rank": 2.7},
            {"brandName": "YKK", "rank": 1},
        ]
        updated_at = datetime(2026, 8, 11, 10, 0)

    class _Sub12:
        task_id = "t12"
        mention_position = 2
        all_rankings_json = [
            {"brandName": "SAB伟星拉链", "rank": 2},
            {"brandName": "YKK", "rank": 1.5},
        ]
        updated_at = datetime(2026, 8, 12, 10, 0)

    class _Sub14:
        task_id = "t14"
        mention_position = 2
        all_rankings_json = [
            {"brandName": "SAB伟星拉链", "rank": 2},
            {"brandName": "YKK", "rank": 1},
        ]
        updated_at = datetime(2026, 8, 14, 10, 0)

    rows = _build_molizhishu_ranking_rows(
        [_Sub11(), _Sub12(), _Sub14()],
        brand="SAB伟星拉链",
        competitors=["YKK"],
        task_run_map={"t11": _Run11(), "t12": _Run12(), "t14": _Run14()},
    )
    ykk = {r["type_label"]: r for r in rows if r["name"] == "YKK"}
    # YKK 日均：08-11=1、08-12=1.5、08-14=1 → 最优应是 1，最差应是 1.5
    best_row = ykk.get("最优") or ykk.get("最近/最优")
    assert best_row is not None
    assert float(best_row["rank_display"]) == 1.0
    assert "最差" in ykk
    assert float(ykk["最差"]["rank_display"]) == 1.5
    assert float(best_row["rank_display"]) <= float(ykk["最差"]["rank_display"])

    from app.services.lead_diagnosis_analytics import compact_ranking_rows_for_deck

    rows = [
        {
            "name": "分众传媒",
            "type_label": "最近",
            "category": "全国头部龙头",
            "rank_display": "1",
            "is_brand": False,
        },
        {
            "name": "分众传媒",
            "type_label": "最近",
            "category": "怎么选",
            "rank_display": "1",
            "is_brand": False,
        },
        {
            "name": "艾迪亚控股集团有限公司",
            "type_label": "最近",
            "category": "全国性中腰部",
            "rank_display": "3",
            "is_brand": True,
        },
        {
            "name": "分众传媒",
            "type_label": "最优",
            "category": "全国头部龙头",
            "rank_display": "1",
            "is_brand": False,
        },
    ]
    out = compact_ranking_rows_for_deck(rows, only_recent=False)
    assert len(out) == 3
    assert {r["category"] for r in out} == {"默认分类"}
    assert {r["type_label"] for r in out} == {"最近", "最优"}
    recent = [r for r in out if r["type_label"] == "最近"]
    assert len(recent) == 2


def test_strict_entity_match_avoids_two_char_false_positive() -> None:
    from app.services.lead_diagnosis_analytics import _is_tracked_entity

    brand = "艾迪亚控股集团有限公司"
    competitors = ["分众传媒", "白马户外媒体", "华铁传媒", "德高中国", "北京优视传媒"]
    assert _is_tracked_entity("新潮传媒（已被分众收购）", brand, competitors) is False
    assert _is_tracked_entity("北京信时光传媒", brand, competitors) is False
    assert _is_tracked_entity("分众传媒（Focus Media）", brand, competitors) is True
    assert _is_tracked_entity("艾迪亚传媒", brand, competitors) is True


def test_mine_competitors_from_acquisition_rankings() -> None:
    from app.services.lead_diagnosis_analytics import mine_competitors_from_acquisition_prompts

    brand = "SAB伟星拉链"
    subtasks = [
        _SubtaskStub(
            prompt="拉链品牌推荐哪家好",
            task_id="t1",
            all_rankings=[
                {"brandName": "YKK", "rank": 1},
                {"brandName": "SBS", "rank": 2},
                {"brandName": "SAB伟星拉链", "rank": 3},
            ],
        ),
        _SubtaskStub(
            prompt="工业拉链厂家排名",
            task_id="t1",
            all_rankings=[
                {"brandName": "YKK", "rank": 1},
                {"brandName": "SBS", "rank": 3},
            ],
        ),
        _SubtaskStub(
            prompt="高品质拉链供应商推荐",
            task_id="t1",
            all_rankings=[
                {"brandName": "YKK", "rank": 2},
                {"brandName": "RIRI", "rank": 4},
            ],
        ),
    ]
    mined = mine_competitors_from_acquisition_prompts(subtasks, brand=brand, aliases=["伟星拉链"])
    names = [row["name"] for row in mined]
    assert "YKK" in names
    assert "SBS" in names
    assert all(n not in {"SAB伟星拉链", "伟星拉链"} for n in names)
    ykk = next(row for row in mined if row["name"] == "YKK")
    assert ykk["hit_count"] == 3
    assert ykk["sample_total"] == 3
    assert ykk["rate"] == 100.0
    sbs = next(row for row in mined if row["name"] == "SBS")
    assert sbs["hit_count"] == 2
    assert sbs["rate"] == round(2 / 3 * 100, 1)


def test_mine_excludes_own_brand_variant_without_aliases() -> None:
    from app.services.lead_diagnosis_analytics import mine_competitors_from_acquisition_prompts

    subtasks = [
        _SubtaskStub(
            prompt="拉链品牌推荐哪家好",
            task_id="t1",
            all_rankings=[
                {"brandName": "伟星股份 SAB｜浙江临海[citation", "rank": 1},
                {"brandName": "YKK Excella系列", "rank": 2},
                {"brandName": "东莞虎门国际布料辅料城", "rank": 3},
                {"brandName": "我比较建议重点考察这几家", "rank": 4},
            ],
        ),
    ]
    mined = mine_competitors_from_acquisition_prompts(subtasks, brand="SAB伟星拉链")
    names = [row["name"] for row in mined]
    assert names == ["YKK"]
    assert all("伟星" not in n and "SAB" not in n.upper() for n in names)
    assert all("辅料城" not in n and "建议" not in n for n in names)


def test_mine_competitors_empty_when_only_brand_defense_falls_back() -> None:
    from app.services.lead_diagnosis_analytics import resolve_competitors_with_mining

    brand = "SAB伟星拉链"
    subtasks = [
        _SubtaskStub(
            prompt="SAB伟星拉链口碑怎么样",
            task_id="t1",
            all_rankings=[
                {"brandName": "YKK", "rank": 1},
                {"brandName": "SAB伟星拉链", "rank": 2},
            ],
        ),
    ]
    names, stats = resolve_competitors_with_mining(
        subtasks,
        brand=brand,
        configured=["建单竞品甲", "建单竞品乙"],
    )
    assert names == ["建单竞品甲", "建单竞品乙"]
    assert all(int(row["hit_count"] or 0) == 0 for row in stats)


def test_build_analytics_keeps_configured_competitors_and_adds_mined_competitors() -> None:
    lead = _LeadStub()
    lead.competitors_json = ["建单兜底"]
    lead.prompts_json = ["HR课程性价比高的品牌推荐", "HR培训机构品牌排名"]
    runs = [_RunStub("202607030930", "2026-07-03 09:30", "task-1")]
    subtasks = [
        _SubtaskStub(
            prompt="HR课程性价比高的品牌推荐",
            task_id="task-1",
            all_rankings=[
                {"brandName": "光华赋能", "rank": 1},
                {"brandName": "儒思HR", "rank": 4},
            ],
        ),
        _SubtaskStub(
            prompt="HR培训机构品牌排名",
            task_id="task-1",
            all_rankings=[
                {"brandName": "光华赋能", "rank": 2},
                {"brandName": "北森", "rank": 1},
            ],
        ),
    ]
    result = build_lead_diagnosis_analytics(lead, subtasks, runs, competitors=["建单兜底"])
    assert "建单兜底" in result["competitors"]
    assert "光华赋能" in result["competitors"]
    assert result["competitors_mined"]
    configured = next(row for row in result["competitor_stats"] if row["name"] == "建单兜底")
    mined = next(row for row in result["competitor_stats"] if row["name"] == "光华赋能")
    assert configured["rate"] == 0.0
    assert configured["origin"] == "configured"
    assert mined["rate"] > 0
    assert mined["origin"] == "mined"


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
