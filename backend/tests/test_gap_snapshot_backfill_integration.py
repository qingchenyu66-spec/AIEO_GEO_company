"""Integration: 到期漏跑日缺口格 → gap-subtask API → 快照补录 → 日统计落业务日。"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.main import app
from app.models.brand import BrandAsset
from app.models.monitor import (
    GeoMonitorDailyStat,
    GeoMonitorScheduleRun,
    GeoMonitorSourceDaily,
    GeoMonitorSubtask,
    GeoMonitorTask,
)
from app.models.tenant import Tenant
from app.services.share_page_fetch_service import SharePageFetchResult

client = TestClient(app)

_DETECT_DAY = date(2026, 8, 2)
_WINDOW_KEY = "20260802-0935"
_PROMPT = "集成漏跑品牌怎么样"
_PLATFORM = "doubao"


def _platform_token() -> str:
    login = client.post("/api/v1/auth/login", json={"username": "demo", "password": "Geo@2026"})
    assert login.status_code == 200, login.text
    data = login.json()["data"]
    if data.get("requires_identity_selection"):
        platform_identity = next(item for item in data["identities"] if item["identity_type"] == "PLATFORM")
        selected = client.post(
            "/api/v1/auth/select-identity",
            json={"ticket": data["ticket"], "identity_id": platform_identity["id"]},
        )
        assert selected.status_code == 200, selected.text
        return selected.json()["data"]["access_token"]
    return data["session"]["access_token"]


@pytest.fixture()
def gap_tenant_id() -> int:
    """真实库临时企业：到期后漏跑日应出缺口格；用例结束清理。"""
    code = f"itest-gap-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        tenant = Tenant(
            name=f"集成漏跑-{code}",
            code=code,
            deleted=False,
            status=True,
            service_start_date=date(2026, 1, 1),
            service_end_date=date(2026, 8, 1),
        )
        db.add(tenant)
        db.flush()
        tenant_id = int(tenant.id)
        db.add(
            BrandAsset(
                tenant_id=tenant_id,
                company_full_name=f"{code}有限公司",
                brand_name="集成漏跑品牌",
                brand_short_name="集成漏跑",
                monitor_keywords_json=[_PROMPT],
                aliases_json=[],
                product_keywords_json=[],
                monitored_platforms_json=[_PLATFORM],
                region_codes_json=[],
                schedule_times_json=["09:35"],
                schedule_type="daily_times",
                schedule_frequency=1,
                schedule_weekdays_json=[],
                schedule_month_days_json=[],
                status=True,
                deleted=False,
            )
        )
        db.commit()
    yield tenant_id
    with SessionLocal() as db:
        task_ids = list(
            db.scalars(select(GeoMonitorTask.task_id).where(GeoMonitorTask.tenant_id == tenant_id))
        )
        if task_ids:
            db.execute(delete(GeoMonitorSubtask).where(GeoMonitorSubtask.task_id.in_(task_ids)))
            db.execute(delete(GeoMonitorTask).where(GeoMonitorTask.tenant_id == tenant_id))
        db.execute(delete(GeoMonitorScheduleRun).where(GeoMonitorScheduleRun.tenant_id == tenant_id))
        db.execute(delete(GeoMonitorDailyStat).where(GeoMonitorDailyStat.tenant_id == tenant_id))
        db.execute(delete(GeoMonitorSourceDaily).where(GeoMonitorSourceDaily.tenant_id == tenant_id))
        db.execute(delete(BrandAsset).where(BrandAsset.tenant_id == tenant_id))
        db.execute(delete(Tenant).where(Tenant.id == tenant_id))
        db.commit()


def test_gap_snapshot_backfill_api_writes_daily_stat_on_business_date(
    gap_tenant_id: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """矩阵缺口 → 占位子任务 → 补录（mock 分享页）→ 日统计写入 2026-08-02。"""
    monkeypatch.setattr(
        "app.api.v1.endpoints.monitor.require_snapshot_backfill_permission",
        lambda *_args, **_kwargs: None,
    )

    def _fake_fetch(url: str, **kwargs):
        return SharePageFetchResult(
            answer_content="1. 竞品A\n2. 集成漏跑品牌\n3. 竞品B",
            references=[{"index": 1, "url": "https://example.com/r", "title": "示例", "site": "example.com"}],
            title="fake",
            source_host="doubao.com",
        )

    monkeypatch.setattr("app.services.snapshot_backfill_service.fetch_share_page", _fake_fetch)
    monkeypatch.setattr(
        "app.services.snapshot_backfill_service.enqueue_backfill_screenshot",
        lambda **kwargs: "queued",
    )

    token = _platform_token()
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "tenant_id": gap_tenant_id,
        "date_from": _DETECT_DAY.isoformat(),
        "date_to": _DETECT_DAY.isoformat(),
    }

    matrix_resp = client.get("/api/v1/monitor/snapshot-backfill/matrix", headers=headers, params=params)
    assert matrix_resp.status_code == 200, matrix_resp.text
    matrix = matrix_resp.json()["data"]
    gap_cells = [cell for cell in matrix.get("cells") or [] if int(cell.get("gap_count") or 0) > 0]
    assert gap_cells, matrix
    gap_slot = next(
        slot
        for cell in gap_cells
        for slot in cell.get("slots") or []
        if slot.get("is_gap") and slot.get("schedule_window_key") == _WINDOW_KEY
    )
    assert gap_slot.get("needs_backfill") is True

    gap_resp = client.post(
        "/api/v1/monitor/snapshot-backfill/gap-subtask",
        headers=headers,
        json={
            "tenant_id": gap_tenant_id,
            "platform": _PLATFORM,
            "prompt": _PROMPT,
            "schedule_window_key": _WINDOW_KEY,
        },
    )
    assert gap_resp.status_code == 200, gap_resp.text
    subtask_id = gap_resp.json()["data"]["subtask"]["subtask_id"]
    assert subtask_id.startswith("bfs")

    backfill_resp = client.post(
        f"/api/v1/monitor/subtasks/{subtask_id}/snapshot-backfill",
        headers=headers,
        json={
            "snapshot_url": "https://www.doubao.com/thread/integration-gap-backfill-test",
            "mention_position": 2,
        },
    )
    assert backfill_resp.status_code == 200, backfill_resp.text
    saved = backfill_resp.json()["data"]["subtask"]
    assert saved.get("mention_position") == 2
    assert saved.get("status") == "completed"

    with SessionLocal() as db:
        row = db.scalar(
            select(GeoMonitorDailyStat).where(
                GeoMonitorDailyStat.tenant_id == gap_tenant_id,
                GeoMonitorDailyStat.stat_date == _DETECT_DAY,
                GeoMonitorDailyStat.platform == _PLATFORM,
            )
        )
        assert row is not None, "补录后日统计应落在调度业务日 2026-08-02"
        assert row.completed_count >= 1
        assert row.mentioned_count >= 1
        assert row.rank_count >= 1

    # 缺口格应随补录消失（同参数重拉矩阵）
    matrix_after = client.get("/api/v1/monitor/snapshot-backfill/matrix", headers=headers, params=params)
    assert matrix_after.status_code == 200
    remaining_gaps = [
        cell
        for cell in matrix_after.json()["data"].get("cells") or []
        if int(cell.get("gap_count") or 0) > 0
        and cell.get("word") == _PROMPT
        and cell.get("platform") == _PLATFORM
        and cell.get("date") == _DETECT_DAY.isoformat()
    ]
    assert not remaining_gaps
