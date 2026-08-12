"""客户定制「优化建议」Word → 监测幻灯 HTML（pack-item 拆页）。"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any, Iterator

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

_SECTION_RE = re.compile(r"^[一二三四五六]、")
_SUBHEAD_RE = re.compile(r"^.{1,24}：$")
_TABLE_ONLY_SECTIONS = frozenset({"三、", "四、"})
_TABLE_MAX_ROWS = 3
# 2026-08-06 - 微信稿前半是截图+序号批注，正文从「优化文字整体报告」或「一、」起
_BODY_START_RE = re.compile(r"^(优化文字整体报告|[一二三四五六]、)")


def _esc(text: str) -> str:
    return html.escape(str(text or "").strip())


def _is_opt_body_start(text: str, style: str = "") -> bool:
    t = str(text or "").strip()
    if _BODY_START_RE.match(t):
        return True
    return str(style or "").startswith("Heading") and bool(_SECTION_RE.match(t))


def _iter_body_blocks(doc: Document) -> Iterator[tuple[str, Any]]:
    """按 docx 正文顺序交替产出段落与表格。"""
    para_map = {id(p._element): p for p in doc.paragraphs}
    tbl_map = {id(t._tbl): t for t in doc.tables}
    for element in doc.element.body:
        tag = element.tag.split("}")[-1]
        if tag == "p":
            para = para_map.get(id(element))
            if para is None:
                continue
            text = str(para.text or "").strip()
            if not text:
                continue
            style = str(getattr(para.style, "name", "") or "")
            yield ("p", (style, text))
        elif tag == "tbl":
            table = tbl_map.get(id(element))
            if table is not None:
                yield ("table", table)


def _format_opt_cell(text: str, *, col_name: str = "") -> str:
    """单元格 HTML。推荐关键词列：一词一行。"""
    raw = str(text or "").strip()
    if not raw:
        return ""
    if "推荐关键词" in str(col_name or ""):
        # 2026-08-06 - 先按换行拆，避免「推荐、\\n防火…」被顿号拆丢「防」
        lines = [ln.strip().rstrip("、，,") for ln in raw.replace("\r", "").split("\n") if ln.strip()]
        if len(lines) >= 2:
            return "<br>".join(_esc(ln) for ln in lines)
        if re.search(r"[、，,]", raw):
            parts = [p.strip() for p in re.split(r"[、，,]+", raw) if p.strip()]
            return "<br>".join(_esc(p) for p in parts)
        return _esc(raw)
    if "\n" in raw or "<br>" in raw:
        bits = raw.replace("<br>", "\n").split("\n")
        return "<br>".join(_esc(b.strip()) for b in bits if b.strip())
    return _esc(raw)


def _table_rows(table: Table) -> tuple[list[str], list[list[str]]]:
    rows: list[list[str]] = []
    for row in table.rows:
        cells = [cell.text.strip() for cell in row.cells]
        if any(cells):
            rows.append(cells)
    if not rows:
        return [], []
    return rows[0], rows[1:]


def _first_col_rowspan_plan(body: list[list[str]]) -> list[int]:
    """空首列视为上一「选词方向」续行 → HTML rowspan（对齐 Word 观感）。"""
    n = len(body)
    plan = [1] * n
    i = 0
    while i < n:
        label = str(body[i][0] if body[i] else "").strip()
        if not label:
            plan[i] = 0
            i += 1
            continue
        j = i + 1
        while j < n and not str(body[j][0] if body[j] else "").strip():
            j += 1
        plan[i] = j - i
        for k in range(i + 1, j):
            plan[k] = 0
        i = j
    return plan


def _category_row_groups(body: list[list[str]]) -> list[list[list[str]]]:
    """按首列有值分组，保证「四大场景」续行与标题同行组。"""
    groups: list[list[list[str]]] = []
    cur: list[list[str]] = []
    for row in body:
        label = str(row[0] if row else "").strip()
        if label and cur:
            groups.append(cur)
            cur = [row]
        else:
            cur.append(row)
    if cur:
        groups.append(cur)
    return groups


def _render_table_html(head: list[str], body: list[list[str]]) -> str:
    if not head:
        return ""
    head_html = "".join(f"<th>{_esc(c)}</th>" for c in head)
    span_plan = _first_col_rowspan_plan(body) if head and "选词方向" in head[0] else [1] * len(body)
    body_html = ""
    for ri, row in enumerate(body):
        cells_html: list[str] = []
        for i, c in enumerate(row):
            col = head[i] if i < len(head) else ""
            cell_inner = _format_opt_cell(c, col_name=col)
            if i == 0 and span_plan[ri] == 0:
                continue
            attrs = ""
            cls = ""
            if i == 0:
                cls = ' class="opt-col-dir"'
                if span_plan[ri] > 1:
                    attrs = f' rowspan="{span_plan[ri]}"'
            elif "推荐关键词" in col:
                cls = ' class="opt-col-kw"'
            elif "推荐理由" in col:
                cls = ' class="opt-col-reason"'
            elif "优化建议" in col:
                cls = ' class="opt-col-tip"'
            cells_html.append(f"<td{cls}{attrs}>{cell_inner}</td>")
        body_html += "<tr>" + "".join(cells_html) + "</tr>"
    # 2026-08-06 - 关键词表对齐 Word：浅蓝表头+细线+首列合并，勿用 RankTable 圆角阴影
    table_cls = "opt-table opt-table--doc ranking-unit"
    if head and "选词方向" in head[0]:
        table_cls += " opt-table--keywords"
    return (
        '<div class="opt-table-wrap">'
        f'<table class="{table_cls}">'
        f"<thead><tr>{head_html}</tr></thead>"
        f"<tbody>{body_html}</tbody>"
        "</table></div>"
    )


def _render_text_section(title: str, card_bits: list[str]) -> str:
    inner = f'<div class="card-box">{"".join(card_bits)}</div>' if card_bits else ""
    return f'<div class="custom-opt-block"><h3 class="opt-section-title">{_esc(title)}</h3>{inner}</div>'


def optimization_part_slide_title(part_html: str, fallback: str = "优化建议") -> str:
    """pack 拆页后的外层 slide-title；勿与 tail 总标题混用导致 deck 误合并表。"""
    m = re.search(r'opt-section-title">([^<]+)', str(part_html or ""))
    if m:
        return html.unescape(m.group(1).strip())
    return fallback


def _continued_section_title(title: str) -> str:
    # 2026-08-06 - 客户要求去掉所有「（续）」；多页靠 slide 页码区分
    return str(title or "").strip().removesuffix("（续）").strip()


def _split_table_parts(title: str, table: Table, *, intro: str = "", max_rows: int = _TABLE_MAX_ROWS) -> list[str]:
    head, body = _table_rows(table)
    if not head or not body:
        return [_render_text_section(title, [_render_table_html(head, body)])]
    # 2026-08-06 - 小表不拆续页；5 行（如「四、已有词组」）一页装得下，勿拆成 3+2
    if len(body) <= 5:
        bits: list[str] = []
        if intro:
            bits.append(f'<p class="note">{_esc(intro)}</p>')
        bits.append(_render_table_html(head, body))
        return [_render_text_section(title, bits)]

    # 关键词表按「选词方向」组拆页，避免四大场景 rowspan 被拆散、空首列单独成页
    if head and "选词方向" in head[0]:
        groups = _category_row_groups(body)
        chunks: list[list[list[str]]] = []
        cur: list[list[str]] = []
        cur_groups = 0
        for group in groups:
            # 单组过大（四大场景 4 行）单独成页
            if len(group) >= 4 and cur:
                chunks.append(cur)
                cur = []
                cur_groups = 0
            if cur_groups >= 3 and cur:
                chunks.append(cur)
                cur = []
                cur_groups = 0
            cur.extend(group)
            cur_groups += 1
            if len(group) >= 4:
                chunks.append(cur)
                cur = []
                cur_groups = 0
        if cur:
            chunks.append(cur)
    else:
        chunks = []
        cur = []
        for row in body:
            cur.append(row)
            if len(cur) >= max_rows:
                chunks.append(cur)
                cur = []
        if cur:
            chunks.append(cur)

    parts: list[str] = []
    for idx, chunk in enumerate(chunks):
        bits: list[str] = []
        if idx == 0 and intro:
            bits.append(f'<p class="note">{_esc(intro)}</p>')
        bits.append(_render_table_html(head, chunk))
        parts.append(_render_text_section(title, bits))
    return parts


def docx_to_optimization_parts(docx_path: Path | str) -> list[str]:
    """每节/每表一块 pack-item HTML，避免合页裁切丢内容。"""
    path = Path(docx_path)
    if not path.is_file():
        raise FileNotFoundError(f"优化建议 docx 不存在: {path}")

    doc = Document(str(path))
    parts: list[str] = []
    section_title = ""
    card_bits: list[str] = []
    list_buf: list[str] = []
    pending_intro = ""
    started = False

    def _flush_list() -> None:
        nonlocal list_buf, card_bits
        if list_buf:
            card_bits.append('<ul class="opt-list">' + "".join(f"<li>{_esc(x)}</li>" for x in list_buf) + "</ul>")
            list_buf = []

    def _flush_text_section() -> None:
        nonlocal section_title, card_bits, list_buf
        if not section_title:
            return
        _flush_list()
        parts.append(_render_text_section(section_title, card_bits))
        section_title = ""
        card_bits = []

    for kind, payload in _iter_body_blocks(doc):
        if kind == "table":
            if not started:
                continue
            if section_title:
                prefix = section_title[:2]
                if prefix in _TABLE_ONLY_SECTIONS or pending_intro or not card_bits:
                    _flush_list()
                    parts.extend(_split_table_parts(section_title, payload, intro=pending_intro))
                    section_title = ""
                    card_bits = []
                    pending_intro = ""
                    continue
                card_bits.append(_render_table_html(*_table_rows(payload)))
                _flush_text_section()
            else:
                head, body = _table_rows(payload)
                parts.append(f'<div class="custom-opt-block">{_render_table_html(head, body)}</div>')
            continue

        style, text = payload
        # 2026-08-06 - 跳过截图区序号/批注，从「优化文字整体报告」或「一、」起读
        if not started:
            if _is_opt_body_start(text, style):
                started = True
                if text.startswith("优化文字整体报告"):
                    continue
            else:
                continue
        if text.startswith("优化文字整体报告"):
            continue

        is_section = style.startswith("Heading") or bool(_SECTION_RE.match(text))
        if is_section:
            _flush_text_section()
            section_title = text
            pending_intro = ""
            continue

        if _SUBHEAD_RE.match(text):
            _flush_list()
            # 2026-08-06 - 二节双 h4 拆页；六、总结合页勿拆
            has_prior_subsection = any("<h4>" in bit for bit in card_bits)
            keep_together = str(section_title or "").startswith("六、")
            if section_title and card_bits and has_prior_subsection and not keep_together:
                parts.append(_render_text_section(section_title, card_bits))
                section_title = _continued_section_title(section_title)
                card_bits = []
            card_bits.append(f"<h4>{_esc(text.rstrip('：'))}</h4>")
            continue

        if text.startswith("结合洁净厂房"):
            _flush_list()
            pending_intro = text
            continue

        if text.startswith("下季度优化"):
            _flush_list()
            card_bits.append(f'<p class="note">{_esc(text)}</p>')
            continue

        list_buf.append(text)

    _flush_text_section()
    return [p for p in parts if p.strip()]


def append_custom_optimization_docx(document, docx_path: Path | str) -> None:
    """deck Word 导出：按 docx 顺序写入定制优化建议。"""
    from docx.shared import Pt, RGBColor

    from app.services.report_period_deck_docx_service import _add_table, _section_title

    path = Path(docx_path)
    if not path.is_file():
        return
    src = Document(str(path))
    _section_title(document, "优化建议")
    started = False
    for kind, payload in _iter_body_blocks(src):
        if kind == "table":
            if not started:
                continue
            head, body = _table_rows(payload)
            if head:
                _add_table(document, head, body)
            continue
        style, text = payload
        if not started:
            if _is_opt_body_start(text, style):
                started = True
                if text.startswith("优化文字整体报告"):
                    continue
            else:
                continue
        if text.startswith("优化文字整体报告"):
            continue
        if style.startswith("Heading") or _SECTION_RE.match(text):
            p = document.add_paragraph(text)
            for run in p.runs:
                run.bold = True
                run.font.size = Pt(14)
                run.font.color.rgb = RGBColor(0x17, 0x40, 0x6A)
            continue
        if _SUBHEAD_RE.match(text):
            p = document.add_paragraph(text.rstrip("："))
            for run in p.runs:
                run.bold = True
            continue
        document.add_paragraph(text)


def optimization_parts_from_modules(content_modules: dict[str, Any] | None) -> list[str]:
    modules = content_modules or {}
    inline = modules.get("custom_optimization_parts")
    if isinstance(inline, list) and inline:
        return [str(x) for x in inline if str(x).strip()]
    docx_path = modules.get("custom_optimization_docx")
    if docx_path:
        return docx_to_optimization_parts(str(docx_path))
    return []
