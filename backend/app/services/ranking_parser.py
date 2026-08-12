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
    # 公司详情 / 选型段标题（常见被误当成选手）
    "成立时间", "注册资金", "一站式服务", "标杆项目", "全链条资质", "生产设备齐全",
    "选择建议", "补充推荐", "选择要点", "按需求类型选", "核实资质", "看案例",
    "价格透明", "媒体资源型", "技术创新型",
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
    r"|成立时间|注册资金|一站式服务|标杆项目|全链条资质|生产设备齐全"
    r"|选择建议|补充推荐|选择要点|按需求类型选"
    r")$"
)
# 「一、广州伟源光电科技有限公司」= 选手；「一、电梯广告公司」= 分类
# 「艾迪亚控股集团」等无「有限公司」后缀的简称也要认成选手
_COMPANY_ENTITY_HINT_RE = re.compile(
    r"(有限公司|股份有限公司|有限责任公司|集团有限|控股集团|集团$|股份公司|（集团）|株式会社|"
    r"Co\.,?\s*Ltd\.?|Inc\.?)"
)
# 学科/学习项误入榜（教育类正文），不当作公司
_NON_COMPANY_TOKENS = frozenset({
    "语文", "数学", "英语", "物理", "化学", "生物", "历史", "地理", "政治",
    "单词", "作文", "阅读", "听力", "口语", "语法", "古诗", "文言文",
    # 选型 checklist / 决策步骤 / 行业标签词，不是公司名
    "需求定义", "实地考察", "试点验证", "行业经验", "语种能力", "合规资质",
    "交付模式", "成本结构", "技术能力", "数据安全", "弹性", "资质",
    "金融", "保险", "电商", "通讯", "出海", "新零售", "跨境电商",
})
_SUBCATEGORY_HINTS = (
    "大厂", "工程商", "运营商", "代理商", "服务商", "制造商", "厂家", "媒体",
    "头部", "区域", "性价比", "上市", "量产", "工程", "本地",
    # 元宝「按梯队」：🥇一线 / 🥈本土全国代理 / 🥉策略购买型
    "一线", "二线", "三线", "梯队", "持有方", "全国代理", "购买型", "自营",
)
_TIER_MEDAL_RE = re.compile(r"^[🥇🥈🥉🏅]\s*")


