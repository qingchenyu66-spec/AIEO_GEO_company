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


_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def _refs_from_html(page_html: str, host: str) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if host.endswith("doubao.com"):
        refs = extract_doubao_references(page_html)
    if refs:
        return refs
    for m in re.finditer(r'href=["\'](https?://[^"\']+)["\']', page_html, flags=re.I):
        href = html.unescape(m.group(1))
        if _normalize_host(href) == host or _is_icon_or_cdn(href):
            continue
        refs.append({"title": href, "site": _normalize_host(href), "url": href})
    return _dedupe_refs(refs)


def _result_from_html(
    page_html: str,
    *,
    host: str,
    title: str | None = None,
    body_text: str = "",
) -> SharePageFetchResult | None:
    answer = _extract_answer_from_html(page_html, body_text)
    if _looks_like_share_error_page(answer) or len(answer) < 20:
        return None
    return SharePageFetchResult(
        answer_content=answer,
        references=_refs_from_html(page_html, host),
        title=title,
        source_host=host or None,
    )


def _try_http_fetch(url: str, host: str) -> SharePageFetchResult | None:
    """SSR 站（豆包 thread 等）优先裸 HTTP，避免起浏览器拖垮提交。"""
    try:
        import httpx
    except ImportError:
        return None
    try:
        with httpx.Client(
            timeout=httpx.Timeout(12.0, connect=5.0),
            follow_redirects=True,
            trust_env=False,
        ) as client:
            resp = client.get(url, headers={"User-Agent": _BROWSER_UA, "Accept-Language": "zh-CN,zh;q=0.9"})
        if resp.status_code >= 400:
            return None
        page_html = resp.text or ""
        title_m = re.search(r"<title[^>]*>([^<]+)</title>", page_html, flags=re.I)
        title = html.unescape(title_m.group(1)).strip() if title_m else None
        return _result_from_html(page_html, host=host, title=title or None)
    except Exception as exc:  # noqa: BLE001
        logger.info("share page http fetch skipped host=%s err=%s", host, exc)
        return None


def fetch_share_page(url: str, *, timeout_ms: int = 60000) -> SharePageFetchResult:
    """抓取分享页正文 + 信源；优先 HTTP，不够再 Playwright。"""
    import time

    value = str(url or "").strip()
    if not value.startswith(("http://", "https://")):
        raise ValueError("分享链接无效")
    host = _normalize_host(value)

    # 2026-08-07 - 补录「提交中」卡十几秒 - 截图已异步，正文仍同步 Playwright+固定 3.5s；SSR 先走 HTTP
    http_hit = _try_http_fetch(value, host)
    if http_hit is not None:
        return http_hit

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ValueError("服务器未安装 Playwright，无法解析分享页") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(
                user_agent=_BROWSER_UA,
                viewport={"width": 1280, "height": 900},
            )
            page.goto(value, wait_until="domcontentloaded", timeout=timeout_ms)
            # 正文够长即停，最多再等约 2s（原固定 3.5s）
            body_text = ""
            deadline = time.monotonic() + 2.0
            while True:
                body_text = page.inner_text("body") or ""
                if len(_clean_answer_text(body_text)) >= 80:
                    break
                if time.monotonic() >= deadline:
                    break
                page.wait_for_timeout(200)
            title = (page.title() or "").strip() or None
            page_html = page.content() or ""
        finally:
            browser.close()

    result = _result_from_html(page_html, host=host, title=title, body_text=body_text)
    if result is None:
        answer = _extract_answer_from_html(page_html, body_text)
        if _looks_like_share_error_page(answer):
            raise ValueError("分享页不可用或已失效，请更换可公开访问的链接")
        raise ValueError("未能从分享页解析到回答正文，请确认链接可公开访问")
    return result
