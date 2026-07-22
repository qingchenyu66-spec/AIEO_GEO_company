"""Async export job: queue → ready → fingerprint reuse."""

from __future__ import annotations


def test_export_job_ready_and_fingerprint_cache(monkeypatch, tmp_path) -> None:
    from app.services import report_export_job_service as svc

    monkeypatch.setattr(svc, "_JOB_DIR", tmp_path)
    monkeypatch.setattr(svc, "_jobs", {})

    def fake_build(db, lead_id, export_format="pdf", current=None):
        return b"%PDF-fake%", f"lead-{lead_id}.pdf", "application/pdf"

    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.build_lead_diagnosis_export",
        fake_build,
    )
    monkeypatch.setattr(svc, "_lead_fingerprint", lambda db, lead_id, fmt, theme: f"fp-{lead_id}-{fmt}")

    job = svc.start_export_job(
        kind="lead_diagnosis",
        ref_id=99,
        export_format="pdf",
        owner_user_id=1,
    )
    assert job["status"] in {"queued", "running", "ready"}
    job_id = job["job_id"]

    for _ in range(50):
        meta = svc.get_export_job(job_id)
        assert meta is not None
        if meta["status"] == "ready":
            break
        if meta["status"] == "failed":
            raise AssertionError(meta.get("error"))
        import time

        time.sleep(0.05)
    else:
        raise AssertionError("job not ready")

    data, filename, mime = svc.read_export_job_file(job_id)
    assert data.startswith(b"%PDF")
    assert filename.endswith(".pdf")
    assert mime == "application/pdf"
    assert (tmp_path / f"fp-fp-99-pdf.json").is_file()

    # 清空内存，模拟 API 重启后仍能命中磁盘指纹
    monkeypatch.setattr(svc, "_jobs", {})
    reused = svc.start_export_job(
        kind="lead_diagnosis",
        ref_id=99,
        export_format="pdf",
        owner_user_id=1,
    )
    assert reused["status"] == "ready"
    assert reused.get("cached") is True


def test_load_meta_prefers_redis_over_stale_local(monkeypatch, tmp_path) -> None:
    """多 worker：本地仍是 running 时，应以 Redis ready 为准。"""
    from app.services import report_export_job_service as svc

    monkeypatch.setattr(svc, "_JOB_DIR", tmp_path)
    job_id = "job-stale-local"
    monkeypatch.setattr(
        svc,
        "_jobs",
        {job_id: {"job_id": job_id, "status": "running", "progress": "PDF渲染中…"}},
    )
    monkeypatch.setattr(
        svc,
        "get_json_cache",
        lambda key: {"job_id": job_id, "status": "ready", "filename": "a.pdf", "mime": "application/pdf"}
        if key == f"export_job:{job_id}"
        else None,
    )
    meta = svc._load_meta(job_id)
    assert meta is not None
    assert meta["status"] == "ready"
    assert svc._jobs[job_id]["status"] == "ready"


def test_pdf_from_slide_images_accepts_jpeg() -> None:
    from io import BytesIO

    from PIL import Image

    from app.services.report_molizhishu_pdf_service import pdf_from_slide_images

    buf = BytesIO()
    Image.new("RGB", (64, 36), (240, 240, 240)).save(buf, format="JPEG", quality=90)
    pdf = pdf_from_slide_images([buf.getvalue()])
    assert pdf.startswith(b"%PDF")
    assert len(pdf) < 50_000
