# -*- coding: utf-8 -*-
"""只读：门店卡切段规则（C+D）对现有位次的影响。

对比两层：
1. 旧 store_card 切段 vs 新 _store_guide_card_brand_rank（本规则本身）
2. 库内 mention_position vs 现行全文规则位次（落地后重算会动多少）

不写库。示例：
  python -m scripts.impact_store_card_rank_change --days 30
  python -m scripts.impact_store_card_rank_change --days 60 --tenant-id 6 --limit 200
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import or_, select

from app.core.database import SessionLocal
from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
from app.models.tenant import Tenant
from app.services.brand_service import get_brand_asset, keyword_group_to_dict, list_keyword_groups
from app.services.monitor_service import (
    _configured_exposure_term_in_text,
    _ranking_match_terms,
    _resolve_brand_rank_detail,
    _store_guide_card_brand_rank,
    _subtask_answer_plaintext,
    _task_brand_terms_for_rank,
)

sys.stdout.reconfigure(encoding="utf-8")

_PROMPT_STORE_RE = re.compile(r"门店|专卖店|板材店|建材店")
_LEGACY_ATTR_RE = re.compile(
    r"^(?:地址|位置|主营|适合|电话|主打|业务范围|本地优势|服务能力)\s*[:：]"
)
_LEGACY_SECTION_RE = re.compile(
    r"^(?:[✅📍📌🪵🛋️]|[一二三四五六七八九十]+[、.．]|#{1,4}\s+\S)"
)
_LEGACY_TIP_RE = re.compile(
    r"避坑|选购要点|总结与建议|如果需要|可以一次性对比|优先去|探店要点|选购板材|怎么逛"
)


def _legacy_is_attr(line: str) -> bool:
    plain = re.sub(r"\*\*", "", str(line or "")).strip()
    if not plain:
        return False
    if _LEGACY_ATTR_RE.match(plain):
        return True
    if plain.startswith("📍") and len(plain) <= 80:
        return True
    if re.match(r"^✅?\s*主营\s*[:：]", plain):
        return True
    return False


def _legacy_looks_title(line: str) -> bool:
    plain = re.sub(r"\*\*", "", str(line or "")).strip()
    if not plain or len(plain) > 48:
        return False
    if _LEGACY_ATTR_RE.match(plain):
        return False
    if _LEGACY_SECTION_RE.match(plain):
        return False
    if re.match(r"^\d{1,2}\s*[.、．)]\s*\S", plain):
        return False
    if _LEGACY_TIP_RE.search(plain):
        return False
    if re.search(
        r"(?:门店|市场|专卖店).{0,6}推荐|授权店[（(]|采购大市场|工厂\s*/\s*定制|买裸板|可配套加工",
        plain,
    ):
        return False
    if "对比" in plain or (plain.count("、") >= 2 and len(plain) > 24):
        return False
    if re.search(r"[。；;]$", plain) and len(plain) > 20:
        return False
    return True


def _legacy_store_guide_card_brand_rank(
    text: str,
    brand_terms: list[str],
    *,
    prompt: str | None = None,
) -> int | None:
    """改前切段：✅ 行当分区，✅亮点会把每张卡清掉。"""
    if not text or not brand_terms:
        return None
    prompt_text = str(prompt or "")
    body = str(text)
    store_prompt = bool(re.search(r"门店|专卖店|板材店|建材店", prompt_text))
    store_body = bool(
        re.search(r"[✅📍]", body)
        and (
            re.search(r"(?m)^(?:地址|位置|主营)\s*[:：]", body)
            or re.search(r"(?m)^📍\s*\S", body)
            or re.search(r"(?m)^✅?\s*主营\s*[:：]", body)
        )
    )
    if not store_prompt and not store_body:
        return None
    lines = [re.sub(r"\*\*", "", ln).strip() for ln in str(text).splitlines()]
    section_cards: list[str] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if not line:
            idx += 1
            continue
        if _legacy_is_attr(line):
            idx += 1
            continue
        if _LEGACY_TIP_RE.search(line) and (
            line.startswith(("✅", "📍", "📌", "⚠️")) or line.startswith("#") or len(line) < 40
        ):
            if section_cards:
                for rank, title in enumerate(section_cards, 1):
                    if _configured_exposure_term_in_text(title, brand_terms):
                        return rank
            break
        if _LEGACY_SECTION_RE.match(line) and not _legacy_is_attr(line):
            if section_cards:
                for rank, title in enumerate(section_cards, 1):
                    if _configured_exposure_term_in_text(title, brand_terms):
                        return rank
                section_cards = []
            idx += 1
            continue
        if not _legacy_looks_title(line):
            idx += 1
            continue
        first_follow = next((x for x in lines[idx + 1 :] if x), "")
        has_attr = bool(first_follow and _legacy_is_attr(first_follow))
        if not has_attr:
            idx += 1
            continue
        section_cards.append(line)
        nxt = idx + 1
        while nxt < len(lines):
            nxt_line = lines[nxt]
            if not nxt_line:
                nxt += 1
                continue
            if _legacy_is_attr(nxt_line):
                nxt += 1
                continue
            break
        idx = nxt
    if len(section_cards) >= 2:
        for rank, title in enumerate(section_cards, 1):
            if _configured_exposure_term_in_text(title, brand_terms):
                return rank
    elif len(section_cards) == 1 and _configured_exposure_term_in_text(
        section_cards[0], brand_terms
    ):
        return 1
    return None


def _is_manual_locked(subtask: GeoMonitorSubtask) -> bool:
    raw = subtask.raw_result_json if isinstance(subtask.raw_result_json, dict) else {}
    return bool(raw.get("manual_rank_locked") or raw.get("manual_snapshot"))


def _rank_pair(a, b) -> str:
    return f"{a}->{b}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--tenant-id", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0, help="0=不截断")
    parser.add_argument("--sample", type=int, default=25, help="打印变更样例条数")
    args = parser.parse_args()

    since = datetime.now() - timedelta(days=max(1, args.days))
    db = SessionLocal()
    try:
        stmt = (
            select(GeoMonitorSubtask, GeoMonitorTask, Tenant)
            .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
            .join(Tenant, Tenant.id == GeoMonitorTask.tenant_id)
            .where(
                GeoMonitorSubtask.status == "completed",
                GeoMonitorSubtask.updated_at >= since,
                GeoMonitorSubtask.answer_content.isnot(None),
                or_(
                    GeoMonitorSubtask.prompt.like("%门店%"),
                    GeoMonitorSubtask.prompt.like("%专卖店%"),
                    GeoMonitorSubtask.prompt.like("%板材店%"),
                    GeoMonitorSubtask.prompt.like("%建材店%"),
                    GeoMonitorSubtask.answer_content.like("%📍%"),
                ),
            )
            .order_by(GeoMonitorSubtask.updated_at.desc())
        )
        if args.tenant_id:
            stmt = stmt.where(GeoMonitorTask.tenant_id == args.tenant_id)
        rows = db.execute(stmt).all()
        if args.limit:
            rows = rows[: args.limit]

        terms_cache: dict[int, list[str]] = {}
        scanned = 0
        store_eligible = 0
        rule_changed = 0
        db_would_change = 0
        this_rule_moves_db = 0
        skipped_locked = 0
        skipped_no_terms = 0
        rule_pairs: Counter[str] = Counter()
        db_pairs: Counter[str] = Counter()
        rule_samples: list[dict] = []
        db_samples: list[dict] = []
        highlight_like = 0
        highlight_rule_changed = 0

        for subtask, task, tenant in rows:
            text = _subtask_answer_plaintext(subtask) or ""
            if len(text.strip()) < 40:
                continue
            prompt = str(subtask.prompt or "")
            store_like = bool(_PROMPT_STORE_RE.search(prompt)) or bool(
                re.search(r"(?m)^📍", text)
            )
            if not store_like:
                continue
            scanned += 1
            tenant_id = int(task.tenant_id or 0)
            if tenant_id not in terms_cache:
                terms_cache[tenant_id] = _task_brand_terms_for_rank(db, task)
                if not terms_cache[tenant_id]:
                    asset = get_brand_asset(db, tenant_id) if tenant_id else None
                    groups = (
                        [keyword_group_to_dict(g) for g in list_keyword_groups(db, tenant_id)]
                        if tenant_id
                        else []
                    )
                    terms_cache[tenant_id] = _ranking_match_terms(asset, groups)
            terms = terms_cache[tenant_id]
            if not terms:
                skipped_no_terms += 1
                continue

            old_card = _legacy_store_guide_card_brand_rank(text, terms, prompt=prompt)
            new_card = _store_guide_card_brand_rank(text, terms, prompt=prompt)
            if old_card is None and new_card is None:
                continue
            store_eligible += 1
            has_highlight = bool(re.search(r"(?m)^✅\s*(?:亮点|优势)", text))
            if has_highlight:
                highlight_like += 1

            if old_card != new_card:
                rule_changed += 1
                if has_highlight:
                    highlight_rule_changed += 1
                key = _rank_pair(old_card, new_card)
                rule_pairs[key] += 1
                if len(rule_samples) < args.sample:
                    rule_samples.append(
                        {
                            "tenant": tenant.name,
                            "platform": subtask.platform,
                            "prompt": prompt[:60],
                            "old_card": old_card,
                            "new_card": new_card,
                            "db": subtask.mention_position,
                            "subtask_id": subtask.subtask_id,
                            "highlight": has_highlight,
                        }
                    )

            if _is_manual_locked(subtask):
                skipped_locked += 1
                continue
            # 全文重算对照：只统计「本规则新旧不一致」或「现行卡规则命中」两类，避免混入历史 LLM 漂移
            if new_card is None and old_card is None:
                continue
            asset = get_brand_asset(db, tenant_id) if tenant_id else None
            detail = _resolve_brand_rank_detail(
                subtask, task.monitor_keywords, terms, asset
            )
            new_full = detail.rank
            db_rank = subtask.mention_position
            caused_by_this_rule = old_card != new_card
            if db_rank != new_full:
                db_would_change += 1
                db_pairs[_rank_pair(db_rank, new_full)] += 1
                if caused_by_this_rule:
                    this_rule_moves_db += 1
                if len(db_samples) < args.sample:
                    db_samples.append(
                        {
                            "tenant": tenant.name,
                            "platform": subtask.platform,
                            "prompt": prompt[:60],
                            "db": db_rank,
                            "new_full": new_full,
                            "basis": detail.rank_basis,
                            "old_card": old_card,
                            "new_card": new_card,
                            "this_rule": caused_by_this_rule,
                            "subtask_id": subtask.subtask_id,
                        }
                    )

        print(f"窗口 {args.days} 天, 扫描门店/📍题 {scanned} 条, 新旧卡规则至少命中一方 {store_eligible}")
        print(f"无品牌词跳过 {skipped_no_terms}, 人工锁跳过全文对照 {skipped_locked}")
        print("--- 本规则本身（旧切段 vs C+D）---")
        print(f"卡序变化 {rule_changed}/{store_eligible} ({(100 * rule_changed / store_eligible) if store_eligible else 0:.1f}%)")
        print(f"其中含 ✅亮点/优势 正文 {highlight_like} 条, 卡序变化 {highlight_rule_changed}")
        print("卡序变化分布:", dict(rule_pairs.most_common(20)))
        print("--- 落地后重算 vs 库内 mention_position（未锁）---")
        unlocked = store_eligible - skipped_locked
        print(
            f"会改库内位次 {db_would_change}/{max(unlocked, 0)}"
            f" ({(100 * db_would_change / unlocked) if unlocked else 0:.1f}%)"
        )
        print(f"其中由本规则新旧不一致直接带动 {this_rule_moves_db}")
        print("库内变化分布:", dict(db_pairs.most_common(20)))
        print("--- 卡序变化样例 ---")
        for row in rule_samples:
            print(row)
        print("--- 库内会变样例 ---")
        for row in db_samples:
            print(row)
    finally:
        db.close()


if __name__ == "__main__":
    main()
