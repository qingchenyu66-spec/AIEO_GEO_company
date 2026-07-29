"""信源文章正文抓取（Playwright）。供渠道价值拆解异步预生成使用。"""

from __future__ import annotations

import html
import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def is_http_url(url: str) -> bool:
    value = str(url or "").strip()
    if not value.startswith(("http://", "https://")):
        return False
    try:
        host = (urlparse(value).hostname or "").strip()
    except Exception:
        return False
    return bool(host)


def html_to_plain_text(page_html: str) -> str:
    """从 HTML 抽纯文本；无 BeautifulSoup 依赖。"""
    plain = re.sub(r"<script[\s\S]*?</script>", " ", page_html or "", flags=re.I)
    plain = re.sub(r"<style[\s\S]*?</style>", " ", plain, flags=re.I)
    plain = re.sub(r"<noscript[\s\S]*?</noscript>", " ", plain, flags=re.I)
    plain = re.sub(r"<[^>]+>", "\n", plain)
    plain = html.unescape(plain)
    lines = [re.sub(r"\s+", " ", line).strip() for line in plain.splitlines()]
    compact = "\n".join(line for line in lines if line)
    return re.sub(r"\n{3,}", "\n\n", compact).strip()


def _looks_like_block_page(text: str) -> bool:
    low = (text or "").strip()
    if len(low) < 40:
        return True
    markers = (
        "验证码",
        "安全验证",
        "请登录后查看",
        "登录后继续",
        "访问过于频繁",
        "该内容无法查看",
        "页面不存在",
        "404 Not Found",
        "Access Denied",
    )
    return any(m.lower() in low.lower() for m in markers) and len(low) < 400


def fetch_source_article_text(
    url: str,
    *,
    timeout_ms: int = 45000,
    settle_ms: int = 2500,
    max_chars: int = 3500,
) -> str:
    """Playwright 打开信源链接，返回正文摘录；失败返回空串。"""
    # 2026-07-29 - 渠道价值拆解要读正文非标题 - Playwright 抓链，失败由调用方规则兜底
    value = str(url or "").strip()
    if not is_http_url(value):
        return ""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright 未安装，无法抓取信源正文 url=%s", value[:120])
        return ""

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                # 2026-07-29 - 部分信源站证书过期(ERR_CERT_DATE_INVALID) - 忽略 HTTPS 错误继续抽正文
                context = browser.new_context(
                    user_agent=_DEFAULT_UA,
                    viewport={"width": 1280, "height": 900},
                    ignore_https_errors=True,
                )
                page = context.new_page()
                page.goto(value, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(settle_ms)
                body_text = page.inner_text("body") or ""
                page_html = page.content() or ""
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 - 单链失败不打断整批
        logger.warning("信源正文抓取失败 url=%s err=%s", value[:160], exc)
        return ""

    text = re.sub(r"\s+", " ", (body_text or "").strip())
    if len(text) < 80:
        text = html_to_plain_text(page_html)
    text = re.sub(r"\s+", " ", text).strip()
    if _looks_like_block_page(text):
        return ""
    if len(text) < 60:
        return ""
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


def fetch_source_articles_batch(
    urls: list[str],
    *,
    timeout_ms: int = 45000,
    settle_ms: int = 2000,
    max_chars: int = 3500,
) -> dict[str, str]:
    """同一浏览器会话批量抓取，减少启动开销。"""
    cleaned = [str(u).strip() for u in urls if is_http_url(str(u))]
    cleaned = list(dict.fromkeys(cleaned))
    if not cleaned:
        return {}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright 未安装，批量抓取跳过")
        return {}

    out: dict[str, str] = {}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                # 2026-07-29 - 批量抓取同样忽略过期证书，并每条新开 page 避免导航互相打断
                context = browser.new_context(
                    user_agent=_DEFAULT_UA,
                    viewport={"width": 1280, "height": 900},
                    ignore_https_errors=True,
                )
                for value in cleaned:
                    page = context.new_page()
                    try:
                        page.goto(value, wait_until="domcontentloaded", timeout=timeout_ms)
                        page.wait_for_timeout(settle_ms)
                        body_text = page.inner_text("body") or ""
                        page_html = page.content() or ""
                        text = re.sub(r"\s+", " ", (body_text or "").strip())
                        if len(text) < 80:
                            text = html_to_plain_text(page_html)
                        text = re.sub(r"\s+", " ", text).strip()
                        if _looks_like_block_page(text) or len(text) < 60:
                            continue
                        if len(text) > max_chars:
                            text = text[: max_chars - 1].rstrip() + "…"
                        out[value] = text
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("信源批量抓取单条失败 url=%s err=%s", value[:160], exc)
                    finally:
                        page.close()
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("信源批量抓取会话失败 err=%s", exc)
    return out
