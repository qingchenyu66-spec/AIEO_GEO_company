"""Parse brand ranks from AI answers: category-local rank first, else appearance order."""

from __future__ import annotations

import re
from typing import Any, Callable

from app.services.report_text_sanitize import sanitize_entity_name

CIRCLE_NUM_MAP = {
    "①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5,
    "⑥": 6, "⑦": 7, "⑧": 8, "⑨": 9, "⑩": 10,
    "⑪": 11, "⑫": 12,
}

CHINESE_NUM_MAP = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

LIST_ITEM_RE = re.compile(
    r"^\s*(?:"
    r"(\d+)\s*[\.、．\)）]|"
    r"[（(](\d+)[)）]|"
    r"([①②③④⑤⑥⑦⑧⑨⑩⑪⑫])"
    r")\s*(.+)$"
)

BULLET_ITEM_RE = re.compile(r"^[-*•·▪]\s*(.+)$")

PROSE_RANK_RE = re.compile(
    r"第([一二三四五六七八九十\d]+)[个位名项]?[，,：:\s]+([^，,。；;\n]{2,50})"
)

MARKDOWN_HEADER_RE = re.compile(r"^(#+)\s*(.+)$")
NUMBERED_TITLE_RE = re.compile(r"^(\d+)\s*[\.、．]\s*(.+)$")
SECTION_TITLE_RE = re.compile(r"^[一二三四五六七八九十百]+[、.．]\s*\S")

SUBSECTION_LABELS = frozenset({
    "特点", "适用", "适用人群", "优势", "短板", "特色", "定位", "覆盖", "适合",
    "核心场景", "覆盖规模", "核心优势", "投放建议", "快速选型",
})


def _clean_item_name(text: str) -> str:
    value = re.sub(r"\*\*", "", text or "")
    value = re.sub(r"\[\[[^\]]+\]\]", "", value)
    value = re.sub(r"\[[^\]]+\]\([^)]+\)", "", value)
    value = re.sub(r"^[「『\"'“]+|[」』\"'”]+$", "", value.strip())
    value = re.sub(r"[（(].*?[)）]$", "", value.strip())
    value = re.sub(r"[：:，,;；\.。]+$", "", value.strip())
    return value.strip()


def _parse_rank_token(token: str | None) -> int | None:
    text = str(token or "").strip()
    if not text:
        return None
    if text in CIRCLE_NUM_MAP:
        return CIRCLE_NUM_MAP[text]
    if text.isdigit():
        try:
            return int(text)
        except ValueError:
            return None
    if len(text) == 1 and text in CHINESE_NUM_MAP:
        return CHINESE_NUM_MAP[text]
    if text.startswith("十") and len(text) == 2 and text[1] in CHINESE_NUM_MAP:
        return 10 + CHINESE_NUM_MAP[text[1]]
    return None


