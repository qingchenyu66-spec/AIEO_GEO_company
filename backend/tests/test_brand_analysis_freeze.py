"""品牌分析：抓取日锚定 + write-once 冻结。"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.models.tenant import Tenant
from app.services.brand_analysis_service import (
    _try_freeze_brand_analysis_snapshot,
    brand_analysis_filter_fp,
    brand_compare_windows,
)
from app.services.window_snapshot_service import (
    BRAND_ANALYSIS_KIND,
    get_window_snapshot,
    insert_window_snapshot_if_absent,
    invalidate_window_snapshots_for_tenant,
    upsert_window_snapshot,
)


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
        raw_result_json={},
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
