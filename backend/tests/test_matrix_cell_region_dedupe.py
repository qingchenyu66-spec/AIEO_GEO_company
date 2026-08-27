"""排名矩阵格子：同场次多地区应各保留一条快照。"""

from datetime import datetime

from app.services.monitor_service import _dedupe_matrix_cell_samples, _finalize_matrix_cell


def test_dedupe_matrix_cell_samples_keeps_each_region_per_window() -> None:
    samples = [
        {
            "schedule_window_key": "20260826-0930",
            "region_code": "350000",
            "region_label": "福建",
            "mention_position": 2,
            "_updated_at": datetime(2026, 8, 26, 9, 35),
            "subtask_id": "a",
            "status": "completed",
        },
        {
            "schedule_window_key": "20260826-0930",
            "region_code": "440000",
            "region_label": "广东",
            "mention_position": 3,
            "_updated_at": datetime(2026, 8, 26, 9, 36),
            "subtask_id": "b",
            "status": "completed",
        },
        {
            "schedule_window_key": "20260826-1430",
            "region_code": "350000",
            "region_label": "福建",
            "mention_position": 1,
            "_updated_at": datetime(2026, 8, 26, 14, 35),
            "subtask_id": "c",
            "status": "completed",
        },
    ]
    deduped = _dedupe_matrix_cell_samples(samples)
    assert len(deduped) == 3
    labels = {item["region_label"] for item in deduped}
    assert labels == {"福建", "广东"}


def test_dedupe_caps_by_schedule_round_not_flat_row_count() -> None:
    """3 场次 × 2 地区 = 6 条；勿被 schedule_frequency=3 截成 3。"""
    samples = []
    for slot, hour in (("0930", 9), ("1330", 13), ("1630", 16)):
        for region_code, label in (("350000", "福建"), ("440000", "广东")):
            samples.append(
                {
                    "schedule_window_key": f"20260825-{slot}",
                    "region_code": region_code,
                    "region_label": label,
                    "mention_position": 2,
                    "_updated_at": datetime(2026, 8, 25, hour, 35),
                    "subtask_id": f"{slot}-{region_code}",
                    "status": "completed",
                    "schedule_source": "run",
                }
            )
    deduped = _dedupe_matrix_cell_samples(samples, max_samples=3)
    assert len(deduped) == 6
    labels = {(item["schedule_window_key"], item["region_label"]) for item in deduped}
    assert labels == {
        ("20260825-0930", "福建"),
        ("20260825-0930", "广东"),
        ("20260825-1330", "福建"),
        ("20260825-1330", "广东"),
        ("20260825-1630", "福建"),
        ("20260825-1630", "广东"),
    }


def test_dedupe_drops_legacy_no_region_when_regional_exists() -> None:
    samples = [
        {
            "schedule_window_key": "20260825-1630",
            "region_code": "350000",
            "region_label": "福建",
            "mention_position": 2,
            "_updated_at": datetime(2026, 8, 25, 16, 40),
            "subtask_id": "reg-fj",
            "status": "completed",
        },
        {
            "schedule_window_key": "20260825-1630",
            "region_code": None,
            "region_label": "全部区域",
            "mention_position": 2,
            "_updated_at": datetime(2026, 8, 25, 16, 47),
            "subtask_id": "legacy-all",
            "status": "completed",
        },
    ]
    deduped = _dedupe_matrix_cell_samples(samples)
    assert len(deduped) == 1
    assert deduped[0]["subtask_id"] == "reg-fj"


def test_matrix_row_schedule_round_count_uses_distinct_windows_not_snapshot_rows() -> None:
    from app.services.monitor_service import _matrix_row_schedule_round_count

    cell = {
        "sample_count": 6,
        "rank_sample_count": 6,
        "snapshots": [
            {"schedule_window_key": "20260825-0930", "region_label": "福建"},
            {"schedule_window_key": "20260825-0930", "region_label": "广东"},
            {"schedule_window_key": "20260825-1330", "region_label": "福建"},
            {"schedule_window_key": "20260825-1330", "region_label": "广东"},
            {"schedule_window_key": "20260825-1630", "region_label": "福建"},
            {"schedule_window_key": "20260825-1630", "region_label": "广东"},
        ],
    }
    assert _matrix_row_schedule_round_count({"p1": cell}) == 3


def test_finalize_matrix_cell_snapshot_carries_region_label() -> None:
    cell = _finalize_matrix_cell([
        {
            "subtask_id": "x1",
            "mention_position": 2,
            "schedule_window_key": "20260826-0930",
            "region_code": "350000",
            "region_label": "福建",
            "status": "completed",
            "_updated_at": datetime(2026, 8, 26, 9, 35),
        },
    ])
    assert len(cell["snapshots"]) == 1
    assert cell["snapshots"][0]["region_label"] == "福建"
