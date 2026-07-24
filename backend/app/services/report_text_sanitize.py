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


def sanitize_analysis_html(html: str | None) -> str:
    """清洗 AI 解读 HTML；编号句拆成列表；短段标记不缩进。"""
    from html import escape as html_escape

    text = str(html or "").strip()
    if not text:
        return ""
    text = _JS_RE.sub(" ", text)
    text = _GARBAGE_SOURCE_RE.sub("相关聚合页", text)

    def _expand_p(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        plain = _TAG_RE.sub("", inner)
        plain = _WS_RE.sub(" ", plain).strip()
        numbered = re.findall(r"\d+[\.、．]\s*", plain)
        if len(numbered) >= 2:
            parts = re.split(r"(?:(?<=^)|(?<=\s)|(?<=[。；;]))\d+[\.、．]\s*", plain)
            items = [p.strip(" ；;，,") for p in parts if p and p.strip(" ；;，,")]
            if len(items) >= 2:
                lis = "".join(f"<li>{html_escape(item)}</li>" for item in items[:12])
                return f"<ol>{lis}</ol>"
        cls = "para--short"
        return f'<p class="{cls}">{inner}</p>'

    text = re.sub(r"<p[^>]*>(.*?)</p>", _expand_p, text, flags=re.I | re.S)
    return text.strip()
