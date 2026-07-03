"""为 PDF / Word 报告生成图表 PNG。"""

from __future__ import annotations

import io
import re
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

from app.services.molizhishu_catalog_service import get_supported_platform_catalog

_CHART_DPI = 160
_CHART_FIGSIZE = (7.2, 3.2)
_PLATFORM_COLORS = ["#1f6feb", "#2272d9", "#3b8eed", "#58708f", "#17406a", "#45627f", "#6b8cae"]
_ENTITY_LINE_COLORS = ["#ef4444", "#22c55e", "#3b82f6", "#f59e0b", "#8b5cf6"]


def _configure_matplotlib() -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def _short_schedule_label(label: Any) -> str:
    text = str(label or "").strip()
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2}:\d{2})", text)
    if match:
        return f"{match.group(2)}-{match.group(3)}\n{match.group(4)}"
    if len(text) > 14:
        return text[:12] + "…"
    return text or "—"


def _platform_label_map() -> dict[str, str]:
    return {
        str(item.get("code") or ""): str(item.get("name") or item.get("code") or "")
        for item in get_supported_platform_catalog()
    }


def _figure_to_png(fig: plt.Figure) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=_CHART_DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buffer.seek(0)
    return buffer.read()


def build_rank_trend_chart(rank_trend: list[dict[str, Any]]) -> bytes | None:
    """平均排名 + 提及率双轴趋势图。"""
    if not rank_trend:
        return None
    _configure_matplotlib()

    labels = [
        _short_schedule_label(row.get("schedule_label") or row.get("schedule_key"))
        for row in rank_trend
    ]
    ranks = [
        float(row["avg_rank"]) if row.get("avg_rank") is not None else None
        for row in rank_trend
    ]
    mention_rates = [
        float(row["mention_rate"]) if row.get("mention_rate") is not None else None
        for row in rank_trend
    ]
    if not any(value is not None for value in ranks) and not any(value is not None for value in mention_rates):
        return None

    fig, ax_rank = plt.subplots(figsize=_CHART_FIGSIZE)
    x = list(range(len(labels)))

    rank_points = [(index, value) for index, value in enumerate(ranks) if value is not None]
    if rank_points:
        rx, ry = zip(*rank_points)
        ax_rank.plot(rx, ry, color="#1f6feb", marker="o", linewidth=2.4, markersize=6, label="平均排名")
        ax_rank.invert_yaxis()
        ax_rank.set_ylabel("平均排名（越小越靠前）", color="#17406a")
        ax_rank.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=6))
        ax_rank.grid(axis="y", linestyle="--", alpha=0.25)

    ax_rate = ax_rank.twinx()
    rate_points = [(index, value) for index, value in enumerate(mention_rates) if value is not None]
    if rate_points:
        mx, my = zip(*rate_points)
        ax_rate.plot(mx, my, color="#16a34a", marker="s", linewidth=2.0, markersize=5, label="提及率")
        ax_rate.set_ylabel("提及率 (%)", color="#166534")
        ax_rate.set_ylim(0, max(100, max(my) * 1.15 if my else 100))

    ax_rank.set_xticks(x)
    ax_rank.set_xticklabels(labels, fontsize=8)
    ax_rank.set_title("平均排名趋势", fontsize=13, fontweight="bold", color="#12385f", pad=12)
    ax_rank.spines["top"].set_visible(False)

    lines, legends = [], []
    if rank_points:
        lines.append(ax_rank.lines[0])
        legends.append("平均排名")
    if rate_points:
        lines.append(ax_rate.lines[0])
        legends.append("提及率")
    if lines:
        ax_rank.legend(lines, legends, loc="upper right", framealpha=0.9, fontsize=8)

    fig.tight_layout()
    return _figure_to_png(fig)


def _entity_series(
    trend_rows: list[dict[str, Any]],
    entity_names: list[str],
) -> dict[str, list[tuple[int, float]]]:
    series: dict[str, list[tuple[int, float]]] = {name: [] for name in entity_names}
    for index, row in enumerate(trend_rows):
        entities = row.get("entities") or {}
        for name in entity_names:
            value = entities.get(name)
            if value is None and names_match(name, row.get("brand_name")):
                value = row.get("avg_rank")
            if value is not None:
                series[name].append((index, float(value)))
    return series


def names_match(left: str | None, right: str | None) -> bool:
    a = re.sub(r"\s+", "", str(left or "").strip().lower())
    b = re.sub(r"\s+", "", str(right or "").strip().lower())
    if not a or not b:
        return False
    return a == b or a in b or b in a