_REGION_LABEL_RE = re.compile(
    r"^(?:"
    r"华东|华南|华西|华北|华中|西南|西北|东北|东南|其他|其他强市|本地|全国|"
    r"北京|上海|广州|深圳|杭州|成都|重庆|武汉|西安|南京|天津|苏州|济南|合肥|"
    # 须带省/市/区；不可选后缀，否则「利亚德」「艾比森」会被当成地区
    r"[\u4e00-\u9fff]{1,3}(?:省|市|区)"
    r")$"
)
_NON_RANK_CATEGORY_HINTS = (
    "判断标准", "挑选", "如何选", "怎么选", "注意事项", "总结", "结语",
    "核心判断", "选型建议", "快速对照", "快速参考", "对照",
    "关键考量", "决策路径", "评估", "checklist", "Checklist",
    "下一步", "建议的下一步", "维度", "关键问题",
    "选择建议", "补充推荐", "选择要点", "案例总结",
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
    # 2026-07-30 - markdown 表格内 <br> 若先剥成换行会拆断 | 行，品牌表只剩首行
    normalized = re.sub(r"<br\s*/?>", " ", text or "", flags=re.I)
    normalized = re.sub(r"<[^>]+>", "\n", normalized)
    normalized = re.sub(r"\r", "\n", normalized)
    # 元宝分享页：孤立「•」行后接「公司名：说明」——合成可解析 bullet
    # ponytail: 只合并空子弹行；编号清单 1.\\n1.\\n 另案，避免把「点位权属」抬成选手
    normalized = re.sub(
        r"(?m)^(?:[•·▪]\s*\n)+\s*(?=\S)",
        "- ",
        normalized,
    )
    # 粘连标题：`...[citation:5]## 下一节` 与 `...科技。##户外大屏` / `##二、全国`
    # ponytail: 行首正常标题不动；只拆「非空白后紧跟的 ##～######」
    normalized = re.sub(r"(?<=[^\s#\n])(#{2,6})(?=\s*\S)", r"\n\1", normalized)
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
    if _is_subsection_label(cleaned) or cleaned in SUBSECTION_LABELS:
        return False
    if cleaned in _NON_COMPANY_TOKENS:
        return False
    # A 类 / B类 / 区域强者 — 分类标签，不是选手
    if re.fullmatch(r"[A-Za-zＡ-Ｚａ-ｚ]?\s*类", cleaned) or cleaned.endswith("类") and len(cleaned) <= 4:
        return False
    if cleaned in {"区域强者", "全国强者", "本地强者", "行业强者"}:
        return False
    if "→" in cleaned or "->" in cleaned:
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


def _strip_numbered_heading_prefix(content: str) -> str | None:
    """Strip 一、 / 1. prefix; return body or None if not numbered."""
    text = str(content or "").strip()
    match = re.match(r"^[一二三四五六七八九十百]+[、.．]\s*(.+)$", text)
    if match:
        return match.group(1).strip()
    numbered = NUMBERED_TITLE_RE.match(text)
    if numbered:
        return numbered.group(2).strip()
    return None


def _company_from_numbered_heading(content: str) -> str | None:
    """「一、广州伟源光电科技有限公司（…）」→ 公司名；「一、电梯广告公司」→ None（分类）。"""
    body = _strip_numbered_heading_prefix(content)
    if not body:
        return None
    name = re.split(r"[（(]", body, maxsplit=1)[0].strip()
    name = _clean_item_name(name)
    if not name or _is_subsection_label(name) or name in SUBSECTION_LABELS:
        return None
    if not _COMPANY_ENTITY_HINT_RE.search(name):
        return None
    if not _looks_like_company_list_name(name):
        return None
    return name


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
    # 2026-08-12 - 分享页荣誉碎行「-」勿当 markdown 表行，否则会掐断 TSV 品牌表
    if "|" not in stripped:
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


_TABLE_COMPANY_HEADERS = (
    "企业名称",
    "公司名称",
    "公司名",
    "品牌名称",
    "机构名称",
    "代表公司",
    "代表厂商",
    "推荐公司",
    "供应商",
    "服务商",
    "供应商梯队",
    # 2026-08-12 - DeepSeek「系统名称|核心特点」产品表未认公司列 → 动码吃不到主表第5
    "系统名称",
    "产品名称",
    "产品名",
    "软件名称",
)
_TABLE_COMPANY_FALLBACK = ("公司", "企业", "品牌", "供应商", "服务商", "厂商")
_TABLE_COMPANY_HEADER_EXCLUDE = ("诉求", "红线", "场景", "能力", "标签", "适合", "指标", "数值", "说明", "特点")
_TABLE_RANK_HEADERS = ("排名", "序号", "位次", "rank", "no")
_TABLE_CATEGORY_LABEL_HINTS = ("梯队", "优先", "应对", "场景", "诉求", "头部人力", "驱动型", "科技驱动")


def _normalize_table_header(cell: str) -> str:
    return re.sub(r"\s+", "", _clean_item_name(cell)).casefold()


def _header_matches_company(column: str) -> bool:
    norm = _normalize_table_header(column)
    if not norm:
        return False
    if any(hint in norm for hint in _TABLE_COMPANY_HEADER_EXCLUDE):
        return False
    if any(token.casefold() in norm for token in _TABLE_COMPANY_HEADERS):
        return True
    # 2026-08-12 - 「系统/产品」「推荐品牌」等变体
    if "系统" in norm and any(x in norm for x in ("产品", "名称", "软件")):
        return True
    return any(token in norm for token in _TABLE_COMPANY_FALLBACK)


def _header_matches_rank(column: str) -> bool:
    raw = str(column or "")
    # 2026-08-12 - 「品牌名单（排名不分先后）」含「排名」勿当名次列；括号会被 clean 剥掉
    if "不分先后" in raw:
        return False
    norm = _normalize_table_header(column)
    return any(token.casefold() in norm for token in _TABLE_RANK_HEADERS)


def _table_headers_mark_unordered(header_cells: list[str]) -> bool:
    """表头声明名单无序时，格内/跨行出现序都不是推荐位次。

    2026-08-12 - _clean_item_name 会剥掉「（排名不分先后）」括号，须查原文
    """
    return any("不分先后" in str(cell or "") for cell in header_cells)


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


def _looks_like_table_category_label(name: str) -> bool:
    text = str(name or "").strip()
    if not text:
        return True
    if any(hint in text for hint in _TABLE_CATEGORY_LABEL_HINTS):
        return True
    if len(text) >= 4 and (text.endswith("型") or text.endswith("类")):
        return True
    if re.fullmatch(r".*(BPO|外包)$", text) and len(text) >= 6:
        return True
    return False


def _split_table_company_cell(cell: str) -> list[str]:
    """格内并列公司拆成名单（按出现顺序）；方案 B：位次=格内第几个。"""
    raw = str(cell or "").strip()
    if not raw:
        return []

    names: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        cleaned = _clean_item_name(value)
        if not cleaned or cleaned in seen:
            return
        if _looks_like_table_category_label(cleaned):
            return
        if not _looks_like_company_list_name(cleaned):
            return
        seen.add(cleaned)
        names.append(cleaned)

    # 优先：加粗公司名（表格常见 **泰盈**、**鸿联九五**）
    bolds = re.findall(r"\*\*([^*]+)\*\*", raw)
    if bolds:
        for item in bolds:
            add(item)
        if names:
            return names

    # （如A、B）/ （例如A、B）
    like = re.search(r"[（(](?:如|例如|比如)?([^）)]+)[)）]", raw)
    if like:
        for part in re.split(r"[、，,/]", like.group(1)):
            add(part)
        if names:
            return names

    # 去括号说明后按顿号拆
    stripped = re.sub(r"[（(][^）)]*[)）]", "", raw)
    if any(sep in stripped for sep in ("、", "，", ",")):
        for part in re.split(r"[、，,]", stripped):
            add(part)
        if names:
            return names

    add(raw)
    return names


def _parse_markdown_table_block(
    lines: list[str],
    append_item: Callable[..., None],
    category: str | None,
) -> bool:
    """Parse company rows from a markdown table; multi-name cells rank by in-cell order."""
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
    # 2026-08-12 - 「排名不分先后」多源名单勿摊成结构化名次（派雅被抬到10/25）
    if _table_headers_mark_unordered(header_cells):
        return True
    row_rank = 0
    parsed_any = False
    for row in parsed_lines[1:]:
        cells = _split_markdown_table_cells(row)
        if company_col >= len(cells):
            continue
        names = _split_table_company_cell(cells[company_col])
        if not names:
            continue
        explicit_rank = None
        if rank_col is not None and rank_col < len(cells):
            explicit_rank = _parse_rank_token(cells[rank_col])
        if len(names) == 1:
            row_rank += 1
            append_item(
                names[0],
                explicit_rank if explicit_rank is not None else row_rank,
                category=category,
            )
            parsed_any = True
            continue
        # 方案 B：格内并列按出现顺序记 1..n（展示仍是普通名次）
        for index, name in enumerate(names, 1):
            append_item(name, index, category=category)
            parsed_any = True
        row_rank += 1
    return parsed_any


def _split_tsv_cells(line: str) -> list[str]:
    return [cell.strip() for cell in str(line or "").split("\t")]


def _is_tsv_table_header_line(line: str) -> bool:
    """分享页制表符表头：品牌名称\\t核心特点\\t…

    2026-08-12 - 数据行「…领导品牌」含「品牌」勿当表头，否则公司列偏到描述列
    """
    if "\t" not in (line or ""):
        return False
    cells = _split_tsv_cells(line)
    if len(cells) < 2:
        return False
    company_col, _rank_col = _resolve_table_columns(cells)
    if company_col is None:
        return False
    header_cell = cells[company_col]
    norm = _normalize_table_header(header_cell)
    if not norm or len(norm) > 12:
        return False
    # 首列已是具体品牌名，且「品牌」命中在其它列 → 数据行
    first = _clean_item_name(cells[0])
    if (
        first
        and _looks_like_company_list_name(first)
        and company_col != 0
        and not any(token.casefold() in _normalize_table_header(cells[0]) for token in _TABLE_COMPANY_HEADERS)
        and _normalize_table_header(cells[0]) not in {"品牌", "企业", "公司", "厂商"}
    ):
        return False
    if any(token.casefold() in norm for token in _TABLE_COMPANY_HEADERS):
        return True
    if norm in {"品牌", "企业", "公司", "厂商", "机构"}:
        return True
    return False


def _is_tsv_table_noise_line(line: str) -> bool:
    """分享页表格被拆开的荣誉/脚注行，不当选手、也不结束表。"""
    text = str(line or "").strip()
    if not text:
        return True
    if "\t" in text:
        return False
    if text in {"-", "—", "–"}:
        return True
    if text.isdigit():
        return True
    if text.startswith(("、", "，", ",")):
        return True
    if re.match(r"^20\d{2}年", text) and len(text) <= 40:
        return True
    return False


def _tsv_row_company_names(line: str, company_col: int) -> list[str]:
    cells = _split_tsv_cells(line)
    if company_col >= len(cells):
        return []
    names = _split_table_company_cell(cells[company_col])
    # 表头噪声（偶发被当成数据行）
    skip = {
        _normalize_table_header(h)
        for h in (*_TABLE_COMPANY_HEADERS, "品牌", "企业", "公司")
    }
    return [
        name
        for name in names
        if _normalize_table_header(name) not in skip and not _looks_like_table_category_label(name)
    ]


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
    """### 区域优质工程商 / 🥇 一线… → 子分类标题，不是公司名。"""
    cleaned = re.sub(r"^[#\s\d\.、]+", "", (content or "").strip())
    cleaned = re.sub(r"[（(].*[)）]$", "", cleaned).strip()
    if not cleaned or NUMBERED_TITLE_RE.match(cleaned):
        return False
    if _TIER_MEDAL_RE.match(cleaned):
        return True
    cleaned = _TIER_MEDAL_RE.sub("", cleaned).strip()
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
    # 2026-08-12 - 分享页「主流门窗品牌榜单概览 / 实力品牌速览」无 # 也要当段
    if re.search(r"(?:榜单概览|品牌速览|实力品牌速览|主流门窗品牌)", stripped) and len(stripped) <= 60:
        return True
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

    # ponytail: 模力 allRankings 常整表 rank=1；无分段且同位次扎堆时按出场序重排
    unscoped = [row for row in results if not row.get("category")]
    if len(unscoped) >= 2:
        numeric_ranks: list[float] = []
        for row in unscoped:
            coerced = _coerce_rank_number(row.get("rank"))
            if coerced is not None:
                numeric_ranks.append(float(coerced))
        if len(numeric_ranks) == len(unscoped) and len(set(numeric_ranks)) == 1:
            for index, row in enumerate(unscoped, start=1):
                row["rank"] = index
    return results


def rankings_for_storage(
    answer: str | None,
    remote_rankings: list[Any] | None = None,
) -> list[dict[str, Any]] | None:
    """入库榜单：正文能分段则写段内序+category；否则规范化远端扁平榜。

    2026-07-27 - 模力 allRankings 跨段连号与段内名次冲突 - 持久化以正文分段为准
    """
    parsed = parse_answer_rankings(answer or "")
    if parsed:
        return [
            {
                "name": row.get("name"),
                "rank": row.get("rank"),
                "category": row.get("category"),
            }
            for row in parsed
            if row.get("name")
        ]
    remote_norm = normalize_structured_rankings(remote_rankings or [])
    return remote_norm or None


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
    # 2026-08-12 - DeepSeek 分享页制表符品牌表（非 markdown |）也要进结构化榜
    tsv_mode = False
    tsv_company_col = 0

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

    def end_tsv_mode() -> None:
        nonlocal tsv_mode, tsv_company_col
        tsv_mode = False
        tsv_company_col = 0

    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line:
            flush_table_buffer()
            # 分享页表行间常插空行/荣誉碎行，保持 tsv_mode
            continue
        if _is_markdown_table_line(line):
            end_tsv_mode()
            table_buffer.append(line)
            continue
        flush_table_buffer()

        # 已在 TSV 表内：先当数据行，避免描述含「品牌」被误判为新表头
        if tsv_mode and "\t" in line:
            names = _tsv_row_company_names(line, tsv_company_col)
            if names:
                for name in names:
                    append_item(name, None, category=current_section or current_category)
                continue

        if _is_tsv_table_header_line(line):
            cells = _split_tsv_cells(line)
            company_col, _rank_col = _resolve_table_columns(cells)
            if company_col is not None:
                tsv_mode = True
                tsv_company_col = company_col
            continue

        if tsv_mode:
            if _is_tsv_table_noise_line(line):
                continue
            # 非制表符：新段标题则结束表；短碎行跳过；长散文结束表后落入后续逻辑
            header = _parse_markdown_header(line)
            if header or _is_category_header(line) or LIST_ITEM_RE.match(line):
                end_tsv_mode()
            elif len(line) <= 40:
                continue
            else:
                end_tsv_mode()

        header = _parse_markdown_header(line)
        if header:
            end_tsv_mode()
            level, content = header
            numbered_company = _company_from_numbered_heading(content)
            if numbered_company:
                # ### 一、广州伟源光电科技有限公司（…）→ 选手，不是分类
                append_item(numbered_company, None)
                in_company_block = True
                continue
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
                # 选择建议 / 补充推荐：结束公司详情块，不当选手
                in_company_block = False
                if _is_non_rank_category(content) or content in SUBSECTION_LABELS:
                    current_section = _extract_category_name(line)
                    current_category = current_section
                continue
            # H3 不像公司名（梯队/描述标题）→ 当段重置，避免吞掉后续 bullet
            # ponytail: 旧逻辑一律 append_item，🥇一线 会被当成选手且 in_company_block 丢掉公司列表
            if level >= 3 and not _looks_like_company_list_name(
                _clean_item_name(_TIER_MEDAL_RE.sub("", content))
            ):
                current_section = _extract_category_name(line)
                current_category = current_section
                appearance_counters.setdefault(current_section, 0)
                in_company_block = False
                continue
            append_item(content, _next_section_rank(appearance_counters, current_section))
            in_company_block = True
            continue

        if _is_category_header(line):
            end_tsv_mode()
            stripped = re.sub(r"^\*\*|\*\*$", "", line.strip())
            stripped = re.sub(r"^【|】$", "", stripped).strip()
            numbered_company = _company_from_numbered_heading(stripped)
            if numbered_company:
                append_item(numbered_company, None)
                in_company_block = True
                continue
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
    end_tsv_mode()

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


_SCOPE_GENERIC_TOKENS = frozenset({
    "公司", "企业", "厂商", "品牌", "外包", "服务商", "推荐", "哪家", "哪个",
    "平台", "机构", "厂家",
})


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
        if token.casefold() not in left_fold:
            continue
        # 泛词（公司/外包）易把「国际知名…」「关键考量」打到同分，降权
        if token in _SCOPE_GENERIC_TOKENS:
            score += 20 + min(len(token), 2)
        else:
            score += 100 + len(token)
    return score


def _scene_alignment_bonus(category: str, scope: str) -> int:
    category_text = str(category or "").casefold()
    scope_text = str(scope or "").casefold()
    bonus = 0
    media_scope = any(token in scope_text for token in ("广告", "传媒", "媒体", "大屏", "户外", "机场", "电梯"))
    factory_scope = any(token in scope_text for token in ("显示屏", "生产", "工程", "厂家", "厂商"))
    bpo_scope = any(token in scope_text for token in ("呼叫中心", "外包", "客服", "bpo"))
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
    # 呼叫/外包类问题：本土/国内/性价比段优先于纯「云呼叫」产品段或选型 checklist
    if bpo_scope and any(token in category_text for token in ("本土", "中国", "国内", "亚太", "性价比", "外包商")):
        bonus += 280
    if bpo_scope and any(token in category_text for token in ("云呼叫", "技术驱动", "saas")):
        bonus -= 80
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


def _numeric_rank(entry: dict[str, Any]) -> float | None:
    rank = entry.get("rank")
    if rank is None:
        return None
    try:
        return float(rank)
    except (TypeError, ValueError):
        return None


def _pick_best_rank_entry(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """业务口径：多命中取名次最靠前（数字最小）的那条。"""
    best: dict[str, Any] | None = None
    best_rank: float | None = None
    for entry in entries:
        numeric = _numeric_rank(entry)
        if numeric is None:
            continue
        if best_rank is None or numeric < best_rank:
            best = entry
            best_rank = numeric
    return best


def find_best_brand_hit_scoped(
    entries: list[dict[str, Any]],
    match_name: Callable[[str], bool],
    scope: str,
    *,
    skip_name: Callable[[str], bool] | None = None,
) -> tuple[int | float | None, bool, dict[str, Any] | None]:
    """一次扫描：返回 (rank, matched, winning_entry)。"""
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
        return None, False, None

    categorized = [
        entry for entry in matched_entries
        if str(entry.get("category") or "").strip()
    ]
    winner = _pick_best_rank_entry(categorized or matched_entries)
    if winner is None:
        return None, True, None
    try:
        target = float(winner["rank"])
    except (TypeError, ValueError):
        return None, True, winner

    hits = [
        entry for entry in matched_entries
        if (numeric := _numeric_rank(entry)) is not None and float(numeric) == target
    ]
    if not hits:
        return target, True, winner
    scope_text = str(scope or "").strip()
    if scope_text and len(hits) > 1:
        hits_sorted = sorted(
            hits,
            key=lambda item: ranking_category_scope_score(
                str(item.get("category") or "").strip(),
                scope_text,
            ),
            reverse=True,
        )
        return target, True, hits_sorted[0]
    return target, True, hits[0]


def find_best_brand_rank_scoped(
    entries: list[dict[str, Any]],
    match_name: Callable[[str], bool],
    scope: str,
    *,
    skip_name: Callable[[str], bool] | None = None,
) -> tuple[int | float | None, bool]:
    """分段名次：多命中取最靠前；scope 用于同分时偏爱相关段，不用来抬高差名次。"""
    rank, matched, _entry = find_best_brand_hit_scoped(
        entries, match_name, scope, skip_name=skip_name,
    )
    return rank, matched


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


def _is_company_nomination_line(line: str) -> bool:
    """Appearance 只计「提名公司」的行，不计成立时间/核心优势等字段 bullet。"""
    stripped = line.strip()
    if not stripped or len(stripped) > 120:
        return False
    header = _parse_markdown_header(stripped)
    if header:
        return _company_from_numbered_heading(header[1]) is not None
    plain = re.sub(r"^\*\*|\*\*$", "", stripped).strip()
    if _company_from_numbered_heading(plain):
        return True
    list_match = LIST_ITEM_RE.match(stripped)
    if list_match:
        name = _extract_list_item_name(list_match.group(4))
        return bool(name) and _looks_like_company_list_name(name)
    bullet = BULLET_ITEM_RE.match(stripped)
    if bullet:
        name = _extract_list_item_name(bullet.group(1) or bullet.group(2) or "")
        if not name or not _looks_like_company_list_name(name):
            return False
        # 字段短标签已在 _looks_like_company_list_name 拦掉；无公司后缀的短词也不计
        return any(hint in name for hint in _CORP_NAME_HINTS) or bool(_COMPANY_ENTITY_HINT_RE.search(name))
    if NUMBERED_TITLE_RE.match(plain):
        name = _extract_list_item_name(NUMBERED_TITLE_RE.match(plain).group(2))
        return bool(name) and _looks_like_company_list_name(name)
    return False


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
            if not _is_company_nomination_line(line):
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
        if not _is_company_nomination_line(line):
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
    """Return best (smallest) rank among matched entries; prefer categorized over flat."""
    categorized: list[dict[str, Any]] = []
    flat: list[dict[str, Any]] = []
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
        if entry.get("category"):
            categorized.append(entry)
        else:
            flat.append(entry)
    winner = _pick_best_rank_entry(categorized) or _pick_best_rank_entry(flat)
    if winner is not None:
        return float(winner["rank"]), True
    return None, matched


def find_best_brand_entry_scoped(
    entries: list[dict[str, Any]],
    match_name: Callable[[str], bool],
    scope: str,
    *,
    skip_name: Callable[[str], bool] | None = None,
) -> dict[str, Any] | None:
    """同 find_best_brand_rank_scoped，返回取胜的那条（含 category）。"""
    _rank, _matched, entry = find_best_brand_hit_scoped(
        entries, match_name, scope, skip_name=skip_name,
    )
    return entry



