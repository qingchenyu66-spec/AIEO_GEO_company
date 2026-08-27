"""矩阵异步 job：同条件 job_id 稳定、入队复用。"""

import time
from unittest.mock import patch

from app.services.ranking_matrix_job_service import (
    enqueue_or_reuse_matrix_job,
    matrix_job_id_for_cache_key,
)


def test_matrix_job_id_stable_for_same_cache_key():
    key = "monitor:ranking-matrix:v2:CUSTOMER:1:all:2026-08-01:2026-08-20"
    assert matrix_job_id_for_cache_key(key) == matrix_job_id_for_cache_key(key)
    assert matrix_job_id_for_cache_key(key).startswith("mx-")


def test_enqueue_reuses_inflight_job():
    cache_key = "monitor:ranking-matrix:v2:test:reuse"
    params = {"identity_id": 1, "tenant_id": 1, "limit_rows": 120}
    with patch(
        "app.services.ranking_matrix_job_service.read_matrix_job",
        return_value={
            "status": "processing",
            "cache_key": cache_key,
            "updated_at": int(time.time()),
        },
    ), patch(
        "app.services.ranking_matrix_job_service.mark_matrix_job",
    ) as mark_fn, patch(
        "app.tasks.monitor.build_ranking_matrix_job_task",
    ):
        out = enqueue_or_reuse_matrix_job(cache_key, params)
    assert out["matrix_status"] == "processing"
    assert out["job_id"] == matrix_job_id_for_cache_key(cache_key)
    mark_fn.assert_not_called()


def test_enqueue_requeues_stale_processing_job():
    cache_key = "monitor:ranking-matrix:v2:test:stale"
    params = {"identity_id": 1, "tenant_id": 1, "limit_rows": 120}
    stale_meta = {
        "status": "processing",
        "cache_key": cache_key,
        "updated_at": int(time.time()) - 200,
    }
    with patch(
        "app.services.ranking_matrix_job_service.read_matrix_job",
        return_value=stale_meta,
    ), patch(
        "app.services.ranking_matrix_job_service.mark_matrix_job",
    ) as mark_fn, patch(
        "app.tasks.monitor.build_ranking_matrix_job_task",
    ) as task_fn:
        out = enqueue_or_reuse_matrix_job(cache_key, params)
    assert out["matrix_status"] == "processing"
    mark_fn.assert_called()
    task_fn.apply_async.assert_called_once()


def test_resolve_sync_fallback_when_enqueue_failed():
    from app.services.ranking_matrix_job_service import resolve_ranking_matrix_response

    cache_key = "monitor:ranking-matrix:v2:test:fallback"
    with patch(
        "app.services.ranking_matrix_job_service.redis_enabled",
        return_value=True,
    ), patch(
        "app.services.ranking_matrix_job_service.settings.celery_enabled",
        True,
    ), patch(
        "app.services.ranking_matrix_job_service.get_json_cache",
        return_value=None,
    ), patch(
        "app.services.ranking_matrix_job_service.enqueue_or_reuse_matrix_job",
        return_value={"matrix_status": "failed", "error": "broker down"},
    ), patch(
        "app.services.ranking_matrix_job_service._sync_build_matrix_response",
        return_value={"matrix_status": "ready", "rows": []},
    ) as sync_fn:
        out = resolve_ranking_matrix_response(
            cache_key=cache_key,
            builder=lambda: {"rows": []},
            build_params={"identity_id": 1},
            prefer_async=True,
        )
    assert out["matrix_status"] == "ready"
    sync_fn.assert_called_once()
