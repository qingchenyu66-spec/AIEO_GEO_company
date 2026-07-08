"""Premium PDF 中文字体解析——Playwright 无法依赖 Google Fonts CDN。"""

from __future__ import annotations

from pathlib import Path

_FONT_REGULAR_CANDIDATES = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
)

_FONT_BOLD_CANDIDATES = (
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
)


def _first_existing(candidates: tuple[Path, ...]) -> Path | None:
    for path in candidates:
        if path.exists():
            return path
    return None


def build_font_face_css() -> str:
    """生成本地 @font-face，供 Premium HTML/PDF 使用。"""
    regular = _first_existing(_FONT_REGULAR_CANDIDATES)
    if regular is None:
        return ""
    bold = _first_existing(_FONT_BOLD_CANDIDATES) or regular
    regular_uri = regular.resolve().as_uri()
    bold_uri = bold.resolve().as_uri()
    return (
        "@font-face {\n"
        "  font-family: 'GeoReportCJK';\n"
        f"  src: url('{regular_uri}') format('truetype');\n"
        "  font-weight: 400;\n"
        "  font-style: normal;\n"
        "}\n"
        "@font-face {\n"
        "  font-family: 'GeoReportCJK';\n"
        f"  src: url('{bold_uri}') format('truetype');\n"
        "  font-weight: 600;\n"
        "  font-style: normal;\n"
        "}\n"
        "@font-face {\n"
        "  font-family: 'GeoReportCJK';\n"
        f"  src: url('{bold_uri}') format('truetype');\n"
        "  font-weight: 700;\n"
        "  font-style: normal;\n"
        "}"
    )
