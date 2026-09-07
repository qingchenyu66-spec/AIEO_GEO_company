# -*- coding: utf-8 -*-
"""品牌分析 B1 一页纸 PDF：事实锁死 + DeepSeek 3 条建议（D1 跟页面周期）。"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentSession
from app.services.brand_analysis_service import (
    build_brand_analysis_dashboard,
    resolve_brand_compare_period,
)
from app.services.deepseek_client import DeepseekApiError, DeepseekClient
from app.services.menu_permission_service import has_identity_menu_permission

logger = logging.getLogger(__name__)

PDF_FONT = "STSong-Light"
COLOR_OK = colors.Color(0.133, 0.639, 0.369)
COLOR_MID = colors.Color(0.580, 0.639, 0.722)
COLOR_BAD = colors.Color(0.937, 0.267, 0.267)
COLOR_INK = colors.HexColor("#0f172a")
COLOR_MUTED = colors.HexColor("#64748b")
COLOR_LINE = colors.HexColor("#e2e8f0")
COLOR_CARD = colors.HexColor("#f8fafc")

_GRAIN_LABEL = {"week": "周", "month": "月", "quarter": "季", "year": "年"}
_ADVICE_CACHE_DIR = Path(__file__).resolve().parents[2] / "storage" / "cache" / "brand_analysis_b1"


def require_brand_analysis_export_permission(db: Session, current: CurrentSession) -> None:
    if current.identity.identity_type == "CUSTOMER":
        if not has_identity_menu_permission(db, current.identity.id, "customer.brand_analysis", "can_export"):
            raise PermissionError("当前账号无权导出品牌分析")
        return
    if current.identity.identity_type == "PLATFORM":
        return
    raise PermissionError("无权导出品牌分析")


def _register_font() -> None:
    if PDF_FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(PDF_FONT))


def _platform_share(platform: dict[str, Any], key: str) -> float:
    share = platform.get("sentiment_share") or {}
    if share.get(key) is not None:
        return float(share.get(key) or 0)
    return 0.0


# 2026-09-07 - V1：过滤工商/注册类描述，对外只留有口碑信息量的要点
_REGISTRY_NOISE_RE = re.compile(
    r"成立于|注册资本|法定代表人|统一社会信用|经营范围|工商|住所|注册地址|"
    r"企业法人|营业执照|信用代码|登记机关|实缴资本"
)


def _is_registry_noise(text: str) -> bool:
    return bool(_REGISTRY_NOISE_RE.search(text or ""))


def _desc_rank_key(row: dict[str, Any]) -> tuple:
    sent = str(row.get("sentiment") or "")
    # 对外优先正/负洞察，中性靠后
    sent_rank = 0 if sent in ("正面", "负面") else 1
    return (sent_rank, -int(row.get("sample_count") or 0), str(row.get("description") or ""))


def _top_descriptions(data: dict[str, Any], limit: int = 4) -> list[dict[str, Any]]:
    rows = list(data.get("ai_descriptions") or [])
    cleaned = []
    for row in rows:
        desc = str(row.get("description") or "").strip()
        if not desc or _is_registry_noise(desc):
            continue
        plats = "、".join(
            str(p.get("name") or p.get("code") or "")
            for p in (row.get("platforms") or [])
        )
        cleaned.append(
            {
                "sentiment": row.get("sentiment") or "",
                "description": desc,
                "sample_count": int(row.get("sample_count") or 0),
                "platforms": plats,
            }
        )
    cleaned.sort(key=_desc_rank_key)
    return cleaned[:limit]


def _facts_payload(data: dict[str, Any], *, brand: str, grain_label: str) -> dict[str, Any]:
    share = data.get("description_share") or {}
    cmp = data.get("description_compare") or {}
    deltas = cmp.get("deltas") or {}
    insufficient = bool(cmp.get("insufficient"))
    platforms = []
    for p in data.get("platforms") or []:
        platforms.append(
            {
                "name": p.get("name") or p.get("code"),
                "positive_pct": round(_platform_share(p, "正面"), 1),
                "neutral_pct": round(_platform_share(p, "中性"), 1),
                "negative_pct": round(_platform_share(p, "负面"), 1),
                "sample_count": int(p.get("sample_count") or 0),
            }
        )
    platforms.sort(key=lambda x: (-x["sample_count"], -x["negative_pct"]))
    return {
        "brand": brand,
        "period_label": data.get("period_label") or "",
        "previous_period_label": data.get("previous_period_label") or "",
        "compare_window": grain_label,
        "sample_count": int(data.get("sample_count") or 0),
        "share_pct": {
            "正面": round(float(share.get("正面") or 0), 1),
            "中性": round(float(share.get("中性") or 0), 1),
            "负面": round(float(share.get("负面") or 0), 1),
        },
        "delta_pt": None
        if insufficient
        else {
            "正面": deltas.get("正面_pt"),
            "中性": deltas.get("中性_pt"),
            "负面": deltas.get("负面_pt"),
        },
        "compare_insufficient": insufficient,
        "platforms": platforms,
        "top_descriptions": _top_descriptions(data, 4),
        "metric_note": "占比按 AI 描述归并组数；样本数为监测回答条数",
    }


def _fallback_advice(facts: dict[str, Any]) -> dict[str, Any]:
    share = facts["share_pct"]
    plats = facts["platforms"]
    worst = max(plats, key=lambda x: x["negative_pct"]) if plats else None
    summary = (
        f"{facts['brand']}本期正面 {share['正面']}%、负面 {share['负面']}%，"
        f"样本 {facts['sample_count']} 条。"
    )
    actions = [
        {
            "title": "稳住正面表达",
            "body": f"正面占比 {share['正面']}%，优先把高频正面描述固化进知识库与对外口径。",
        },
        {
            "title": "压降负面口径",
            "body": (
                f"重点看{(worst or {}).get('name') or '高负面平台'}："
                f"负面 {(worst or {}).get('negative_pct', share['负面'])}%，先核对争议点是否属实。"
            ),
        },
        {
            "title": "补齐中性转化",
            "body": f"中性 {share['中性']}% 仍高，把中性场景改写成可验证的优势证据与案例。",
        },
    ]
    return {"summary": summary, "actions": actions, "source": "rule_fallback"}


def _generate_advice(facts: dict[str, Any]) -> dict[str, Any]:
    client = DeepseekClient()
    # 导出建议：有 Key 就调；不绑 sentiment_keyword 开关
    if not str(getattr(client, "api_key", "") or "").strip():
        return _fallback_advice(facts)
    system = (
        "你是 GEO 品牌口碑分析顾问。只根据给定 JSON 事实写结论，禁止编造未出现的数据、平台或事件。"
        "输出严格 JSON：{\"summary\":\"一句总览≤60字\",\"actions\":[{\"title\":\"≤12字\",\"body\":\"≤40字\"},...]}"
        "actions 必须恰好 3 条，可执行、具体，对应高负面平台或环比变化或高频描述。"
    )
    user = "事实JSON如下，请生成建议：\n" + json.dumps(facts, ensure_ascii=False)
    try:
        raw = client.chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            max_tokens=600,
            source="brand-analysis-b1",
        )
        payload = DeepseekClient._parse_json_payload(raw)
        if not isinstance(payload, dict):
            raise DeepseekApiError("建议 JSON 非对象")
        summary = str(payload.get("summary") or "").strip()
        actions_raw = payload.get("actions") if isinstance(payload.get("actions"), list) else []
        actions = []
        for item in actions_raw[:3]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            body = str(item.get("body") or "").strip()
            if title and body:
                actions.append({"title": title[:16], "body": body[:48]})
        if not summary or len(actions) < 3:
            raise DeepseekApiError("建议字段不完整")
        while len(actions) < 3:
            actions.append({"title": "持续监测", "body": "保持周度复盘，跟踪负面平台变化。"})
        return {"summary": summary[:80], "actions": actions[:3], "source": "deepseek"}
    except Exception as exc:  # noqa: BLE001 - 导出兜底，勿因 LLM 失败整单失败
        logger.warning("brand analysis b1 advice fallback: %s", exc)
        return _fallback_advice(facts)


def _advice_cache_key(tenant_id: int, grain: str, facts: dict[str, Any]) -> str:
    payload = {
        "tenant_id": tenant_id,
        "grain": grain,
        "period_label": facts.get("period_label"),
        "sample_count": facts.get("sample_count"),
        "share_pct": facts.get("share_pct"),
        "delta_pt": facts.get("delta_pt"),
        "platforms": facts.get("platforms"),
        "top_descriptions": facts.get("top_descriptions"),
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]
    return f"{tenant_id}_{grain}_{digest}"


def _load_advice_cache(cache_key: str) -> dict[str, Any] | None:
    path = _ADVICE_CACHE_DIR / f"{cache_key}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("actions"):
            return data
    except Exception as exc:  # noqa: BLE001
        logger.warning("brand analysis b1 cache read fail: %s", exc)
    return None


def _save_advice_cache(cache_key: str, advice: dict[str, Any]) -> None:
    try:
        _ADVICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (_ADVICE_CACHE_DIR / f"{cache_key}.json").write_text(
            json.dumps(advice, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("brand analysis b1 cache write fail: %s", exc)


class StackedBarRow(Flowable):
    """平台一行：名称 + 100% 堆叠条。"""

    def __init__(self, name: str, pos: float, mid: float, neg: float, width: float, height: float = 12):
        super().__init__()
        self.name = name
        self.pos = max(0.0, pos)
        self.mid = max(0.0, mid)
        self.neg = max(0.0, neg)
        self.bar_width = width
        self.bar_height = height
        self.name_w = 58
        self._width = width
        self._height = height + 2

    def wrap(self, availWidth, availHeight):
        self._width = availWidth
        return availWidth, self._height

    def draw(self):
        c = self.canv
        c.setFillColor(COLOR_INK)
        c.setFont(PDF_FONT, 9)
        label = self.name
        if c.stringWidth(label, PDF_FONT, 9) > self.name_w - 2:
            while label and c.stringWidth(label + "…", PDF_FONT, 9) > self.name_w - 2:
                label = label[:-1]
            label = label + "…"
        c.drawString(0, 2, label)

        x0 = self.name_w
        total_w = max(40.0, self._width - self.name_w)
        y = 1
        h = self.bar_height
        total = self.pos + self.mid + self.neg
        if total <= 0:
            c.setFillColor(COLOR_LINE)
            c.roundRect(x0, y, total_w, h, 2, stroke=0, fill=1)
            return
        segments = [
            (self.pos / total * total_w, COLOR_OK, self.pos),
            (self.mid / total * total_w, COLOR_MID, self.mid),
            (self.neg / total * total_w, COLOR_BAD, self.neg),
        ]
        x = x0
        for w, color, pct in segments:
            if w <= 0:
                continue
            c.setFillColor(color)
            c.rect(x, y, w, h, stroke=0, fill=1)
            if w >= 28:
                c.setFillColor(colors.white)
                c.setFont(PDF_FONT, 7)
                txt = f"{pct:.0f}%"
                tw = c.stringWidth(txt, PDF_FONT, 7)
                c.drawString(x + (w - tw) / 2, y + 2.5, txt)
            x += w


def _kpi_table(facts: dict[str, Any], styles: dict[str, ParagraphStyle], content_w: float) -> Table:
    # 2026-09-07 - KPI 标签曾与大数字重叠（Paragraph leading 不够）- 改三行分格垂直排
    share = facts["share_pct"]
    deltas = facts["delta_pt"]

    def delta_text(key: str) -> str:
        if deltas is None or deltas.get(key) is None:
            return "环比 —"
        val = float(deltas[key])
        sign = "+" if val > 0 else ""
        return f"环比 {sign}{val:.1f} pt"

    gap = 4 * mm
    card_w = (content_w - 2 * gap) / 3
    label_style = ParagraphStyle(
        "kpi_label", fontName=PDF_FONT, fontSize=9, textColor=COLOR_MUTED, leading=12, alignment=1,
    )
    value_style = ParagraphStyle(
        "kpi_value", fontName=PDF_FONT, fontSize=20, leading=26, alignment=1,
    )
    delta_style = ParagraphStyle(
        "kpi_delta", fontName=PDF_FONT, fontSize=8, textColor=COLOR_MUTED, leading=11, alignment=1,
    )

    def one_card(label: str, pct: float, value_color: str, bg: str, delta_key: str) -> Table:
        value_style_local = ParagraphStyle(
            f"kpi_value_{label}",
            parent=value_style,
            textColor=colors.HexColor(value_color),
        )
        inner = Table(
            [
                [Paragraph(label, label_style)],
                [Paragraph(f"<b>{pct:.1f}%</b>", value_style_local)],
                [Paragraph(delta_text(delta_key), delta_style)],
            ],
            colWidths=[card_w - 4],
        )
        inner.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (0, 0), 0),
            ("BOTTOMPADDING", (0, 0), (0, 0), 4),
            ("TOPPADDING", (0, 1), (0, 1), 2),
            ("BOTTOMPADDING", (0, 1), (0, 1), 4),
            ("TOPPADDING", (0, 2), (0, 2), 0),
            ("BOTTOMPADDING", (0, 2), (0, 2), 0),
        ]))
        t = Table([[inner]], colWidths=[card_w])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)),
            ("BOX", (0, 0), (-1, -1), 0.6, COLOR_LINE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        return t

    cards = [
        one_card("正面", share["正面"], "#15803d", "#ecfdf5", "正面"),
        one_card("中性", share["中性"], "#334155", "#f8fafc", "中性"),
        one_card("负面", share["负面"], "#b91c1c", "#fef2f2", "负面"),
    ]
    row = [cards[0], "", cards[1], "", cards[2]]
    t = Table([row], colWidths=[card_w, gap, card_w, gap, card_w])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _desc_table(rows: list[dict[str, Any]], styles: dict[str, ParagraphStyle], content_w: float) -> Table:
    sent_color = {"正面": "#15803d", "中性": "#64748b", "负面": "#b91c1c"}
    head = [
        Paragraph("<b>情感</b>", styles["th"]),
        Paragraph("<b>要点</b>", styles["th"]),
        Paragraph("<para align='right'><b>条数</b></para>", styles["th"]),
    ]
    data = [head]
    for row in rows[:4]:
        sent = row.get("sentiment") or "—"
        color = sent_color.get(str(sent), "#64748b")
        desc = str(row.get("description") or "")
        if len(desc) > 56:
            desc = desc[:55] + "…"
        data.append([
            Paragraph(f"<font color='{color}'><b>{sent}</b></font>", styles["td"]),
            Paragraph(desc, styles["td"]),
            Paragraph(f"<para align='right'>{int(row.get('sample_count') or 0)}</para>", styles["td"]),
        ])
    col_sent, col_cnt = 16 * mm, 16 * mm
    col_desc = content_w - col_sent - col_cnt
    t = Table(data, colWidths=[col_sent, col_desc, col_cnt])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("BOX", (0, 0), (-1, -1), 0.5, COLOR_LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, COLOR_LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafbfc")]),
    ]))
    return t


def _build_pdf(facts: dict[str, Any], advice: dict[str, Any]) -> bytes:
    # 2026-09-07 - V1.1：KPI 分卡留缝；口碑要点改情感/要点/条数表；标签/数字分格防重叠
    _register_font()
    styles = {
        "hero": ParagraphStyle(
            "ba_hero", fontName=PDF_FONT, fontSize=16, textColor=COLOR_INK, leading=20, spaceAfter=0,
        ),
        "sample": ParagraphStyle(
            "ba_sample", fontName=PDF_FONT, fontSize=9, textColor=colors.HexColor("#15803d"), leading=12, alignment=2,
        ),
        "sub": ParagraphStyle(
            "ba_sub", fontName=PDF_FONT, fontSize=9, textColor=COLOR_MUTED, leading=12, spaceAfter=10,
        ),
        "h": ParagraphStyle(
            "ba_h", fontName=PDF_FONT, fontSize=11, textColor=COLOR_INK, leading=14, spaceBefore=10, spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "ba_body", fontName=PDF_FONT, fontSize=9.5, textColor=COLOR_INK, leading=14, spaceAfter=4,
        ),
        "muted": ParagraphStyle(
            "ba_muted", fontName=PDF_FONT, fontSize=8, textColor=COLOR_MUTED, leading=11,
        ),
        "foot": ParagraphStyle(
            "ba_foot", fontName=PDF_FONT, fontSize=7, textColor=colors.HexColor("#94a3b8"), leading=9, spaceBefore=10,
        ),
        "cell": ParagraphStyle(
            "ba_cell", fontName=PDF_FONT, fontSize=9, textColor=COLOR_INK, leading=12,
        ),
        "th": ParagraphStyle(
            "ba_th", fontName=PDF_FONT, fontSize=8.5, textColor=COLOR_MUTED, leading=11,
        ),
        "td": ParagraphStyle(
            "ba_td", fontName=PDF_FONT, fontSize=9, textColor=COLOR_INK, leading=12,
        ),
        "action_title": ParagraphStyle(
            "ba_at", fontName=PDF_FONT, fontSize=10, textColor=COLOR_INK, leading=13, spaceAfter=1,
        ),
        "action_body": ParagraphStyle(
            "ba_ab", fontName=PDF_FONT, fontSize=8.5, textColor=COLOR_MUTED, leading=12,
        ),
    }

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=12 * mm,
        title=f"{facts['brand']} · 品牌口碑",
    )
    content_w = A4[0] - 32 * mm
    story: list[Any] = []
    # 2026-09-07 - 头：一行「品牌 · 品牌口碑」+ 右上样本；去掉单独品牌行与「×环比」
    head = Table(
        [[
            Paragraph(f"{facts['brand']} · 品牌口碑", styles["hero"]),
            Paragraph(f"样本 {facts['sample_count']}", styles["sample"]),
        ]],
        colWidths=[content_w * 0.72, content_w * 0.28],
    )
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(head)
    story.append(Paragraph(str(facts["period_label"] or "—"), styles["sub"]))
    story.append(_kpi_table(facts, styles, content_w))
    story.append(Spacer(1, 8))
    story.append(Paragraph(str(advice["summary"]), styles["body"]))

    story.append(Paragraph("平台情感构成", styles["h"]))
    story.append(Paragraph(
        "<font color='#22c55e'>■</font> 正面　"
        "<font color='#94a3b8'>■</font> 中性　"
        "<font color='#ef4444'>■</font> 负面",
        styles["muted"],
    ))
    story.append(Spacer(1, 4))
    for p in facts["platforms"]:
        story.append(StackedBarRow(
            str(p["name"]),
            float(p["positive_pct"]),
            float(p["neutral_pct"]),
            float(p["negative_pct"]),
            width=content_w,
            height=14,
        ))
        story.append(Spacer(1, 4))

    story.append(Paragraph("口碑要点", styles["h"]))
    story.append(_desc_table(facts["top_descriptions"], styles, content_w))

    story.append(Paragraph("行动建议", styles["h"]))
    accent = [
        colors.HexColor("#2563eb"),
        colors.HexColor("#0d9488"),
        colors.HexColor("#d97706"),
    ]
    action_blocks: list[Any] = []
    for i, act in enumerate(advice["actions"][:3]):
        inner = Table(
            [[
                Paragraph(f"<b>{i + 1}. {act['title']}</b>", styles["action_title"]),
            ], [
                Paragraph(act["body"], styles["action_body"]),
            ]],
            colWidths=[content_w - 5 * mm],
        )
        inner.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        card = Table([["", inner]], colWidths=[3.2 * mm, content_w - 3.2 * mm])
        card.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), accent[i % len(accent)]),
            ("BACKGROUND", (1, 0), (1, 0), COLOR_CARD),
            ("BOX", (0, 0), (-1, -1), 0.4, COLOR_LINE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (0, 0), 0),
            ("RIGHTPADDING", (0, 0), (0, 0), 0),
            ("LEFTPADDING", (1, 0), (1, 0), 8),
            ("RIGHTPADDING", (1, 0), (1, 0), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        action_blocks.append(card)
        action_blocks.append(Spacer(1, 5))
    story.append(KeepTogether(action_blocks))
    # 2026-09-07 - 页脚「占比口径/建议来源/仅供参考」对客户多余 - 去掉
    doc.build(story)
    return buf.getvalue()


def _safe_filename(brand: str, period_label: str, grain_label: str) -> str:
    raw = f"{brand}_品牌口碑_{period_label}_{grain_label}.pdf"
    cleaned = re.sub(r'[<>:"/\\|?*]+', "-", raw).strip(" .-") or "品牌口碑.pdf"
    return cleaned[:120]


def export_brand_analysis_snapshot_pdf(
    db: Session,
    current: CurrentSession,
    *,
    tenant_id: int | None,
    compare_period: str | None = "month",
) -> tuple[bytes, str]:
    """D1：按页面当前环比窗口导出 B1 PDF。返回 (pdf_bytes, filename)。"""
    require_brand_analysis_export_permission(db, current)
    grain = resolve_brand_compare_period(compare_period)
    grain_label = _GRAIN_LABEL.get(grain, grain)
    data = build_brand_analysis_dashboard(
        db,
        current,
        tenant_id=tenant_id,
        parse_sentiments=False,
        compare_period=grain,
    )
    brand = str(data.get("company_name") or data.get("brand_name") or "监测品牌")
    facts = _facts_payload(data, brand=brand, grain_label=grain_label)
    resolved_tenant = int(data.get("tenant_id") or tenant_id or 0)
    cache_key = _advice_cache_key(resolved_tenant, grain, facts)
    advice = _load_advice_cache(cache_key)
    if advice is None:
        advice = _generate_advice(facts)
        if advice.get("source") == "deepseek":
            _save_advice_cache(cache_key, advice)
    pdf_bytes = _build_pdf(facts, advice)
    filename = _safe_filename(brand, str(facts.get("period_label") or ""), grain_label)
    return pdf_bytes, filename


def content_disposition_attachment(filename: str) -> str:
    ascii_name = re.sub(r"[^\x20-\x7E]", "_", filename) or "brand-analysis.pdf"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"