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

BULLET_ITEM_RE = re.compile(r"^[-•·▪]\s*(.+)$|^\*(?!\*)\s*(.+)$")

PROSE_RANK_RE = re.compile(
    r"第([一二三四五六七八九十\d]+)[个位名项]?[，,：:\s]+([^，,。；;\n]{2,50})"
)

MARKDOWN_HEADER_RE = re.compile(r"^(#+)\s*(.+)$")
NUMBERED_TITLE_RE = re.compile(r"^(\d+)\s*[\.、．]\s*(.+)$")
SECTION_TITLE_RE = re.compile(r"^[一二三四五六七八九十百]+[、.．]\s*\S")

SUBSECTION_LABELS = frozenset({
    "特点", "适用", "适用人群", "优势", "短板", "劣势", "特色", "定位", "覆盖", "适合",
    "核心场景", "覆盖规模", "核心优势", "服务能力", "服务", "资源", "资源能力",
    "投放建议", "快速选型", "核心能力", "适配场景", "覆盖面", "适用场景", "适合场景",
    "资质", "资质层面", "规模", "规模体量", "价格", "价格水平", "报价", "案例",
    "客户", "客户群", "要点", "建议", "总结", "对比", "说明", "简介", "劣势短板",
    "核心覆盖", "核心资源", "核心服务", "产品能力", "技术能力", "团队能力",
    "渠道能力", "品牌能力", "服务体系", "资源体系", "核心亮点", "主要优势",
    "资源覆盖", "服务特色", "特色服务", "适合客户", "适合对象", "适合需求",
    "覆盖范围", "服务范围", "服务优势", "服务特点", "资源规模", "资源真实性",
    "核心资质",
})
# 公司详情字段名：资质层面 / 规模体量 / XX能力 / XX优势… — 不是选手
_FIELD_LABEL_RE = re.compile(
    r"^("
    r"(?:核心|主要)?"
    r"(?:优势|亮点|短板|劣势|特点|特色|定位|资源|服务|能力|规模|价格|报价|"
    r"案例|客户|资质|要点|建议|总结|对比|说明|简介|覆盖|适合|适用)"
    r"(?:能力|层面|维度|方面|体量|水平|优势|体系|群|场景|规模|范围|覆盖|"
    r"特色|真实性|对象|需求|客户|亮点)?"
    r"|(?:适用|适合|适配)(?:场景|客户|对象|需求|人群)"
    r"|(?:服务|资源|产品|渠道|品牌|技术|团队)"
    r"(?:能力|特色|特点|优势|规模|范围|覆盖|体系|真实性)"
    r"|投放建议|快速选型|覆盖面|覆盖规模|覆盖范围"
    r")$"
)
# 学科/学习项误入榜（教育类正文），不当作公司
_NON_COMPANY_TOKENS = frozenset({
    "语文", "数学", "英语", "物理", "化学", "生物", "历史", "地理", "政治",
    "单词", "作文", "阅读", "听力", "口语", "语法", "古诗", "文言文",
})
_SUBCATEGORY_HINTS = (
    "大厂", "工程商", "运营商", "代理商", "服务商", "制造商", "厂家", "媒体",
    "头部", "区域", "性价比", "上市", "量产", "工程", "本地",
)


_REGION_LABEL_RE = re.compile(
    r"^(?:"
    r"华东|华南|华西|华北|华中|西南|西北|东北|其他|其他强市|"
    r"北京|上海|广州|深圳|杭州|成都|重庆|武汉|西安|南京|天津|苏州|济南|合肥|"
    r"[\u4e00-\u9fff]{1,3}(?:省|市|区)?"
    r")$"
)
_NON_RANK_CATEGORY_HINTS = (
    "判断标准", "挑选", "如何选", "怎么选", "注意事项", "总结", "结语",
    "核心判断", "选型建议", "快速对照", "快速参考", "对照",
)
_SENTENCE_NAME_HINTS = (
    "有优势", "而不", "优先问", "好的公司", "能否提供", "在一线", "适合区域", "适合全国",
    "→", "->", "只投", "预算有限",
    "擅长", "售后", "漏刊", "无多层", "案例极", "审批", "上刊", "运维", "补刊",
    "授权", "转包", "监测", "落地",
)
_CORP_NAME_HINTS = (
    "公司", "集团", "控股", "股份", "有限", "传媒", "广告", "媒体", "科技", "网络",
    "商社", "银行", "证券", "保险", "医院", "大学", "学院",
)


