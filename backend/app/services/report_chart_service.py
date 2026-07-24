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
from app.services.report_competitor_visuals import entity_visual_style
from app.services.report_premium_font_service import configure_matplotlib_cjk
from app.services.report_molizhishu_theme import get_theme

_CHART_DPI = 160
_CHART_FIGSIZE = (7.2, 3.2)


def _configure_matplotlib() -> None:
    family = configure_matplotlib_cjk()
    if family:
        plt.rcParams["font.sans-serif"] = [family, "DejaVu Sans"]
    else:
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def _short_schedule_label(label: Any) -> str:
    text = str(label or "").strip()
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{2}:\d{2}))?", text)
    if match:
        if match.group(4):
            return f"{match.group(2)}-{match.group(3)}\n{match.group(4)}"
        return f"{match.group(2)}-{match.group(3)}"
    if len(text) > 14:
        return text[:12] + "…"
    return text or "—"


def _short_entity_label(name: str, *, limit: int = 8) -> str:
    text = re.sub(r"\s+", "", str(name or "").strip())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _platform_label_map() -> dict[str, str]:
    return {
        str(item.get("code") or ""): str(item.get("name") or item.get("code") or "")
        for item in get_supported_platform_catalog()
    }


def _figure_to_png(fig: plt.Figure, *, pad_inches: float = 0.55, tight: bool = True) -> bytes:
    buffer = io.BytesIO()
    kwargs: dict[str, Any] = {
        "format": "png",
        "dpi": _CHART_DPI,
        "facecolor": "white",
    }
    if tight:
        # pad_inches 防止 X 轴日期/标签贴边被裁切
        kwargs["bbox_inches"] = "tight"
        kwargs["pad_inches"] = pad_inches
    fig.savefig(buffer, **kwargs)
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
    theme = get_theme()

    rank_points = [(index, value) for index, value in enumerate(ranks) if value is not None]
    if rank_points:
        rx, ry = zip(*rank_points)
        ax_rank.plot(rx, ry, color=theme.primary, marker="o", linewidth=2.4, markersize=6, label="平均排名")
        ax_rank.invert_yaxis()
        ax_rank.set_ylabel("平均排名（越小越靠前）", color=theme.chart_axis)
        ax_rank.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=6))
        ax_rank.grid(axis="y", linestyle="--", alpha=0.25)

    ax_rate = ax_rank.twinx()
    rate_points = [(index, value) for index, value in enumerate(mention_rates) if value is not None]
    if rate_points:
        mx, my = zip(*rate_points)
        ax_rate.plot(mx, my, color=theme.success, marker="s", linewidth=2.0, markersize=5, label="提及率")
        ax_rate.set_ylabel("提及率 (%)", color=theme.success)
        ax_rate.set_ylim(0, max(100, max(my) * 1.15 if my else 100))

    ax_rank.set_xticks(x)
    ax_rank.set_xticklabels(labels, fontsize=8)
    ax_rank.set_title("平均排名趋势", fontsize=13, fontweight="bold", color=theme.chart_title, pad=12)
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


def names_match(left: str | None, right: str | None) -> bool:
    a = re.sub(r"\s+", "", str(left or "").strip().lower())
    b = re.sub(r"\s+", "", str(right or "").strip().lower())
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _collect_entity_series(
    trend_rows: list[dict[str, Any]],
    *,
    brand: str,
    entities: list[str],
) -> tuple[list[dict[str, Any]], list[str], float]:
    labels = [
        _short_schedule_label(row.get("schedule_label") or row.get("schedule_key"))
        for row in trend_rows
    ]
    series_data: list[dict[str, Any]] = []
    max_rank = 1.0
    for name in entities[:8]:
        points: list[tuple[int, float]] = []
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
        style = entity_visual_style(name, brand_name=brand)
        series_data.append(
            {
                "name": name,
                "points": points,
                "style": style,
                "is_brand": names_match(name, brand),
            }
        )
    return series_data, labels, max_rank


