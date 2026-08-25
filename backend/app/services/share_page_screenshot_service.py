"""分享页截图：展开整容器优先，必要时滚动拼接 → 本地落盘 → media 路径。

失败软降级（调用方勿把分享链写入 page_screenshot）。
"""

from __future__ import annotations

import logging
import re
import threading
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from PIL import Image

from app.core.config import settings

logger = logging.getLogger(__name__)

BACKFILL_SHOT_PATH_PREFIX = "/api/v1/media/backfill-shot/"

SCROLLERS: dict[str, list[str]] = {
    # 2026-08-25 - 千问分享域是 qianwen.my.cn；page-content 能滚但展开截高度锁死，优先 answer/chat-room 整容器
    "qianwen.com": [
        '[class*="answer"]',
        '[class*="chat-room"]',
        '[class*="message-list-scroll"]',
        '[class*="scroll-container"]',
        '[class*="page-content"]',
    ],
    "yb.tencent.com": [".agent-chat__list__content", ".app-share-ssr", "body"],
    "yuanbao.tencent.com": [".agent-chat__list__content", ".app-share-ssr", "body"],
    "kimi.com": [".share-content-container", ".share-detail"],
    "deepseek.com": [".ds-scroll-area", '[class*="ds-virtual-list"]', "main"],
    # 豆包：优先 message 正文容器，避免整页 scroller 拼接重复
    "doubao.com": ['[class*="message"]', '[class*="overflow-y-scroll"]', "#root"],
}


def _scroller_list(host: str) -> list[str]:
    """按域名族取滚动容器候选（分享页常换二级域）。"""
    h = (host or "").lower()
    if h in SCROLLERS:
        return list(SCROLLERS[h])
    if "qianwen" in h or h.endswith("tongyi.com"):
        return list(SCROLLERS["qianwen.com"])
    if "kimi" in h or "moonshot" in h:
        return list(SCROLLERS["kimi.com"])
    if "deepseek" in h:
        return list(SCROLLERS["deepseek.com"])
    if "doubao" in h:
        return list(SCROLLERS["doubao.com"])
    if "yuanbao" in h or h in ("yb.tencent.com",):
        return list(SCROLLERS["yuanbao.tencent.com"])
    return []


