"""品牌分析：抓取日锚定 + write-once 冻结。"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from app.models.monitor import GeoMonitorScheduleRun, GeoMonitorSubtask, GeoMonitorTask
from app.models.tenant import Tenant
from app.services.brand_analysis_service import (
    _brand_analysis_freeze_source,
    _load_brand_word_subtasks,
    _try_freeze_brand_analysis_snapshot,
    brand_analysis_filter_fp,
    brand_compare_windows,
    resolve_brand_analysis_anchor,
)
from app.services.window_snapshot_service import (
    BRAND_ANALYSIS_KIND,
    get_window_snapshot,
    insert_window_snapshot_if_absent,
    invalidate_window_snapshots_for_tenant,
    upsert_window_snapshot,
)


PARSED_RAW = {
    "_ba_sentiment_source": "deepseek-v3",
    "_ba_description_source": "deepseek-v3",
}


def test_brand_analysis_filter_fp_stable() -> None:
    assert brand_analysis_filter_fp(["b", "a"]) == brand_analysis_filter_fp(["a", "b"])
    assert brand_analysis_filter_fp([]) == "default"
    assert brand_analysis_filter_fp(["a"]) != brand_analysis_filter_fp(["a", "b"])


def test_insert_window_snapshot_if_absent_is_write_once(db) -> None:
    suffix = uuid.uuid4().hex[:8]
    tenant = Tenant(name="ba-freeze", code=f"BAF{suffix}", status=True)
    db.add(tenant)
    db.flush()
    as_of = date(2026, 9, 22)
    first = {"description_share": {"正面": 60.0, "中性": 30.0, "负面": 10.0}, "v": 1}
    second = {"description_share": {"正面": 99.0, "中性": 1.0, "负面": 0.0}, "v": 2}
    assert insert_window_snapshot_if_absent(
        db,
        tenant_id=int(tenant.id),
        kind=BRAND_ANALYSIS_KIND,
        window_days=7,
        payload=first,
        as_of_date=as_of,
        filter_fp="fp-a",
    )
    assert not insert_window_snapshot_if_absent(
        db,
        tenant_id=int(tenant.id),
        kind=BRAND_ANALYSIS_KIND,
        window_days=7,
        payload=second,
        as_of_date=as_of,
        filter_fp="fp-a",
    )
    snap = get_window_snapshot(
        db,
        tenant_id=int(tenant.id),
        kind=BRAND_ANALYSIS_KIND,
        window_days=7,
        as_of_date=as_of,
        filter_fp="fp-a",
    )
    assert snap is not None
    assert snap["v"] == 1
    assert snap["description_share"]["正面"] == 60.0


def test_invalidate_window_snapshots_keeps_brand_analysis(db) -> None:
    suffix = uuid.uuid4().hex[:8]
    tenant = Tenant(name="ba-inv", code=f"BAI{suffix}", status=True)
    db.add(tenant)
    db.flush()
    as_of = date(2026, 9, 22)
    upsert_window_snapshot(
        db,
        tenant_id=int(tenant.id),
        kind="workspace_brief",
        window_days=7,
        payload={"k": "brief"},
        as_of_date=as_of,
    )
    insert_window_snapshot_if_absent(
        db,
        tenant_id=int(tenant.id),
        kind=BRAND_ANALYSIS_KIND,
        window_days=7,
        payload={"k": "ba"},
        as_of_date=as_of,
        filter_fp="fp-b",
    )
    invalidate_window_snapshots_for_tenant(db, int(tenant.id))
    assert (
        get_window_snapshot(
            db,
            tenant_id=int(tenant.id),
            kind="workspace_brief",
            window_days=7,
            as_of_date=as_of,
        )
        is None
    )
    assert (
        get_window_snapshot(
            db,
            tenant_id=int(tenant.id),
            kind=BRAND_ANALYSIS_KIND,
            window_days=7,
            as_of_date=as_of,
            filter_fp="fp-b",
        )
        is not None
    )


def test_anchor_label_matches_customer_explainable_week() -> None:
    crawl = datetime(2026, 9, 22, 9, 0, 0)
    win = brand_compare_windows(crawl, "week")
    assert win["current_label"].endswith("2026-09-22")
    assert win["current_label"].startswith("2026-09-16")
    assert "2026-09-24" not in win["current_label"]


def test_brand_analysis_freeze_waits_for_latest_batch_and_records_task_id(db) -> None:
    suffix = uuid.uuid4().hex[:8]
    tenant = Tenant(name="ba-ready", code=f"BAR{suffix}", status=True)
    db.add(tenant)
    db.flush()
    task_id = f"brand-ready-{suffix}"
    task = GeoMonitorTask(
        task_id=task_id,
        tenant_id=int(tenant.id),
        monitor_keywords="brand",
        status="processing",
        total_items=2,
        completed_items=1,
        failed_items=0,
        prompts_json=["p1", "p2"],
        platforms_json=[{"platform": "doubao"}],
        purpose="brand_word",
        raw_request_json={},
        raw_response_json={},
        created_at=datetime(2026, 10, 5, 9, 0, 0),
    )
    db.add(task)
    db.flush()
    first = GeoMonitorSubtask(
        subtask_id=f"sub-ready-1-{suffix}",
        task_id=task_id,
        platform="doubao",
        mode="standard",
        prompt="p1",
        status="completed",
        answer_content="answer 1",
        raw_result_json=dict(PARSED_RAW),
    )
    second = GeoMonitorSubtask(
        subtask_id=f"sub-ready-2-{suffix}",
        task_id=task_id,
        platform="doubao",
        mode="standard",
        prompt="p2",
        status="processing",
        raw_result_json={},
    )
    db.add_all([first, second])
    db.flush()

    assert not _try_freeze_brand_analysis_snapshot(
        db,
        tenant_id=int(tenant.id),
        grain="week",
        as_of=date(2026, 10, 5),
        filter_fp="ready-fp",
        data={"sample_count": 1},
        parse_meta={"pending_left": 0, "description_pending_left": 0},
    )

    task.status = "completed"
    db.flush()

    assert not _try_freeze_brand_analysis_snapshot(
        db,
        tenant_id=int(tenant.id),
        grain="week",
        as_of=date(2026, 10, 5),
        filter_fp="ready-fp",
        data={"sample_count": 1},
        parse_meta={"pending_left": 0, "description_pending_left": 0},
    )

    second.status = "completed"
    second.answer_content = "answer 2"
    task.completed_items = 2
    db.flush()

    assert not _try_freeze_brand_analysis_snapshot(
        db,
        tenant_id=int(tenant.id),
        grain="week",
        as_of=date(2026, 10, 5),
        filter_fp="ready-fp",
        data={"sample_count": 2},
        parse_meta={"pending_left": 0, "description_pending_left": 0},
    )

    second.raw_result_json = dict(PARSED_RAW)
    db.flush()

    assert _try_freeze_brand_analysis_snapshot(
        db,
        tenant_id=int(tenant.id),
        grain="week",
        as_of=date(2026, 10, 5),
        filter_fp="ready-fp",
        data={"sample_count": 2},
        parse_meta={"pending_left": 0, "description_pending_left": 0},
    )
    snap = get_window_snapshot(
        db,
        tenant_id=int(tenant.id),
        kind=BRAND_ANALYSIS_KIND,
        window_days=7,
        as_of_date=date(2026, 10, 5),
        filter_fp="ready-fp",
    )
    assert snap is not None
    assert snap["source_task_id"] == task_id
    assert snap["source_task_total_items"] == 2


def test_brand_analysis_freeze_waits_for_every_task_in_schedule_batch(db) -> None:
    suffix = uuid.uuid4().hex[:8]
    tenant = Tenant(name="ba-batch", code=f"BAB{suffix}", status=True)
    db.add(tenant)
    db.flush()
    created_at = datetime(2026, 10, 5, 9, 0, 0)
    tasks = []
    for index, status in enumerate(("processing", "completed"), start=1):
        task_id = f"brand-batch-{index}-{suffix}"
        task = GeoMonitorTask(
            task_id=task_id,
            tenant_id=int(tenant.id),
            monitor_keywords=f"brand-{index}",
            status=status,
            total_items=1,
            completed_items=1 if status == "completed" else 0,
            failed_items=0,
            prompts_json=[f"p{index}"],
            platforms_json=[{"platform": "doubao"}],
            purpose="brand_word",
            raw_request_json={},
            raw_response_json={},
            created_at=created_at + timedelta(seconds=index),
        )
        db.add(task)
        db.flush()
        db.add(
            GeoMonitorScheduleRun(
                tenant_id=int(tenant.id),
                schedule_key=f"bw20261005-0900-kw{index}",
                task_id=task_id,
                status="submitted",
                prompt_count=1,
                platform_count=1,
            )
        )
        db.add(
            GeoMonitorSubtask(
                subtask_id=f"brand-batch-sub-{index}-{suffix}",
                task_id=task_id,
                platform="doubao",
                mode="standard",
                prompt=f"p{index}",
                status=status,
                answer_content="answer" if status == "completed" else None,
                raw_result_json=dict(PARSED_RAW),
            )
        )
        tasks.append(task)
    db.flush()

    assert not _try_freeze_brand_analysis_snapshot(
        db,
        tenant_id=int(tenant.id),
        grain="week",
        as_of=date(2026, 10, 5),
        filter_fp="batch-fp",
        data={"sample_count": 1},
        parse_meta={"pending_left": 0, "description_pending_left": 0},
    )

    tasks[0].status = "completed"
    tasks[0].completed_items = 1
    tasks[0].subtasks[0].status = "completed"
    tasks[0].subtasks[0].answer_content = "answer"
    db.flush()

    assert _try_freeze_brand_analysis_snapshot(
        db,
        tenant_id=int(tenant.id),
        grain="week",
        as_of=date(2026, 10, 5),
        filter_fp="batch-fp",
        data={"sample_count": 2},
        parse_meta={"pending_left": 0, "description_pending_left": 0},
    )
    snap = get_window_snapshot(
        db,
        tenant_id=int(tenant.id),
        kind=BRAND_ANALYSIS_KIND,
        window_days=7,
        as_of_date=date(2026, 10, 5),
        filter_fp="batch-fp",
    )
    assert snap is not None
    assert snap["source_batch_key"] == "bw20261005-0900"
    assert set(snap["source_task_ids"]) == {task.task_id for task in tasks}


def test_brand_analysis_uses_previous_complete_batch_until_new_batch_finishes(db) -> None:
    suffix = uuid.uuid4().hex[:8]
    tenant = Tenant(name="ba-stable", code=f"BAS{suffix}", status=True)
    db.add(tenant)
    db.flush()

    old_task_id = f"brand-old-{suffix}"
    old_created_at = datetime(2026, 10, 5, 9, 0)
    old_task = GeoMonitorTask(
        task_id=old_task_id,
        tenant_id=int(tenant.id),
        monitor_keywords="old",
        status="completed",
        total_items=1,
        completed_items=1,
        failed_items=0,
        prompts_json=["p-old"],
        platforms_json=[{"platform": "doubao"}],
        purpose="brand_word",
        raw_request_json={},
        raw_response_json={},
        created_at=old_created_at,
    )
    db.add(old_task)
    db.flush()
    db.add_all(
        [
            GeoMonitorScheduleRun(
                tenant_id=int(tenant.id),
                schedule_key="bw20261005-0900-kw1",
                task_id=old_task_id,
                status="submitted",
                prompt_count=1,
                platform_count=1,
            ),
            GeoMonitorSubtask(
                subtask_id=f"old-sub-{suffix}",
                task_id=old_task_id,
                platform="doubao",
                mode="standard",
                prompt="p-old",
                status="completed",
                answer_content="old answer",
                raw_result_json=dict(PARSED_RAW),
            ),
        ]
    )

    new_task_id = f"brand-new-{suffix}"
    new_task = GeoMonitorTask(
        task_id=new_task_id,
        tenant_id=int(tenant.id),
        monitor_keywords="new",
        status="processing",
        total_items=1,
        completed_items=0,
        failed_items=0,
        prompts_json=["p-new"],
        platforms_json=[{"platform": "doubao"}],
        purpose="brand_word",
        raw_request_json={},
        raw_response_json={},
        created_at=datetime(2026, 10, 12, 9, 0),
    )
    db.add(new_task)
    db.flush()
    db.add_all(
        [
            GeoMonitorScheduleRun(
                tenant_id=int(tenant.id),
                schedule_key="bw20261012-0900-kw1",
                task_id=new_task_id,
                status="submitted",
                prompt_count=1,
                platform_count=1,
            ),
            GeoMonitorScheduleRun(
                tenant_id=int(tenant.id),
                schedule_key="bw20261012-0900-kw2",
                status="pending",
                prompt_count=0,
                platform_count=0,
            ),
            GeoMonitorSubtask(
                subtask_id=f"new-sub-{suffix}",
                task_id=new_task_id,
                platform="doubao",
                mode="standard",
                prompt="p-new",
                status="processing",
                raw_result_json=dict(PARSED_RAW),
            ),
        ]
    )
    db.flush()

    source = _brand_analysis_freeze_source(db, int(tenant.id))
    assert source is not None
    assert source["source_batch_key"] == "bw20261005-0900"
    assert source["source_is_latest_batch"] is False
    assert resolve_brand_analysis_anchor(db, int(tenant.id)) == old_created_at


def test_brand_analysis_load_excludes_auto_retry_children(db) -> None:
    suffix = uuid.uuid4().hex[:8]
    tenant = Tenant(name="ba-retry", code=f"BAU{suffix}", status=True)
    db.add(tenant)
    db.flush()
    now = datetime.now()
    origin_id = f"brand-origin-{suffix}"
    retry_id = f"brand-retry-{suffix}"
    for task_id, raw in (
        (origin_id, {}),
        (retry_id, {"_geo_auto_retry": {"of_task_id": origin_id}}),
    ):
        db.add(
            GeoMonitorTask(
                task_id=task_id,
                tenant_id=int(tenant.id),
                monitor_keywords="brand",
                status="completed",
                total_items=1,
                completed_items=1,
                failed_items=0,
                prompts_json=["p"],
                platforms_json=[{"platform": "doubao"}],
                purpose="brand_word",
                raw_request_json=raw,
                raw_response_json={},
                created_at=now,
            )
        )
        db.flush()
        db.add(
            GeoMonitorSubtask(
                subtask_id=f"{task_id}-sub",
                task_id=task_id,
                platform="doubao",
                mode="standard",
                prompt="p",
                status="completed",
                answer_content="answer",
                raw_result_json=dict(PARSED_RAW),
            )
        )
    db.flush()

    rows = _load_brand_word_subtasks(
        db,
        tenant_id=int(tenant.id),
        lookback_start=now - timedelta(days=1),
        range_end=now + timedelta(days=1),
        limit=20,
    )
    assert [row.task_id for row in rows] == [origin_id]


def test_brand_analysis_same_day_new_batch_replaces_snapshot(db) -> None:
    suffix = uuid.uuid4().hex[:8]
    tenant = Tenant(name="ba-rerun", code=f"BAO{suffix}", status=True)
    db.add(tenant)
    db.flush()
    as_of = date(2026, 10, 5)

    def add_batch(batch_key: str, task_id: str, created_at: datetime) -> None:
        db.add(
            GeoMonitorTask(
                task_id=task_id,
                tenant_id=int(tenant.id),
                monitor_keywords="brand",
                status="completed",
                total_items=1,
                completed_items=1,
                failed_items=0,
                prompts_json=["p"],
                platforms_json=[{"platform": "doubao"}],
                purpose="brand_word",
                raw_request_json={},
                raw_response_json={},
                created_at=created_at,
            )
        )
        db.flush()
        db.add_all(
            [
                GeoMonitorScheduleRun(
                    tenant_id=int(tenant.id),
                    schedule_key=f"{batch_key}-kw1",
                    task_id=task_id,
                    status="submitted",
                    prompt_count=1,
                    platform_count=1,
                ),
                GeoMonitorSubtask(
                    subtask_id=f"{task_id}-sub",
                    task_id=task_id,
                    platform="doubao",
                    mode="standard",
                    prompt="p",
                    status="completed",
                    answer_content="answer",
                    raw_result_json=dict(PARSED_RAW),
                ),
            ]
        )
        db.flush()

    first_task_id = f"brand-first-{suffix}"
    add_batch("bwonce-20261005090000", first_task_id, datetime(2026, 10, 5, 9, 0))
    assert _try_freeze_brand_analysis_snapshot(
        db,
        tenant_id=int(tenant.id),
        grain="week",
        as_of=as_of,
        filter_fp="rerun-fp",
        data={"sample_count": 1, "version": 1},
        parse_meta={"pending_left": 0, "description_pending_left": 0},
    )

    second_task_id = f"brand-second-{suffix}"
    add_batch("bwonce-20261005150000", second_task_id, datetime(2026, 10, 5, 15, 0))
    assert _try_freeze_brand_analysis_snapshot(
        db,
        tenant_id=int(tenant.id),
        grain="week",
        as_of=as_of,
        filter_fp="rerun-fp",
        data={"sample_count": 2, "version": 2},
        parse_meta={"pending_left": 0, "description_pending_left": 0},
    )
    snap = get_window_snapshot(
        db,
        tenant_id=int(tenant.id),
        kind=BRAND_ANALYSIS_KIND,
        window_days=7,
        as_of_date=as_of,
        filter_fp="rerun-fp",
    )
    assert snap is not None
    assert snap["version"] == 2
    assert snap["source_task_id"] == second_task_id


def test_refresh_brand_analysis_freeze_rewrites_same_day_snapshot(db) -> None:
    suffix = uuid.uuid4().hex[:8]
    tenant = Tenant(name="ba-refresh", code=f"BAU{suffix}", status=True)
    db.add(tenant)
    db.flush()
    created_at = datetime(2026, 10, 19, 9, 0, 0)
    task_id = f"brand-refresh-{suffix}"
    task = GeoMonitorTask(
        task_id=task_id,
        tenant_id=int(tenant.id),
        monitor_keywords="载望升学",
        status="completed",
        total_items=1,
        completed_items=1,
        failed_items=0,
        prompts_json=["载望规划师培训靠谱吗?"],
        platforms_json=[{"platform": "doubao", "mode": "reasoning_search"}],
        purpose="brand_word",
        raw_request_json={},
        raw_response_json={},
        created_at=created_at,
    )
    db.add(task)
    db.flush()
    db.add(
        GeoMonitorSubtask(
            subtask_id=f"brand-refresh-sub-{suffix}",
            task_id=task_id,
            platform="doubao",
            mode="reasoning_search",
            prompt="载望规划师培训靠谱吗?",
            status="completed",
            answer_content="补录后的新回答，投诉风险很高",
            sentiment="negative",
            raw_result_json={
                **PARSED_RAW,
                "_ba_sentiment": "negative",
                "_ba_description": "补录后描述",
                "_ba_descriptions": ["补录后描述"],
            },
        )
    )
    db.flush()
    as_of = date(2026, 10, 19)
    upsert_window_snapshot(
        db,
        tenant_id=int(tenant.id),
        kind=BRAND_ANALYSIS_KIND,
        window_days=7,
        payload={"sample_count": 1, "version": "stale", "source_batch_key": f"task:{task_id}"},
        as_of_date=as_of,
        filter_fp="default",
    )
    from app.services.brand_analysis_service import refresh_brand_analysis_freeze

    outcome = refresh_brand_analysis_freeze(db, int(tenant.id))
    assert outcome["released"] >= 1
    assert "week" in outcome["frozen"]
    snap = get_window_snapshot(
        db,
        tenant_id=int(tenant.id),
        kind=BRAND_ANALYSIS_KIND,
        window_days=7,
        as_of_date=as_of,
        filter_fp="default",
    )
    assert snap is not None
    assert snap.get("version") != "stale"
    assert snap.get("frozen") is True
    descriptions = " ".join(str(row.get("description") or "") for row in snap.get("ai_descriptions") or [])
    assert "补录后描述" in descriptions
