"""keyword miner history service unit checks."""

from app.services.keyword_miner_service import _summary_from_result


def test_summary_from_result_counts_and_tops():
    result = {
        "source": "demo",
        "model": "m1",
        "meta": {"task": "both", "platforms": ["kimi", "豆包"]},
        "selection": [
            {"word": "a", "score": 10},
            {"word": "b", "score": 90},
            {"word": "c", "score": 50},
        ],
        "expansion": {"阶段1": [{"q": "x"}, {"q": "y"}], "阶段2": [{"q": "z"}]},
    }
    summary = _summary_from_result(result)
    assert summary["selection_count"] == 3
    assert summary["expansion_count"] == 3
    assert summary["task"] == "both"
    assert summary["platforms"] == ["kimi", "豆包"]
    assert summary["top_words"][0] == "b"
    assert summary["source"] == "demo"
    assert summary["model"] == "m1"


def test_summary_from_result_empty():
    summary = _summary_from_result(None)
    assert summary["selection_count"] == 0
    assert summary["expansion_count"] == 0
    assert summary["top_words"] == []