# 2026-08-07 - 补录 page_screenshot 误存分享链 - 拼接长图落本地 media，勿写链
# 2026-08-25 - DeepSeek 分享页英文 Continue 按钮未藏 + 滚屏拼重复 - 扩隐藏文案；deepseek 先整容器截
# 2026-08-25 - 豆包底栏「打开豆包 →」fixed 叠正文；仅匹配文案不够稳 - 再杀底部 fixed/sticky CTA
HIDE_CHROME_JS = """() => {
  const kill = (el) => { if (el) el.style.setProperty('display', 'none', 'important'); };
  const CTA_RE = /继续向千问提问|和元宝继续聊|打开豆包|和 DeepSeek 继续聊|Continue with DeepSeek|Continue with Doubao|在App中打开|打开 App/i;
  for (const el of document.querySelectorAll('div,span,a,header,button,img')) {
    const r = el.getBoundingClientRect();
    if (r.top < 0 || r.top > 140 || r.height <= 0 || r.height > 120) continue;
    const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
    const isAv = el.tagName === 'IMG' && r.width <= 64 && r.height <= 64;
    if (isAv || (/^分享于|该对话来自分享|来自分享的对话|下载APP|^反馈$|快速模式/.test(t) && t.length < 80)) {
      let p = el;
      for (let i = 0; i < 6 && p; i++) {
        const pr = p.getBoundingClientRect();
        if (pr.top < 150 && pr.height < 130) { kill(p); break; }
        p = p.parentElement;
      }
    }
  }
  for (const el of document.querySelectorAll('h1,h2,div,span,p')) {
    const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
    if (!t || t.length > 60) continue;
    const r = el.getBoundingClientRect();
    if (r.top > 220 || r.top < 0) continue;
    if (/^\\d{4}\\s*年\\s*\\d{1,2}\\s*月\\s*\\d{1,2}\\s*日/.test(t) || t === '内容由 AI 生成，不能完全保障真实') {
      let p = el.parentElement;
      for (let i = 0; i < 4 && p; i++) {
        const pr = p.getBoundingClientRect();
        if (pr.height > 0 && pr.height < 160 && pr.top < 220) { kill(p); break; }
        p = p.parentElement;
      }
    }
  }
  for (const el of document.querySelectorAll('button,a,div')) {
    const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
    if (!t || t.length > 60) continue;
    if (CTA_RE.test(t)) {
      kill(el);
      let p = el.parentElement;
      for (let i = 0; i < 4 && p; i++) {
        const pr = p.getBoundingClientRect();
        const pt = (p.innerText || '').replace(/\\s+/g, ' ').trim();
        if (pr.height > 0 && pr.height < 120 && pt.length < 80) { kill(p); break; }
        p = p.parentElement;
      }
    }
  }
  // 底部悬浮 CTA：文案节点可能被拆开，按 fixed/sticky + 贴底再杀一层
  for (const el of document.querySelectorAll('button,a,div,footer')) {
    const st = getComputedStyle(el);
    if (st.position !== 'fixed' && st.position !== 'sticky') continue;
    const r = el.getBoundingClientRect();
    if (r.height <= 0 || r.height > 160 || r.width < 40) continue;
    if (r.top < window.innerHeight * 0.55) continue;
    const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
    if (t && t.length <= 220 && (CTA_RE.test(t) || /内容由AI生成|月之暗面|京ICP备2023011302/.test(t))) kill(el);
  }
  // 2026-08-25 - Kimi sticky 法律页脚滚屏时嵌进正文中间（上下色差缝）
  for (const el of document.querySelectorAll('footer,div')) {
    const cls = (el.className || '').toString();
    const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
    if (!t || t.length > 220) continue;
    if (!(/legal-footer|share-actions/.test(cls) || /内容由AI生成.*月之暗面|京ICP备2023011302/.test(t))) continue;
    if (/内容由AI生成|月之暗面|京ICP备/.test(t)) kill(el);
  }
}"""


def _frame_sig(im: Image.Image) -> bytes:
    return im.convert("L").resize((64, 64)).tobytes()


def _frame_near_dup(a: bytes, b: bytes, *, max_mad: float = 6.0) -> bool:
    """滚屏相邻两帧是否近似同一屏（仅完全相等会漏掉轻微重排）。"""
    if a == b:
        return True
    if len(a) != len(b) or not a:
        return False
    total = 0
    for x, y in zip(a, b):
        total += abs(x - y)
    return (total / len(a)) <= max_mad


def backfill_screenshot_dir() -> Path:
    raw = (getattr(settings, "backfill_screenshot_dir", None) or "").strip()
    if raw:
        path = Path(raw)
    else:
        # 2026-08-10 - 补录截图会涨；默认进 storage（生产软链 /data/geo/storage），勿再写系统盘 data/
        path = Path(__file__).resolve().parents[2] / "storage" / "backfill_screenshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_backfill_shot_url(url: str | None) -> bool:
    text = str(url or "").strip()
    return bool(text) and (
        text.startswith(BACKFILL_SHOT_PATH_PREFIX) or "/media/backfill-shot/" in text
    )


