"""项目结项报告 HTML（完整版结构）。

2026-08-04 - 收编桌面「生产数据完整版」骨架；成绩样本改本品牌先露出，竞品领先进挑战区
2026-08-04 - 「结果完整度」改称任务回填完整度，不放成绩总览主 KPI
"""

from __future__ import annotations

import html
from typing import Any


def _text(value: Any, fallback: str = "-") -> str:
    text = str(value or "").strip()
    return html.escape(text or fallback)


def _number(value: Any, suffix: str = "") -> str:
    if value is None or value == "":
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _text(value)
    if number.is_integer():
        return f"{int(number)}{suffix}"
    return f"{number:.1f}{suffix}"


def _pct(value: Any) -> str:
    return _number(value, "%")


def _platform_label(code: str, platform_names: dict[str, str]) -> str:
    return platform_names.get(code) or code or "未知平台"


def _evidence_cards(rows: list[dict[str, Any]], platform_names: dict[str, str], *, empty: str) -> str:
    if not rows:
        return f'<p class="sub">{_text(empty)}</p>'
    parts = []
    for row in rows:
        shot = row.get("screenshot_url")
        shot_html = (
            f'<a href="{html.escape(str(shot))}" target="_blank" rel="noopener">打开</a>'
            if shot
            else "无"
        )
        rank = row.get("rank")
        parts.append(
            f"""
        <article class="evidence-card">
          <header><b>{_text(_platform_label(str(row.get('platform') or ''), platform_names))}</b>
            <span>{_text(row.get('prompt'))}</span></header>
          <p>{_text(row.get('answer_excerpt'))}</p>
          <footer>本品牌推荐排名：{_number(rank)} · 回答附带信源：{_number(row.get('reference_count'))} 条 ·
            情感：{_text(row.get('sentiment') or '-')} · 快照：{shot_html}</footer>
        </article>
            """
        )
    return "".join(parts)


def _platform_table(rows: list[dict[str, Any]], platform_names: dict[str, str]) -> str:
    if not rows:
        return '<tr><td colspan="4" class="muted">暂无平台维度数据</td></tr>'
    html_rows = []
    for row in rows[:16]:
        code = str(row.get("platform") or "")
        label = _platform_label(code, platform_names) or row.get("platform_name") or code
        html_rows.append(
            "<tr>"
            f"<td>{_text(label)}</td>"
            f"<td>{_number(row.get('completed'))}/{_number(row.get('total'))}</td>"
            f"<td>{_pct(row.get('mention_rate'))}</td>"
            f"<td>{_number(row.get('avg_rank'))}</td>"
            "</tr>"
        )
    return "".join(html_rows)


def _prompt_score_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<tr><td colspan="6" class="muted">暂无问题词成绩</td></tr>'
    parts = []
    for idx, row in enumerate(rows[:30], 1):
        parts.append(
            "<tr>"
            f"<td>{idx}</td>"
            f"<td>{_text(row.get('prompt'))}</td>"
            f"<td>{_number(row.get('completed'))}</td>"
            f"<td>{_pct(row.get('mention_rate'))}</td>"
            f"<td>{_number(row.get('avg_rank'))}</td>"
            f"<td>{_pct(row.get('top3_rate'))}</td>"
            "</tr>"
        )
    return "".join(parts)


def _risk_table(rows: list[dict[str, Any]]) -> str:
    focus = [r for r in rows if str(r.get("risk_level") or "") in {"P0", "P1", "样本不足"}]
    if not focus:
        return '<tr><td colspan="5" class="muted">当前无高风险或样本不足问题词</td></tr>'
    parts = []
    for row in focus[:20]:
        level = str(row.get("risk_level") or "")
        cls = "risk-p0" if level == "P0" else ("risk-p1" if level == "P1" else "risk-sparse")
        parts.append(
            "<tr>"
            f"<td><span class=\"risk-tag {cls}\">{_text(level)}</span></td>"
            f"<td>{_text(row.get('prompt'))}</td>"
            f"<td>{_pct(row.get('mention_rate'))}</td>"
            f"<td>{_number(row.get('avg_rank'))}</td>"
            f"<td>{_text(row.get('risk_reason'))}</td>"
            "</tr>"
        )
    return "".join(parts)


def _group_score_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    parts = []
    for row in rows[:16]:
        parts.append(
            "<tr>"
            f"<td>{_text(row.get('group'))}</td>"
            f"<td>{_number(row.get('prompt_count'))}</td>"
            f"<td>{_number(row.get('completed'))}</td>"
            f"<td>{_pct(row.get('mention_rate'))}</td>"
            f"<td>{_number(row.get('avg_rank'))}</td>"
            f"<td>{_pct(row.get('top3_rate'))}</td>"
            "</tr>"
        )
    return "".join(parts)


def _lifecycle_cards(lifecycle: dict[str, Any]) -> str:
    if not lifecycle.get("available"):
        return f'<p class="sub">{_text(lifecycle.get("note") or "暂无期初/峰值/期末数据。")}</p>'
    # 2026-08-05 - 勿再贴首末窗卡片，与上方「首末窗口对比」重复，易被当成数据冲突
    cards = [
        ("期初监测日（单日）", lifecycle.get("initial") or {}),
        ("峰值日（单日）", lifecycle.get("peak") or {}),
        ("期末监测日（单日）", lifecycle.get("final") or {}),
    ]
    parts = []
    for title, node in cards:
        parts.append(
            f'<div class="kpi"><span>{_text(title)}</span>'
            f"<b>{_pct(node.get('mention_rate'))}</b>"
            f"<em>{_text(node.get('date') or node.get('label') or '-')}</em></div>"
        )
    note = lifecycle.get("note") or ""
    return f'<div class="grid3">{"".join(parts)}</div><p class="sub">{_text(note)}</p>'


