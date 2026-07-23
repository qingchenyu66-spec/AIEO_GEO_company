"""Minimal HTML allowlist sanitizer for announcement body (stdlib only)."""

from __future__ import annotations

import re
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse

_ALLOWED_TAGS = frozenset(
    {
        "p",
        "br",
        "div",
        "span",
        "strong",
        "b",
        "em",
        "i",
        "u",
        "ul",
        "ol",
        "li",
        "a",
        "img",
        "h1",
        "h2",
        "h3",
        "h4",
        "blockquote",
        "hr",
    }
)
_VOID = frozenset({"br", "img", "hr"})
_ALLOWED_ATTRS: dict[str, frozenset[str]] = {
    "a": frozenset({"href", "title", "target", "rel", "download"}),
    "img": frozenset({"src", "alt", "title"}),
    "p": frozenset({"style"}),
    "span": frozenset({"style"}),
    "div": frozenset({"style"}),
}
# 仅放行排版相关声明；禁止 url()/expression/行为属性渗入
_SAFE_STYLE = re.compile(
    r"^(?:"
    r"color\s*:\s*#[0-9a-fA-F]{3,8}"
    r"|color\s*:\s*rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\)"
    r"|font-weight\s*:\s*(?:normal|bold|[1-9]00)"
    r"|font-style\s*:\s*(?:normal|italic)"
    r"|text-decoration\s*:\s*(?:none|underline|line-through)"
    r"|font-size\s*:\s*\d{1,3}(?:\.\d+)?(?:px|pt|em|rem)"
    r"|font-family\s*:\s*[a-zA-Z0-9\s,\-\"']+"
    r")\s*;?$",
    re.I,
)
_SCRIPTISH = re.compile(r"javascript:|data:text/html|vbscript:|expression\s*\(|url\s*\(", re.I)


def _safe_url(value: str, *, allow_relative: bool = True) -> str | None:
    text = (value or "").strip()
    if not text or _SCRIPTISH.search(text):
        return None
    parsed = urlparse(text)
    scheme = (parsed.scheme or "").lower()
    if scheme in {"http", "https"}:
        return text
    if allow_relative and not scheme and text.startswith("/"):
        return text
    return None


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in _ALLOWED_TAGS:
            return
        allowed = _ALLOWED_ATTRS.get(tag, frozenset())
        cleaned: list[str] = []
        for key, raw in attrs:
            name = (key or "").lower()
            if name not in allowed or raw is None:
                continue
            if name in {"href", "src"}:
                url = _safe_url(raw, allow_relative=True)
                if not url:
                    continue
                cleaned.append(f'{name}="{url}"')
                if name == "href":
                    cleaned.append('rel="noopener noreferrer"')
                    if "target" not in {a[0].lower() for a in attrs if a[0]}:
                        cleaned.append('target="_blank"')
            elif name == "style":
                parts = [p.strip() for p in str(raw).split(";") if p.strip()]
                safe: list[str] = []
                for part in parts:
                    candidate = part if part.endswith(";") else f"{part};"
                    if _SCRIPTISH.search(candidate):
                        continue
                    if _SAFE_STYLE.match(candidate):
                        safe.append(part.rstrip(";"))
                if safe:
                    cleaned.append(f'style="{escape("; ".join(safe), quote=True)}"')
                continue
            elif name == "target":
                if raw in {"_blank", "_self"}:
                    cleaned.append(f'{name}="{raw}"')
            else:
                cleaned.append(f'{name}="{raw}"')
        attr_s = (" " + " ".join(cleaned)) if cleaned else ""
        if tag in _VOID:
            self._out.append(f"<{tag}{attr_s}>")
            return
        self._stack.append(tag)
        self._out.append(f"<{tag}{attr_s}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag not in _ALLOWED_TAGS or tag in _VOID:
            return
        if tag in self._stack:
            while self._stack:
                top = self._stack.pop()
                self._out.append(f"</{top}>")
                if top == tag:
                    break

    def handle_data(self, data: str) -> None:
        self._out.append(
            data.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )

    def handle_entityref(self, name: str) -> None:
        self._out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._out.append(f"&#{name};")

    def result(self) -> str:
        while self._stack:
            self._out.append(f"</{self._stack.pop()}>")
        return "".join(self._out)


def sanitize_announcement_html(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        raise ValueError("公告正文不能为空")
    parser = _Sanitizer()
    parser.feed(text)
    parser.close()
    cleaned = parser.result().strip()
    if not cleaned:
        raise ValueError("公告正文不能为空")
    return cleaned
