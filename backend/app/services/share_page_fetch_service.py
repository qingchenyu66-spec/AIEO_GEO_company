"""从 AI 分享页抓取回答正文与信源（补录用）。

豆包：SSR 内嵌 search_query_result / text_card。
Kimi：分享页内嵌 web_search 的 title/url/siteName。
DeepSeek：Playwright 水合后抽回答区外链。
千问：点开「参考了 N 篇」+「查看全部」后再抽锚点。
元宝：JSON title/url（必要时点开引用面板）。
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
    # 2026-08-14 - 非豆包分享页静态/CDN 勿进信源
    "fe-static.deepseek.com",
    "cdn.deepseek.com",
    "alicdn.com",
    "mmstat.com",
    "cnzz.com",
    "googleapis.com",
    "gtimg.com",
    "static.yuanbao.tencent.com",
    "avatar.yuanbao.tencent.com",
    "cdn-hybrid-prod.hunyuan.tencent.com",
    "cdn-yb.icon.qq.com",
    "kimi-web-img.moonshot.cn",
    "w3.org",
)

_PLATFORM_SELF_HOSTS = (
    "doubao.com",
    "deepseek.com",
    "deepseek.cn",
    "qianwen.com",
    "qianwen.my.cn",
    "tongyi.aliyun.com",
    "yuanbao.tencent.com",
    "yb.tencent.com",
    "kimi.com",
    "moonshot.cn",
    "quark.cn",
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
    # 2026-08-14 - 回答区「参考了N篇」口径（清洗前），用于判断 HTTP 信源是否抽全
    claimed_refs: int | None = None


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
    cur = cur.replace("\\u002F", "/").replace("\\u002f", "/").replace("\\/", "/")
    # 2026-08-14 - 元宝 JSON url 里 \\u0026 未还原会导致信源链断裂
    cur = cur.replace("\\u0026", "&")
    cur = cur.replace('\\"', '"')
    return cur


def _claimed_material_count(text: str) -> int | None:
    """回答文案里的「参考了 N 篇」口径，用于判断 HTTP 信源是否抽全。"""
    for pat in (
        r"参考了\s*(\d+)\s*篇",
        r"参考\s*(\d+)\s*篇",
        r"(\d+)\s*篇材料",
        r"(\d+)\s*篇资料",
    ):
        m = re.search(pat, text or "")
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


def _http_refs_enough(hit: SharePageFetchResult, host: str) -> bool:
    """HTTP 已够用：豆包直接过；其它平台要有外链，且条数不低于文案宣称（若有）。"""
    if not hit:
        return False
    if not _needs_browser_for_refs(host):
        return True
    if not _refs_quality_ok(hit.references, page_host=host):
        return False
    claimed = hit.claimed_refs
    if claimed is None:
        claimed = _claimed_material_count(hit.answer_content or "")
    if claimed is None:
        return True
    # 2026-08-14 - 千问 HTTP 只有几条外链却宣称 18 篇 - 强制 Playwright 点开面板+查看全部
    return len(hit.references or []) >= claimed


def _is_icon_or_cdn(url: str) -> bool:
    low = (url or "").lower()
    if any(bit in low for bit in _ICON_HOST_BITS):
        return True
    path = urlparse(url).path.lower()
    return path.endswith((
        ".css", ".js", ".mjs", ".map", ".json",
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
        ".woff", ".woff2", ".ttf", ".eot",
    ))


def _is_platform_self_url(url: str, page_host: str = "") -> bool:
    host = _normalize_host(url)
    if not host:
        return True
    if page_host and (host == page_host or host.endswith("." + page_host)):
        return True
    for self_host in _PLATFORM_SELF_HOSTS:
        if host == self_host or host.endswith("." + self_host):
            return True
    return False


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


def extract_kimi_references(page_html: str) -> list[dict[str, Any]]:
    """Kimi 分享页 web_search 卡片：title/url/siteName。"""
    clean = _peel_escapes(page_html)
    rows: list[dict[str, Any]] = []
    for m in re.finditer(
        r'"title"\s*:\s*"([^"]{1,300})"\s*,\s*"url"\s*:\s*"(https?://[^"]+)"\s*,\s*"siteName"\s*:\s*"([^"]{0,120})"',
        clean,
    ):
        rows.append({"title": m.group(1), "url": m.group(2), "site": m.group(3)})
    # 容错字段顺序：url 在前
    for m in re.finditer(
        r'"url"\s*:\s*"(https?://[^"]+)"\s*,\s*"siteName"\s*:\s*"([^"]{0,120})"',
        clean,
    ):
        url, site = m.group(1), m.group(2)
        window = clean[max(0, m.start() - 400) : m.start()]
        title_m = re.search(r'"title"\s*:\s*"([^"]{1,300})"', window)
        rows.append({"title": title_m.group(1) if title_m else site, "url": url, "site": site})
    return _dedupe_refs(rows)


def extract_anchor_references(page_html: str, *, page_host: str = "") -> list[dict[str, Any]]:
    """从回答区外链锚点抽信源（DeepSeek/千问/元宝展开后常见）。"""
    rows: list[dict[str, Any]] = []
    for m in re.finditer(
        r'<a[^>]+href=["\'](https?://[^"\']+)["\'][^>]*>([\s\S]*?)</a>',
        page_html,
        flags=re.I,
    ):
        url = html.unescape(m.group(1)).strip()
        if _is_icon_or_cdn(url) or _is_platform_self_url(url, page_host):
            continue
        raw_title = re.sub(r"<[^>]+>", " ", m.group(2) or "")
        title = html.unescape(re.sub(r"\s+", " ", raw_title)).strip()
        if not title or title.startswith("http") or len(title) < 2:
            # 无标题时仍保留真实外链，title 用 host
            title = _normalize_host(url) or url
        rows.append({"title": title[:300], "url": url, "site": _normalize_host(url)})
    # 再扫裸 href（部分卡片只有属性）
    for m in re.finditer(r'href=["\'](https?://[^"\']+)["\']', page_html, flags=re.I):
        url = html.unescape(m.group(1)).strip()
        if _is_icon_or_cdn(url) or _is_platform_self_url(url, page_host):
            continue
        rows.append({"title": _normalize_host(url) or url, "url": url, "site": _normalize_host(url)})
    return _dedupe_refs(rows)


def _refs_quality_ok(refs: list[dict[str, Any]], *, page_host: str = "") -> bool:
    """至少一条非平台/非 CDN 外链，才认为抓到了可用信源。"""
    for row in refs or []:
        url = str(row.get("url") or "")
        if url and not _is_icon_or_cdn(url) and not _is_platform_self_url(url, page_host):
            return True
    return False


def extract_json_title_url_references(page_html: str, *, page_host: str = "") -> list[dict[str, Any]]:
    """通用：HTML/SSR JSON 中的 title+url 对（元宝展开引用面板后常见）。"""
    clean = _peel_escapes(page_html)
    clean = clean.replace("\\u0026", "&").replace("\\/", "/")
    rows: list[dict[str, Any]] = []
    for m in re.finditer(
        r'"title"\s*:\s*"([^"]{2,300})"\s*,\s*"url"\s*:\s*"(https?://[^"]+)"',
        clean,
    ):
        title, url = m.group(1), m.group(2)
        if _is_icon_or_cdn(url) or _is_platform_self_url(url, page_host):
            continue
        if url.rstrip("/").endswith(("svg", "png", "jpg", "jpeg", "gif", "webp", "ico")):
            continue
        rows.append({"title": title, "url": url, "site": _normalize_host(url)})
    for m in re.finditer(r'"url"\s*:\s*"(https?://[^"]+)"', clean):
        url = m.group(1)
        if _is_icon_or_cdn(url) or _is_platform_self_url(url, page_host):
            continue
        window = clean[max(0, m.start() - 400) : m.start()]
        title_m = re.search(r'"title"\s*:\s*"([^"]{2,300})"', window)
        if not title_m:
            continue
        rows.append(
            {
                "title": title_m.group(1),
                "url": url,
                "site": _normalize_host(url),
            }
        )
    return _dedupe_refs(rows)


def _refs_from_html(page_html: str, host: str) -> list[dict[str, Any]]:
    """按域名走专用解析，失败再回退 JSON title/url 与回答区外链。"""
    host_l = (host or "").lower()
    refs: list[dict[str, Any]] = []
    if host_l.endswith("doubao.com"):
        refs = extract_doubao_references(page_html)
    elif host_l.endswith("kimi.com") or host_l.endswith("moonshot.cn"):
        refs = extract_kimi_references(page_html)
    if _refs_quality_ok(refs, page_host=host_l):
        return refs
    json_refs = extract_json_title_url_references(page_html, page_host=host_l)
    if _refs_quality_ok(json_refs, page_host=host_l):
        return json_refs
    return extract_anchor_references(page_html, page_host=host_l)


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
    claimed = _claimed_material_count(body_text) or _claimed_material_count(page_html)
    return SharePageFetchResult(
        answer_content=answer,
        references=_refs_from_html(page_html, host),
        title=title,
        source_host=host or None,
        claimed_refs=claimed,
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


def _needs_browser_for_refs(host: str) -> bool:
    host_l = (host or "").lower()
    if host_l.endswith("doubao.com"):
        return False
    return any(
        host_l.endswith(h)
        for h in (
            "deepseek.com",
            "deepseek.cn",
            "qianwen.com",
            "tongyi.aliyun.com",
            "yuanbao.tencent.com",
            "yb.tencent.com",
            "kimi.com",
            "moonshot.cn",
        )
    )


def _expand_citation_panels(page: Any) -> None:
    """点开千问/元宝等「参考了 N 篇」面板，并点「查看全部」让折叠信源进 DOM。"""
    selectors = (
        '[data-toolbar-type="citation"]',
        'button:has-text("引用")',
        'button:has-text("参考")',
        'span:has-text("参考了")',
        'div:has-text("参考了")',
        'span:has-text("篇材料")',
        'span:has-text("篇资料")',
        'text=/参考了\\s*\\d+\\s*篇/',
        '[aria-label*="引用"]',
        '[aria-label*="参考"]',
    )
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            if not loc.is_visible():
                continue
            loc.click(timeout=1500)
            page.wait_for_timeout(1200)
        except Exception:  # noqa: BLE001
            continue
    # 2026-08-14 - 千问折叠只露 6 条，点「查看全部」才到宣称的 18 篇
    try:
        locs = page.locator("text=查看全部")
        for i in range(min(locs.count(), 4)):
            try:
                locs.nth(i).click(timeout=1500)
                page.wait_for_timeout(1000)
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass


def fetch_share_page(url: str, *, timeout_ms: int = 60000) -> SharePageFetchResult:
    """抓取分享页正文 + 信源；优先 HTTP，SPA/弱信源再 Playwright。"""
    import time

    value = str(url or "").strip()
    if not value.startswith(("http://", "https://")):
        raise ValueError("分享链接无效")
    host = _normalize_host(value)

    # 2026-08-07 - 补录「提交中」卡十几秒 - 截图已异步，正文仍同步 Playwright；SSR 先走 HTTP
    # 2026-08-14 - 非豆包若 HTTP 信源质量差/条数低于「参考了N篇」，继续 Playwright 点开引用面板再抽
    http_hit = _try_http_fetch(value, host)
    if http_hit is not None and _http_refs_enough(http_hit, host):
        return http_hit

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        if http_hit is not None:
            return http_hit
        raise ValueError("服务器未安装 Playwright，无法解析分享页") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(
                user_agent=_BROWSER_UA,
                viewport={"width": 1280, "height": 900},
            )
            page.goto(value, wait_until="domcontentloaded", timeout=timeout_ms)
            # 正文够长即停，最多再等约 2.5s
            body_text = ""
            deadline = time.monotonic() + 2.5
            while True:
                body_text = page.inner_text("body") or ""
                if len(_clean_answer_text(body_text)) >= 80:
                    break
                if time.monotonic() >= deadline:
                    break
                page.wait_for_timeout(200)
            _expand_citation_panels(page)
            title = (page.title() or "").strip() or None
            page_html = page.content() or ""
        finally:
            browser.close()

    result = _result_from_html(page_html, host=host, title=title, body_text=body_text)
    if result is None and http_hit is not None:
        return http_hit
    if result is None:
        answer = _extract_answer_from_html(page_html, body_text)
        if _looks_like_share_error_page(answer):
            raise ValueError("分享页不可用或已失效，请更换可公开访问的链接")
        raise ValueError("未能从分享页解析到回答正文，请确认链接可公开访问")
    return result