def _draw_entity_lines(
    ax: Any,
    *,
    series_data: list[dict[str, Any]],
    labels: list[str],
    max_rank: float,
    title: str | None,
    theme: Any,
    compact: bool = False,
    show_legend: bool = True,
) -> list[Any]:
    """在 ax 上画品牌/竞品折线；返回 legend handles。"""
    if not series_data:
        ax.set_axis_off()
        if title:
            ax.set_title(title, fontsize=11, color=theme.chart_title)
        return []

    point_count = max(len(item["points"]) for item in series_data)
    sparse = point_count <= 3
    y_bottom = max(max_rank + 1.2, 6.0)

    ax.axhline(3.0, color="#21b981", linestyle="--", linewidth=0.9, alpha=0.45, zorder=1)
    handles = []
    for series_idx, item in enumerate(series_data):
        points = item["points"]
        px, py = zip(*points)
        is_brand = bool(item["is_brand"])
        color = item["style"].color
        (line,) = ax.plot(
            px,
            py,
            color=color,
            linestyle=item["style"].line_style,
            marker=item["style"].marker,
            linewidth=2.8 if is_brand else 1.7,
            markersize=(9 if sparse else 7) if is_brand else (7 if sparse else 5),
            label=item["name"],
            zorder=4 if is_brand else 2,
            solid_capstyle="round",
        )
        handles.append(line)
        if is_brand and not compact:
            ax.fill_between(px, py, y_bottom, color=color, alpha=0.08, zorder=1)
        # 每个有排名的点都标注数值（竞品此前只标首/尾/最优，导致「有些点不显示」）
        if compact:
            label_points = [points[-1]] if is_brand else []
        else:
            label_points = list(points)
        series_offset = (series_idx % 3) * 3
        for px_val, py_val in label_points:
            rank_text = (
                str(int(py_val)) if float(py_val).is_integer() else f"{py_val:.1f}"
            )
            ax.annotate(
                rank_text,
                (px_val, py_val),
                textcoords="offset points",
                xytext=(0, 8 + series_offset),
                ha="center",
                fontsize=(8 if compact else 9) if is_brand else (7 if compact else 8),
                fontweight="bold" if is_brand else "normal",
                color=color,
                zorder=5 if is_brand else 3,
            )

    ax.invert_yaxis()
    ax.set_ylim(y_bottom, 0.5)
    ax.set_xticks(list(range(len(labels))))
    ax.set_xticklabels(labels, fontsize=7 if compact else 9)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=5 if compact else 6))
    ax.grid(axis="both", linestyle="--", alpha=0.2)
    ax.set_facecolor("#f7fafc")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    if title:
        ax.set_title(title, fontsize=11 if compact else 13, fontweight="bold", color=theme.chart_title, pad=6)
    if show_legend and not compact:
        ax.legend(loc="upper right", framealpha=0.92, fontsize=12, ncol=1)
    if not compact:
        ax.set_ylabel("平均排名（越小越靠前）", color=theme.chart_axis, fontsize=15)
    return handles


def build_entity_rank_trend_chart(
    trend_rows: list[dict[str, Any]],
    *,
    brand: str,
    tracked_entities: list[str] | None = None,
    title: str = "品牌及竞品平均排名",
    subtitle: str | None = None,
    figsize: tuple[float, float] | None = None,
) -> bytes | None:
    """品牌 + 竞品多线排名趋势图（纯折线，Y 轴反向）。"""
    if not trend_rows:
        return None
    entities = tracked_entities or []
    if not entities:
        first_entities = (trend_rows[0].get("entities") or {}).keys()
        entities = list(first_entities)
    if not entities:
        return build_rank_trend_chart(trend_rows)

    _configure_matplotlib()
    theme = get_theme()
    series_data, labels, max_rank = _collect_entity_series(
        trend_rows, brand=brand, entities=entities
    )
    if not series_data:
        return None

    size = figsize or _CHART_FIGSIZE
    fig, ax = plt.subplots(figsize=size, facecolor="white")
    _draw_entity_lines(
        ax,
        series_data=series_data,
        labels=labels,
        max_rank=max_rank,
        title=title or None,
        theme=theme,
        compact=False,
        show_legend=True,
    )
    if subtitle:
        ax.text(0.0, 1.05, subtitle, transform=ax.transAxes, fontsize=10, color=theme.gray)
    fig.tight_layout()
    return _figure_to_png(fig)


