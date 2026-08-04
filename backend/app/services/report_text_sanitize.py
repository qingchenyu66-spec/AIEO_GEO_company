"""报告展示文本清洗：过滤引用标题/名称中的脚本与 SEO 垃圾。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_JS_RE = re.compile(
    r"window\.\w+\s*=\s*[^;]+;?|document\.\w+|function\s*\(|=>|Date\.now\s*\(\s*\)|var\s+\w+\s*=",
    re.I,
)


def _domain_from_url(url: str | None) -> str | None:
    text = str(url or "").strip()
    if not text:
        return None
    try:
        host = urlparse(text).netloc or urlparse(f"https://{text}").netloc
    except Exception:
        return None
    host = host.lower().removeprefix("www.")
    return host or None


def _looks_like_seo_spam(text: str) -> bool:
    return len(text) >= 96 or text.count("/") >= 3 or text.count("-") >= 8


_GARBAGE_TITLE_RE = re.compile(
    r"摩洛哥|点球大战|世界杯|欧冠|彩票|博彩|淘汰荷兰|淘汰赛",
    re.I,
)


def _looks_like_irrelevant_title(text: str) -> bool:
    """明显与行业无关的抓取标题（体育/杂讯等）。"""
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _GARBAGE_TITLE_RE.search(stripped):
        return True
    # ponytail: 形如「1摩洛哥…新」的 SEO/杂讯前缀，无 URL 时直接丢弃
    return bool(re.match(r"^\d+\S{0,3}[\u4e00-\u9fff]{2,24}(?:新|热|爆)?$", stripped))


def sanitize_source_title(title: str | None, url: str | None = None, *, max_len: int = 80) -> str:
    """清洗引用信源标题；无法识别时回退为域名。"""
    domain = _domain_from_url(url)
    raw = str(title or "").strip()
    if not raw or raw.startswith("http"):
        return domain or raw or "未知信源"

    text = _TAG_RE.sub(" ", raw)
    text = _JS_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip(" ;，,")
    if _JS_RE.search(text):
        text = _JS_RE.sub(" ", text)
        text = _WS_RE.sub(" ", text).strip(" ;，,")

    if _looks_like_irrelevant_title(text):
        return domain or ""
    if not text or _looks_like_seo_spam(text):
        return domain or text[:max_len] or "未知信源"
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


def consolidate_top_sources(rows: list[dict[str, Any]], *, limit: int = 12) -> list[dict[str, Any]]:
    """按清洗后标题合并引用次数，并过滤无法识别的杂讯信源。"""
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        url = row.get("url")
        title = sanitize_source_title(row.get("title"), url)
        if not title:
            continue
        bucket = merged.setdefault(
            title,
            {"title": title, "url": url, "count": 0, "platforms": []},
        )
        bucket["count"] += int(row.get("count") or 0)
        if url and not bucket.get("url"):
            bucket["url"] = url
        for platform in row.get("platforms") or []:
            if platform not in bucket["platforms"]:
                bucket["platforms"].append(platform)
    return sorted(merged.values(), key=lambda item: item["count"], reverse=True)[:limit]


def sanitize_entity_name(name: str | None, *, max_len: int = 64) -> str:
    """清洗排名/提及表中的品牌名称。"""
    raw = str(name or "").strip()
    if not raw:
        return ""
    text = _TAG_RE.sub(" ", raw)
    text = _JS_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    if not text or _JS_RE.search(text):
        return ""
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


_GARBAGE_SOURCE_RE = re.compile(
    r"摩洛哥|点球大战|window\.|Date\.now|1摩洛哥[^<\"]{0,40}",
    re.I,
)


def soften_diagnosis_goal_phrasing(text: str | None) -> str:
    """把「N天内提升至X% / 60天目标Y%」收成对外可解释的首要目标区间句。

    2026-08-04 - 客户交付忌死日期+单点承诺 - 统一「首要目标：争取将…提到约A%～B%」
    先剥标签再改写，避免 <strong>40%以上</strong> 等夹标签导致正则落空。
    """
    raw = str(text or "")
    if not raw:
        return ""

    def _pct_range(low: float, high: float | None = None) -> str:
        a = float(low)
        b = float(high) if high is not None else min(100.0, a + 10.0)
        if b < a:
            a, b = b, a

        def _fmt(v: float) -> str:
            return str(int(v)) if abs(v - int(v)) < 1e-6 else f"{v:.1f}".rstrip("0").rstrip(".")

        if abs(a - b) < 1e-6:
            b = min(100.0, a + 10.0)
        return f"{_fmt(a)}%～{_fmt(b)}%"

    def _soften_plain_goal(plain: str) -> str | None:
        s = plain.strip()
        if not s.endswith(("。", ".")):
            s = s + "。"
        m = re.search(
            r"目标\s*[:：]\s*\d+\s*天内[，,]?提及率争取提升至\s*"
            r"(\d+(?:\.\d+)?)\s*%\s*以上\s*[，,]\s*\d+\s*天目标\s*(\d+(?:\.\d+)?)\s*%"
            r"(?P<tail>[^。]*)[。.]",
            s,
        )
        if m:
            return f"首要目标：争取将提及率提到约{_pct_range(float(m.group(1)), float(m.group(2)))}{m.group('tail')}。"
        m = re.search(
            r"目标\s*[:：]\s*\d+\s*天内[，,]?提及率争取(?:提升至|稳定在)\s*"
            r"(\d+(?:\.\d+)?)\s*%\s*(?:以上)?"
            r"(?P<tail>[，,][^。]*)?[。.]",
            s,
        )
        if m:
            return f"首要目标：争取将提及率提到约{_pct_range(float(m.group(1)))}{m.group('tail') or ''}。"
        m = re.search(
            r"目标\s*[:：]\s*\d+\s*天内[，,]?均排争取(?:进入|提升至|提到)\s*"
            r"(\d+(?:\.\d+)?)\s*以内"
            r"(?P<tail>[^。]*)[。.]",
            s,
        )
        if m:
            return f"首要目标：争取将均排提到约{m.group(1)}以内{m.group('tail')}。"
        m = re.search(
            r"目标\s*[:：]\s*\d+\s*天内[，,]?品牌相关引用占比(?:提升至|提到)\s*"
            r"(\d+(?:\.\d+)?)\s*%\s*(?:以上)?"
            r"(?P<tail>[^。]*)[。.]",
            s,
        )
        if m:
            return (
                f"首要目标：争取将品牌相关引用占比提到约"
                f"{_pct_range(float(m.group(1)))}{m.group('tail')}。"
            )
        return None

    def _repl_goal_chunk(match: re.Match[str]) -> str:
        chunk = match.group(0)
        plain = _TAG_RE.sub("", chunk)
        softened = _soften_plain_goal(plain)
        return softened if softened else chunk

    raw = re.sub(r"目标\s*[:：](?:[^。<]|<[^>]+>)*[。.]", _repl_goal_chunk, raw)

    def _repl_from_to(match: re.Match[str]) -> str:
        plain = _TAG_RE.sub("", match.group(0))
        m = re.search(
            r"提及率从\s*(\d+(?:\.\d+)?)\s*%\s*提升至\s*(\d+(?:\.\d+)?)\s*%",
            plain,
        )
        if not m:
            return match.group(0)
        return f"提及率从{m.group(1)}%争取提到约{_pct_range(float(m.group(2)))}"

    raw = re.sub(
        r"提及率从(?:[^<%]|<[^>]+>)*%\s*提升至(?:[^<%]|<[^>]+>)*%",
        _repl_from_to,
        raw,
    )
    return raw


def sanitize_analysis_html(html: str | None) -> str:
    """清洗 AI 解读 HTML；编号句拆成列表；短段标记不缩进。"""
    from html import escape as html_escape

    text = str(html or "").strip()
    if not text:
        return ""
    text = _JS_RE.sub(" ", text)
    text = _GARBAGE_SOURCE_RE.sub("相关聚合页", text)
    text = soften_diagnosis_goal_phrasing(text)

    # 2026-08-04 - 勿把 52.7% / 1.7 均排里的小数点当成「1. 2.」编号列表（否则分页碎成「整体提及率」「7%」）
    _num_item = r"\d+[\.、．](?!\d)\s*"

    def _expand_p(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        plain = _TAG_RE.sub("", inner)
        plain = _WS_RE.sub(" ", plain).strip()
        numbered = re.findall(_num_item, plain)
        if len(numbered) >= 2:
            parts = re.split(
                rf"(?:(?<=^)|(?<=\s)|(?<=[。；;])){_num_item}",
                plain,
            )
            items = [p.strip(" ；;，,") for p in parts if p and p.strip(" ；;，,")]
            if len(items) >= 2:
                lis = "".join(f"<li>{html_escape(item)}</li>" for item in items[:12])
                return f"<ol>{lis}</ol>"
        cls = "para--short"
        return f'<p class="{cls}">{inner}</p>'

    text = re.sub(r"<p[^>]*>(.*?)</p>", _expand_p, text, flags=re.I | re.S)
    return text.strip()