def build_entity_rank_trend_chart(
    trend_rows: list[dict[str, Any]],
    *,
    brand: str,
    tracked_entities: list[str] | None = None,
    title: str = "品牌及竞品平均排名",
    subtitle: str | None = None,
) -> bytes | None:
    """品牌 + 竞品多线排名趋势图（Y 轴反向）。"""
    if not trend_rows:
        return None
    entities = tracked_entities or []
    if not entities:
        first_entities = (trend_rows[0].get("entities") or {}).keys()
        entities = list(first_entities)
    if not entities:
        return build_rank_trend_chart(trend_rows)

    _configure_matplotlib()
    labels = [
        _short_schedule_label(row.get("schedule_label") or row.get("schedule_key"))
        for row in trend_rows
    ]
    fig, ax = plt.subplots(figsize=_CHART_FIGSIZE)
    x = list(range(len(labels)))
    max_rank = 1.0

    for index, name in enumerate(entities[:5]):
        points = []
        for point_index, row in enumerate(trend_rows):
            entities_map = row.get("entities") or {}
            value = entities_map.get(name)
            if value is None and names_match(name, brand):
                value = row.get("avg_rank")
            if value is not None:
                points.append((point_index, float(value)))
                max_rank = max(max_rank, float(value))
        if not points:
            continue
        px, py = zip(*points)
        color = _ENTITY_LINE_COLORS[index % len(_ENTITY_LINE_COLORS)]
        linewidth = 2.8 if names_match(name, brand) else 2.0
        ax.plot(px, py, color=color, marker="o", linewidth=linewidth, markersize=5, label=name)
        for px_val, py_val in points:
            ax.annotate(
                f"{py_val:.1f}",
                (px_val, py_val),
                textcoords="offset points",
                xytext=(0, 8),
                ha="center",
                fontsize=7,
                color=color,
            )

    ax.invert_yaxis()
    ax.set_ylim(max(max_rank + 1, 6), 0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("平均排名（越小越靠前）", color="#17406a")
    ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=6))
    ax.grid(axis="y", linestyle="--", alpha=0.25)
    ax.set_title(title, fontsize=13, fontweight="bold", color="#12385f", pad=12)
    if subtitle:
        ax.text(0.01, 1.02, subtitle, transform=ax.transAxes, fontsize=9, color="#58708f")
    ax.legend(loc="upper right", framealpha=0.9, fontsize=8)
    ax.spines["top"].set_visible(False)
    fig.tight_layout()
    return _figure_to_png(fig)


def build_mention_rate_bar_chart(
    mention_table: list[dict[str, Any]],
    *,
    title: str,
    brand: str,
    limit: int = 12,
) -> bytes | None:
    """语义词下品牌提及率横向柱状图。"""
    if not mention_table:
        return None
    _configure_matplotlib()
    rows = sorted(mention_table, key=lambda item: float(item.get("mention_rate") or 0), reverse=True)[:limit]
    labels = [str(row.get("name") or "—") for row in rows]
    values = [float(row.get("mention_rate") or 0) for row in rows]
    bar_colors = []
    for row in rows:
        if row.get("is_brand"):
            bar_colors.append("#22c55e")
        elif row.get("is_competitor"):
            bar_colors.append("#3b82f6")
        elif float(row.get("mention_rate") or 0) >= 60:
            bar_colors.append("#86efac")
        elif float(row.get("mention_rate") or 0) >= 30:
            bar_colors.append("#fde047")
        else:
            bar_colors.append("#fdba74")

    fig, ax = plt.subplots(figsize=(7.2, max(2.8, len(rows) * 0.28)))
    y_pos = list(range(len(labels)))
    bars = ax.barh(y_pos, values, color=bar_colors, height=0.62)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, max(100, max(values) * 1.12 if values else 100))
    ax.set_xlabel("提及率 (%)", color="#17406a")
    ax.set_title(title, fontsize=12, fontweight="bold", color="#12385f", pad=10)
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for bar, value in zip(bars, values):
        ax.text(min(value + 1.0, 98), bar.get_y() + bar.get_height() / 2, f"{value:.1f}%", va="center", fontsize=8)
    fig.tight_layout()
    return _figure_to_png(fig)


def build_platform_mention_chart(platform_stats: list[dict[str, Any]]) -> bytes | None:
    """各平台品牌提及率横向柱状图。"""
    if not platform_stats:
        return None
    _configure_matplotlib()
    names = _platform_label_map()
    rows = sorted(platform_stats, key=lambda item: float(item.get("mention_rate") or 0), reverse=True)
    labels = [names.get(str(row.get("platform") or ""), str(row.get("platform") or "—")) for row in rows]
    values = [float(row.get("mention_rate") or 0) for row in rows]

    fig, ax = plt.subplots(figsize=_CHART_FIGSIZE)
    y_pos = list(range(len(labels)))
    colors = [_PLATFORM_COLORS[index % len(_PLATFORM_COLORS)] for index in range(len(labels))]
    bars = ax.barh(y_pos, values, color=colors, height=0.62)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, max(100, max(values) * 1.12 if values else 100))
    ax.set_xlabel("品牌提及率 (%)", color="#17406a")
    ax.set_title("各平台品牌提及率", fontsize=13, fontweight="bold", color="#12385f", pad=12)
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    for bar, value in zip(bars, values):
        ax.text(
            min(value + 1.2, 98),
            bar.get_y() + bar.get_height() / 2,
            f"{value:.1f}%",
            va="center",
            fontsize=8,
            color="#334e6f",
        )

    fig.tight_layout()
    return _figure_to_png(fig)
