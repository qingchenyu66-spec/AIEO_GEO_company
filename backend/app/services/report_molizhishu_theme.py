"""售前诊断报告主题：与 aieokj 门户色板对齐。"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

# ponytail: 主题 token 集中一处，A/B 仅 override 差异项
_PORTAL = {
    "primary": "#1677ff",
    "primary_dark": "#1664cf",
    "secondary": "#15b8c8",
    "accent": "#2272d9",
    "dark": "#10233f",
    "light": "#f8fbff",
    "gray": "#667c99",
    "success": "#087a55",
    "warning": "#ad6800",
    "danger": "#b42318",
    "border": "#d9e6f5",
    "muted_bg": "#f2f8ff",
    "chart_title": "#17395f",
    "chart_axis": "#54708f",
}


@dataclass(frozen=True)
class ReportTheme:
    id: str
    label: str
    primary: str
    primary_dark: str
    secondary: str
    accent: str
    dark: str
    light: str
    gray: str
    success: str
    warning: str
    danger: str
    border: str
    muted_bg: str
    brand_text: str
    competitor_text: str
    rank_table_mode: str  # light | gradient
    progress_track: str
    entity_line_colors: tuple[str, ...]
    platform_colors: tuple[str, ...]
    chart_title: str
    chart_axis: str
    matrix_mode: str  # tier | gradient

    def rank_cell_bg(self, rank: object) -> str | None:
        if rank is None or rank == "":
            return None
        try:
            value = float(rank)
        except (TypeError, ValueError):
            return None
        if self.matrix_mode == "tier":
            if value <= 3:
                return "#e9fbf3"
            if value <= 10:
                return "#eaf4ff"
            return "#f4f8fd"
        # gradient: 排名越小越深蓝
        light = max(88, min(96, 96 - (value - 1) * 2.5))
        sat = max(45, min(78, 78 - (value - 1) * 3))
        return f"hsl(210, {sat:.0f}%, {light:.0f}%)"

    def mention_bar_fill(self, rate: float) -> str:
        width = max(0.0, min(100.0, float(rate)))
        if self.id == "b":
            hue = 205
            sat = int(72 + width * 0.12)
            light = int(58 - width * 0.08)
            return f"hsl({hue}, {sat}%, {light}%)"
        return f"linear-gradient(90deg, {self.primary}, {self.secondary})"

    def css_block(self) -> str:
        header_bg = self.primary
        if self.rank_table_mode == "gradient":
            header_bg = f"linear-gradient(135deg, {self.primary}, {self.secondary})"
        rank_bg = "#ffffff" if self.rank_table_mode == "light" else self.muted_bg
        rank_color = self.dark
        rank_border = self.border
        return f"""
:root {{
    --primary: {self.primary};
    --primary-dark: {self.primary_dark};
    --secondary: {self.secondary};
    --accent: {self.accent};
    --dark: {self.dark};
    --light: {self.light};
    --gray: {self.gray};
    --success: {self.success};
    --warning: {self.warning};
    --danger: {self.danger};
}}
body.report-theme-{self.id} {{
    color: {self.dark};
}}
body.report-theme-{self.id} .report-header {{
    background: linear-gradient(135deg, {self.muted_bg} 0%, #eef7ff 100%);
    border-bottom-color: {self.primary};
}}
body.report-theme-{self.id} .report-table thead,
body.report-theme-{self.id} .RankTable thead {{
    background: {header_bg};
}}
body.report-theme-{self.id} .RankTable {{
    background: {rank_bg};
    color: {rank_color};
    border: 1px solid {rank_border};
}}
body.report-theme-{self.id} .RankTable td {{
    border-bottom-color: {rank_border};
}}
body.report-theme-{self.id} .RankTable tr:hover {{
    background: {self.muted_bg};
}}
body.report-theme-{self.id} .brand-highlight {{
    background: linear-gradient(120deg, rgba(22, 119, 255, 0.12) 0%, rgba(21, 184, 200, 0.08) 100%);
    color: {self.brand_text};
}}
body.report-theme-{self.id} .competitor-highlight {{
    background: linear-gradient(120deg, rgba(173, 104, 0, 0.1) 0%, rgba(173, 104, 0, 0.05) 100%);
    color: {self.competitor_text};
}}
body.report-theme-{self.id} .analysis-section {{
    background: linear-gradient(135deg, {self.muted_bg} 0%, #eef7ff 100%);
    border-left-color: {self.secondary};
}}
body.report-theme-{self.id} .analysis-h2 {{
    color: {self.primary_dark};
    border-bottom-color: #cfe5ff;
}}
body.report-theme-{self.id} .chart-container {{
    background: {self.muted_bg};
    border-color: {rank_border};
}}
body.report-theme-{self.id} .progress-container {{
    background: {self.progress_track} !important;
}}
body.report-theme-{self.id} .progress-text {{
    color: {self.dark} !important;
    text-shadow: none !important;
}}
body.report-theme-{self.id} .brand-row-outline {{
    border-color: {self.primary} !important;
}}
body.report-theme-{self.id} .prompt-accent {{
    color: {self.primary_dark};
    font-weight: 600;
}}
"""


THEME_A = ReportTheme(
    id="a",
    label="商务清爽",
    rank_table_mode="light",
    matrix_mode="tier",
    progress_track="#e5edf7",
    brand_text="#1664cf",
    competitor_text="#ad6800",
    entity_line_colors=("#1677ff", "#15b8c8", "#21b981", "#2272d9", "#54708f"),
    platform_colors=("#1677ff", "#2272d9", "#15b8c8", "#21b981", "#54708f", "#1664cf", "#667c99"),
    **_PORTAL,
)

THEME_B = ReportTheme(
    id="b",
    label="数据可视化",
    rank_table_mode="gradient",
    matrix_mode="gradient",
    progress_track="#dce9f8",
    brand_text="#0d6fca",
    competitor_text="#b45309",
    entity_line_colors=("#1677ff", "#15b8c8", "#21b981", "#2272d9", "#ad6800"),
    platform_colors=("#1677ff", "#15b8c8", "#2272d9", "#21b981", "#1664cf", "#0d6fca", "#667c99"),
    **_PORTAL,
)

THEMES: dict[str, ReportTheme] = {"a": THEME_A, "b": THEME_B, "portal": THEME_B}
_DEFAULT = THEME_B

_theme_var: ContextVar[ReportTheme] = ContextVar("report_theme", default=_DEFAULT)


def get_theme() -> ReportTheme:
    return _theme_var.get()


def resolve_theme(theme_id: str | None) -> ReportTheme:
    if not theme_id:
        return _DEFAULT
    return THEMES.get(str(theme_id).lower(), _DEFAULT)


@contextmanager
def theme_scope(theme_id: str) -> Iterator[ReportTheme]:
    theme = resolve_theme(theme_id)
    token = _theme_var.set(theme)
    try:
        yield theme
    finally:
        _theme_var.reset(token)
