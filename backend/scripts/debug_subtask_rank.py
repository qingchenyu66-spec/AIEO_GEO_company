"""Debug rank resolution for a tenant/platform/prompt snapshot."""
from __future__ import annotations

import sys

from sqlalchemy import select, create_engine
from sqlalchemy.orm import sessionmaker

sys.stdout.reconfigure(encoding="utf-8")

from app.core.config import settings
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.services.brand_service import get_brand_asset, keyword_group_to_dict, list_keyword_groups, _is_industry_monitor_keyword
from app.services.monitor_service import (
    _find_brand_in_rankings,
    _resolve_brand_rank_detail,
    _ranking_match_terms,
    _subtask_answer_plaintext,
)
from app.services.ranking_parser import parse_answer_rankings


def main() -> None:
    tenant_id = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    platform = sys.argv[2] if len(sys.argv) > 2 else "yuanbao"
    prompt_like = sys.argv[3] if len(sys.argv) > 3 else "公交"
    rank_filter = int(sys.argv[4]) if len(sys.argv) > 4 else 13

    engine = create_engine(
        f"mysql+pymysql://{settings.database_user}:{settings.database_password}"
        f"@{settings.database_host}:{settings.database_port}/{settings.database_name}"
    )
    db = sessionmaker(bind=engine)()
    asset = get_brand_asset(db, tenant_id)
    groups = [keyword_group_to_dict(g) for g in list_keyword_groups(db, tenant_id)]
    terms = _ranking_match_terms(asset, groups)

    rows = db.execute(
        select(GeoMonitorSubtask, GeoMonitorTask)
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .where(
            GeoMonitorTask.tenant_id == tenant_id,
            GeoMonitorSubtask.platform == platform,
            GeoMonitorSubtask.prompt.like(f"%{prompt_like}%"),
            GeoMonitorSubtask.status == "completed",
        )
        .order_by(GeoMonitorSubtask.updated_at.desc())
    ).all()

    for subtask, task in rows:
        if subtask.mention_position != rank_filter:
            continue
        text = _subtask_answer_plaintext(subtask)
        parsed = parse_answer_rankings(text)
        list_rank, in_list = _find_brand_in_rankings(
            subtask, terms, asset, monitor_keywords=task.monitor_keywords,
        )
        detail = _resolve_brand_rank_detail(subtask, task.monitor_keywords, terms, asset)
        mk = task.monitor_keywords
        is_industry = asset is not None and _is_industry_monitor_keyword(str(mk or ""), asset)
        hits = [e for e in parsed if "艾迪亚" in str(e.get("name") or "")]
        print("subtask_id", subtask.subtask_id)
        print("updated_at", subtask.updated_at)
        print("prompt", subtask.prompt)
        print("monitor_keywords", mk)
        print("is_industry_task", is_industry)
        print("db_rank", subtask.mention_position)
        print("detail", detail)
        print("list_rank", list_rank, "in_list", in_list)
        print("parsed_hits", hits[:8])
        print("rank_resolution", (subtask.raw_result_json or {}).get("rank_resolution"))
        print("--- answer excerpt ---")
        for line in text.splitlines()[:40]:
            if line.strip():
                print(line[:120])
        break
    else:
        print("no match")


if __name__ == "__main__":
    main()
