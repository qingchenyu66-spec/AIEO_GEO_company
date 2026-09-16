# -*- coding: utf-8 -*-
"""Offline impact: prod export JSON vs current local rank rules."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from app.services.monitor_service import (
    _numbered_list_brand_rank,
    _numbered_subheading_title_rank,
    _resolve_brand_rank_detail,
    _store_guide_card_brand_rank,
)
from scripts.impact_store_card_rank_change import _legacy_store_guide_card_brand_rank

sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "scripts/prod_store_rank_sample.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data["items"]
    print(f"prod sample {data.get('count')} exported {data.get('exported_at')}")

    rule_pairs: Counter[str] = Counter()
    db_pairs: Counter[str] = Counter()
    basis_ct: Counter[str] = Counter()
    eligible = 0
    changed: list[dict] = []

    for it in items:
        terms = it.get("brand_terms") or []
        if not terms:
            continue
        text = it["answer"]
        prompt = it.get("prompt") or ""
        old_card = _legacy_store_guide_card_brand_rank(text, terms, prompt=prompt)
        new_card = _store_guide_card_brand_rank(text, terms, prompt=prompt)
        num = _numbered_list_brand_rank(text, terms)
        head = _numbered_subheading_title_rank(text, terms)
        sub = SimpleNamespace(
            prompt=prompt,
            answer_content=text,
            mention_context=None,
            all_rankings_json=[],
            mention_position=it.get("db_rank"),
            raw_result_json={"manual_rank_locked": False, "source": "rules_compare"},
            platform=it.get("platform"),
            status="completed",
            mode="standard",
            subtask_id=it.get("subtask_id"),
            task_id="t",
        )
        detail = _resolve_brand_rank_detail(sub, it.get("monitor_keywords"), terms, None)
        basis = str(detail.rank_basis or "")
        related = (
            old_card is not None
            or new_card is not None
            or num is not None
            or head is not None
            or basis in {"store_card_local", "numbered_list", "numbered_subheading"}
        )
        if not related:
            continue
        eligible += 1
        basis_ct[basis or "none"] += 1
        if old_card != new_card:
            rule_pairs[f"{old_card}->{new_card}"] += 1
        if (not it.get("manual_locked")) and it.get("db_rank") != detail.rank:
            db_pairs[f"{it.get('db_rank')}->{detail.rank}"] += 1
            changed.append(
                {
                    "sid": it.get("subtask_id"),
                    "tenant": str(it.get("tenant") or "")[:24],
                    "plat": it.get("platform"),
                    "prompt": prompt[:40],
                    "db": it.get("db_rank"),
                    "new": detail.rank,
                    "basis": basis,
                    "old_card": old_card,
                    "new_card": new_card,
                    "num": num,
                    "head": head,
                }
            )

    print(f"eligible (store/numbered related) {eligible}")
    print("card rule old->new", dict(rule_pairs.most_common(15)))
    print(f"db->new_full changes {len(changed)}", dict(db_pairs.most_common(20)))
    print("basis among eligible", dict(basis_ct.most_common(12)))
    print("--- sample changes (first 30) ---")
    for row in changed[:30]:
        print(row)

    # confirmed-safe preview: old_card==1, head/num >1, new==catalog, brand catalog path
    safe = []
    for row in changed:
        catalog = row["head"] if row["head"] is not None else row["num"]
        if row["old_card"] != 1:
            continue
        if catalog is None or int(catalog) <= 1:
            continue
        if row["new"] != catalog:
            continue
        if row["basis"] not in {"numbered_list", "numbered_subheading"}:
            continue
        safe.append(row)
    print(f"--- safe-ish preview (old_card=1 & numbered catalog==new) {len(safe)} ---")
    for row in safe[:20]:
        print(row)


if __name__ == "__main__":
    main()
