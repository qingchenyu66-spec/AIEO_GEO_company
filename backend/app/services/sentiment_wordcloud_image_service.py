"""品牌情绪词云图片生成（Python wordcloud + 中国地图蒙版，对齐优词云 fill 模式）。"""

from __future__ import annotations

import base64
import hashlib
import io
from functools import lru_cache
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image
from wordcloud import WordCloud

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
_MASK_PATH = _ASSETS_DIR / "masks" / "china-map-mask.png"

_POSITIVE_PALETTE = [
    "#2ecc71", "#27ae60", "#1abc9c", "#16a085", "#48c9b0",
    "#3498db", "#2980b9", "#5dade2", "#1f8dd6",
    "#9b59b6", "#8e44ad", "#6c3483", "#a569bd",
    "#e67e22", "#d35400", "#f39c12", "#e59866",
    "#e74c3c", "#c0392b", "#e84393", "#fd79a8",
    "#795548", "#a1887f", "#8d6e63",
    "#f1c40f", "#d4ac0d", "#f4d03f",
]

_NEGATIVE_PALETTE = [
    "#c0392b", "#e74c3c", "#e67e22", "#d35400", "#e84393",
    "#9b59b6", "#8e44ad", "#e59866", "#fd79a8", "#ff7675",
    "#fab1a0", "#e17055", "#d63031", "#b71540", "#eb4d4b",
    "#574b90", "#786fa6", "#cf6a87", "#a1887f", "#795548",
]

_FONT_CANDIDATES = [
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/simkai.ttf"),
    Path("C:/Windows/Fonts/STKAITI.TTF"),
    Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
]

_RENDER_SIDE = 1024
_UNIQUE_LIMIT = 20
_MAX_PHRASE_LEN = 14
_MIN_LAYOUT_FONT = 16


def _resolve_font_path() -> str | None:
    for candidate in _FONT_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return None


def _stable_color(text: str, polarity: Literal["positive", "negative"]) -> str:
    palette = _POSITIVE_PALETTE if polarity == "positive" else _NEGATIVE_PALETTE
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return palette[int(digest[:8], 16) % len(palette)]


@lru_cache(maxsize=1)
def _load_cropped_mask() -> tuple[np.ndarray, float]:
    """裁剪蒙版空白边距，使地图在画布中占比更大。"""
    raw = np.array(Image.open(_MASK_PATH).convert("RGB"))
    gray = raw[:, :, 0]
    coords = np.argwhere(gray < 200)
    if coords.size == 0:
        return raw, 1.0

    y0, x0 = coords.min(axis=0)
    y1, x1 = coords.max(axis=0)
    pad = 8
    y0 = max(0, int(y0) - pad)
    x0 = max(0, int(x0) - pad)
    y1 = min(raw.shape[0], int(y1) + pad)
    x1 = min(raw.shape[1], int(x1) + pad)
    cropped = raw[y0:y1, x0:x1]
    aspect = cropped.shape[1] / max(cropped.shape[0], 1)
    return cropped, aspect


def _effective_count(text: str, count: int) -> int:
    """长短语降权，避免被压成难以辨认的小字。"""
    extra = max(0, len(text) - 6)
    adjusted = int(round(count * (0.88 ** extra)))
    return max(1, adjusted)


def _build_frequencies(items: list[dict]) -> dict[str, int]:
    ranked: list[tuple[str, int, int]] = []
    for item in items:
        text = str(item.get("text") or "").strip()
        count = int(item.get("count") or 0)
        if not text or count <= 0 or len(text) > _MAX_PHRASE_LEN:
            continue
        ranked.append((text, _effective_count(text, count), count))

    ranked.sort(key=lambda row: (row[1], row[2], -len(row[0])), reverse=True)
    ranked = ranked[:_UNIQUE_LIMIT]

    frequencies: dict[str, int] = {}
    for text, effective, _raw in ranked:
        frequencies[text] = effective

    if not frequencies:
        return {}

    if len(frequencies) < 12:
        return {text: max(value, 4) for text, value in frequencies.items()}
    return frequencies


