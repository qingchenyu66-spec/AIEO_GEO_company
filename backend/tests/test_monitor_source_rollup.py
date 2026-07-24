"""信源日级物化：合并与冷读路径。"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.brand import BrandAsset
from app.models.lead_diagnosis import LeadDiagnosisRun
from app.models.monitor import (
    GeoMonitorDailyStat,
    GeoMonitorScheduleRun,
    GeoMonitorSourceDaily,
    GeoMonitorSubtask,
    GeoMonitorTask,
)
from app.services.monitor_source_rollup_service import (
    _merge_url_maps,
    build_customer_source_stats_from_daily,
    rebuild_source_daily_for_day,
)


def _brand_asset(tenant_id: int) -> BrandAsset:
    return BrandAsset(
        tenant_id=tenant_id,
        company_full_name="艾迪亚控股集团有限公司",
        brand_name="艾迪亚",
        brand_short_name="艾迪亚",
        monitor_keywords_json=["艾迪亚"],
        aliases_json=[],
        product_keywords_json=[],
        monitored_platforms_json=["kimi"],
        region_codes_json=[],
        schedule_times_json=[],
        schedule_weekdays_json=[],
        schedule_month_days_json=[],
        status=True,
        deleted=False,
    )


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            GeoMonitorTask.__table__,
            GeoMonitorSubtask.__table__,
            GeoMonitorDailyStat.__table__,
            GeoMonitorSourceDaily.__table__,
            GeoMonitorScheduleRun.__table__,
            LeadDiagnosisRun.__table__,
            BrandAsset.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_merge_url_maps_sums_counts_and_unions_lists() -> None:
    merged = _merge_url_maps(
        [
            {
                "https://a.example/x": {
                    "title": "A",
                    "url": "https://a.example/x",
                    "site": "站A",
                    "count": 2,
                    "platforms": ["kimi"],
                    "exposure_terms": ["艾迪亚"],
                    "questions": ["q1"],
                    "latest_time": "2026-07-10T23:59:59",
                }
            },
            {
                "https://a.example/x": {
                    "title": "A",
                    "url": "https://a.example/x",
                    "site": "",
                    "count": 3,
                    "platforms": ["doubao"],
                    "exposure_terms": ["艾迪亚"],
                    "questions": ["q2"],
                    "latest_time": "2026-07-12T23:59:59",
                }
            },
        ]
    )
    row = merged["https://a.example/x"]
    assert row["count"] == 5
    assert row["platforms"] == ["kimi", "doubao"]
    assert row["questions"] == ["q1", "q2"]
    assert row["latest_time"] == "2026-07-12T23:59:59"


def test_rebuild_source_daily_and_bundle_reads_rollup(db_session) -> None:
    tenant_id = 6
    day = date(2026, 7, 12)
    db_session.add(_brand_asset(tenant_id))
    db_session.add(
        GeoMonitorTask(
            task_id="src-roll-1",
            tenant_id=tenant_id,
            status="completed",
            total_items=1,
            completed_items=1,
            failed_items=0,
            prompts_json=["电梯广告推荐"],
            platforms_json=[{"platform": "kimi"}],
            raw_request_json={},
            raw_response_json={},
            created_at=datetime(2026, 7, 12, 10, 0, 0),
        )
    )
    db_session.add(
        GeoMonitorSubtask(
            subtask_id="src-roll-1-1",
            task_id="src-roll-1",
            platform="kimi",
            mode="standard",
            prompt="电梯广告推荐",
            status="completed",
            reference_list_json=[
                {
                    "title": "艾迪亚传媒案例",
                    "url": "https://brand.example.com/case",
                    "site": "brand",
                },
                {
                    "title": "行业报告",
                    "url": "https://example.com/ads-report",
                    "site": "example",
                },
            ],
            raw_result_json={},
            updated_at=datetime(2026, 7, 12, 12, 0, 0),
        )
    )
    db_session.add(
        GeoMonitorDailyStat(
            tenant_id=tenant_id,
            stat_date=day,
            platform="kimi",
            completed_count=1,
            mentioned_count=1,
            top3_count=1,
            rank_sum=1,
            rank_count=1,
            citation_count=2,
        )
    )
    db_session.commit()

    purchased = {"kimi"}
    exposure = ["艾迪亚"]
    rebuild_source_daily_for_day(
        db_session,
        tenant_id=tenant_id,
        stat_date=day,
        purchased_platforms=purchased,
        exposure_terms=exposure,
        config_fp="seed",
    )
    db_session.commit()

    row = db_session.query(GeoMonitorSourceDaily).one()
    assert row.daily_branded_count == 1
    assert "https://brand.example.com/case" in row.branded_json
    assert "https://example.com/ads-report" in row.all_json
    assert "https://example.com/ads-report" not in row.branded_json

    with patch(
        "app.services.monitor_service.customer_display_cutoff",
        return_value=datetime(2026, 7, 13, 0, 0, 0),
    ):
        bundle = build_customer_source_stats_from_daily(
            db_session,
            tenant_id,
            purchased_platforms=purchased,
            exposure_terms=exposure,
        )

    assert len(bundle["source_stats"]) == 1
    assert bundle["source_stats"][0]["url"] == "https://brand.example.com/case"
    assert len(bundle["source_stats_all"]) == 2
    assert any(int(p.get("value") or 0) == 1 for p in bundle["source_citation_trend"]["points"])


def test_backfill_when_no_candidate_days(db_session) -> None:
    tenant_id = 7
    db_session.add(_brand_asset(tenant_id))
    db_session.add(
        GeoMonitorTask(
            task_id="src-roll-2",
            tenant_id=tenant_id,
            status="completed",
            total_items=1,
            completed_items=1,
            failed_items=0,
            prompts_json=["q"],
            platforms_json=[{"platform": "kimi"}],
            raw_request_json={},
            raw_response_json={},
            created_at=datetime(2026, 7, 11, 9, 0, 0),
        )
    )
    db_session.add(
        GeoMonitorSubtask(
            subtask_id="src-roll-2-1",
            task_id="src-roll-2",
            platform="kimi",
            mode="standard",
            prompt="q",
            status="completed",
            reference_list_json=[
                {"title": "艾迪亚官网", "url": "https://aidiya.example/", "site": "aidiya"},
            ],
            raw_result_json={},
            updated_at=datetime(2026, 7, 11, 10, 0, 0),
        )
    )
    db_session.commit()

    with patch(
        "app.services.monitor_service.customer_display_cutoff",
        return_value=datetime(2026, 7, 13, 0, 0, 0),
    ):
        bundle = build_customer_source_stats_from_daily(
            db_session,
            tenant_id,
            purchased_platforms={"kimi"},
            exposure_terms=["艾迪亚"],
        )

    assert len(bundle["source_stats"]) == 1
    assert db_session.query(GeoMonitorSourceDaily).count() == 1