def _next_actions_html(actions: dict[str, Any]) -> str:
    blocks = [
        ("巩固", actions.get("consolidate") or []),
        ("攻坚", actions.get("attack") or []),
        ("监测", actions.get("monitor") or []),
    ]
    parts = []
    for title, items in blocks:
        lis = "".join(f"<li>{_text(item)}</li>" for item in items[:6]) or "<li>暂无</li>"
        parts.append(f'<div class="note"><b>{_text(title)}</b><ol class="action-list">{lis}</ol></div>')
    return f'<div class="grid3">{"".join(parts)}</div>'


def _delta_text(value: Any, *, higher_better: bool = True, unit: str = "pt") -> str:
    if value is None or value == "":
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if abs(number) < 0.05:
        return "持平"
    improved = (number > 0) if higher_better else (number < 0)
    arrow = "↑" if improved else "↓"
    sign = "+" if number > 0 else ""
    return f"{arrow}{sign}{number:.1f}{unit}"


def _comparison_overall_cards(comparison: dict[str, Any], platform_names: dict[str, str] | None = None) -> str:
    if not comparison.get("available"):
        return f'<p class="sub">{_text(comparison.get("note") or "暂无首末窗口对比数据。")}</p>'
    platform_names = platform_names or {}
    overall = comparison.get("overall") or {}
    early = overall.get("early") or {}
    late = overall.get("late") or {}
    early_label = comparison.get("early_label") or "期初窗"
    late_label = comparison.get("late_label") or "期末窗"
    # 2026-08-05 - 首末窗卡片换行难看 - 日期只写一次，期初/期末分栏，避免「33.8% →」折行
    cards = [
        (
            "品牌提及率",
            _pct(early.get("mention_rate")),
            _pct(late.get("mention_rate")),
            _delta_text(overall.get("delta_mention_rate"), higher_better=True, unit="pt"),
        ),
        (
            "平均推荐排名",
            _number(early.get("avg_rank")),
            _number(late.get("avg_rank")),
            _delta_text(overall.get("delta_avg_rank"), higher_better=False, unit=""),
        ),
        (
            "Top3 占比",
            _pct(early.get("top3_rate")),
            _pct(late.get("top3_rate")),
            _delta_text(overall.get("delta_top3_rate"), higher_better=True, unit="pt"),
        ),
        (
            "窗口样本量",
            _number(early.get("completed")),
            _number(late.get("completed")),
            "各自有效样本",
        ),
    ]
    body = "".join(
        f"""
        <div class="cmp-card">
          <div class="cmp-title">{_text(title)}</div>
          <div class="cmp-row">
            <div class="cmp-col"><small>期初</small><strong>{early_v}</strong></div>
            <div class="cmp-arrow" aria-hidden="true">→</div>
            <div class="cmp-col"><small>期末</small><strong>{late_v}</strong></div>
          </div>
          <div class="cmp-delta">{_text(str(delta))}</div>
        </div>
        """
        for title, early_v, late_v, delta in cards
    )
    highlights: list[str] = []
    if overall.get("delta_mention_rate") is not None:
        d = float(overall["delta_mention_rate"])
        verb = "提升" if d > 0 else ("回落" if d < 0 else "持平")
        highlights.append(
            f"全域提及率首末窗{verb} {abs(d)}pt（{early.get('mention_rate')}% → {late.get('mention_rate')}%）"
        )
    reliable_rows = [
        r
        for r in list(comparison.get("platforms") or [])
        if r.get("reliable") and r.get("delta_mention_rate") is not None
    ]
    if reliable_rows:
        best = max(reliable_rows, key=lambda r: float(r["delta_mention_rate"]))
        worst = min(reliable_rows, key=lambda r: float(r["delta_mention_rate"]))
        best_name = _platform_label(str(best.get("platform") or ""), platform_names)
        worst_name = _platform_label(str(worst.get("platform") or ""), platform_names)
        if float(best["delta_mention_rate"]) > 0:
            highlights.append(
                f"提及率提升最大：{best_name}（{best['early'].get('mention_rate')}% → {best['late'].get('mention_rate')}%，"
                f"Δ {best['delta_mention_rate']}pt）"
            )
        if float(worst["delta_mention_rate"]) < 0:
            highlights.append(
                f"提及率回落最明显：{worst_name}（{worst['early'].get('mention_rate')}% → {worst['late'].get('mention_rate')}%，"
                f"Δ {worst['delta_mention_rate']}pt）"
            )
    hl = "".join(f"<li>{_text(item)}</li>" for item in highlights[:4]) or "<li>暂无升降结论</li>"
    return f"""
    <div class="note">{_text(comparison.get("note"))}</div>
    <p class="cmp-window">对比窗口：{_text(early_label)} → {_text(late_label)}</p>
    <div class="cmp-grid">{body}</div>
    <ul class="clean" style="margin-top:14px">{hl}</ul>
    """


def _platform_comparison_table(rows: list[dict[str, Any]], platform_names: dict[str, str]) -> str:
    if not rows:
        return '<tr><td colspan="8" class="muted">暂无分平台首末窗对比</td></tr>'
    parts = []
    for row in rows[:16]:
        code = str(row.get("platform") or "")
        label = _platform_label(code, platform_names)
        early = row.get("early") or {}
        late = row.get("late") or {}
        reliable = bool(row.get("reliable"))
        status = "可对比" if reliable else "样本不足"
        parts.append(
            "<tr>"
            f"<td>{_text(label)}</td>"
            f"<td>{_number(early.get('completed'))}</td>"
            f"<td>{_pct(early.get('mention_rate'))}</td>"
            f"<td>{_number(early.get('avg_rank'))}</td>"
            f"<td>{_number(late.get('completed'))}</td>"
            f"<td>{_pct(late.get('mention_rate'))}</td>"
            f"<td>{_number(late.get('avg_rank'))}</td>"
            f"<td>{_delta_text(row.get('delta_mention_rate'), higher_better=True, unit='pt')}"
            f" / {_delta_text(row.get('delta_avg_rank'), higher_better=False, unit='')}"
            f"<div class='muted'>{_text(status)}</div></td>"
            "</tr>"
        )
    return "".join(parts)


