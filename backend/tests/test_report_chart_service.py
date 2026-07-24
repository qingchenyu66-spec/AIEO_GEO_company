"""Tests for report chart PNG generation."""

from matplotlib.axes import Axes

from app.services.report_chart_service import (
    build_day_entity_grouped_bar,
    build_entity_rank_trend_chart,
    build_mention_rate_bar_chart,
    build_merged_rank_trend_panels,
    build_platform_mention_chart,
    build_prompt_day_grouped_bar,
    build_rank_trend_chart,
    build_sentiment_pie_chart,
)


def test_build_rank_trend_chart_returns_png() -> None:
    png = build_rank_trend_chart([
        {"schedule_label": "2026-06-30 09:30", "avg_rank": 4.2, "mention_rate": 35.0},
        {"schedule_label": "2026-07-01 14:30", "avg_rank": 3.1, "mention_rate": 42.0},
    ])
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_build_entity_rank_trend_chart_returns_png() -> None:
    png = build_entity_rank_trend_chart(
        [
            {
                "schedule_label": "2026-06-07",
                "entities": {"儒思HR": 4.0, "北森": 1.0},
                "avg_rank": 4.0,
            },
            {
                "schedule_label": "2026-06-08",
                "entities": {"儒思HR": 2.0, "北森": 3.0},
                "avg_rank": 2.0,
            },
        ],
        brand="儒思HR",
        tracked_entities=["儒思HR", "北森"],
    )
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_entity_rank_trend_annotates_every_point(monkeypatch) -> None:
    """非合图：品牌与竞品每个有排名的点都要标数值。"""
    texts: list[str] = []
    original_annotate = Axes.annotate

    def recording_annotate(self, text, *args, **kwargs):
        texts.append(str(text))
        return original_annotate(self, text, *args, **kwargs)

    monkeypatch.setattr(Axes, "annotate", recording_annotate)
    rows = [
        {
            "schedule_label": f"2026-07-0{i} 09:30",
            "entities": {"儒思HR": float(i), "北森": float(i) + 0.5},
            "avg_rank": float(i),
        }
        for i in range(1, 5)
    ]
    png = build_entity_rank_trend_chart(
        rows,
        brand="儒思HR",
        tracked_entities=["儒思HR", "北森"],
    )
    assert png is not None
    # 4 时点 × 2 实体 = 8 个点标注
    assert len(texts) == 8


def test_entity_rank_trend_uses_distinct_company_styles(monkeypatch) -> None:
    calls: list[dict] = []
    original_plot = Axes.plot

    def recording_plot(self, *args, **kwargs):
        if kwargs.get("label"):
            calls.append(kwargs.copy())
        return original_plot(self, *args, **kwargs)

    monkeypatch.setattr(Axes, "plot", recording_plot)
    rows = [
        {
            "schedule_label": "2026-07-03 09:30",
            "entities": {
                "艾迪亚控股集团有限公司": 4.2,
                "分众传媒": 1.2,
                "白马户外媒体": 5.1,
                "华铁传媒": 3.8,
            },
        }
    ]

    build_entity_rank_trend_chart(
        rows,
        brand="艾迪亚控股集团有限公司",
        tracked_entities=list(rows[0]["entities"]),
    )

    assert [call["color"] for call in calls] == ["#0057D9", "#F28E2B", "#009E73", "#C43C92"]
    assert len({call["linestyle"] for call in calls}) == 4
    assert len({call["marker"] for call in calls}) == 4


def test_build_mention_rate_bar_chart_returns_png() -> None:
    png = build_mention_rate_bar_chart(
        [
            {"name": "儒思HR", "mention_rate": 83.7, "is_brand": True},
            {"name": "北森", "mention_rate": 27.9, "is_competitor": True},
        ],
        title="语义词测试",
        brand="儒思HR",
    )
    assert png is not None
    assert len(png) > 1000


def test_mention_rate_bars_use_entity_colors(monkeypatch) -> None:
    captured: dict = {}
    original_barh = Axes.barh

    def recording_barh(self, *args, **kwargs):
        captured.update(kwargs)
        return original_barh(self, *args, **kwargs)

    monkeypatch.setattr(Axes, "barh", recording_barh)
    build_mention_rate_bar_chart(
        [
            {"name": "艾迪亚控股集团有限公司", "mention_rate": 8.8, "is_brand": True},
            {"name": "分众传媒", "mention_rate": 93.8, "is_competitor": True},
            {"name": "白马户外媒体", "mention_rate": 3.8, "is_competitor": True},
        ],
        title="竞品提及率",
        brand="艾迪亚控股集团有限公司",
    )

    assert captured["color"] == ["#F28E2B", "#0057D9", "#009E73"]


def test_build_sentiment_pie_chart_skips_zero_unknown() -> None:
    png = build_sentiment_pie_chart({"正面": 100, "中性": 30, "负面": 10, "未知": 0})
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_build_merged_rank_trend_panels_returns_png() -> None:
    rows = [
        {
            "schedule_label": "2026-07-03",
            "entities": {"艾迪亚控股集团有限公司": 2.4, "分众传媒": 2.0},
            "avg_rank": 2.4,
        }
    ]
    png = build_merged_rank_trend_panels(
        [
            {"title": "综合均位", "trend_rows": rows},
            {"title": "Q1 电梯广告", "trend_rows": rows},
            {"title": "Q2 机场广告", "trend_rows": rows},
        ],
        brand="艾迪亚控股集团有限公司",
        tracked_entities=["艾迪亚控股集团有限公司", "分众传媒"],
    )
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_day_entity_and_prompt_day_bars_return_png() -> None:
    rows = [
        {
            "schedule_label": "2026-06-30 09:30",
            "entities": {"艾迪亚控股集团有限公司": 3.0, "分众传媒": 1.5},
            "avg_rank": 3.0,
        },
        {
            "schedule_label": "2026-07-01 09:30",
            "entities": {"艾迪亚控股集团有限公司": 2.4, "分众传媒": 1.8},
            "avg_rank": 2.4,
        },
        {
            "schedule_label": "2026-07-02 09:30",
            "entities": {"艾迪亚控股集团有限公司": 2.1, "分众传媒": 2.0},
            "avg_rank": 2.1,
        },
    ]
    overall = build_day_entity_grouped_bar(
        rows,
        brand="艾迪亚控股集团有限公司",
        tracked_entities=["艾迪亚控股集团有限公司", "分众传媒"],
    )
    assert overall is not None and overall[:8] == b"\x89PNG\r\n\x1a\n"
    prompt_png = build_prompt_day_grouped_bar(
        [
            {"prompt": "电梯广告公司推荐", "round_trend": rows},
            {"prompt": "机场广告公司推荐", "round_trend": rows},
        ],
        brand="艾迪亚控股集团有限公司",
    )
    assert prompt_png is not None and prompt_png[:8] == b"\x89PNG\r\n\x1a\n"
