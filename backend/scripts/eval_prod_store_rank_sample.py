# -*- coding: utf-8 -*-
"""Offline evaluate local rank rules against exported prod store samples."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from types import SimpleNamespace

from app.services.monitor_service import (
    _numbered_list_brand_rank,
    _numbered_subheading_title_rank,
    _resolve_brand_rank_detail,
    _store_guide_card_brand_rank,
)
from scripts.impact_store_card_rank_change import _legacy_store_guide_card_brand_rank

sys.stdout.reconfigure(encoding="utf-8")


def _sub(item: dict) -> SimpleNamespace:
    return SimpleNamespace(
        prompt=item.get("prompt"),
        answer_content=item.get("answer"),
        mention_context=None,
        all_rankings_json=[],
        mention_position=item.get("db_rank"),
        raw_result_json={
            "manual_rank_locked": False,
            "source": "prod_offline",
        },
        platform=item.get("platform") or "doubao",
        status="completed",
        mode="standard",
        subtask_id=item.get("subtask_id"),
        task_id="offline",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--file",
        default="tmp_prod_store_rank_sample.json",
        help="exported json from scripts.export_store_rank_sample",
    )
    parser.add_argument("--sample", type=int, default=25)
    args = parser.parse_args()

    with open(args.file, encoding="utf-8") as f:
        payload = json.load(f)
    items = payload.get("items") or []

    scanned = 0
    card_eligible = 0
    card_changed = 0
    db_diff = 0
    locked_skip = 0
    no_terms = 0
    card_pairs: Counter[str] = Counter()
    db_pairs: Counter[str] = Counter()
    basis_when_db_diff: Counter[str] = Counter()
    card_samples: list[dict] = []
    db_samples: list[dict] = []
    confirmed_candidates: list[dict] = []

    for item in items:
        text = str(item.get("answer") or "")
        prompt = str(item.get("prompt") or "")
        terms = list(item.get("brand_terms") or [])
        if not terms:
            no_terms += 1
            continue
        scanned += 1
        old_card = _legacy_store_guide_card_brand_rank(text, terms, prompt=prompt)
        new_card = _store_guide_card_brand_rank(text, terms, prompt=prompt)
        if old_card is None and new_card is None:
            # still evaluate full resolve for store-like prompts
            pass
        else:
            card_eligible += 1
            if old_card != new_card:
                card_changed += 1
                card_pairs[f"{old_card}->{new_card}"] += 1
                if len(card_samples) < args.sample:
                    card_samples.append(
                        {
                            "subtask_id": item.get("subtask_id"),
                            "tenant": item.get("tenant"),
                            "prompt": prompt[:50],
                            "old_card": old_card,
                            "new_card": new_card,
                            "db": item.get("db_rank"),
                        }
                    )

        if item.get("manual_locked"):
            locked_skip += 1
            continue
        detail = _resolve_brand_rank_detail(
            _sub(item),
            item.get("monitor_keywords"),
            terms,
            None,
        )
        db_rank = item.get("db_rank")
        new_full = detail.rank
        num = _numbered_list_brand_rank(text, terms)
        head = _numbered_subheading_title_rank(text, terms)
        catalog = head if head is not None else num
        if db_rank != new_full:
            db_diff += 1
            db_pairs[f"{db_rank}->{new_full}"] += 1
            basis_when_db_diff[str(detail.rank_basis or "none")] += 1
            if len(db_samples) < args.sample:
                db_samples.append(
                    {
                        "subtask_id": item.get("subtask_id"),
                        "tenant": item.get("tenant"),
                        "prompt": prompt[:50],
                        "db": db_rank,
                        "new_full": new_full,
                        "basis": detail.rank_basis,
                        "old_card": old_card,
                        "new_card": new_card,
                        "catalog": catalog,
                    }
                )
        # 可人工确认候选：旧卡=1，编号主榜>1，且全文=编号
        if (
            old_card == 1
            and catalog is not None
            and int(catalog) > 1
            and new_full == catalog
            and db_rank != new_full
        ):
            confirmed_candidates.append(
                {
                    "subtask_id": item.get("subtask_id"),
                    "tenant": item.get("tenant"),
                    "prompt": prompt[:50],
                    "db": db_rank,
                    "catalog": catalog,
                    "basis": detail.rank_basis,
                }
            )

    unlocked = scanned - locked_skip
    print(f"file={args.file} exported={payload.get('count')} scanned={scanned}")
    print(f"no_terms={no_terms} locked_skip={locked_skip}")
    print("--- store_card old vs C+D ---")
    print(
        f"eligible={card_eligible} changed={card_changed}"
        f" ({(100 * card_changed / card_eligible) if card_eligible else 0:.1f}%)"
    )
    print("card_pairs", dict(card_pairs.most_common(15)))
    print("--- full resolve vs prod db_rank ---")
    print(
        f"db_diff={db_diff}/{max(unlocked, 0)}"
        f" ({(100 * db_diff / unlocked) if unlocked else 0:.1f}%)"
    )
    print("db_pairs", dict(db_pairs.most_common(15)))
    print("basis_when_db_diff", dict(basis_when_db_diff.most_common(10)))
    print("--- card change samples ---")
    for row in card_samples:
        print(row)
    print("--- db diff samples ---")
    for row in db_samples:
        print(row)
    print(f"--- confirmed-style candidates (old_card=1 & catalog>1 & full==catalog) n={len(confirmed_candidates)} ---")
    for row in confirmed_candidates[:20]:
        print(row)


if __name__ == "__main__":
    main()
