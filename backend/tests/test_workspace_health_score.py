"""Tests for workspace health score calculation."""

from app.services.monitor_service import compute_workspace_health_score


def test_health_score_without_rank_uses_visibility_only() -> None:
    result = compute_workspace_health_score(
        brand_mention_rate=50,
        top3_rate=30,
        avg_brand_rank=None,
    )
    assert result["visibility_score"] == 42
    assert result["rank_score"] is None
    assert result["health_score"] == 42


def test_health_score_with_rank_blends_visibility_and_rank() -> None:
    result = compute_workspace_health_score(
        brand_mention_rate=80,
        top3_rate=60,
        avg_brand_rank=2,
    )
    assert result["visibility_score"] == 72
    assert result["rank_score"] == 80
    assert result["health_score"] == round(72 * 0.6 + 80 * 0.4)


def test_health_score_with_competitor_blends_three_dimensions() -> None:
    result = compute_workspace_health_score(
        brand_mention_rate=80,
        top3_rate=60,
        avg_brand_rank=2,
        competitor_count=2,
        competitor_score=70,
    )
    visibility = round(80 * 0.6 + 60 * 0.4)
    rank_score = 80
    assert result["visibility_score"] == visibility
    assert result["rank_score"] == rank_score
    assert result["competitor_score"] == 70
    assert result["health_score"] == round(visibility * 0.5 + rank_score * 0.3 + 70 * 0.2)