def is_image_screenshot_url(url: str | None) -> bool:
    """已是可展示图（模力 CDN / 本地补录图 / 常见图片后缀），不是分享页。"""
    text = str(url or "").strip()
    if not text:
        return False
    if is_backfill_shot_url(text):
        return True
    if "/media/shot/" in text or text.startswith("/api/v1/media/shot/"):
        return True
    low = text.lower()
    if "img.molizhishu" in low:
        return True
    return any(ext in low for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"))


def resolve_backfill_shot_path(file_id: str) -> Path:
    name = str(file_id or "").strip()
    if not name or "/" in name or "\\" in name or ".." in name:
        raise ValueError("无效的快照文件名")
    if not re.fullmatch(r"[A-Za-z0-9._-]{8,180}", name):
        raise ValueError("无效的快照文件名")
    path = (backfill_screenshot_dir() / name).resolve()
    root = backfill_screenshot_dir().resolve()
    if not str(path).startswith(str(root)):
        raise ValueError("无效的快照路径")
    if not path.is_file():
        raise ValueError("快照不存在")
    return path


def _host(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    if h.startswith("www."):
        h = h[4:]
    if h.startswith("chat."):
        h = h[5:]
    return h


def _pick_scroller(page, host: str) -> str:
    # 2026-08-25 - 优先真滚动容器（sh>ch）；body 常只有一屏却 sh>600，会截不全
    cands = _scroller_list(host) + ["main", "body"]
    tall: str | None = None
    for sel in cands:
        meta = page.evaluate(
            """(sel) => {
              const el = document.querySelector(sel);
              if (!el) return null;
              return { sh: el.scrollHeight || 0, ch: el.clientHeight || 0 };
            }""",
            sel,
        )
        if not meta:
            continue
        sh = int(meta.get("sh") or 0)
        ch = int(meta.get("ch") or 0)
        if sh > ch + 40:
            return sel
        if sh > 600 and tall is None:
            tall = sel
    return tall or "body"


def _expand_scroller(page, sel: str) -> dict:
    return page.evaluate(
        """(s) => {
          const root = document.querySelector(s);
          if (!root) return { ok: false };
          const bump = (node) => {
            if (!node || node === document.body || node === document.documentElement) return;
            const sh = node.scrollHeight;
            const ch = node.clientHeight;
            if (sh > ch + 8) {
              node.style.setProperty('height', sh + 'px', 'important');
              node.style.setProperty('max-height', 'none', 'important');
              node.style.setProperty('overflow', 'visible', 'important');
            }
          };
          bump(root);
          for (const el of root.querySelectorAll('*')) {
            const st = getComputedStyle(el);
            if (st.overflowY === 'auto' || st.overflowY === 'scroll' || st.overflowY === 'overlay') bump(el);
          }
          let p = root.parentElement;
          for (let i = 0; i < 8 && p; i++) {
            p.style.setProperty('overflow', 'visible', 'important');
            p.style.setProperty('max-height', 'none', 'important');
            p = p.parentElement;
          }
          const r = root.getBoundingClientRect();
          return { ok: true, sh: root.scrollHeight, h: Math.round(r.height) };
        }""",
        sel,
    )


def _element_png(page, sel: str) -> bytes | None:
    try:
        meta = _expand_scroller(page, sel)
        if not meta.get("ok") or int(meta.get("h") or 0) < 200:
            return None
        # 2026-08-25 - 千问 page-content：expand 后 getBoundingClientRect 仍一屏，勿当成功
        sh = int(meta.get("sh") or 0)
        h = int(meta.get("h") or 0)
        if sh > 0 and h + 80 < sh:
            return None
        page.wait_for_timeout(200)
        return page.locator(sel).first.screenshot(type="png", timeout=120000)
    except Exception as exc:
        logger.info("element screenshot failed sel=%s err=%s", sel, exc)
        return None


def _stitch_png(page, sel: str, *, overlap: int = 100) -> bytes:
    page.evaluate("(s)=>{const el=document.querySelector(s); if(el) el.scrollTop=0;}", sel)
    page.wait_for_timeout(200)
    parts: list[Image.Image] = []
    last = None
    guard = 0
    prev_sig: bytes | None = None
    while guard < 80:
        box = page.evaluate(
            """(s) => {
              const el = document.querySelector(s);
              if (!el) return null;
              const r = el.getBoundingClientRect();
              return {
                x: Math.max(0, r.x),
                y: Math.max(0, r.y),
                width: Math.min(window.innerWidth - Math.max(0, r.x), r.width),
                height: Math.min(window.innerHeight - Math.max(0, r.y), r.height),
              };
            }""",
            sel,
        )
        if not box or box["height"] < 40:
            break
        last = box
        frame = Image.open(BytesIO(page.screenshot(clip=box, type="png"))).convert("RGB")
        sig = _frame_sig(frame)
        # 2026-08-07 - 拼接重复段/表头翻倍 - 跳过与上一屏几乎相同的帧
        # 2026-08-25 - 仅相等不够：DeepSeek 虚拟列表轻微重排仍会叠重复正文
        if prev_sig is not None and _frame_near_dup(prev_sig, sig):
            page.evaluate(
                """(a) => {
                  const el = document.querySelector(a.s);
                  el.scrollTop = Math.min(el.scrollTop + Math.max(80, Math.floor(a.step / 2)), el.scrollHeight);
                }""",
                {"s": sel, "step": max(140, int(box["height"] - overlap))},
            )
            page.wait_for_timeout(200)
            guard += 1
            continue
        prev_sig = sig
        parts.append(frame)
        step = max(140, int(box["height"] - overlap))
        adv = page.evaluate(
            """(a) => {
              const el = document.querySelector(a.s);
              const before = el.scrollTop;
              el.scrollTop = Math.min(el.scrollTop + a.step, el.scrollHeight);
              return { before, after: el.scrollTop };
            }""",
            {"s": sel, "step": step},
        )
        page.wait_for_timeout(280)
        guard += 1
        if adv["after"] <= adv["before"] + 2:
            break
    if not parts or not last:
        raise RuntimeError("截图拼接失败：无可截区域")
    scale = parts[0].width / max(last["width"], 1)
    ov = int(overlap * scale)
    width = max(im.width for im in parts)
    rows: list[Image.Image] = []
    height = 0
    for i, im in enumerate(parts):
        crop = im if i == 0 else im.crop((0, min(ov, im.height - 1), im.width, im.height))
        rows.append(crop)
        height += crop.height
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    y = 0
    for im in rows:
        canvas.paste(im, (0, y))
        y += im.height
    buf = BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _quality_ok(png: bytes) -> bool:
    if len(png) < 40 * 1024:
        return False
    im = Image.open(BytesIO(png)).convert("L")
    w, h = im.size
    if h < 600:
        return False
    step = max(1, (w * h) // 80000)
    pix = im.getdata()
    total = 0
    ink = 0
    for i, v in enumerate(pix):
        if i % step:
            continue
        total += 1
        if v < 245:
            ink += 1
    if total <= 0 or (ink / total) < 0.015:
        return False
    # 2026-08-25 - 千问 answer 展开后高度虚高、下半截空白 - 底部无墨迹则判失败改走滚屏
    if h >= 1600:
        bottom = im.crop((0, int(h * 0.65), w, h))
        bp = list(bottom.getdata())
        b_ink = sum(1 for v in bp if v < 245)
        if bp and (b_ink / len(bp)) < 0.004:
            return False
    return True


def capture_share_page_screenshot(url: str, *, subtask_id: str | None = None) -> str:
    """截分享页并落盘，返回 `/api/v1/media/backfill-shot/{file}`。失败抛 ValueError。"""
    value = str(url or "").strip()
    if not value.startswith(("http://", "https://")):
        raise ValueError("分享链接无效")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ValueError("服务器未安装 Playwright，无法截图") from exc

    host = _host(value)
    mobile = host in ("yb.tencent.com", "yuanbao.tencent.com")
    deepseek = host == "deepseek.com" or host.endswith(".deepseek.com")
    doubao = host == "doubao.com" or host.endswith(".doubao.com")
    qianwen = "qianwen" in host or host.endswith("tongyi.com")
    # 2026-08-25 - deepseek 也先整容器展开截，失败再滚屏拼（已弃用「deepseek 必拼」）
    # 2026-08-25 - 千问 answer 展开虚高空白，优先真滚 page-content 拼接
    prefer_expand = not mobile and not qianwen
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            if mobile:
                context = browser.new_context(
                    viewport={"width": 390, "height": 844},
                    device_scale_factor=3,
                    is_mobile=True,
                    has_touch=True,
                    user_agent=(
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
                        "Mobile/15E148 Safari/604.1"
                    ),
                )
            else:
                context = browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    device_scale_factor=2,
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                )
            page = context.new_page()
            page.goto(value, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4500)
            page.evaluate(HIDE_CHROME_JS)
            page.wait_for_timeout(200)
            sel = _pick_scroller(page, host)
            png: bytes | None = None
            scrollers = _scroller_list(host)
            if prefer_expand:
                for cand in scrollers + [sel]:
                    png = _element_png(page, cand)
                    if png and _quality_ok(png):
                        break
                    png = None
            if png is None:
                # DeepSeek/豆包/千问滚屏叠得更狠，加大 overlap 去重条带
                png = _stitch_png(page, sel, overlap=220 if (deepseek or doubao or qianwen) else 100)
            context.close()
        finally:
            browser.close()

    if not _quality_ok(png):
        raise ValueError("截图质量不足（可能页面空白或链接失效）")

    safe_sid = re.sub(r"[^A-Za-z0-9_-]+", "_", str(subtask_id or "shot"))[:48] or "shot"
    file_id = f"{safe_sid}_{uuid4().hex[:10]}.png"
    path = backfill_screenshot_dir() / file_id
    path.write_bytes(png)
    return f"{BACKFILL_SHOT_PATH_PREFIX}{file_id}"


def apply_backfill_screenshot(db, *, subtask_id: str, snapshot_url: str) -> dict:
    """写入截图结果；失败不把分享链写进 page_screenshot。"""
    from sqlalchemy import select

    from app.models.monitor import GeoMonitorSubtask

    subtask = db.scalar(select(GeoMonitorSubtask).where(GeoMonitorSubtask.subtask_id == subtask_id))
    if subtask is None:
        return {"status": "missing", "subtask_id": subtask_id}

    raw = dict(subtask.raw_result_json or {})
    expected = str(raw.get("snapshot_url") or "").strip()
    url = str(snapshot_url or expected or "").strip()
    if not url:
        raw["screenshot_pending"] = False
        raw["screenshot_ok"] = False
        raw["screenshot_error"] = "missing_snapshot_url"
        subtask.raw_result_json = raw
        db.commit()
        return {"status": "failed", "subtask_id": subtask_id, "error": "missing_snapshot_url"}

    try:
        shot_url = capture_share_page_screenshot(url, subtask_id=subtask_id)
        subtask.page_screenshot = shot_url
        raw["screenshot_ok"] = True
        raw["screenshot_pending"] = False
        raw.pop("screenshot_error", None)
        subtask.raw_result_json = raw
        db.commit()
        return {"status": "ok", "subtask_id": subtask_id, "page_screenshot": shot_url}
    except Exception as exc:  # noqa: BLE001
        logger.warning("backfill screenshot failed subtask_id=%s err=%s", subtask_id, exc)
        raw["screenshot_ok"] = False
        raw["screenshot_pending"] = False
        raw["screenshot_error"] = str(exc)[:240]
        if not is_image_screenshot_url(subtask.page_screenshot):
            subtask.page_screenshot = None
        subtask.raw_result_json = raw
        db.commit()
        return {"status": "failed", "subtask_id": subtask_id, "error": str(exc)[:240]}


def _spawn_backfill_screenshot(*, subtask_id: str, snapshot_url: str) -> None:
    def _job() -> None:
        from app.core.database import SessionLocal

        db = SessionLocal()
        try:
            apply_backfill_screenshot(db, subtask_id=subtask_id, snapshot_url=snapshot_url)
        except Exception:
            logger.exception("background backfill screenshot crashed subtask_id=%s", subtask_id)
        finally:
            db.close()

    threading.Thread(
        target=_job,
        name=f"backfill-shot-{subtask_id}",
        daemon=True,
    ).start()


def enqueue_backfill_screenshot(*, subtask_id: str, snapshot_url: str) -> str:
    """投递异步截图；绝不在请求线程里同步截。返回 queued | thread_fallback。"""
    if settings.celery_enabled:
        try:
            from app.tasks.snapshot_backfill import capture_backfill_screenshot_task

            capture_backfill_screenshot_task.delay(subtask_id, snapshot_url)
            return "queued"
        except Exception as exc:  # noqa: BLE001
            # 2026-08-07 - Celery 投递失败曾同步截导致提交卡十几秒 - 改后台线程，勿堵 HTTP
            logger.warning(
                "backfill screenshot enqueue failed, thread fallback subtask_id=%s err=%s",
                subtask_id,
                exc,
            )
    _spawn_backfill_screenshot(subtask_id=subtask_id, snapshot_url=snapshot_url)
    return "thread_fallback"
