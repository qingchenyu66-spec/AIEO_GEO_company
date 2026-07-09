"""Celery tasks for knowledge base parsing."""

from __future__ import annotations

import logging

from app.celery_app import celery_app
from app.core.database import SessionLocal
from app.services.knowledge_parse_service import parse_knowledge_file

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.knowledge.parse_knowledge_file_task", ignore_result=True)
def parse_knowledge_file_task(file_id: int) -> dict[str, str]:
    db = SessionLocal()
    try:
        parse_knowledge_file(db, file_id)
        return {"status": "ok", "file_id": str(file_id)}
    except ValueError as exc:
        logger.warning("knowledge celery parse failed, file_id=%s, error=%s", file_id, exc)
        return {"status": "failed", "file_id": str(file_id), "error": str(exc)}
    finally:
        db.close()


@celery_app.task(name="app.tasks.knowledge.fail_stale_knowledge_parses", ignore_result=True)
def fail_stale_knowledge_parses_task(timeout_minutes: int | None = None) -> dict[str, int]:
    from app.services.knowledge_parse_service import fail_stale_knowledge_parses

    db = SessionLocal()
    try:
        return fail_stale_knowledge_parses(db, timeout_minutes=timeout_minutes)
    finally:
        db.close()