def _estimate_bbox(text: str, font_size: int, x: int, y: int, width: int, height: int) -> dict[str, float]:
    char_width = font_size * 0.92
    box_w = max(char_width * max(len(text), 1), font_size)
    box_h = font_size * 1.15
    left = max(0.0, (x - box_w * 0.45) / width)
    top = max(0.0, (y - box_h * 0.55) / height)
    return {
        "x": left,
        "y": top,
        "w": min(1.0 - left, box_w / width),
        "h": min(1.0 - top, box_h / height),
    }


def _trim_image_whitespace(pil_image: Image.Image, padding: int = 20) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """裁掉 PNG 四周留白，让词云在容器里视觉居中。"""
    gray = pil_image.convert("L")
    mask = gray.point(lambda value: 255 if value < 248 else 0)
    bbox = mask.getbbox()
    if not bbox:
        size = pil_image.size
        return pil_image, (0, 0, size[0], size[1])

    x0, y0, x1, y1 = bbox
    x0 = max(0, x0 - padding)
    y0 = max(0, y0 - padding)
    x1 = min(pil_image.width, x1 + padding)
    y1 = min(pil_image.height, y1 + padding)
    crop_box = (x0, y0, x1, y1)
    return pil_image.crop(crop_box), crop_box


def generate_sentiment_wordcloud_image(
    items: list[dict],
    *,
    polarity: Literal["positive", "negative"] = "positive",
    width: int = 900,
    height: int = 720,
    max_words: int = 120,
) -> dict:
    """生成中国地图词云 PNG（base64）及词条点击区域。"""
    if not _MASK_PATH.exists():
        raise FileNotFoundError("中国地图蒙版缺失")

    frequencies = _build_frequencies(items)
    if not frequencies:
        return {"image_base64": "", "width": width, "height": height, "placements": []}

    meta_by_text: dict[str, dict] = {}
    for item in items:
        text = str(item.get("text") or "").strip()
        if not text or len(text) > _MAX_PHRASE_LEN:
            continue
        current = meta_by_text.get(text)
        if current is None or int(item.get("count") or 0) > int(current.get("count") or 0):
            meta_by_text[text] = item

    font_path = _resolve_font_path()
    mask, _mask_aspect = _load_cropped_mask()

    safe_width = safe_height = _RENDER_SIDE

    def color_func(
        word: str,
        font_size: int | None = None,
        position: object = None,
        orientation: object = None,
        random_state: object = None,
        **kwargs: object,
    ) -> str:
        return _stable_color(word, polarity)

    word_cap = max(48, min(int(max_words), 80))
    if len(frequencies) <= 8:
        word_cap = min(word_cap, 64)

    wc = WordCloud(
        font_path=font_path,
        width=safe_width,
        height=safe_height,
        mask=mask,
        background_color="white",
        max_words=word_cap,
        repeat=True,
        relative_scaling=0.42,
        prefer_horizontal=1.0,
        min_font_size=_MIN_LAYOUT_FONT,
        max_font_size=72,
        color_func=color_func,
        collocations=False,
        scale=1.5,
        margin=2,
    )
    wc.generate_from_frequencies(frequencies)

    raw_image = wc.to_image()
    trimmed_image, crop_box = _trim_image_whitespace(raw_image)
    crop_x0, crop_y0, crop_x1, crop_y1 = crop_box
    out_width = max(1, crop_x1 - crop_x0)
    out_height = max(1, crop_y1 - crop_y0)

    buffer = io.BytesIO()
    trimmed_image.save(buffer, format="PNG", optimize=True)
    image_base64 = base64.b64encode(buffer.getvalue()).decode("ascii")

    placements: list[dict] = []
    for layout in wc.layout_:
        word = str(layout[0][0])
        font_size = int(layout[1])
        if font_size < _MIN_LAYOUT_FONT:
            continue
        x, y = int(layout[2][0]) - crop_x0, int(layout[2][1]) - crop_y0
        if x < -font_size or y < -font_size or x > out_width or y > out_height:
            continue
        meta = meta_by_text.get(word, {})
        bbox = _estimate_bbox(word, font_size, x, y, out_width, out_height)
        placements.append({
            "text": word,
            "count": int(meta.get("count") or frequencies.get(word, 0)),
            "subtask_id": str(meta.get("subtask_id") or ""),
            "task_id": str(meta.get("task_id") or ""),
            **bbox,
        })

    return {
        "image_base64": image_base64,
        "width": out_width,
        "height": out_height,
        "placements": placements,
    }
