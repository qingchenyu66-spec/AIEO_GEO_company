"""信源露出词匹配：本地字段不够时，HTTP 抓取引用页标题/摘要/正文片段。

2026-08-13 - 方案 A：标题无露出词、正文才有（如凤凰网）→ 抓网页补匹配
"""

from __future__ import annotations

import html
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ponytail: 进程内 LRU 用 dict；单日物化 URL 通常 < 几百，天花板可换 redis
_FETCH_BLOB_CACHE: dict[str, str] = {}
_FETCH_CACHE_MAX = 512

_TAG_RE = re.compile(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<[^>]+>", re.I)
_WS_RE = re.compile(r"\s+")
_META_RE = re.compile(
    r"""<meta\s+[^>]*(?:name|property)\s*=\s*["'](?:description|og:description|twitter:description)["'][^>]*>""",
    re.I,
)
_META_CONTENT_RE = re.compile(r"""content\s*=\s*["']([^"']+)["']""", re.I)
_TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.I)

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def citation_local_match_text(source: dict[str, Any]) -> str:
    """标题/站点/URL/摘要（不含抓取）。"""
    return " ".join(
        str(source.get(key) or "") for key in ("title", "site", "url", "summary")
    ).lower()


def matched_keywords_in_text(text: str, keywords: list[str]) -> list[str]:
    blob = (text or "").lower()
    if not blob or not keywords:
        return []
    return list(dict.fromkeys(kw for kw in keywords if kw and kw.lower() in blob))


def _strip_html_snippet(page_html: str, *, limit: int = 4000) -> str:
    text = _TAG_RE.sub(" ", page_html or "")
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    return text[:limit]


def _meta_snippets(page_html: str) -> list[str]:
    out: list[str] = []
    for tag in _META_RE.findall(page_html or ""):
        m = _META_CONTENT_RE.search(tag)
        if m:
            out.append(html.unescape(m.group(1)).strip())
    return out


def fetch_citation_match_blob(url: str, *, timeout_s: float = 8.0) -> str:
    """HTTP 抓取标题 + meta 摘要 + 正文片段；失败返回空串。"""
    value = str(url or "").strip()
    if not value.startswith(("http://", "https://")):
        return ""
    cached = _FETCH_BLOB_CACHE.get(value)
    if cached is not None:
        return cached
    blob = ""
    try:
        import httpx

        with httpx.Client(
            timeout=httpx.Timeout(timeout_s, connect=min(4.0, timeout_s)),
            follow_redirects=True,
            trust_env=False,
        ) as client:
            resp = client.get(
                value,
                headers={"User-Agent": _BROWSER_UA, "Accept-Language": "zh-CN,zh;q=0.9"},
            )
        if resp.status_code < 400:
            page_html = resp.text or ""
            title_m = _TITLE_RE.search(page_html)
            title = html.unescape(title_m.group(1)).strip() if title_m else ""
            parts = [title, *_meta_snippets(page_html), _strip_html_snippet(page_html)]
            blob = " ".join(p for p in parts if p).lower()
    except Exception as exc:  # noqa: BLE001
        logger.info("citation page fetch skipped url=%s err=%s", value[:120], exc)
        blob = ""
    if len(_FETCH_BLOB_CACHE) >= _FETCH_CACHE_MAX:
        _FETCH_BLOB_CACHE.clear()
    _FETCH_BLOB_CACHE[value] = blob
    return blob


def matched_source_keywords(
    source: dict[str, Any],
    keywords: list[str],
    *,
    allow_page_fetch: bool = False,
    fetch_budget: list[int] | None = None,
) -> list[str]:
    """露出词命中列表；allow_page_fetch 时本地未命中再抓网页。

    fetch_budget: 可变单元素列表 [剩余次数]，抓一次减一；None 表示不限制（仍受缓存）。
    """
    if not keywords:
        return []
    local = matched_keywords_in_text(citation_local_match_text(source), keywords)
    if local or not allow_page_fetch:
        return local
    url = str(source.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return []
    if fetch_budget is not None:
        if not fetch_budget or int(fetch_budget[0]) <= 0:
            return []
        fetch_budget[0] = int(fetch_budget[0]) - 1
    page_blob = fetch_citation_match_blob(url)
    return matched_keywords_in_text(page_blob, keywords)
