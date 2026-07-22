"""从 AI 分享页抓取回答正文与信源（补录用）。

当前以豆包 thread 分享页为主：SSR HTML 内嵌 search_query_result / text_card。
其它域名走通用正文抽取，信源尽力从外链收集。
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_ICON_HOST_BITS = (
    "byteimg.com",
    "doubao.com",
    "bytedance",
    "lf3-static",
    "lf-flow",
    "ibytedapm",
    "spider-image",
    "bytednsdoc",
    "p3-flow",
    "p11-flow",
    "p26-spider",
)

_UI_NOISE_EXACT = frozenset({
    "元宝",
    "反馈",
    "源",
    "登录",
})

_UI_NOISE_PHRASES = (
    "打开豆包",
    "内容由 AI 生成",
    "内容由AI生成",
    "已完成思考",
    "正在思考",
    "下载 App",
    "和元宝的对话",
    "和元宝继续聊",
)


@dataclass
class SharePageFetchResult:
    answer_content: str
    references: list[dict[str, Any]] = field(default_factory=list)
    title: str | None = None
    source_host: str | None = None


def _normalize_host(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


def _peel_escapes(text: str, *, rounds: int = 12) -> str:
    cur = html.unescape(text or "")
    for _ in range(rounds):
        nxt = cur.replace("\\\\", "\\")
        if nxt == cur:
            break
        cur = nxt
    cur = cur.replace("\\u002F", "/").replace("\\/", "/")
    cur = cur.replace('\\"', '"')
    return cur


def _is_icon_or_cdn(url: str) -> bool:
    low = (url or "").lower()
    return any(bit in low for bit in _ICON_HOST_BITS)


def _dedupe_refs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        url = str(row.get("url") or "").strip()
        title = str(row.get("title") or "").strip()
        site = str(row.get("site") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        if _is_icon_or_cdn(url):
            continue
        key = url.split("?", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "index": len(out) + 1,
                "url": url,
                "title": title or site or key,
                "site": site or None,
            }
        )
    return out


def extract_doubao_references(page_html: str) -> list[dict[str, Any]]:
    """从豆包分享页 HTML 抽取信源（text_card / website_name 片段）。"""
    clean = _peel_escapes(page_html)
    rows: list[dict[str, Any]] = []

    # search_query_result_block.text_card
    for m in re.finditer(
        r'"title"\s*:\s*"([^"]{1,300})"\s*,\s*"sitename"\s*:\s*"([^"]{0,120})"\s*,\s*"url"\s*:\s*"(https?://[^"]+)"',
        clean,
    ):
        rows.append({"title": m.group(1), "site": m.group(2), "url": m.group(3)})

    # 兼容字段顺序 sitename/title/url 不同
    for m in re.finditer(
        r'"sitename"\s*:\s*"([^"]{0,120})"\s*,\s*"url"\s*:\s*"(https?://[^"]+)"',
        clean,
    ):
        site, url = m.group(1), m.group(2)
        window = clean[max(0, m.start() - 400) : m.start()]
        title_m = re.search(r'"title"\s*:\s*"([^"]{1,300})"', window)
        rows.append({"title": title_m.group(1) if title_m else site, "site": site, "url": url})

    # 行内引用 website_name + info.url
    for m in re.finditer(r'"website_name"\s*:\s*"([^"]{1,120})"', clean):
        site = m.group(1)
        window = clean[m.start() : m.start() + 2500]
        url_m = re.search(r'"url"\s*:\s*"(https?://[^"]+)"', window)
        title_m = re.search(r'"title"\s*:\s*"([^"]{1,300})"', window)
        if not url_m:
            continue
        url = url_m.group(1)
        if _is_icon_or_cdn(url):
            for um in re.finditer(r'"url"\s*:\s*"(https?://[^"]+)"', window):
                cand = um.group(1)
                if not _is_icon_or_cdn(cand):
                    url = cand
                    break
            else:
                continue
        rows.append(
            {
                "title": title_m.group(1) if title_m else site,
                "site": site,
                "url": url,
            }
        )

    return _dedupe_refs(rows)


def _looks_like_share_error_page(text: str) -> bool:
    low = (text or "").strip()
    if len(low) < 20:
        return True
    markers = (
        "该页面暂时不可用",
        "页面不存在",
        "内容不存在",
        "分享已失效",
        "链接已失效",
        "无法访问此页面",
    )
    return any(m in low for m in markers)


def _clean_answer_text(text: str) -> str:
    lines: list[str] = []
    for raw_line in (text or "").splitlines():
        # 元宝分享页用 Hangul filler 当空白
        line = raw_line.replace("\u3164", "").strip()
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if line in _UI_NOISE_EXACT:
            continue
        if any(noise in line for noise in _UI_NOISE_PHRASES) and len(line) < 40:
            continue
        if re.fullmatch(r"分享于\d{4}-\d{1,2}-\d{1,2}.*", line):
            continue
        if re.fullmatch(r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日.*", line):
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def _extract_answer_from_html(page_html: str, body_text: str) -> str:
    text = _clean_answer_text(body_text)
    if len(text) >= 80:
        return text
    # fallback: strip tags from html
    plain = re.sub(r"<script[\s\S]*?</script>", " ", page_html, flags=re.I)
    plain = re.sub(r"<style[\s\S]*?</style>", " ", plain, flags=re.I)
    plain = re.sub(r"<[^>]+>", "\n", plain)
    plain = html.unescape(plain)
    return _clean_answer_text(plain)


def fetch_share_page(url: str, *, timeout_ms: int = 60000) -> SharePageFetchResult:
    """Playwright 打开分享页，返回正文 + 信源。"""
    value = str(url or "").strip()
    if not value.startswith(("http://", "https://")):
        raise ValueError("分享链接无效")
    host = _normalize_host(value)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ValueError("服务器未安装 Playwright，无法解析分享页") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
            )
            page.goto(value, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(3500)
            title = (page.title() or "").strip() or None
            body_text = page.inner_text("body") or ""
            page_html = page.content() or ""
        finally:
            browser.close()

    answer = _extract_answer_from_html(page_html, body_text)
    if _looks_like_share_error_page(answer):
        raise ValueError("分享页不可用或已失效，请更换可公开访问的链接")
    if len(answer) < 20:
        raise ValueError("未能从分享页解析到回答正文，请确认链接可公开访问")

    refs: list[dict[str, Any]] = []
    if host.endswith("doubao.com"):
        refs = extract_doubao_references(page_html)
    if not refs:
        # 通用：收集非本站外链
        for m in re.finditer(r'href=["\'](https?://[^"\']+)["\']', page_html, flags=re.I):
            href = html.unescape(m.group(1))
            if _normalize_host(href) == host or _is_icon_or_cdn(href):
                continue
            refs.append({"title": href, "site": _normalize_host(href), "url": href})
        refs = _dedupe_refs(refs)

    return SharePageFetchResult(
        answer_content=answer,
        references=refs,
        title=title,
        source_host=host or None,
    )
