"""报告重算异步任务。"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from app.services import report_refresh_job_service as svc


def test_refresh_job_ready(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(svc, "_JOB_DIR", tmp_path)
    monkeypatch.setattr(svc, "_jobs", {})
    monkeypatch.setattr(svc, "_active_by_report", {})
    monkeypatch.setattr(svc, "get_json_cache", lambda key: None)
    monkeypatch.setattr(svc, "set_json_cache", lambda *a, **k: None)
    monkeypatch.setattr(svc, "delete_cache", lambda *a, **k: None)
    monkeypatch.setattr(svc, "SessionLocal", lambda: MagicMock())

    with patch(
        "app.services.report_service.refresh_report_content",
        return_value={"id": 42, "report_title": "GEO 监测周报", "tenant_id": 7},
    ):
        job = svc.start_report_refresh_job(
            report_id=42,
            tenant_id=7,
            report_title="GEO 监测周报",
            owner_user_id=1,
        )
        assert job["status"] in {"queued", "running", "ready"}
        job_id = job["job_id"]

        for _ in range(50):
            meta = svc.get_report_refresh_job(job_id)
            assert meta is not None
            if meta["status"] == "ready":
                break
            if meta["status"] == "failed":
                raise AssertionError(meta.get("error"))
            time.sleep(0.05)
        else:
            raise AssertionError("job not ready")

    ready = svc.get_report_refresh_job(job_id)
    assert ready is not None
    assert ready["status"] == "ready"
    assert ready["result"]["id"] == 42
    assert (tmp_path / f"{job_id}.json").is_file()


def test_refresh_job_dedupes_active(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(svc, "_JOB_DIR", tmp_path)
    monkeypatch.setattr(svc, "_jobs", {})
    monkeypatch.setattr(svc, "_active_by_report", {})

    active = {
        "job_id": "job-a",
        "status": "running",
        "report_id": 9,
        "progress": "正在重新计算…",
    }
    monkeypatch.setattr(svc, "get_json_cache", lambda key: {"job_id": "job-a"} if "active" in key else active)
    monkeypatch.setattr(svc, "_load_meta", lambda job_id: active if job_id == "job-a" else None)

    job = svc.start_report_refresh_job(
        report_id=9,
        tenant_id=1,
        report_title="t",
        owner_user_id=1,
    )
    assert job["job_id"] == "job-a"
    assert job["status"] == "running"


def test_refresh_report_content_delegates_diagnosis():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from app.services.report_service import refresh_report_content

    report = SimpleNamespace(id=11, tenant_id=7, report_type="diagnosis", deleted=False)
    db = MagicMock()
    db.scalar.return_value = report
    with patch(
        "app.services.report_service.refresh_diagnosis_report_for_tenant",
        return_value={"id": 11},
    ) as refresh_diag:
        row = refresh_report_content(db, 11)
    assert row["id"] == 11
    refresh_diag.assert_called_once()
