"""DeepSeek parsing pipeline for enterprise knowledge files."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.knowledge import KnowledgeFile
from app.services.brand_service import get_brand_asset
from app.services.deepseek_client import DeepseekApiError, DeepseekClient
from app.services.knowledge_service import STORAGE_ROOT, knowledge_file_to_dict
from app.services.knowledge_text_extractor import KnowledgeTextExtractError, extract_knowledge_text

logger = logging.getLogger(__name__)


def _resolve_file_path(record: KnowledgeFile) -> Path:
    return STORAGE_ROOT / record.storage_path


def _truncate_text(text: str) -> tuple[str, bool]:
    max_chars = max(1000, settings.deepseek_knowledge_parse_max_chars)
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def parse_knowledge_file(db: Session, file_id: int) -> KnowledgeFile:
    """Extract text locally and ask DeepSeek for structured knowledge insights."""
    record = db.scalar(
        select(KnowledgeFile).where(KnowledgeFile.id == file_id, KnowledgeFile.deleted.is_(False))
    )
    if record is None:
        raise ValueError("文件不存在")

    if not settings.deepseek_knowledge_parse_enabled:
        raise ValueError("未启用 DeepSeek 知识库解析")

    client = DeepseekClient()
    if not client.knowledge_enabled:
        raise ValueError("未配置 DEEPSEEK_API_KEY 或解析功能已关闭")

    record.parse_status = "parsing"
    record.parse_error = None
    db.commit()
    db.refresh(record)

    try:
        file_path = _resolve_file_path(record)
        if not file_path.exists():
            raise ValueError("文件不存在于存储目录")

        raw_text = extract_knowledge_text(file_path, record.file_ext)
        document_text, truncated = _truncate_text(raw_text)
        asset = get_brand_asset(db, record.tenant_id)
        brand_name = asset.brand_name if asset and asset.brand_name else "本品牌"
        company_name = asset.company_full_name if asset and asset.company_full_name else None

        parsed = client.parse_knowledge_document(
            brand_name=brand_name,
            company_name=company_name,
            file_name=record.original_name,
            document_text=document_text,
            truncated=truncated,
        )
        parsed["extracted_chars"] = len(raw_text)
        parsed["truncated"] = truncated

        record.parse_status = "parsed"
        record.parse_error = None
        record.parsed_at = datetime.now()
        record.parse_result_json = parsed
    except (KnowledgeTextExtractError, DeepseekApiError, ValueError) as exc:
        record.parse_status = "failed"
        record.parse_error = str(exc)[:500]
        record.parsed_at = None
        record.parse_result_json = None
        db.commit()
        db.refresh(record)
        logger.warning("knowledge parse failed, file_id=%s, error=%s", file_id, exc)
        raise ValueError(str(exc)) from exc
    except Exception as exc:
        record.parse_status = "failed"
        record.parse_error = "解析过程出现异常"[:500]
        record.parsed_at = None
        record.parse_result_json = None
        db.commit()
        db.refresh(record)
        logger.exception("knowledge parse unexpected error, file_id=%s", file_id)
        raise ValueError("解析过程出现异常") from exc

    db.commit()
    db.refresh(record)
    return record


def request_knowledge_parse(db: Session, file_id: int) -> KnowledgeFile:
    """Mark file as queued for parsing and return latest record."""
    record = db.scalar(
        select(KnowledgeFile).where(KnowledgeFile.id == file_id, KnowledgeFile.deleted.is_(False))
    )
    if record is None:
        raise ValueError("文件不存在")
    if record.parse_status == "parsing":
        # Allow re-queue if the previous attempt is already past the timeout window.
        timeout_min = max(1, settings.knowledge_parse_timeout_minutes)
        stale_before = datetime.now() - timedelta(minutes=timeout_min)
        if record.updated_at and record.updated_at > stale_before:
            return record
    record.parse_status = "parsing"
    record.parse_error = None
    db.commit()
    db.refresh(record)
    return record


def fail_stale_knowledge_parses(
    db: Session,
    *,
    timeout_minutes: int | None = None,
    limit: int = 100,
) -> dict[str, int]:
    """Mark stuck parsing rows as failed so the UI does not spin forever."""
    minutes = max(1, timeout_minutes or settings.knowledge_parse_timeout_minutes)
    cutoff = datetime.now() - timedelta(minutes=minutes)
    rows = list(
        db.scalars(
            select(KnowledgeFile)
            .where(
                KnowledgeFile.deleted.is_(False),
                KnowledgeFile.parse_status == "parsing",
                KnowledgeFile.updated_at < cutoff,
            )
            .order_by(KnowledgeFile.updated_at.asc())
            .limit(max(1, limit))
        )
    )
    for record in rows:
        record.parse_status = "failed"
        record.parse_error = f"解析超时（超过 {minutes} 分钟未完成），请重试"
        record.parsed_at = None
    if rows:
        db.commit()
    return {"checked": len(rows), "failed": len(rows)}


def schedule_knowledge_parse(db: Session, file_id: int) -> KnowledgeFile:
    """Queue or run DeepSeek parse for one knowledge file."""
    if not settings.deepseek_knowledge_parse_enabled:
        raise ValueError("未启用 DeepSeek 知识库解析")
    record = request_knowledge_parse(db, file_id)
    if settings.celery_enabled:
        from app.tasks.knowledge import parse_knowledge_file_task

        parse_knowledge_file_task.delay(file_id)
        return record
    return parse_knowledge_file(db, file_id)


def serialize_knowledge_file(record: KnowledgeFile) -> dict:
    payload = knowledge_file_to_dict(record)
    payload["parse_status"] = record.parse_status
    payload["parse_error"] = record.parse_error
    payload["parsed_at"] = record.parsed_at.isoformat() if record.parsed_at else None
    payload["parse_result"] = record.parse_result_json
    return payload