def _scope_tags(rows: list[dict[str, Any]], *, key: str, soft: bool = False) -> str:
    if not rows:
        return '<span class="muted">暂无</span>'
    cls = "scope-tag soft" if soft else "scope-tag"
    return "".join(
        f'<span class="{cls}">{_text(row.get(key))}<b>{_number(row.get("count"))} 次</b></span>'
        for row in rows[:16]
    )


def _bar_rows(rows: list[dict[str, Any]], platform_names: dict[str, str]) -> str:
    if not rows:
        return '<p class="sub">暂无平台差异数据</p>'
    max_rate = max((float(r.get("mention_rate") or 0) for r in rows), default=1) or 1
    parts = []
    for row in rows[:12]:
        rate = float(row.get("mention_rate") or 0)
        width = max(2, round(rate / max_rate * 100, 1))
        label = _platform_label(str(row.get("platform") or ""), platform_names)
        parts.append(
            f"""
    <div class="bar-row">
      <div class="bar-meta"><b>{_text(label)}</b>
        <span>样本 {_number(row.get('completed'))} · 均排 {_number(row.get('avg_rank'))}</span></div>
      <div class="bar-track"><i style="width:{width}%;background:#14b8a6"></i></div>
      <strong>{_pct(rate)}</strong>
    </div>"""
        )
    return "".join(parts)