def build_merged_rank_trend_panels(
    panels: list[dict[str, Any]],
    *,
    brand: str,
    tracked_entities: list[str] | None = None,
    figsize: tuple[float, float] = (16.5, 8.4),
) -> bytes | None:
    """把多张排名折线收成一页小多图（2 列）。

    panels: [{title, trend_rows}, ...]
    """
    cleaned = [
        {
            "title": str(item.get("title") or "").strip() or "趋势",
            "trend_rows": list(item.get("trend_rows") or []),
        }
        for item in panels
        if item.get("trend_rows")
    ]
    if not cleaned:
        return None

    entities = tracked_entities or []
    _configure_matplotlib()
    theme = get_theme()
    n = len(cleaned)
    cols = 2 if n > 1 else 1
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(
        rows,
        cols,
        figsize=figsize,
        facecolor="white",
        squeeze=False,
    )
    legend_handles: list[Any] = []
    legend_labels: list[str] = []
    for index, panel in enumerate(cleaned):
        r, c = divmod(index, cols)
        ax = axes[r][c]
        panel_entities = entities
        if not panel_entities and panel["trend_rows"]:
            panel_entities = list((panel["trend_rows"][0].get("entities") or {}).keys())
        series_data, labels, max_rank = _collect_entity_series(
            panel["trend_rows"], brand=brand, entities=panel_entities
        )
        handles = _draw_entity_lines(
            ax,
            series_data=series_data,
            labels=labels,
            max_rank=max_rank,
            title=panel["title"],
            theme=theme,
            compact=True,
            show_legend=False,
        )
        if not legend_handles and handles:
            legend_handles = handles
            legend_labels = [h.get_label() for h in handles]

    # 隐藏多余子图
    for index in range(n, rows * cols):
        r, c = divmod(index, cols)
        axes[r][c].set_axis_off()

    if legend_handles:
        fig.legend(
            legend_handles,
            legend_labels,
            loc="lower center",
            ncol=min(4, max(1, len(legend_labels))),
            framealpha=0.95,
            fontsize=9,
            bbox_to_anchor=(0.5, 0.01),
        )
    fig.suptitle("品牌及竞品平均排名趋势（合图）", fontsize=14, fontweight="bold", color=theme.chart_title, y=0.98)
    fig.tight_layout(rect=(0.02, 0.06, 0.98, 0.94))
    return _figure_to_png(fig)