def _normalize_answer_layout(text: str) -> str:
    """Split inline bullets / headers crushed onto one line (yuanbao/doubao HTML export)."""
    normalized = re.sub(r"<[^>]+>", "\n", text or "")
    normalized = re.sub(r"\r", "\n", normalized)
    # [citation:5]## 下一节 — 勿拆行内正常的 ### 标题（### 会被拆成 #\n##）
    normalized = re.sub(r"(?<=[^\s#])(#{2,4}\s+)", r"\n\1", normalized)
    normalized = re.sub(r"(\[[^\]]*\])\s*-\s*", r"\1\n- ", normalized)
    normalized = re.sub(r"(?<=[。；！？])-\s*", "\n- ", normalized)
    # ponytail: `-**Name**` / `...- **Name**` without newline
    normalized = re.sub(r"(?<=\S)-\s*\*\*", "\n- **", normalized)
    normalized = re.sub(r"(?<=\S)-\s+(?=\*\*)", "\n- ", normalized)
    return normalized


def _clean_item_name(text: str) -> str:
    value = re.sub(r"\*\*", "", text or "")
    value = re.sub(r"\[\[[^\]]+\]\]", "", value)
    value = re.sub(r"\[[^\]]+\]\([^)]+\)", "", value)
    value = re.sub(r"\[citation:\d+\]", "", value, flags=re.I)
    value = re.sub(r"^[*·•▪]+", "", value.strip())
    value = re.sub(r"^[「『\"'“]+|[」』\"'”]+$", "", value.strip())
    value = re.sub(r"[（(].*?[)）]$", "", value.strip())
    value = re.sub(r"[：:，,;；\.。]+$", "", value.strip())
    return value.strip()


def _looks_like_company_list_name(name: str) -> bool:
    cleaned = str(name or "").strip()
    if not cleaned or len(cleaned) > 40:
        return False
    if any(hint in cleaned for hint in _SENTENCE_NAME_HINTS):
        return False
    if any(ch in cleaned for ch in "，。；！？"):
        return False
    if cleaned.startswith("看") and "：" not in cleaned:
        return False
    # 长句且无公司后缀 → 描述文案，不是选手
    if len(cleaned) > 14 and not any(hint in cleaned for hint in _CORP_NAME_HINTS):
        return False
    return True


def _is_non_rank_category(category: str | None) -> bool:
    text = str(category or "").strip()
    return bool(text) and any(hint in text for hint in _NON_RANK_CATEGORY_HINTS)


def _extract_list_item_name(text: str) -> str:
    """Extract company name from bullet: **公司**：说明 / 西南：公司 / 公司：说明."""
    raw = re.sub(r"^[-•·▪*]\s*", "", (text or "").strip())
    # **公司名** / **公司名**：说明（优先，避免被「地区：公司」规则抢成描述句）
    bold = re.match(r"^\*\*([^*]+)\*\*", raw)
    if bold:
        company = re.split(r"[（(]", bold.group(1).strip())[0].strip()
        company = re.split(r"[、，,/／]", company)[0].strip()
        cleaned = _clean_item_name(company)
        if cleaned:
            return cleaned
    # 西南：艾迪亚控股 — 仅当冒号前是地区/城市短标签
    region_match = re.match(r"^([^：:\n]{1,10})[：:]\s*(.+)$", raw)
    if region_match:
        head = _clean_item_name(region_match.group(1))
        if head and _REGION_LABEL_RE.match(head):
            tail = region_match.group(2).strip()
            tail = re.split(r"[（(]", tail)[0].strip()
            company = re.split(r"[、，,/／]", tail)[0].strip()
            cleaned = _clean_item_name(company)
            if cleaned:
                return cleaned
    # 公司名：长说明 → 取冒号前
    if "：" in raw or ":" in raw:
        head = re.split(r"[：:]", raw, maxsplit=1)[0].strip()
        head = re.split(r"[（(]", head)[0].strip()
        company = re.split(r"[、，,/／]", head)[0].strip()
        cleaned = _clean_item_name(company)
        if cleaned:
            return cleaned
    return _clean_item_name(raw)


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