def _trend_svg(points: list[dict[str, Any]]) -> str:
    if len(points) < 2:
        return '<p class="sub">周期内趋势节点不足，完整明细可在报告中心查询。</p>'
    rates = [float(p.get("mention_rate") or 0) for p in points]
    lo, hi = min(rates), max(rates)
    span = (hi - lo) or 1.0
    left, right, top, bottom = 48.0, 712.0, 34.0, 226.0
    n = len(points) - 1

    def xy(i: int, rate: float) -> tuple[float, float]:
        x = left if n == 0 else left + (right - left) * i / n
        y = bottom - (rate - lo) / span * (bottom - top)
        return x, y

    coords = [xy(i, rate) for i, rate in enumerate(rates)]
    line = " L ".join(f"{x:.1f} {y:.1f}" for x, y in coords)
    area = f"M {coords[0][0]:.1f} {bottom} L " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in coords) + f" L {coords[-1][0]:.1f} {bottom} Z"
    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#fff" stroke="#14b8a6" stroke-width="3"/>'
        for x, y in coords
    )
    labels = []
    for idx in {0, len(points) // 2, len(points) - 1}:
        x, _ = coords[idx]
        labels.append(
            f'<text x="{x:.1f}" y="252" text-anchor="middle" class="axis">{_text(points[idx].get("label"))}</text>'
        )
    return f"""
    <svg class="line-chart" viewBox="0 0 760 260" role="img">
      <defs><linearGradient id="g1" x1="0" x2="0" y1="0" y2="1">
        <stop stop-color="#14b8a6" stop-opacity=".28"/><stop offset="1" stop-color="#14b8a6" stop-opacity="0"/>
      </linearGradient></defs>
      <line x1="48" x2="712" y1="226" y2="226" class="grid"/>
      <line x1="48" x2="712" y1="34" y2="34" class="grid"/>
      <path d="{area}" fill="url(#g1)"/>
      <path d="M {line}" fill="none" stroke="#14b8a6" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
      {dots}{''.join(labels)}
    </svg>"""


def _prompt_table(rows: list[dict[str, Any]], platform_names: dict[str, str], platform_scope: list[dict[str, Any]]) -> str:
    plat_labels = "、".join(_platform_label(str(p.get("platform") or ""), platform_names) for p in platform_scope[:12]) or "-"
    if not rows:
        return '<tr><td colspan="4" class="muted">暂无监测问题明细</td></tr>'
    parts = []
    for i, row in enumerate(rows[:15], start=1):
        parts.append(
            "<tr>"
            f"<td>{i}</td>"
            f"<td>{_text(row.get('prompt'))}</td>"
            f"<td>{_number(row.get('count'))}</td>"
            f"<td>{_text(plat_labels)}</td>"
            "</tr>"
        )
    return "".join(parts)


def _source_table(rows: list[dict[str, Any]], platform_names: dict[str, str]) -> str:
    if not rows:
        return '<tr><td colspan="4" class="muted">暂无高频信源</td></tr>'
    parts = []
    for i, row in enumerate(rows[:15], start=1):
        plats = row.get("platforms") or []
        if isinstance(plats, list):
            plat_text = "、".join(_platform_label(str(p), platform_names) for p in plats[:6]) or "-"
        else:
            plat_text = str(plats or "-")
        url = str(row.get("url") or "").strip()
        title = row.get("title") or url or "未命名信源"
        title_html = (
            f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{_text(title)}</a>'
            if url.startswith("http")
            else _text(title)
        )
        parts.append(
            "<tr>"
            f"<td>{i}</td>"
            f"<td>{title_html}</td>"
            f"<td>{_number(row.get('count'))}</td>"
            f"<td>{_text(plat_text)}</td>"
            "</tr>"
        )
    return "".join(parts)


def _evidence_index_table(rows: list[dict[str, Any]], platform_names: dict[str, str]) -> str:
    if not rows:
        return '<tr><td colspan="6" class="muted">暂无可回查样本索引</td></tr>'
    parts = []
    for row in rows[:12]:
        shot = row.get("screenshot_url")
        shot_html = (
            f'<a href="{html.escape(str(shot))}" target="_blank" rel="noopener">快照</a>'
            if shot
            else "—"
        )
        parts.append(
            "<tr>"
            f"<td>{_text(row.get('role'))}</td>"
            f"<td>{_text(_platform_label(str(row.get('platform') or ''), platform_names))}</td>"
            f"<td>{_text(row.get('prompt'))}</td>"
            f"<td>{_number(row.get('rank'))}</td>"
            f"<td>{_number(row.get('reference_count'))}</td>"
            f"<td>{shot_html}</td>"
            "</tr>"
        )
    return "".join(parts)


def build_completion_report_html(
    payload: dict[str, Any],
    platform_names: dict[str, str] | None = None,
) -> str:
    """生成结项完整版 HTML；数据来自 payload + completion_pack。"""
    platform_names = platform_names or {}
    brand_name = payload.get("brand_name") or payload.get("company_name") or "客户企业"
    company_name = payload.get("company_name") or brand_name
    title = payload.get("title") or payload.get("report_title") or f"{brand_name} GEO服务总结报告"
    period_label = payload.get("period_label") or "服务周期"
    generated_at = str(payload.get("generated_at") or "")[:16].replace("T", " ")
    kpis = dict(payload.get("kpis") or {})
    for key in ("mention_rate", "avg_rank", "top3_rate", "positive_rate", "completed_count", "source_count"):
        if kpis.get(key) in (None, "") and payload.get(key) not in (None, ""):
            kpis[key] = payload.get(key)

    pack = dict(payload.get("completion_pack") or {})
    assets = dict(pack.get("assets") or {})

    completed = int(float(assets.get("completed_count") or kpis.get("completed_count") or 0))
    screenshots = int(float(assets.get("screenshot_count") or 0))
    citations = int(float(assets.get("citation_count") or 0))
    retention = assets.get("snapshot_retention_rate")
    fill_rate = assets.get("result_fill_rate")
    mentioned = int(float(assets.get("mentioned_count") or 0))
    top3_count = int(float(assets.get("top3_count") or 0))

    platform_stats = pack.get("platform_stats") or payload.get("platform_stats") or []
    top_sources = pack.get("top_sources") or payload.get("top_sources") or []
    competitors = pack.get("competitors") or payload.get("competitors") or []
    competitor_names: list[str] = []
    for item in competitors if isinstance(competitors, list) else []:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("brand_name") or "").strip()
        else:
            name = str(item or "").strip()
        if name:
            competitor_names.append(name)

    brand_evidence = list(pack.get("brand_evidence") or [])
    evidence_index = list(pack.get("evidence_index") or [])
    if not evidence_index:
        evidence_index = [
            {
                "role": "成绩样本",
                "platform": row.get("platform"),
                "prompt": row.get("prompt"),
                "rank": row.get("rank"),
                "reference_count": row.get("reference_count"),
                "screenshot_url": row.get("screenshot_url"),
            }
            for row in brand_evidence
        ]
    # 2026-08-04 - 去掉挑战区 - 证据索引只保留本品牌成绩样本
    evidence_index = [row for row in evidence_index if str(row.get("role") or "") != "挑战样本"]
    prompt_scope = list(pack.get("prompt_scope") or [])
    platform_scope = [
        {**row, "platform": _platform_label(str(row.get("platform") or ""), platform_names)}
        for row in list(pack.get("platform_scope") or [])
    ]
    # 2026-08-04 - 报告中心旧结项无 completion_pack 时 §01 显示 0 - 回退 scope/stats 长度
    platform_count = int(
        float(
            assets.get("platform_count")
            or len(platform_scope)
            or len(platform_stats)
            or payload.get("platform_count")
            or 0
        )
    )
    prompt_count = int(float(assets.get("prompt_count") or len(prompt_scope) or 0))
    trend = list(pack.get("mention_trend") or [])
    period_comparison = dict(pack.get("period_comparison") or {})
    prompt_scorecard = list(pack.get("prompt_scorecard") or [])
    prompt_risks = list(pack.get("prompt_risks") or [])
    group_scorecard = list(pack.get("keyword_group_scorecard") or [])
    lifecycle = dict(pack.get("lifecycle_milestones") or {})
    next_actions = dict(pack.get("next_actions") or {})
    risk_count = int(
        float(assets.get("risk_prompt_count") or sum(1 for r in prompt_risks if r.get("risk_level") in {"P0", "P1"}) or 0)
    )

    hero_summary = (
        f"服务周期内完成 {completed} 条有效监测，沉淀 {screenshots} 份可回查快照，"
        f"覆盖 {platform_count or '-'} 个 AI 平台和 {prompt_count or '-'} 类核心问题场景。"
        f"本阶段品牌提及率为 {_pct(kpis.get('mention_rate'))}，平均推荐排名 {_number(kpis.get('avg_rank'))}，"
        f"Top3 占比 {_pct(kpis.get('top3_rate'))}。"
        if completed
        else "服务周期内暂无足够有效样本，本报告仅输出结项框架与数据补齐提示。"
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{_text(title)}</title>
<style>
:root {{ --navy:#062348; --blue:#1d6bff; --teal:#16c7b7; --green:#21bf73; --orange:#f59e0b; --muted:#637899; --line:#dce8f5; --bg:#eef5fb; }}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);font-family:"Microsoft YaHei","PingFang SC",Arial,sans-serif;color:var(--navy)}} a{{color:#1163db;text-decoration:none}}
.wrap{{width:min(1280px,calc(100vw - 48px));margin:28px auto 72px}} .hero{{border-radius:28px;padding:50px;color:#fff;background:linear-gradient(135deg,#072448,#0b6673 58%,#0d8c7b);box-shadow:0 28px 80px rgba(8,35,72,.20);position:relative;overflow:hidden}}
.hero:after{{content:"";position:absolute;right:-120px;top:-150px;width:420px;height:420px;border-radius:50%;border:54px solid rgba(255,255,255,.08)}} .pill{{display:inline-flex;padding:8px 14px;border:1px solid rgba(255,255,255,.28);border-radius:999px;color:#dffffa;background:rgba(255,255,255,.08);font-size:13px}}
h1{{font-size:44px;line-height:1.18;margin:26px 0 14px}} .hero p{{max-width:860px;font-size:17px;line-height:1.9;color:#e6f6ff}} .meta{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:30px;max-width:1000px}} .meta div{{border:1px solid rgba(255,255,255,.18);border-radius:16px;padding:15px;background:rgba(255,255,255,.08)}} .meta span{{display:block;color:#9fd8ee;font-size:12px;margin-bottom:6px}} .meta b{{font-size:18px;color:#fff}}
.section{{background:#fff;border:1px solid var(--line);border-radius:22px;padding:28px;margin-top:28px;box-shadow:0 18px 48px rgba(40,91,140,.08);page-break-inside:avoid}} .section h2{{font-size:26px;margin:0 0 8px}} .section h3{{font-size:18px;margin:24px 0 12px}} .sub{{color:var(--muted);line-height:1.7;margin:0 0 18px}} .grid4{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}} .grid3{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}} .grid2{{display:grid;grid-template-columns:1fr 1fr;gap:18px}} .kpi{{border:1px solid #dbe9f8;border-radius:18px;padding:18px;background:linear-gradient(180deg,#fff,#f7fbff)}} .kpi span{{display:block;color:var(--muted);font-size:13px}} .kpi b{{display:block;font-size:28px;margin:8px 0;color:#061d3d}} .kpi em{{font-style:normal;color:#079c78;font-size:13px}}
.hero-result{{margin:18px 0 22px;padding:20px 22px;border-radius:20px;background:linear-gradient(135deg,#effdfb,#eef6ff);border:1px solid #cfe9f5}} .hero-result strong{{display:block;font-size:22px;color:#06345f;margin-bottom:6px}} .hero-result p{{margin:0;color:#4f6d8d;line-height:1.7}}
.score-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:18px;margin:18px 0 28px}} .score-card{{border:1px solid #dbe9f8;border-radius:20px;padding:20px;background:linear-gradient(180deg,#ffffff,#f7fbff);position:relative;overflow:hidden}} .score-card:before{{content:"";position:absolute;inset:0 0 auto;height:4px;background:linear-gradient(90deg,#16c7b7,#1d6bff)}} .score-card span{{display:block;color:#637899;font-size:13px}} .score-card b{{display:block;font-size:34px;margin:10px 0 8px;color:#061d3d}} .score-card em{{font-style:normal;color:#057961;font-size:13px}}
.cmp-window{{margin:14px 0 10px;color:#5f7390;font-size:13px;font-weight:600}}
.cmp-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:0 0 20px}}
.cmp-card{{border:1px solid #dbe9f8;border-radius:16px;padding:16px 16px 14px;background:#fff;box-shadow:0 8px 24px rgba(15,55,100,.04)}}
.cmp-title{{color:#5f7390;font-size:13px;font-weight:600;margin-bottom:12px}}
.cmp-row{{display:grid;grid-template-columns:1fr auto 1fr;align-items:end;gap:8px;min-height:52px}}
.cmp-col{{min-width:0}} .cmp-col small{{display:block;color:#8aa0b8;font-size:11px;margin-bottom:4px}}
.cmp-col strong{{display:block;font-size:26px;line-height:1.15;color:#061d3d;font-weight:700;white-space:nowrap}}
.cmp-arrow{{color:#94a3b8;font-size:18px;padding-bottom:4px;line-height:1}}
.cmp-delta{{margin-top:10px;color:#057961;font-size:13px;font-weight:600}}
@media (max-width:1100px){{.cmp-grid{{grid-template-columns:repeat(2,1fr)}}}}

.deliver-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin-top:16px}} .deliver-card{{border:1px solid #dce8f5;border-radius:18px;padding:16px 18px;background:#fbfdff;display:grid;grid-template-columns:auto 1fr;gap:14px;align-items:start}} .deliver-card i{{font-style:normal;display:grid;place-items:center;width:34px;height:34px;border-radius:12px;background:#eaf8ff;color:#1261c4;font-weight:800}} .deliver-card b{{display:block;font-size:15px;margin-bottom:5px}} .deliver-card span{{color:#5e7696;line-height:1.6;font-size:13px}}
.note{{padding:16px 18px;border-left:5px solid var(--teal);background:#effdfb;border-radius:16px;color:#075a58;line-height:1.8}} .warn{{border-left-color:var(--orange);background:#fff8eb;color:#805506}}
.risk-tag{{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;font-weight:700}}
.risk-p0{{background:#fee2e2;color:#b91c1c}}.risk-p1{{background:#ffedd5;color:#c2410c}}.risk-sparse{{background:#f3f4f6;color:#4b5563}}
.action-list{{margin:8px 0 0;padding-left:18px;color:#334155;line-height:1.7}}
table{{width:100%;border-collapse:separate;border-spacing:0;border:1px solid var(--line);border-radius:16px;overflow:hidden}} th,td{{padding:12px 13px;text-align:left;border-bottom:1px solid #e8f0f8;vertical-align:top;font-size:14px}} th{{background:#f3f8fe;color:#46617f}} tr:last-child td{{border-bottom:none}} .muted{{color:var(--muted)}}
.bar-row{{display:grid;grid-template-columns:190px 1fr 70px;gap:12px;align-items:center;margin:12px 0}} .bar-meta b{{display:block}} .bar-meta span{{display:block;color:var(--muted);font-size:12px;margin-top:3px}} .bar-track{{height:13px;background:#eaf1f8;border-radius:999px;overflow:hidden}} .bar-track i{{display:block;height:100%;border-radius:999px}} .bar-row strong{{text-align:right;color:#0c4a6e}} .line-chart{{width:100%;height:auto}} .grid{{stroke:#e2edf7;stroke-width:1}} .axis{{font-size:12px;fill:#6680a1}}
.toc{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}} .toc div{{border:1px solid var(--line);border-radius:14px;padding:14px;background:#fbfdff}} .toc b{{color:var(--blue);margin-right:8px}}
.scope-panel{{border:1px solid #dce8f5;border-radius:18px;padding:18px;background:linear-gradient(180deg,#fbfdff,#f4faff);margin-top:12px}} .scope-panel h4{{margin:0 0 12px;font-size:15px}} .scope-tags{{display:flex;flex-wrap:wrap;gap:10px}} .scope-tag{{display:inline-flex;align-items:center;gap:8px;padding:9px 12px;border:1px solid #bee9df;border-radius:999px;background:#effdf9;color:#075f55;font-size:13px}} .scope-tag b{{font-size:12px;color:#0b806f}} .scope-tag.soft{{border-color:#d6e6fb;background:#f5f9ff;color:#17446f}} .scope-tag.soft b{{color:#2868b4}}
.evidence-card{{border:1px solid #dce8f5;border-radius:16px;padding:16px;background:#fbfdff;margin:10px 0}} .evidence-card header{{display:flex;justify-content:space-between;gap:16px;margin-bottom:10px}} .evidence-card p{{line-height:1.75;color:#28405f;max-height:150px;overflow:hidden}} .evidence-card footer{{color:var(--muted);font-size:13px}}
.tag{{display:inline-block;padding:7px 11px;border-radius:999px;background:#edfdf8;border:1px solid #b9eedf;color:#057961;margin:4px 6px 4px 0;font-size:13px}}
ul.clean{{list-style:none;padding:0;margin:0;display:grid;gap:8px}} ul.clean li{{border:1px solid #dce8f5;border-radius:12px;padding:10px 12px;background:#fbfdff}}
.footer{{text-align:center;color:var(--muted);font-size:12px;margin:20px 0}}
@media print{{.wrap{{width:auto;margin:0}}.section{{box-shadow:none;break-inside:avoid}}}}
@media (max-width:900px){{.meta,.grid4,.grid3,.grid2,.score-grid,.cmp-grid,.deliver-grid,.toc{{grid-template-columns:1fr}} h1{{font-size:32px}} .cmp-col strong{{font-size:22px}}}}

</style>
</head>
<body>
<main class="wrap">
  <section class="hero">
    <span class="pill">GEO Monitor · 服务结项报告</span>
    <h1>{_text(company_name)}<br/>GEO 服务总结报告</h1>
    <p>{_text(hero_summary)}</p>
    <div class="meta">
      <div><span>服务周期</span><b>{_text(period_label)}</b></div>
      <div><span>监测主体</span><b>{_text(brand_name)}</b></div>
      <div><span>有效监测样本</span><b>{_number(completed)} 条</b></div>
      <div><span>生成时间</span><b>{_text(generated_at)}</b></div>
    </div>
  </section>

  <section class="section">
    <h2>目录</h2><p class="sub">围绕服务成绩、数据证据、平台表现与可回查证据链组织内容。</p>
    <div class="toc">
      <div><b>01</b>服务概况</div><div><b>02</b>本次服务成绩总览</div>
      <div><b>03</b>服务执行与交付盘点</div><div><b>04</b>效果数据与证据</div>
      <div><b>05</b>监测方法与数据口径</div><div><b>06</b>平台表现分析</div>
      <div><b>07</b>本品牌高排名样本</div><div><b>08</b>阶段观察与优化空间</div>
      <div><b>09</b>附录与证据链</div>
    </div>
  </section>

  <section class="section">
    <h2>01 服务概况</h2>
    <p class="sub">本项目围绕{_text(brand_name)}在主流 AI 搜索/问答平台中的品牌可见度、推荐顺位、信源引用与竞品对比进行持续监测，并在结项阶段形成可回查的数据与快照证据。</p>
    <div class="grid3">
      <div class="kpi"><span>服务对象</span><b>{_text(company_name)}</b><em>本次结项主体</em></div>
      <div class="kpi"><span>覆盖模型平台</span><b>{_number(platform_count)}</b><em>{_text('、'.join(r.get('platform') or '' for r in platform_scope[:8]) or '按配置平台统计')}</em></div>
      <div class="kpi"><span>有效问题集</span><b>{_number(prompt_count)}</b><em>按监测词与业务场景生成</em></div>
    </div>
    <h3>服务范围</h3>
    <div class="note">对照竞品：{''.join(f'<span class="tag">{_text(n)}</span>' for n in competitor_names[:12]) or '暂无竞品配置'}</div>
  </section>

  <section class="section">
    <h2>02 本次服务成绩总览</h2>
    <p class="sub">以下指标用于呈现本阶段 GEO 服务的可见度成果、推荐位置和证据沉淀情况。</p>
    <div class="hero-result">
      <strong>已形成可验收的 GEO 数据资产与证据链</strong>
      <p>本阶段完成持续监测，沉淀可回查快照、累计引用记录和本品牌高排名代表回答，用于支撑服务验收与后续资料归档。任务回填完整度 {_pct(fill_rate)} 仅反映结果可统计程度，不代表业务达标率。</p>
    </div>
    <div class="score-grid">
      <div class="score-card"><span>品牌提及率</span><b>{_pct(kpis.get('mention_rate'))}</b><em>提及样本 / 有效样本</em></div>
      <div class="score-card"><span>平均推荐排名</span><b>{_number(kpis.get('avg_rank'))}</b><em>越小越靠前</em></div>
      <div class="score-card"><span>Top3 占比</span><b>{_pct(kpis.get('top3_rate'))}</b><em>前三推荐位样本占比</em></div>
      <div class="score-card"><span>正面情绪占比</span><b>{_pct(kpis.get('positive_rate'))}</b><em>正面 / 情绪样本</em></div>
    </div>
    <h3>交付成果清单</h3>
    <div class="deliver-grid">
      <div class="deliver-card"><i>01</i><div><b>{_number(completed)} 条有效监测样本</b><span>已形成可统计结果，覆盖本次服务设定的核心业务问题。</span></div></div>
      <div class="deliver-card"><i>02</i><div><b>{_number(screenshots)} 份可回查快照</b><span>快照留存率 {_pct(retention)}，可用于抽查模型回答与证据链。</span></div></div>
      <div class="deliver-card"><i>03</i><div><b>{_number(citations)} 条累计引用记录</b><span>用于观察哪些内容或站点更容易被 AI 回答采纳。</span></div></div>
      <div class="deliver-card"><i>04</i><div><b>{_number(prompt_count)} 类问题场景</b><span>围绕业务问法与品牌场景形成样本。</span></div></div>
    </div>
    <h3>首末窗口对比</h3>
    <p class="sub">用有监测数据的前 7 日与末 7 日对比，避免单日抖动；分平台详情见 §06。</p>
    {_comparison_overall_cards(period_comparison, platform_names)}
    <h3>期初 / 峰值 / 期末（单日）</h3>
    <p class="sub">以下为有监测数据的单日提及率，与上方「首末 7 日窗均值」口径不同：单日看冲高/收官，窗均值看阶段水平，数字可以不一致。</p>
    {_lifecycle_cards(lifecycle)}
    <h3>高风险问题词</h3>
    <p class="sub">按监测口径自动分级（P0/P1）；共 {_number(risk_count)} 个需关注词。完整词级成绩见 §04。</p>
    <table>
      <thead><tr><th>风险</th><th>监测问题</th><th>提及率</th><th>均排</th><th>说明</th></tr></thead>
      <tbody>{_risk_table(prompt_risks)}</tbody>
    </table>
  </section>

  <section class="section">
    <h2>03 服务执行与交付盘点</h2>
    <p class="sub">本页展示本阶段服务完成情况、有效成果与可回查证据。</p>
    <div class="grid4">
      <div class="kpi"><span>有效监测样本</span><b>{_number(completed)}</b><em>形成可统计结果</em></div>
      <div class="kpi"><span>品牌有效露出</span><b>{_number(mentioned)}</b><em>按提及率折算</em></div>
      <div class="kpi"><span>前三推荐样本</span><b>{_number(top3_count)}</b><em>Top3 位置出现</em></div>
      <div class="kpi"><span>证据快照留存</span><b>{_number(screenshots)}</b><em>支持抽查回看</em></div>
    </div>
    <h3>服务监测范围</h3>
    <div class="scope-panel">
      <h4>本次实际覆盖的高频监测问题</h4>
      <div class="scope-tags">{_scope_tags(prompt_scope, key='prompt')}</div>
    </div>
    <div class="scope-panel">
      <h4>本次实际覆盖的模型平台</h4>
      <div class="scope-tags">{_scope_tags(platform_scope, key='platform', soft=True)}</div>
    </div>
  </section>

  <section class="section">
    <h2>04 效果数据与证据</h2>
    <p class="sub">按照存在感、权重质量、业务证据三层呈现。</p>
    <div class="grid3">
      <div class="note"><b>存在感：</b>品牌提及率 {_pct(kpis.get('mention_rate'))}。</div>
      <div class="note"><b>权重质量：</b>平均排名 {_number(kpis.get('avg_rank'))}，Top3 占比 {_pct(kpis.get('top3_rate'))}。</div>
      <div class="note"><b>证据链：</b>{_number(screenshots)} 个快照、{_number(len(top_sources))} 个业务相关高频信源条目可回查。</div>
    </div>
    <h3>品牌提及率趋势</h3>
    <p class="sub">长周期报告按阶段节点展示均值；完整明细可在报告中心归档查询。</p>
    {_trend_svg(trend)}
    <h3>问题词成绩榜</h3>
    <p class="sub">以监测问题为验收单元：提及率、均排、Top3（样本过少的词见风险表「样本不足」）。</p>
    <table>
      <thead><tr><th>序号</th><th>监测问题</th><th>样本</th><th>提及率</th><th>均排</th><th>Top3</th></tr></thead>
      <tbody>{_prompt_score_table(prompt_scorecard)}</tbody>
    </table>
    {f'''
    <h3>词组成绩汇总</h3>
    <p class="sub">按企业已配置词组聚合；未配置词组时本表不展示（不强造场景标签）。</p>
    <table>
      <thead><tr><th>词组</th><th>问题数</th><th>样本</th><th>提及率</th><th>均排</th><th>Top3</th></tr></thead>
      <tbody>{_group_score_table(group_scorecard)}</tbody>
    </table>
    ''' if group_scorecard else ''}
  </section>

  <section class="section">
    <h2>05 监测方法与数据口径</h2>
    <div class="note">统计周期为 {_text(period_label)}；核心分母为已形成结果的有效监测样本。不同 AI 平台的联网能力、引用策略、模型版本和地区环境存在差异，同一问题在不同时间返回结果可能存在波动。成绩样本仅收录「本品牌推荐位次靠前且正文中本品牌先于竞品出现」的回答。</div>
    <table><thead><tr><th>序号</th><th>监测问题</th><th>样本量</th><th>覆盖平台</th></tr></thead>
    <tbody>{_prompt_table(prompt_scope, platform_names, list(pack.get('platform_scope') or []))}</tbody></table>
  </section>

  <section class="section">
    <h2>06 平台表现分析</h2>
    <div class="grid3">
      <div class="kpi"><span>监测覆盖</span><b>{_number(assets.get('platform_count') or len(platform_stats))}</b><em>有样本平台数</em></div>
      <div class="kpi"><span>任务回填完整度</span><b>{_pct(fill_rate)}</b><em>有效结果 / 统计样本</em></div>
      <div class="kpi"><span>快照留存率</span><b>{_pct(retention)}</b><em>可回查证据覆盖</em></div>
    </div>
    <p class="sub">平台差异说明：不同 AI 平台的返回机制、实时联网能力和引用策略不同，因此提及率与推荐排名会呈现差异。</p>
    <table>
      <thead><tr><th>平台</th><th>完成/总数</th><th>品牌提及率</th><th>平均排名</th></tr></thead>
      <tbody>{_platform_table(platform_stats, platform_names)}</tbody>
    </table>
    <h3>分平台首末窗升降</h3>
    <p class="sub">期初/期末均为 7 日窗；样本任一侧不足 {_number((period_comparison.get('min_platform_samples') if period_comparison else None) or 30)} 条时标记「样本不足」，不作为结论依据。</p>
    <table>
      <thead><tr>
        <th>平台</th><th>期初样本</th><th>期初提及率</th><th>期初均排</th>
        <th>期末样本</th><th>期末提及率</th><th>期末均排</th><th>变化（提及/均排）</th>
      </tr></thead>
      <tbody>{_platform_comparison_table(list(period_comparison.get('platforms') or []), platform_names)}</tbody>
    </table>
  </section>

  <section class="section">
    <h2>07 本品牌高排名样本</h2>
    <p class="sub">仅展示本品牌被推荐到靠前位置、且回答正文中本品牌先于竞品出现的样本，用于体现正向成绩。</p>
    {_evidence_cards(brand_evidence, platform_names, empty='本周期暂无满足条件的本品牌高排名样本。')}
  </section>

  <section class="section">
    <h2>08 阶段观察与优化空间</h2>
    <p class="sub">以下内容用于说明本阶段服务后的客观观察点，并给出可执行的巩固 / 攻坚 / 监测建议初稿。</p>
    <div class="grid4">
      <div class="kpi"><span>有效样本</span><b>{_number(completed)}</b><em>与全文分母一致</em></div>
      <div class="kpi"><span>内容资产</span><b>{_number(completed)}</b><em>有效回答文本口径</em></div>
      <div class="kpi"><span>信源资产</span><b>{_number(assets.get('source_count') or len(top_sources))}</b><em>有效引用信源</em></div>
      <div class="kpi"><span>快照资产</span><b>{_number(screenshots)}</b><em>可回查证据</em></div>
    </div>
    <div class="grid2">
      <div class="note warn">平台表现存在差异：部分平台提及率低于整体均值，说明不同模型对信源与行业语境的识别偏好并不一致。</div>
      <div class="note warn">推荐语义仍有提升空间：正面情绪占比 {_pct(kpis.get('positive_rate'))}，说明“被提到”与“被主动推荐”之间仍有差距。</div>
    </div>
    <h3>后续建议（巩固 / 攻坚 / 监测）</h3>
    <p class="sub">由问题词风险与平台首末窗变化自动生成，可按客户业务再改。</p>
    {_next_actions_html(next_actions)}
    <h3>平台差异</h3>
    {_bar_rows(platform_stats, platform_names)}
  </section>

  <section class="section">
    <!-- 2026-08-04 - 删结项移交空话页；证据链改为样本索引+信源表+资产计数 -->
    <h2>09 附录与证据链</h2>
    <p class="sub">把「样本 → 排名 → 快照 → 信源」串成可回查链条，便于验收抽查与归档复核。</p>
    <div class="grid4">
      <div class="kpi"><span>有效样本</span><b>{_number(completed)}</b><em>统计分母</em></div>
      <div class="kpi"><span>可回查快照</span><b>{_number(screenshots)}</b><em>留存率 {_pct(retention)}</em></div>
      <div class="kpi"><span>引用记录</span><b>{_number(citations)}</b><em>回答附带引用次数</em></div>
      <div class="kpi"><span>独立信源</span><b>{_number(assets.get('source_count') or len(top_sources))}</b><em>去重后站点/页面</em></div>
    </div>
    <div class="grid2" style="margin-top:16px">
      <div class="note"><b>成绩证据：</b>{_number(assets.get('brand_evidence_count') or len(brand_evidence))} 条本品牌高排名样本（见 §07），均可对照快照复核。</div>
      <div class="note"><b>信源证据：</b>{_number(assets.get('source_count') or len(top_sources))} 个去噪后的高频引用信源，优先品牌相关页面。</div>
    </div>
    <h3>样本证据索引</h3>
    <p class="sub">索引对应正文展示样本；点击快照可回看当时模型回答页面。</p>
    <table>
      <thead><tr><th>类型</th><th>平台</th><th>监测问题</th><th>本品牌排名</th><th>信源数</th><th>快照</th></tr></thead>
      <tbody>{_evidence_index_table(evidence_index, platform_names)}</tbody>
    </table>
    <h3>高频引用信源</h3>
    <p class="sub">按服务周期内引用次数排序；可用于判断哪些站点更容易被 AI 采纳。</p>
    <table>
      <thead><tr><th>序号</th><th>信源</th><th>引用次数</th><th>出现平台</th></tr></thead>
      <tbody>{_source_table(top_sources, platform_names)}</tbody>
    </table>
    <h3>对照竞品口径</h3>
    <div class="note">本报告竞品对照范围：{''.join(f'<span class="tag">{_text(n)}</span>' for n in competitor_names[:12]) or '暂无竞品配置'}</div>
  </section>

  <p class="footer">GEO Monitor 自动生成 · 数据来自本系统数据库与外部平台返回结果 · 禁止脱离统计口径夸大展示</p>
</main>
</body>
</html>"""
