"""Playwright Chromium 可用性探测（报告 PDF 导出依赖）。"""

from __future__ import annotations


def playwright_chromium_health() -> dict[str, str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"status": "error", "detail": "playwright 包未安装"}

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            browser.close()
        return {"status": "ready", "detail": "Chromium 可启动"}
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        hint = "请执行: python -m playwright install chromium"
        if "Executable doesn't exist" in detail or "browserType.launch" in detail:
            detail = f"{detail} · {hint}"
        return {"status": "error", "detail": detail[:400]}