def aggregate_trend_by_day(trend_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把多批次压成按自然日均值，便于「三天」对照图。"""
    buckets: dict[str, dict[str, Any]] = {}
    for row in trend_rows:
        label = str(row.get("schedule_label") or row.get("schedule_key") or "").strip()
        day = label[:10] if len(label) >= 10 else label
        if not day:
            continue
        bucket = buckets.setdefault(
            day,
            {"schedule_key": day, "schedule_label": day, "entities_acc": {}, "brand_ranks": []},
        )
        entities = row.get("entities") or {}
        for name, value in entities.items():
            if value is None:
                continue
            bucket["entities_acc"].setdefault(name, []).append(float(value))
        if row.get("avg_rank") is not None:
            bucket["brand_ranks"].append(float(row["avg_rank"]))
    out: list[dict[str, Any]] = []
    for day in sorted(buckets.keys()):
        bucket = buckets[day]
        entities = {
            name: round(sum(vals) / len(vals), 1)
            for name, vals in bucket["entities_acc"].items()
            if vals
        }
        brand_ranks = bucket["brand_ranks"]
        out.append(
            {
                "schedule_key": day,
                "schedule_label": day[5:] if len(day) >= 10 else day,  # MM-DD
                "avg_rank": round(sum(brand_ranks) / len(brand_ranks), 1) if brand_ranks else None,
                "entities": entities,
            }
        )
    return out


def build_day_entity_grouped_bar(
    trend_rows: list[dict[str, Any]],
    *,
    brand: str,
    tracked_entities: list[str] | None = None,
    title: str = "三日品牌/竞品均位对照",
    figsize: tuple[float, float] = (16.5, 7.8),
) -> bytes | None:
    """一张柱状图：X=日期，系列=品牌/竞品，覆盖多日均位。"""
    daily = aggregate_trend_by_day(trend_rows)
    if not daily:
        return None
    entities = tracked_entities or []
    if not entities:
        entities = list((daily[0].get("entities") or {}).keys())
    entities = entities[:6]
    if not entities:
        return None

    _configure_matplotlib()
    theme = get_theme()
    days = [str(row.get("schedule_label") or row.get("schedule_key") or "") for row in daily]
    x = list(range(len(days)))
    width = min(0.8 / max(len(entities), 1), 0.22)
    fig, ax = plt.subplots(figsize=figsize, facecolor="white")
    max_rank = 1.0
    for index, name in enumerate(entities):
        values = []
        for row in daily:
            entities_map = row.get("entities") or {}
            value = entities_map.get(name)
            if value is None and names_match(name, brand):
                value = row.get("avg_rank")
            values.append(float(value) if value is not None else 0.0)
            if value is not None:
                max_rank = max(max_rank, float(value))
        style = entity_visual_style(name, brand_name=brand)
        offsets = [pos + (index - (len(entities) - 1) / 2) * width for pos in x]
        bars = ax.bar(
            offsets,
            values,
            width=width * 0.92,
            color=style.color,
            label=_short_entity_label(name, limit=10),
            zorder=2,
        )
        for bar, value in zip(bars, values):
            # 无排名也标 0，避免「完全不显示」被误读成缺系列
            label = f"{value:.1f}" if value > 0 else "0"
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                (value + 0.08) if value > 0 else 0.12,
                label,
                ha="center",
                va="bottom",
                fontsize=9,
                fontweight="bold" if names_match(name, brand) else "normal",
                color="#0f2744",
            )
    ax.axhline(3.0, color="#21b981", linestyle="--", linewidth=1.1, alpha=0.55, zorder=1)
    ax.set_xticks(x)
    day_labels = [_short_schedule_label(day) for day in days]
    ax.set_xticklabels(day_labels, fontsize=14)
    ax.tick_params(axis="x", pad=16, length=8, width=1.2)
    ax.set_ylabel("平均排名（数值越小越靠前）", color=theme.chart_axis, fontsize=11)
    ax.set_ylim(0, max(max_rank + 1.2, 5.5))
    ax.set_title(title, fontsize=15, fontweight="bold", color=theme.chart_title, pad=12)
    ax.grid(axis="y", linestyle="--", alpha=0.25)
    ax.set_facecolor("#f7fafc")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(loc="upper right", framealpha=0.95, fontsize=10, ncol=2)
    # 不用 tight bbox：固定底部留白，保证日期完整进 PNG
    fig.subplots_adjust(left=0.08, right=0.98, top=0.88, bottom=0.26)
    return _figure_to_png(fig, tight=False)


def build_prompt_day_grouped_bar(
    prompt_analytics: list[dict[str, Any]],
    *,
    brand: str,
    title: str = "分语义词三日品牌均位",
    figsize: tuple[float, float] = (16.5, 7.8),
) -> bytes | None:
    """一张柱状图：X=语义词，系列=自然日，值为本品牌均位（含三天全量）。"""
    prompt_days: list[tuple[str, list[dict[str, Any]]]] = []
    all_days: list[str] = []
    for index, block in enumerate(prompt_analytics, start=1):
        daily = aggregate_trend_by_day(list(block.get("round_trend") or []))
        if not daily:
            continue
        prompt = str(block.get("prompt") or "").strip() or f"问题{index}"
        short = prompt if len(prompt) <= 12 else prompt[:11] + "…"
        prompt_days.append((f"Q{index}\n{short}", daily))
        for row in daily:
            day = str(row.get("schedule_key") or row.get("schedule_label") or "")
            if day and day not in all_days:
                all_days.append(day)
    if not prompt_days or not all_days:
        return None
    all_days = sorted(all_days)

    _configure_matplotlib()
    theme = get_theme()
    day_colors = ["#0057D9", "#F28E2B", "#009E73", "#C43C92", "#7A7A7A"]
    x = list(range(len(prompt_days)))
    width = min(0.8 / max(len(all_days), 1), 0.24)
    fig, ax = plt.subplots(figsize=figsize, facecolor="white")
    max_rank = 1.0
    for day_index, day in enumerate(all_days):
        values = []
        for _label, daily in prompt_days:
            matched = next(
                (row for row in daily if str(row.get("schedule_key") or "") == day),
                None,
            )
            value = None
            if matched:
                entities = matched.get("entities") or {}
                value = entities.get(brand)
                if value is None:
                    for name, rank in entities.items():
                        if names_match(name, brand):
                            value = rank
                            break
                if value is None:
                    value = matched.get("avg_rank")
            values.append(float(value) if value is not None else 0.0)
            if value is not None:
                max_rank = max(max_rank, float(value))
        offsets = [pos + (day_index - (len(all_days) - 1) / 2) * width for pos in x]
        label = day[5:] if len(day) >= 10 else day
        bars = ax.bar(
            offsets,
            values,
            width=width * 0.9,
            color=day_colors[day_index % len(day_colors)],
            label=label,
            zorder=2,
        )
        for bar, value in zip(bars, values):
            label = f"{value:.1f}" if value > 0 else "0"
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                (value + 0.08) if value > 0 else 0.12,
                label,
                ha="center",
                va="bottom",
                fontsize=8,
                color="#0f2744",
            )
    ax.axhline(3.0, color="#21b981", linestyle="--", linewidth=1.1, alpha=0.55, zorder=1)
    ax.set_xticks(x)
    ax.set_xticklabels([item[0] for item in prompt_days], fontsize=10)
    ax.set_ylabel("本品牌平均排名（越小越靠前）", color=theme.chart_axis, fontsize=11)
    ax.set_ylim(0, max(max_rank + 1.2, 5.5))
    ax.set_title(title, fontsize=15, fontweight="bold", color=theme.chart_title, pad=12)
    ax.grid(axis="y", linestyle="--", alpha=0.25)
    ax.set_facecolor("#f7fafc")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(title="监测日期", loc="upper right", framealpha=0.95, fontsize=10)
    ax.tick_params(axis="x", pad=12, length=6)
    fig.subplots_adjust(left=0.07, right=0.98, top=0.86, bottom=0.24)
    return _figure_to_png(fig, tight=False)


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
    theme = get_theme()
    rows = sorted(mention_table, key=lambda item: float(item.get("mention_rate") or 0), reverse=True)[:limit]
    labels = [str(row.get("name") or "—") for row in rows]
    values = [float(row.get("mention_rate") or 0) for row in rows]
    bar_colors = [
        entity_visual_style(str(row.get("name") or ""), brand_name=brand).color
        for row in rows
    ]

    fig, ax = plt.subplots(figsize=(7.2, max(2.8, len(rows) * 0.28)))
    y_pos = list(range(len(labels)))
    bars = ax.barh(y_pos, values, color=bar_colors, height=0.62)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, max(100, max(values) * 1.12 if values else 100))
    ax.set_xlabel("提及率 (%)", color=theme.chart_axis)
    ax.set_title(title, fontsize=12, fontweight="bold", color=theme.chart_title, pad=10)
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
    theme = get_theme()
    names = _platform_label_map()
    rows = sorted(platform_stats, key=lambda item: float(item.get("mention_rate") or 0), reverse=True)
    labels = [names.get(str(row.get("platform") or ""), str(row.get("platform") or "—")) for row in rows]
    values = [float(row.get("mention_rate") or 0) for row in rows]

    fig, ax = plt.subplots(figsize=_CHART_FIGSIZE)
    y_pos = list(range(len(labels)))
    bar_colors = [theme.platform_colors[index % len(theme.platform_colors)] for index in range(len(labels))]
    bars = ax.barh(y_pos, values, color=bar_colors, height=0.62)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, max(100, max(values) * 1.12 if values else 100))
    ax.set_xlabel("品牌提及率 (%)", color=theme.chart_axis)
    ax.set_title("各平台品牌提及率", fontsize=13, fontweight="bold", color=theme.chart_title, pad=12)
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
            color=theme.chart_axis,
        )

    fig.tight_layout()
    return _figure_to_png(fig)


def build_sentiment_pie_chart(sentiment_counts: dict[str, int]) -> bytes | None:
    """正/中/负面舆情占比饼图（忽略计数为 0 的分类）。"""
    from app.services.report_period_content_service import normalize_sentiment_counts

    normalized = normalize_sentiment_counts(sentiment_counts)
    if not normalized:
        return None
    filtered = {
        str(label): int(value)
        for label, value in normalized.items()
        if int(value or 0) > 0
    }
    if not filtered:
        return None
    _configure_matplotlib()
    theme = get_theme()
    labels = list(filtered.keys())
    values = [float(filtered[label]) for label in labels]
    colors_map = {"正面": "#21b981", "中性": "#667c99", "负面": theme.danger, "未知": "#cfe5ff"}
    pie_colors = [colors_map.get(label, theme.primary) for label in labels]

    fig, ax = plt.subplots(figsize=(4.8, 3.8))
    legend_labels = [f"{label} {filtered[label]}条" for label in labels]

    def _autopct(pct: float) -> str:
        return f"{pct:.1f}%" if pct >= 3 else ""

    wedges, _texts, autotexts = ax.pie(
        values,
        labels=None,
        autopct=_autopct,
        startangle=90,
        colors=pie_colors,
        pctdistance=0.72,
        textprops={"fontsize": 8},
    )
    for autotext in autotexts:
        if autotext.get_text():
            autotext.set_color("white")
            autotext.set_fontsize(8)
    ax.legend(
        wedges,
        legend_labels,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.12),
        ncol=min(len(labels), 4),
        fontsize=8,
        frameon=False,
    )
    ax.set_title("舆情情绪占比分布", fontsize=12, fontweight="bold", color=theme.chart_title, pad=10)
    fig.tight_layout()
    return _figure_to_png(fig)


def build_source_bar_chart(top_sources: list[dict[str, Any]], *, limit: int = 8) -> bytes | None:
    """高频信源引用次数条形图。"""
    if not top_sources:
        return None
    _configure_matplotlib()
    theme = get_theme()
    rows = top_sources[:limit]
    labels = [str(row.get("title") or row.get("url") or "—")[:18] for row in rows]
    values = [float(row.get("count") or 0) for row in rows]

    fig, ax = plt.subplots(figsize=(6.8, max(2.8, len(rows) * 0.35)))
    y_pos = list(range(len(labels)))
    bars = ax.barh(y_pos, values, color=theme.primary, height=0.62)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("引用次数", color=theme.chart_axis)
    ax.set_title("TOP 信源引用次数", fontsize=12, fontweight="bold", color=theme.chart_title, pad=10)
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for bar, value in zip(bars, values):
        ax.text(value + 0.1, bar.get_y() + bar.get_height() / 2, f"{int(value)}", va="center", fontsize=8)
    fig.tight_layout()
    return _figure_to_png(fig)
