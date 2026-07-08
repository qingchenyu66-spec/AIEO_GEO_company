"""Regression: snapshot backfill mention_position parsing (mirrors frontend helper)."""


def parse_snapshot_backfill_mention_position(value: str | int | float | None) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = float(raw)
    if not parsed == parsed:  # NaN
        return None
    return int(parsed) if parsed == int(parsed) else int(parsed)


def test_mention_position_accepts_number_like_string() -> None:
    assert parse_snapshot_backfill_mention_position("1") == 1


def test_mention_position_accepts_int() -> None:
    assert parse_snapshot_backfill_mention_position(1) == 1


def test_mention_position_empty_is_none() -> None:
    assert parse_snapshot_backfill_mention_position("") is None
    assert parse_snapshot_backfill_mention_position(None) is None