def _coerce_rank_number(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if not text:
        return None
    parsed = _parse_rank_token(text)
    if parsed is not None:
        return parsed
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _is_markdown_table_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("|") and "|" in stripped[1:]:
        return True
    return bool(re.match(r"^[\|\s:\-]+$", stripped))


def _split_combined_header_brands(text: str) -> list[str]:
    """### 艾迪亚控股、澜翼传媒、麦迪威广告 → 多个品牌名（同段并列排名）。"""
    cleaned = re.sub(r"^#+\s*", "", (text or "").strip())
    cleaned = re.sub(r"^\d+[\.、．]\s*", "", cleaned)
    if not cleaned or ("、" not in cleaned and "，" not in cleaned):
        return []
    # 一、行业双寡头 这类章节标题不要拆成多个品牌
    if SECTION_TITLE_RE.match(cleaned):
        return []
    parts = re.split(r"[、，,]", cleaned)
    names = [_clean_item_name(part.strip()) for part in parts if part.strip()]
    if len(names) < 2:
        return []
    if any(len(name) > 36 for name in names):
        return []
    return names


def _strip_category_prefix(text: str) -> str:
    return re.sub(r"^[一二三四五六七八九十百]+[、.．]\s*", "", text.strip()).strip()


def _parse_markdown_header(line: str) -> tuple[int, str] | None:
    match = MARKDOWN_HEADER_RE.match(line.strip())
    if not match:
        return None
    return len(match.group(1)), match.group(2).strip()


def _is_subsection_label(content: str) -> bool:
    cleaned = re.sub(r"^[一二三四五六七八九十\d]+[\.、．]\s*", "", content).strip()
    head = cleaned.split("：", 1)[0].split(":", 1)[0].strip()
    return head in SUBSECTION_LABELS or any(cleaned.startswith(label) for label in SUBSECTION_LABELS)


def _next_section_rank(counters: dict[str | None, int], section: str | None) -> int:
    counters[section] = counters.get(section, 0) + 1
    return counters[section]


def _is_category_header(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 80:
        return False
    if LIST_ITEM_RE.match(stripped) or BULLET_ITEM_RE.match(stripped):
        return False
    header = _parse_markdown_header(stripped)
    if header:
        level, content = header
        if NUMBERED_TITLE_RE.match(content):
            return False
        if level >= 3 and not _is_subsection_label(content) and not SECTION_TITLE_RE.match(content):
            return False
        if level == 1:
            return False
        return True
    if re.match(r"^\*\*.+\*\*$", stripped):
        return True
    if re.match(r"^【.+】$", stripped):
        return True
    if re.match(r"^(?:分类|类别|类型|场景)[一二三四五六七八九十\d]+[：:]", stripped):
        return True
    if SECTION_TITLE_RE.match(stripped):
        content = re.sub(r"^[一二三四五六七八九十百]+[、.．]\s*", "", stripped)
        return len(content) <= 40 and not content.endswith("。")
    return False


def _extract_category_name(line: str) -> str:
    stripped = line.strip()
    for pattern in (
        r"^#{1,4}\s*(.+)$",
        r"^\*\*(.+?)\*\*$",
        r"^【(.+?)】$",
        r"^[一二三四五六七八九十百]+[、.．]\s*(.+)$",
        r"^(?:分类|类别|类型|场景)[一二三四五六七八九十\d]+[：:]\s*(.+)$",
    ):
        match = re.match(pattern, stripped)
        if match:
            return _strip_category_prefix(_clean_item_name(match.group(1)))
    return _strip_category_prefix(_clean_item_name(stripped))


def ranking_entry_category(entry: dict[str, Any]) -> str | None:
    for key in ("category", "group", "type", "section", "categoryName", "category_name"):
        value = entry.get(key)
        if value:
            return str(value).strip()
    return None


def ranking_entry_name(entry: dict[str, Any]) -> str:
    raw = str(
        entry.get("name")
        or entry.get("brandName")
        or entry.get("brand")
        or entry.get("keyword")
        or "",
    ).strip()
    return sanitize_entity_name(raw)


def ranking_entry_explicit_rank(entry: dict[str, Any]) -> int | float | None:
    for key in ("rank", "position", "rankNo", "mentionPosition"):
        value = entry.get(key)
        if value is None:
            continue
        coerced = _coerce_rank_number(value)
        if coerced is not None:
            return coerced
    return None


def normalize_structured_rankings(raw_entries: list[Any] | None) -> list[dict[str, Any]]:
    """Normalize API ranking JSON; fill missing ranks by appearance order within each category."""
    results: list[dict[str, Any]] = []
    appearance_counters: dict[str | None, int] = {}
    for raw in raw_entries or []:
        if not isinstance(raw, dict):
            continue
        name = ranking_entry_name(raw)
        if not name:
            continue
        category = ranking_entry_category(raw)
        rank_value = ranking_entry_explicit_rank(raw)
        if rank_value is None:
            appearance_counters[category] = appearance_counters.get(category, 0) + 1
            rank_value = appearance_counters[category]
        else:
            numeric = _coerce_rank_number(rank_value)
            if numeric is not None:
                appearance_counters[category] = max(appearance_counters.get(category, 0), int(numeric))
        results.append({"name": name, "rank": rank_value, "category": category})
    return results


def parse_answer_rankings(text: str) -> list[dict[str, Any]]:
    """Extract ranked list items from answer text, grouped by category when present."""
    if not text:
        return []

    normalized = re.sub(r"<[^>]+>", "\n", text)
    normalized = re.sub(r"\r", "\n", normalized)

    results: list[dict[str, Any]] = []
    current_category: str | None = None
    current_section: str | None = None
    appearance_counters: dict[str | None, int] = {}
    in_company_block = False

    def append_item(name: str, rank: int | None, *, category: str | None = None) -> None:
        cleaned = _clean_item_name(name)
        if not cleaned:
            return
        bucket = category if category is not None else (current_section or current_category)
        if rank is None:
            appearance_counters[bucket] = appearance_counters.get(bucket, 0) + 1
            rank = appearance_counters[bucket]
        else:
            appearance_counters[bucket] = max(appearance_counters.get(bucket, 0), rank)
        results.append({"name": cleaned, "rank": rank, "category": bucket})

    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _is_markdown_table_line(line):
            continue

        header = _parse_markdown_header(line)
        if header:
            level, content = header
            numbered = NUMBERED_TITLE_RE.match(content)
            if numbered:
                append_item(numbered.group(2), _next_section_rank(appearance_counters, current_section))
                in_company_block = True
                continue
            if level == 1:
                continue
            if level == 2 or SECTION_TITLE_RE.match(content):
                current_section = _extract_category_name(line)
                current_category = current_section
                appearance_counters.setdefault(current_section, 0)
                in_company_block = False
                continue
            combined = _split_combined_header_brands(content)
            if combined:
                for index, name in enumerate(combined, 1):
                    append_item(name, index, category=current_section or current_category)
                in_company_block = True
                continue
            if _is_subsection_label(content):
                current_category = _extract_category_name(line)
                in_company_block = True
                continue
            append_item(content, _next_section_rank(appearance_counters, current_section))
            in_company_block = True
            continue

        if _is_category_header(line):
            category_name = _extract_category_name(line)
            combined = _split_combined_header_brands(category_name)
            if combined:
                for index, name in enumerate(combined, 1):
                    append_item(name, index, category=current_section or current_category)
                in_company_block = True
                continue
            current_section = category_name
            current_category = category_name
            appearance_counters.setdefault(current_category, 0)
            in_company_block = False
            continue

        if in_company_block:
            continue

        match = LIST_ITEM_RE.match(line)
        if match:
            rank = _parse_rank_token(match.group(1) or match.group(2) or match.group(3))
            append_item(match.group(4), rank)
            continue

        bullet = BULLET_ITEM_RE.match(line)
        if bullet:
            append_item(bullet.group(1), None)
            continue

    if not results:
        for match in PROSE_RANK_RE.finditer(normalized):
            rank = _parse_rank_token(match.group(1))
            append_item(match.group(2), rank)

    return results


def find_best_brand_rank(
    entries: list[dict[str, Any]],
    match_name: Callable[[str], bool],
    *,
    skip_name: Callable[[str], bool] | None = None,
) -> tuple[int | float | None, bool]:
    """Return best rank among matched entries; prefer category-local over flat global rank."""
    category_ranks: list[float] = []
    flat_ranks: list[float] = []
    matched = False
    for entry in entries:
        name = str(entry.get("name") or "").strip()
        if not name or not match_name(name):
            continue
        if skip_name and skip_name(name):
            continue
        matched = True
        rank = entry.get("rank")
        if rank is None:
            continue
        try:
            numeric = float(rank)
        except (TypeError, ValueError):
            continue
        if entry.get("category"):
            category_ranks.append(numeric)
        else:
            flat_ranks.append(numeric)
    if category_ranks:
        return min(category_ranks), True
    if flat_ranks:
        return min(flat_ranks), True
    return None, matched
