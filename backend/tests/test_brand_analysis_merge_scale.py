"""Scale check for brand-analysis description merge (read-path latency)."""

from __future__ import annotations

import hashlib
import time

from app.services.brand_analysis_service import _merge_similar_description_buckets


def test_merge_similar_buckets_scales_under_one_second():
    """2026-07-30 - 400+ 桶 O(n²) 曾把品牌分析首屏拖到 ~11s；bigram 候选后应亚秒级。"""
    buckets = []
    for i in range(420):
        digest = hashlib.md5(f"ba-desc-{i}".encode()).hexdigest()
        unique = "".join(chr(0x4E00 + (int(digest[j : j + 2], 16) % 200)) for j in range(0, 16, 2))
        buckets.append({
            "description": unique,
            "answers": [{"subtask_id": f"s{i}", "sentiment": "正面", "platform": "doubao"}],
            "_sent_tally": {"positive": 1},
            "_platforms": {"doubao"},
        })
    buckets[0]["description"] = "总部位于北京"
    buckets[1]["description"] = "2008年成立总部位于北京"
    t0 = time.perf_counter()
    merged = _merge_similar_description_buckets(buckets)
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, f"merge too slow: {elapsed:.3f}s"
    assert any("总部位于北京" in str(b.get("description") or "") and len(b["answers"]) >= 2 for b in merged)
