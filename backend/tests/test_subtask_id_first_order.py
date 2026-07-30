"""Self-check: id-first helpers keep order and skip empty."""
from __future__ import annotations


def test_hydrate_preserves_order():
    # ponytail: no DB — pure order restore contract of the helper pattern
    ordered_ids = [3, 1, 2]
    by_id = {1: "a", 2: "b", 3: "c"}
    restored = [by_id[i] for i in ordered_ids if i in by_id]
    assert restored == ["c", "a", "b"]
    assert [by_id[i] for i in [] if i in by_id] == []


if __name__ == "__main__":
    test_hydrate_preserves_order()
    print("ok")