def _is_table_separator_row(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    return bool(re.match(r"^[\|\s:\-]+$", stripped))


def _split_markdown_table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


_TABLE_COMPANY_HEADERS = ("企业名称", "公司名称", "公司名", "品牌名称", "机构名称")
_TABLE_COMPANY_FALLBACK = ("公司", "企业", "品牌")
_TABLE_RANK_HEADERS = ("排名", "序号", "位次", "rank", "no")


def _normalize_table_header(cell: str) -> str:
    return re.sub(r"\s+", "", _clean_item_name(cell)).casefold()


def _header_matches_company(column: str) -> bool:
    norm = _normalize_table_header(column)
    if any(token.casefold() in norm or norm in token.casefold() for token in _TABLE_COMPANY_HEADERS):
        return True
    return norm in {token.casefold() for token in _TABLE_COMPANY_FALLBACK}


def _header_matches_rank(column: str) -> bool:
    norm = _normalize_table_header(column)
    return any(token.casefold() in norm for token in _TABLE_RANK_HEADERS)


def _resolve_table_columns(header_cells: list[str]) -> tuple[int | None, int | None]:
    company_col: int | None = None
    rank_col: int | None = None
    for index, cell in enumerate(header_cells):
        if _header_matches_company(cell):
            company_col = index
        if _header_matches_rank(cell):
            rank_col = index
    if company_col is None:
        return None, None
    return company_col, rank_col


def _parse_markdown_table_block(
    lines: list[str],
    append_item: Callable[..., None],
    category: str | None,
) -> bool:
    """Parse company rows from a markdown table; rank by row order under category."""
    parsed_lines = [
        line.strip()
        for line in lines
        if line.strip() and not _is_table_separator_row(line)
    ]
    if len(parsed_lines) < 2:
        return False
    header_cells = _split_markdown_table_cells(parsed_lines[0])
    company_col, rank_col = _resolve_table_columns(header_cells)
    if company_col is None:
        return False
    row_rank = 0
    for row in parsed_lines[1:]:
        cells = _split_markdown_table_cells(row)
        if company_col >= len(cells):
            continue
        name = _clean_item_name(cells[company_col])
        if not name or _header_matches_company(name):
            continue
        row_rank += 1
        explicit_rank = None
        if rank_col is not None and rank_col < len(cells):
            explicit_rank = _parse_rank_token(cells[rank_col])
        append_item(name, explicit_rank if explicit_rank is not None else row_rank, category=category)
    return row_rank > 0


def _split_combined_header_brands(text: str) -> list[str]:
    """### 艾迪亚控股、澜翼传媒、麦迪威广告 → 多个品牌名（同段并列排名）。"""
    cleaned = re.sub(r"^#+\s*", "", (text or "").strip())
    cleaned = re.sub(r"^\d+[\.、．]\s*", "", cleaned)
    if not cleaned or ("、" not in cleaned and "，" not in cleaned):
        return []
    # 一、行业双寡头 这类章节标题不要拆成多个品牌
    if SECTION_TITLE_RE.match(cleaned):
        return []
    if _looks_like_subcategory_header(cleaned):
        return []
    head = re.sub(r"[（(][^）)]*[)）]", "", cleaned).strip()
    if "、" not in head and "，" not in head:
        return []
    parts = re.split(r"[、，,]", head)
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
    cleaned = re.sub(r"^\*\*|\*\*$", "", cleaned).strip()
    head = cleaned.split("：", 1)[0].split(":", 1)[0].strip()
    head = re.sub(r"^\*\*|\*\*$", "", head).strip()
    if head in SUBSECTION_LABELS or cleaned in SUBSECTION_LABELS:
        return True
    if _FIELD_LABEL_RE.match(head) or _FIELD_LABEL_RE.match(cleaned):
        return True
    return any(cleaned.startswith(label) for label in SUBSECTION_LABELS)


def _looks_like_subcategory_header(content: str) -> bool:
    """### 区域优质工程商 / 头部上市大厂 → 子分类标题，不是公司名。"""
    cleaned = re.sub(r"^[#\s\d\.、]+", "", (content or "").strip())
    cleaned = re.sub(r"[（(].*[)）]$", "", cleaned).strip()
    if not cleaned or NUMBERED_TITLE_RE.match(cleaned):
        return False
    if SECTION_TITLE_RE.match(cleaned):
        return True
    return any(hint in cleaned for hint in _SUBCATEGORY_HINTS)


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
    """Normalize API ranking JSON；有 category 时按段内出场序重排，忽略跨段连号。"""
    results: list[dict[str, Any]] = []
    appearance_counters: dict[str | None, int] = {}
    for raw in raw_entries or []:
        if not isinstance(raw, dict):
            continue
        name = ranking_entry_name(raw)
        if not name:
            continue
        # API/旧缓存也会把「核心优势」当成选手；与正文解析同一门禁
        if _is_subsection_label(name) or name in SUBSECTION_LABELS:
            continue
        if name in _NON_COMPANY_TOKENS:
            continue
        if not _looks_like_company_list_name(name):
            continue
        category = ranking_entry_category(raw)
        if category:
            appearance_counters[category] = appearance_counters.get(category, 0) + 1
            rank_value: int | float = appearance_counters[category]
        else:
            rank_value_opt = ranking_entry_explicit_rank(raw)
            if rank_value_opt is None:
                appearance_counters[None] = appearance_counters.get(None, 0) + 1
                rank_value = appearance_counters[None]
            else:
                rank_value = rank_value_opt
                numeric = _coerce_rank_number(rank_value)
                if numeric is not None:
                    appearance_counters[None] = max(appearance_counters.get(None, 0), int(numeric))
        results.append({"name": name, "rank": rank_value, "category": category})
    return results


def parse_answer_rankings(text: str) -> list[dict[str, Any]]:
    """Extract ranked list items from answer text, grouped by category when present."""
    if not text:
        return []

    normalized = _normalize_answer_layout(text)

    results: list[dict[str, Any]] = []
    current_category: str | None = None
    current_section: str | None = None
    appearance_counters: dict[str | None, int] = {}
    in_company_block = False

    def append_item(name: str, rank: int | None, *, category: str | None = None) -> None:
        cleaned = _extract_list_item_name(name)
        if not cleaned or not _looks_like_company_list_name(cleaned):
            return
        # 公司块下的「核心优势/服务能力」不是选手
        if _is_subsection_label(cleaned) or cleaned in SUBSECTION_LABELS:
            return
        if cleaned in _NON_COMPANY_TOKENS:
            return
        bucket = category if category is not None else (current_section or current_category)
        if _is_non_rank_category(bucket):
            return
        if rank is None:
            appearance_counters[bucket] = appearance_counters.get(bucket, 0) + 1
            rank = appearance_counters[bucket]
        else:
            appearance_counters[bucket] = max(appearance_counters.get(bucket, 0), rank)
        results.append({"name": cleaned, "rank": rank, "category": bucket})

    table_buffer: list[str] = []

    def flush_table_buffer() -> None:
        nonlocal table_buffer
        if not table_buffer:
            return
        _parse_markdown_table_block(
            table_buffer,
            append_item,
            current_section or current_category,
        )
        table_buffer = []

    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line:
            flush_table_buffer()
            continue
        if _is_markdown_table_line(line):
            table_buffer.append(line)
            continue
        flush_table_buffer()

        header = _parse_markdown_header(line)
        if header:
            level, content = header
            numbered = NUMBERED_TITLE_RE.match(content)
            if numbered:
                append_item(numbered.group(2), _next_section_rank(appearance_counters, current_section))
                in_company_block = True
                continue
            if level == 1:
                # `# 怎么选公司？` 不能直接跳过：否则 1~7 对照表仍挂在上一 ## 节，rank 被吃成 7
                cat = _extract_category_name(line)
                if _is_non_rank_category(cat):
                    current_section = cat
                    current_category = cat
                    appearance_counters.setdefault(current_section, 0)
                    in_company_block = False
                continue
            if level == 2 or SECTION_TITLE_RE.match(content):
                current_section = _extract_category_name(line)
                current_category = current_section
                appearance_counters.setdefault(current_section, 0)
                in_company_block = False
                continue
            if level == 3 and _looks_like_subcategory_header(content):
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
            # 同段下一家编号公司：结束上家详情块
            peer = LIST_ITEM_RE.match(line)
            if peer:
                append_item(peer.group(4), None)
                in_company_block = True
            continue

        match = LIST_ITEM_RE.match(line)
        if match:
            # 分段重排：段内按出场序计位；编号公司后进入详情块，忽略核心优势等 bullet
            before = len(results)
            append_item(match.group(4), None)
            if len(results) > before:
                in_company_block = True
            continue

        bullet = BULLET_ITEM_RE.match(line)
        if bullet:
            append_item(bullet.group(1) or bullet.group(2) or "", None)
            continue

    flush_table_buffer()

    if not results:
        for match in PROSE_RANK_RE.finditer(normalized):
            rank = _parse_rank_token(match.group(1))
            append_item(match.group(2), rank)

    return results


_SCOPE_NOISE_RE = re.compile(r"推荐|哪家好|哪个|怎么选|怎么样|排行|榜单|有哪些|是什么")
_MAJOR_SECTION_RE = re.compile(r"^[一二三四五六七八九十百]+[、.．]\s*\S")


def _scope_match_tokens(scope: str) -> list[str]:
    cleaned = _SCOPE_NOISE_RE.sub(" ", str(scope or ""))
    tokens: list[str] = []
    for match in re.finditer(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{2,}", cleaned):
        token = match.group(0).strip()
        if token and token not in tokens:
            tokens.append(token)
        # 机场广告公司 → 再切 机场/广告/公司，避免整词拼不上分段标题
        if len(token) >= 4 and re.fullmatch(r"[\u4e00-\u9fff]+", token):
            for size in (2, 3):
                for index in range(0, len(token) - size + 1):
                    piece = token[index:index + size]
                    if piece not in tokens:
                        tokens.append(piece)
    return tokens


def _text_overlap_score(left: str, right: str) -> int:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return -1
    if left_text == right_text:
        return 2000 + len(left_text)
    if left_text in right_text:
        return 1500 + len(left_text)
    if right_text in left_text:
        return 1400 + len(right_text)
    prefix = 0
    for left_char, right_char in zip(left_text, right_text):
        if left_char != right_char:
            break
        prefix += 1
    if prefix >= 4:
        return 500 + prefix
    left_fold = left_text.casefold()
    score = 0
    for token in _scope_match_tokens(right_text):
        if token.casefold() in left_fold:
            score += 100 + len(token)
    return score


def _scene_alignment_bonus(category: str, scope: str) -> int:
    category_text = str(category or "").casefold()
    scope_text = str(scope or "").casefold()
    bonus = 0
    media_scope = any(token in scope_text for token in ("广告", "传媒", "媒体", "大屏", "户外", "机场", "电梯"))
    factory_scope = any(token in scope_text for token in ("显示屏", "生产", "工程", "厂家", "厂商"))
    if media_scope and any(
        token in category_text
        for token in ("传媒", "媒体", "运营商", "广告", "户外", "大屏", "代理", "平台", "整合", "机场", "梯媒")
    ):
        bonus += 250
    if factory_scope and any(token in category_text for token in ("显示屏", "生产", "工程", "厂家", "厂商")):
        bonus += 250
    if media_scope and any(token in category_text for token in ("显示屏", "生产", "工程", "厂家", "厂商")):
        bonus -= 120
    if factory_scope and any(token in category_text for token in ("传媒", "媒体", "运营商", "户外")):
        bonus -= 120
    return bonus


def ranking_category_scope_score(category: str | None, scope: str) -> int:
    """Score how well a parsed category matches monitor keyword / prompt."""
    category_text = str(category or "").strip()
    scope_text = str(scope or "").strip()
    if not category_text or not scope_text:
        return -1
    direct = _text_overlap_score(category_text, scope_text)
    reverse = _text_overlap_score(scope_text, category_text)
    base = max(direct, reverse)
    bonus = _scene_alignment_bonus(category_text, scope_text)
    return base + bonus if base >= 0 else bonus


def _entries_in_scope(entries: list[dict[str, Any]], scope: str) -> tuple[list[dict[str, Any]], bool]:
    """Return entries whose category best matches scope; scoped=True when filter applied."""
    scope_text = str(scope or "").strip()
    if not scope_text:
        return entries, False
    categories = {str(entry.get("category") or "").strip() for entry in entries}
    categories.discard("")
    if not categories:
        return entries, False
    scores = {category: ranking_category_scope_score(category, scope_text) for category in categories}
    best = max(scores.values(), default=-1)
    if best < 100:
        return entries, False
    threshold = max(best * 0.45, 100)
    allowed = {category for category, score in scores.items() if score >= threshold}
    scoped = [entry for entry in entries if str(entry.get("category") or "").strip() in allowed]
    return scoped or entries, True


def find_best_brand_rank_scoped(
    entries: list[dict[str, Any]],
    match_name: Callable[[str], bool],
    scope: str,
    *,
    skip_name: Callable[[str], bool] | None = None,
) -> tuple[int | float | None, bool]:
    """同分段内：优先正文第一次出现；scope 只用来丢掉明显串段的后文命中。"""
    matched_entries: list[dict[str, Any]] = []
    for entry in entries:
        name = str(entry.get("name") or "").strip()
        if not name or not match_name(name):
            continue
        if skip_name and skip_name(name):
            continue
        if _is_non_rank_category(entry.get("category")):
            continue
        matched_entries.append(entry)
    if not matched_entries:
        return None, False

    scope_text = str(scope or "").strip()
    categorized = [
        entry for entry in matched_entries
        if str(entry.get("category") or "").strip()
    ]
    if scope_text and categorized:
        scores = {
            str(entry.get("category") or "").strip(): ranking_category_scope_score(
                str(entry.get("category") or "").strip(),
                scope_text,
            )
            for entry in categorized
        }
        best_score = max(scores.values(), default=-1)
        if best_score >= 100:
            threshold = max(best_score * 0.45, 100)
            preferred = {category for category, score in scores.items() if score >= threshold}
        else:
            preferred = set(scores)

        # 正文首次命中若在 preferred 内直接用；否则才在 preferred 里找第一次
        for entry in categorized:
            category = str(entry.get("category") or "").strip()
            if preferred and category not in preferred:
                continue
            rank = entry.get("rank")
            if rank is None:
                continue
            try:
                return float(rank), True
            except (TypeError, ValueError):
                continue

        # preferred 全无品牌：退回全文第一次（避免「整合代理」因缺「传媒」二字被踢掉后误吃区域第 9）
        for entry in categorized:
            rank = entry.get("rank")
            if rank is None:
                continue
            try:
                return float(rank), True
            except (TypeError, ValueError):
                continue

    return find_best_brand_rank(entries, match_name, skip_name=skip_name)


def _is_major_section_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    header = _parse_markdown_header(stripped)
    if header:
        level, content = header
        return level == 2 or bool(SECTION_TITLE_RE.match(content))
    return bool(_MAJOR_SECTION_RE.match(stripped))


def _is_rankable_content_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 120:
        return False
    if LIST_ITEM_RE.match(stripped) or BULLET_ITEM_RE.match(stripped):
        return True
    plain = re.sub(r"^\*+\s*|\*+$", "", stripped)
    return bool(NUMBERED_TITLE_RE.match(plain))


def appearance_order_rank_scoped(
    text: str,
    match_line: Callable[[str], bool],
    scope: str,
) -> int | None:
    """Rank within major sections that contain the brand; prefer scope-best section."""
    lines = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)).strip() for raw in text.splitlines()]
    scope_text = str(scope or "").strip()

    section_ranges: list[tuple[int, int, int]] = []
    current_start: int | None = None
    current_score = -1
    for index, line in enumerate(lines):
        if not line or not _is_major_section_line(line):
            continue
        if current_start is not None:
            section_ranges.append((current_start, index, current_score))
        current_start = index
        current_score = ranking_category_scope_score(_extract_category_name(line), scope_text) if scope_text else 0
    if current_start is not None:
        section_ranges.append((current_start, len(lines), current_score))

    def rank_in_range(start: int, end: int) -> int | None:
        order = 0
        for line in lines[start + 1:end]:
            if not line or _is_major_section_line(line):
                continue
            if not _is_rankable_content_line(line):
                continue
            order += 1
            if match_line(line):
                return order
        return None

    hits: list[tuple[int, int]] = []
    for start, end, score in section_ranges:
        rank = rank_in_range(start, end)
        if rank is not None:
            hits.append((score, rank))

    if hits:
        best_score = max(score for score, _ in hits)
        threshold = max(best_score * 0.45, 100) if scope_text else -1
        preferred = [rank for score, rank in hits if score >= threshold]
        if preferred:
            return min(preferred)
        return min(rank for _, rank in hits)

    order = 0
    for line in lines:
        if not _is_rankable_content_line(line):
            continue
        order += 1
        if match_line(line):
            return order
    return None


def find_best_brand_rank(
    entries: list[dict[str, Any]],
    match_name: Callable[[str], bool],
    *,
    skip_name: Callable[[str], bool] | None = None,
) -> tuple[int | float | None, bool]:
    """Return first document-order rank among matched entries; prefer categorized over flat."""
    category_rank: float | None = None
    flat_rank: float | None = None
    matched = False
    for entry in entries:
        name = str(entry.get("name") or "").strip()
        if not name or not match_name(name):
            continue
        if skip_name and skip_name(name):
            continue
        if _is_non_rank_category(entry.get("category")):
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
            if category_rank is None:
                category_rank = numeric
        elif flat_rank is None:
            flat_rank = numeric
    if category_rank is not None:
        return category_rank, True
    if flat_rank is not None:
        return flat_rank, True
    return None, matched
