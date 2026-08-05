"""结项报告富数据：成绩样本、挑战样本、范围盘点。

2026-08-04 - 完整版结项证据选错竞品龙头 - 成绩样本要求本品牌位次+正文先于竞品露出
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.services.brand_service import (
    active_keyword_groups,
    brand_exposure_terms,
    get_brand_asset,
    keyword_group_display_label,
    keyword_group_monitor_keywords,
    list_competitors,
)
from app.services.media_proxy_service import public_screenshot_url
from app.services.monitor_service import (
    _is_valid_citation_source,
    _matched_source_keywords,
    kpi_rank_for_subtask,
)
from app.services.monitor_stats_service import load_subtasks_for_business_date_range
from app.services.report_text_sanitize import consolidate_top_sources


def expand_match_names(names: list[str]) -> list[str]:
    """竞品/品牌匹配扩展：保留全称，并去掉常见后缀以便命中「分众」这类简称。"""
    out: list[str] = []
    seen: set[str] = set()
    suffixes = ("有限公司", "控股集团", "集团", "控股", "传媒", "媒体", "中国")
    for name in names:
        text = str(name or "").strip()
        if not text:
            continue
        variants = [text]
        shortened = text
        for suffix in suffixes:
            if shortened.endswith(suffix) and len(shortened) > len(suffix) + 1:
                shortened = shortened[: -len(suffix)]
                variants.append(shortened)
        for item in variants:
            if item not in seen and len(item) >= 2:
                seen.add(item)
                out.append(item)
    # 长词优先，避免短词抢先误匹配
    out.sort(key=len, reverse=True)
    return out


def _first_index(text: str, needles: list[str]) -> int | None:
    hits = [text.find(n) for n in needles if n and n in text]
    hits = [i for i in hits if i >= 0]
    return min(hits) if hits else None


def brand_leads_answer(
    answer: str,
    *,
    brand_terms: list[str],
    competitor_names: list[str],
) -> bool:
    """本品牌在回答中的首次出现早于任一配置竞品（成绩证据硬条件）。"""
    text = str(answer or "")
    if not text.strip():
        return False
    brands = expand_match_names(brand_terms)
    comps = expand_match_names(competitor_names)
    brand_at = _first_index(text, brands)
    if brand_at is None:
        return False
    comp_at = _first_index(text, comps)
    if comp_at is not None and comp_at < brand_at:
        return False
    return True


def competitor_leads_answer(
    answer: str,
    *,
    brand_terms: list[str],
    competitor_names: list[str],
) -> bool:
    """竞品先于本品牌出现，或仅有竞品露出——归入挑战区。"""
    text = str(answer or "")
    if not text.strip() or not competitor_names:
        return False
    brands = expand_match_names(brand_terms)
    comps = expand_match_names(competitor_names)
    brand_at = _first_index(text, brands)
    comp_at = _first_index(text, comps)
    if comp_at is None:
        return False
    if brand_at is None:
        return True
    return comp_at < brand_at


def _clip(text: str | None, limit: int = 220) -> str:
    raw = " ".join(str(text or "").split())
    if len(raw) <= limit:
        return raw
    return raw[: limit - 1] + "…"


def _shot_url(raw: str | None) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    # 结项 HTML 常离线打开：优先保留可外链的原始快照地址
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return public_screenshot_url(text)


def _ref_count(subtask: Any) -> int:
    refs = getattr(subtask, "reference_list_json", None) or getattr(subtask, "citation_list_json", None) or []
    return len(refs) if isinstance(refs, list) else 0


def _sample_dict(
    *,
    platform: str,
    prompt: str,
    rank: float | int | None,
    sentiment: str | None,
    answer: str,
    screenshot: str | None,
    refs: int,
    kind: str,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "platform": platform,
        "prompt": prompt,
        "rank": rank,
        "sentiment": sentiment or "",
        "answer_excerpt": _clip(answer, 260),
        "screenshot_url": screenshot,
        "reference_count": refs,
    }


def select_completion_evidence(
    rows: list[dict[str, Any]],
    *,
    brand_terms: list[str],
    competitor_names: list[str],
    brand_limit: int = 6,
    challenge_limit: int = 4,
) -> dict[str, list[dict[str, Any]]]:
    """从候选行挑选成绩样本 / 挑战样本（纯函数，便于单测）。

    候选行字段：platform, prompt, brand_rank, answer, screenshot_url, sentiment, reference_count
    """
    brand_rows: list[dict[str, Any]] = []
    challenge_rows: list[dict[str, Any]] = []
    for row in rows:
        answer = str(row.get("answer") or "")
        rank = row.get("brand_rank")
        try:
            rank_num = float(rank) if rank is not None else None
        except (TypeError, ValueError):
            rank_num = None
        base = {
            "platform": str(row.get("platform") or ""),
            "prompt": str(row.get("prompt") or ""),
            "brand_rank": rank_num,
            "sentiment": str(row.get("sentiment") or ""),
            "answer": answer,
            "screenshot_url": row.get("screenshot_url"),
            "reference_count": int(row.get("reference_count") or 0),
        }
        if (
            rank_num is not None
            and rank_num <= 5
            and brand_leads_answer(answer, brand_terms=brand_terms, competitor_names=competitor_names)
        ):
            brand_rows.append(base)
        elif competitor_leads_answer(answer, brand_terms=brand_terms, competitor_names=competitor_names):
            challenge_rows.append(base)

    def _brand_key(item: dict[str, Any]) -> tuple:
        return (
            float(item["brand_rank"] or 99),
            0 if item.get("screenshot_url") else 1,
            -int(item.get("reference_count") or 0),
        )

    def _challenge_key(item: dict[str, Any]) -> tuple:
        return (
            0 if item.get("screenshot_url") else 1,
            float(item["brand_rank"] if item.get("brand_rank") is not None else 99),
            -int(item.get("reference_count") or 0),
        )

    brand_rows.sort(key=_brand_key)
    challenge_rows.sort(key=_challenge_key)

    def _diversify(items: list[dict[str, Any]], limit: int, kind: str) -> list[dict[str, Any]]:
        picked: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in items:
            key = (item["platform"], item["prompt"])
            if key in seen and len(picked) + 1 < limit:
                continue
            seen.add(key)
            picked.append(
                _sample_dict(
                    platform=item["platform"],
                    prompt=item["prompt"],
                    rank=item.get("brand_rank"),
                    sentiment=item.get("sentiment"),
                    answer=item["answer"],
                    screenshot=item.get("screenshot_url"),
                    refs=int(item.get("reference_count") or 0),
                    kind=kind,
                )
            )
            if len(picked) >= limit:
                break
        return picked

    return {
        "brand_evidence": _diversify(brand_rows, brand_limit, "brand_win"),
        "challenge_evidence": _diversify(challenge_rows, challenge_limit, "competitor_lead"),
    }


def _build_trend_points(db: Session, tenant_id: int, start: date, end: date) -> list[dict[str, Any]]:
    from app.services.monitor_stats_service import list_daily_stats_for_tenant

    rows = list_daily_stats_for_tenant(db, tenant_id, since=start, until=end)
    by_day: dict[date, dict[str, int]] = {}
    for row in rows:
        day = row.stat_date
        bucket = by_day.setdefault(day, {"completed": 0, "mentioned": 0})
        bucket["completed"] += int(row.completed_count or 0)
        bucket["mentioned"] += int(row.mentioned_count or 0)
    points: list[dict[str, Any]] = []
    for day in sorted(by_day):
        completed = by_day[day]["completed"]
        mentioned = by_day[day]["mentioned"]
        rate = round(mentioned / completed * 100, 1) if completed else 0.0
        points.append({"date": day.isoformat(), "label": day.strftime("%m-%d"), "mention_rate": rate, "completed": completed})
    # 长周期压成最多 12 个节点，避免 SVG 过密
    if len(points) <= 12:
        return points
    step = max(1, len(points) // 11)
    sampled = points[::step][:11]
    if points[-1] not in sampled:
        sampled.append(points[-1])
    return sampled


def _metrics_from_bucket(bucket: dict[str, int]) -> dict[str, Any]:
    completed = int(bucket.get("completed") or 0)
    mentioned = int(bucket.get("mentioned") or 0)
    top3 = int(bucket.get("top3") or 0)
    rank_sum = int(bucket.get("rank_sum") or 0)
    rank_count = int(bucket.get("rank_count") or 0)
    return {
        "completed": completed,
        "mention_rate": round(mentioned / completed * 100, 1) if completed else None,
        "top3_rate": round(top3 / completed * 100, 1) if completed else None,
        "avg_rank": round(rank_sum / rank_count, 1) if rank_count else None,
    }


def _delta(a: Any, b: Any) -> float | None:
    if a is None or b is None:
        return None
    try:
        return round(float(b) - float(a), 1)
    except (TypeError, ValueError):
        return None


def build_prompt_scorecard(candidates: list[dict[str, Any]], *, limit: int = 40) -> list[dict[str, Any]]:
    """按监测问题汇总成绩（借鉴结案 PPT 词级表，口径=系统提及/均排/Top3）。"""
    buckets: dict[str, dict[str, int]] = {}
    for item in candidates:
        prompt = str(item.get("prompt") or "").strip() or "未命名问题"
        bucket = buckets.setdefault(
            prompt,
            {"completed": 0, "mentioned": 0, "top3": 0, "rank_sum": 0, "rank_count": 0},
        )
        bucket["completed"] += 1
        rank = item.get("brand_rank")
        if rank is None:
            continue
        try:
            rank_i = int(rank)
        except (TypeError, ValueError):
            continue
        bucket["mentioned"] += 1
        bucket["rank_sum"] += rank_i
        bucket["rank_count"] += 1
        if rank_i <= 3:
            bucket["top3"] += 1

    rows: list[dict[str, Any]] = []
    for prompt, bucket in buckets.items():
        metrics = _metrics_from_bucket(bucket)
        rows.append(
            {
                "prompt": prompt,
                "completed": metrics["completed"],
                "mention_rate": metrics["mention_rate"],
                "top3_rate": metrics["top3_rate"],
                "avg_rank": metrics["avg_rank"],
            }
        )
    rows.sort(
        key=lambda row: (
            -(float(row["mention_rate"]) if row.get("mention_rate") is not None else -1.0),
            float(row["avg_rank"]) if row.get("avg_rank") is not None else 999.0,
            -int(row.get("completed") or 0),
        )
    )
    return rows[: max(1, int(limit))]


def classify_prompt_risks(scorecard: list[dict[str, Any]], *, min_samples: int = 5) -> list[dict[str, Any]]:
    """词级风险分级：P0/P1 需关注，样本不足单独标记（借鉴旺旺风险表思路，规则写死可解释）。"""
    # 2026-08-05 - 结案借鉴 PPT 风险词 - 用监测口径规则打标，非客户第三方达成率
    out: list[dict[str, Any]] = []
    for row in scorecard:
        completed = int(row.get("completed") or 0)
        mention = row.get("mention_rate")
        avg_rank = row.get("avg_rank")
        top3 = row.get("top3_rate")
        if completed < min_samples:
            level = "样本不足"
            reason = f"有效样本仅 {completed} 条，不足以判定风险等级"
        else:
            mention_f = float(mention) if mention is not None else 0.0
            rank_f = float(avg_rank) if avg_rank is not None else 99.0
            top3_f = float(top3) if top3 is not None else 0.0
            if mention_f < 40.0 or rank_f > 3.5:
                level = "P0"
                reason = "提及率偏低或均排明显靠后，需优先攻坚"
            elif mention_f < 60.0 or rank_f > 2.5 or top3_f < 50.0:
                level = "P1"
                reason = "成绩未稳，存在回落或占位不足风险"
            else:
                level = "P2"
                reason = "整体可控，保持巡检即可"
        out.append({**row, "risk_level": level, "risk_reason": reason})
    order = {"P0": 0, "P1": 1, "样本不足": 2, "P2": 3}
    out.sort(key=lambda row: (order.get(str(row.get("risk_level")), 9), -int(row.get("completed") or 0)))
    return out


def build_lifecycle_milestones(
    trend: list[dict[str, Any]],
    period_comparison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """期初监测日 / 峰值日 / 期末监测日 + 首末窗摘要（借鉴美团初/峰/末内容）。"""
    points = [p for p in trend if isinstance(p, dict) and p.get("date")]
    if not points:
        return {"available": False, "note": "暂无日趋势，无法给出期初/峰值/期末。"}
    initial = points[0]
    final = points[-1]
    peak = max(points, key=lambda p: float(p.get("mention_rate") or 0))
    comparison = period_comparison or {}
    overall = (comparison.get("overall") or {}) if comparison.get("available") else {}
    return {
        "available": True,
        "initial": {
            "date": initial.get("date"),
            "label": initial.get("label") or "期初",
            "mention_rate": initial.get("mention_rate"),
            "completed": initial.get("completed"),
        },
        "peak": {
            "date": peak.get("date"),
            "label": peak.get("label") or "峰值",
            "mention_rate": peak.get("mention_rate"),
            "completed": peak.get("completed"),
        },
        "final": {
            "date": final.get("date"),
            "label": final.get("label") or "期末",
            "mention_rate": final.get("mention_rate"),
            "completed": final.get("completed"),
        },
        "early_window": overall.get("early"),
        "late_window": overall.get("late"),
        "early_label": comparison.get("early_label"),
        "late_label": comparison.get("late_label"),
        "note": "峰值取服务期内日提及率最高的一天。单日可与上方 7 日窗均值不同，属正常波动，不是口径冲突。",
    }


def build_keyword_group_scorecard(
    scorecard: list[dict[str, Any]],
    groups: list[Any],
) -> list[dict[str, Any]]:
    """有词组配置时，按词组聚合问题成绩（对齐美团「场景」叙事，不强造找店等标签）。"""
    if not groups or not scorecard:
        return []
    rows: list[dict[str, Any]] = []
    assigned: set[str] = set()
    for group in groups:
        label = keyword_group_display_label(group)
        keywords = [k.lower() for k in keyword_group_monitor_keywords(group) if k]
        if not keywords:
            continue
        matched = []
        for item in scorecard:
            prompt = str(item.get("prompt") or "")
            prompt_l = prompt.lower()
            if any(k in prompt_l or prompt_l == k for k in keywords):
                matched.append(item)
                assigned.add(prompt)
        if not matched:
            continue
        completed = sum(int(i.get("completed") or 0) for i in matched)
        # 加权回算提及/Top3/均排
        mentioned = 0
        top3 = 0
        rank_sum = 0.0
        rank_weight = 0
        for i in matched:
            c = int(i.get("completed") or 0)
            mr = i.get("mention_rate")
            tr = i.get("top3_rate")
            ar = i.get("avg_rank")
            if mr is not None:
                mentioned += int(round(c * float(mr) / 100.0))
            if tr is not None:
                top3 += int(round(c * float(tr) / 100.0))
            if ar is not None and mr is not None and float(mr) > 0:
                m_count = int(round(c * float(mr) / 100.0))
                rank_sum += float(ar) * m_count
                rank_weight += m_count
        rows.append(
            {
                "group": label,
                "prompt_count": len(matched),
                "completed": completed,
                "mention_rate": round(mentioned / completed * 100, 1) if completed else None,
                "top3_rate": round(top3 / completed * 100, 1) if completed else None,
                "avg_rank": round(rank_sum / rank_weight, 1) if rank_weight else None,
            }
        )
    rows.sort(key=lambda r: -(float(r["mention_rate"]) if r.get("mention_rate") is not None else -1.0))
    return rows


def build_next_actions(
    risk_rows: list[dict[str, Any]],
    *,
    platform_highlights: list[str] | None = None,
) -> dict[str, list[str]]:
    """后续建议骨架：巩固 / 攻坚 / 监测（规则初稿，可人工改）。"""
    consolidate: list[str] = []
    attack: list[str] = []
    monitor: list[str] = []
    for row in risk_rows:
        prompt = str(row.get("prompt") or "").strip()
        if not prompt:
            continue
        level = str(row.get("risk_level") or "")
        clip = prompt if len(prompt) <= 36 else prompt[:35] + "…"
        if level == "P2" and len(consolidate) < 5:
            consolidate.append(
                f"「{clip}」表现稳定（提及率 {row.get('mention_rate')}%，均排 {row.get('avg_rank')}），建议常规巡检防回落。"
            )
        elif level in {"P0", "P1"} and len(attack) < 6:
            attack.append(f"「{clip}」标为 {level}：{row.get('risk_reason')}。")
        elif level == "样本不足" and len(monitor) < 4:
            monitor.append(f"「{clip}」样本不足，建议优先补测后再判定。")
    if not consolidate:
        consolidate.append("暂无明确的高稳定问题词；建议先稳住全域提及率与 Top3 占位。")
    if not attack:
        attack.append("当前无 P0/P1 高风险问题词；可将精力放在内容与信源质量深化。")
    monitor.append("对 P0/P1 词保持短周期复测，出现连续掉出 Top3 时触发专项复盘。")
    for tip in platform_highlights or []:
        if tip and len(monitor) < 6:
            monitor.append(str(tip))
    return {"consolidate": consolidate, "attack": attack, "monitor": monitor}


def build_early_late_comparison(
    daily_rows: list[Any],
    *,
    window_days: int = 7,
    min_platform_samples: int = 30,
) -> dict[str, Any]:
    """首末窗口对比（纯函数）。

    期初 = 有日统计数据的前 N 天；期末 = 末 N 天。
    分平台样本不足时 reliable=False，前端灰显「样本不足」。
    """
    days_n = max(1, int(window_days))
    overall: dict[date, dict[str, int]] = {}
    by_plat: dict[str, dict[date, dict[str, int]]] = {}
    for row in daily_rows:
        day = getattr(row, "stat_date", None) or (row.get("stat_date") if isinstance(row, dict) else None)
        if day is None:
            continue
        if isinstance(day, str):
            day = date.fromisoformat(day[:10])
        platform = str(getattr(row, "platform", None) or (row.get("platform") if isinstance(row, dict) else "") or "unknown")
        completed = int(getattr(row, "completed_count", None) or (row.get("completed_count") if isinstance(row, dict) else 0) or 0)
        mentioned = int(getattr(row, "mentioned_count", None) or (row.get("mentioned_count") if isinstance(row, dict) else 0) or 0)
        top3 = int(getattr(row, "top3_count", None) or (row.get("top3_count") if isinstance(row, dict) else 0) or 0)
        rank_sum = int(getattr(row, "rank_sum", None) or (row.get("rank_sum") if isinstance(row, dict) else 0) or 0)
        rank_count = int(getattr(row, "rank_count", None) or (row.get("rank_count") if isinstance(row, dict) else 0) or 0)

        ob = overall.setdefault(day, {"completed": 0, "mentioned": 0, "top3": 0, "rank_sum": 0, "rank_count": 0})
        ob["completed"] += completed
        ob["mentioned"] += mentioned
        ob["top3"] += top3
        ob["rank_sum"] += rank_sum
        ob["rank_count"] += rank_count

        pb = by_plat.setdefault(platform, {})
        day_b = pb.setdefault(day, {"completed": 0, "mentioned": 0, "top3": 0, "rank_sum": 0, "rank_count": 0})
        day_b["completed"] += completed
        day_b["mentioned"] += mentioned
        day_b["top3"] += top3
        day_b["rank_sum"] += rank_sum
        day_b["rank_count"] += rank_count

    days = sorted(d for d, b in overall.items() if int(b.get("completed") or 0) > 0)
    if len(days) < 2:
        return {
            "available": False,
            "window_days": days_n,
            "early": None,
            "late": None,
            "overall": None,
            "platforms": [],
            "highlights": [],
            "note": "有效监测日不足，无法做首末窗口对比。",
        }

    early_days = days[: min(days_n, len(days))]
    late_days = days[-min(days_n, len(days)) :]
    # 总天数不足 2N 时首末窗会重叠，仍可算但需注明
    overlap = bool(set(early_days) & set(late_days))

    def _sum_days(day_map: dict[date, dict[str, int]], picked: list[date]) -> dict[str, int]:
        out = {"completed": 0, "mentioned": 0, "top3": 0, "rank_sum": 0, "rank_count": 0}
        for d in picked:
            b = day_map.get(d) or {}
            for k in out:
                out[k] += int(b.get(k) or 0)
        return out

    early_m = _metrics_from_bucket(_sum_days(overall, early_days))
    late_m = _metrics_from_bucket(_sum_days(overall, late_days))
    overall_cmp = {
        "early": early_m,
        "late": late_m,
        "delta_mention_rate": _delta(early_m.get("mention_rate"), late_m.get("mention_rate")),
        "delta_top3_rate": _delta(early_m.get("top3_rate"), late_m.get("top3_rate")),
        "delta_avg_rank": _delta(early_m.get("avg_rank"), late_m.get("avg_rank")),
    }

    platforms: list[dict[str, Any]] = []
    for platform, day_map in by_plat.items():
        e = _metrics_from_bucket(_sum_days(day_map, early_days))
        l = _metrics_from_bucket(_sum_days(day_map, late_days))
        reliable = int(e["completed"] or 0) >= min_platform_samples and int(l["completed"] or 0) >= min_platform_samples
        platforms.append(
            {
                "platform": platform,
                "early": e,
                "late": l,
                "delta_mention_rate": _delta(e.get("mention_rate"), l.get("mention_rate")),
                "delta_top3_rate": _delta(e.get("top3_rate"), l.get("top3_rate")),
                "delta_avg_rank": _delta(e.get("avg_rank"), l.get("avg_rank")),
                "reliable": reliable,
            }
        )
    platforms.sort(
        key=lambda row: (
            0 if row.get("reliable") else 1,
            -(row.get("delta_mention_rate") if row.get("delta_mention_rate") is not None else -999),
        )
    )

    highlights: list[str] = []
    reliable_rows = [r for r in platforms if r.get("reliable") and r.get("delta_mention_rate") is not None]
    if reliable_rows:
        best = max(reliable_rows, key=lambda r: float(r["delta_mention_rate"]))
        worst = min(reliable_rows, key=lambda r: float(r["delta_mention_rate"]))
        if float(best["delta_mention_rate"]) > 0:
            highlights.append(
                f"提及率提升最大平台：{best['platform']}（{best['early'].get('mention_rate')}% → {best['late'].get('mention_rate')}%，Δ {best['delta_mention_rate']}pt）"
            )
        if float(worst["delta_mention_rate"]) < 0:
            highlights.append(
                f"提及率回落最明显平台：{worst['platform']}（{worst['early'].get('mention_rate')}% → {worst['late'].get('mention_rate')}%，Δ {worst['delta_mention_rate']}pt）"
            )
    if overall_cmp.get("delta_mention_rate") is not None:
        d = overall_cmp["delta_mention_rate"]
        verb = "提升" if d > 0 else ("回落" if d < 0 else "持平")
        highlights.insert(
            0,
            f"全域提及率首末窗{verb} {abs(d)}pt（{early_m.get('mention_rate')}% → {late_m.get('mention_rate')}%）",
        )

    note = (
        f"对比口径：有监测数据的前 {len(early_days)} 日 vs 末 {len(late_days)} 日"
        f"（{early_days[0].isoformat()}~{early_days[-1].isoformat()} → {late_days[0].isoformat()}~{late_days[-1].isoformat()}）。"
        "单日波动大，故不用「首日/结项前一日」硬比。"
    )
    if overlap:
        note += " 有效监测日较短，首末窗口存在重叠，环比仅供参考。"

    return {
        "available": True,
        "window_days": days_n,
        "min_platform_samples": min_platform_samples,
        "early_label": f"{early_days[0].strftime('%m-%d')}~{early_days[-1].strftime('%m-%d')}",
        "late_label": f"{late_days[0].strftime('%m-%d')}~{late_days[-1].strftime('%m-%d')}",
        "early_dates": [d.isoformat() for d in early_days],
        "late_dates": [d.isoformat() for d in late_days],
        "overlap": overlap,
        "overall": overall_cmp,
        "platforms": platforms,
        "highlights": highlights,
        "note": note,
    }


def _build_period_comparison(db: Session, tenant_id: int, start: date, end: date) -> dict[str, Any]:
    from app.services.monitor_stats_service import list_daily_stats_for_tenant

    rows = list_daily_stats_for_tenant(db, tenant_id, since=start, until=end)
    return build_early_late_comparison(rows, window_days=7, min_platform_samples=30)


def build_completion_pack(
    db: Session,
    tenant_id: int,
    *,
    period_start: date,
    period_end: date,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """组装结项完整版所需附加块（样本、范围、趋势、资产计数）。"""
    asset = get_brand_asset(db, tenant_id)
    competitors = list_competitors(db, tenant_id)
    competitor_names = [c.name for c in competitors if c.name]
    brand_terms = brand_exposure_terms(asset, active_keyword_groups(db, tenant_id)) if asset else []
    if asset and asset.brand_name and asset.brand_name not in brand_terms:
        brand_terms = [asset.brand_name, *brand_terms]

    subtasks, task_rows, _ = load_subtasks_for_business_date_range(
        db,
        tenant_id,
        start_date=period_start,
        end_date=period_end,
        asset=asset,
    )
    task_by_id = {t.task_id: t for t in task_rows if t.task_id}
    completed = [s for s in subtasks if str(s.status or "") in {"completed", "partial_completed"}]

    candidates: list[dict[str, Any]] = []
    prompt_counter: Counter[str] = Counter()
    platform_counter: Counter[str] = Counter()
    screenshot_count = 0
    citation_count = 0
    for item in completed:
        prompt_counter[str(item.prompt or "").strip() or "未命名问题"] += 1
        platform_counter[str(item.platform or "unknown")] += 1
        if item.page_screenshot:
            screenshot_count += 1
        citation_count += _ref_count(item)
        task = task_by_id.get(item.task_id or "")
        rank = kpi_rank_for_subtask(
            item,
            task.monitor_keywords if task is not None else None,
            brand_terms,
            asset,
        )
        candidates.append(
            {
                "platform": item.platform,
                "prompt": item.prompt,
                "brand_rank": rank,
                "answer": item.answer_content or "",
                "screenshot_url": _shot_url(item.page_screenshot),
                "sentiment": item.sentiment,
                "reference_count": _ref_count(item),
            }
        )

    evidence = select_completion_evidence(
        candidates,
        brand_terms=brand_terms,
        competitor_names=competitor_names,
    )

    snap = snapshot or {}
    kpis = dict(snap.get("kpis") or {})
    completed_count = int(kpis.get("completed_count") or len(completed) or 0)
    platform_stats = list(snap.get("platform_stats") or [])
    top_sources = list(snap.get("top_sources") or [])

    prompt_scope = [
        {"prompt": prompt, "count": count}
        for prompt, count in prompt_counter.most_common(15)
    ]
    platform_scope = [
        {"platform": platform, "count": count}
        for platform, count in platform_counter.most_common(20)
    ]

    retention = round(screenshot_count / completed_count * 100, 1) if completed_count else 0.0
    # 回填完整度：有回答文本的成功样本占比（运维口径，不作成绩 KPI）
    with_answer = sum(1 for s in completed if str(s.answer_content or "").strip())
    fill_rate = round(with_answer / completed_count * 100, 1) if completed_count else 0.0

    # 2026-08-04 - 证据链信源噪音 - 对齐 snapshot：校验+品牌露出词，再 consolidate 清洗标题
    branded_map: dict[str, dict[str, Any]] = {}
    all_map: dict[str, dict[str, Any]] = {}
    for item in completed:
        for source in item.reference_list_json or []:
            if not isinstance(source, dict):
                continue
            if not _is_valid_citation_source(source):
                continue
            url = source.get("url") or source.get("site") or source.get("title")
            if not url:
                continue
            key = str(url).split("?")[0]
            payload = {
                "title": source.get("title") or source.get("site") or key,
                "url": url,
                "count": 1,
                "platforms": [str(item.platform or "")],
            }
            all_row = all_map.setdefault(
                key,
                {"title": payload["title"], "url": url, "count": 0, "platforms": set()},
            )
            all_row["count"] += 1
            all_row["platforms"].add(str(item.platform or ""))
            if brand_terms and _matched_source_keywords(source, brand_terms):
                brand_row = branded_map.setdefault(
                    key,
                    {"title": payload["title"], "url": url, "count": 0, "platforms": set()},
                )
                brand_row["count"] += 1
                brand_row["platforms"].add(str(item.platform or ""))

    def _finalize(source_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for row in source_map.values():
            rows.append(
                {
                    "title": row["title"],
                    "url": row["url"],
                    "count": row["count"],
                    "platforms": sorted(p for p in row["platforms"] if p),
                }
            )
        return consolidate_top_sources(rows, limit=12)

    branded_sources = _finalize(branded_map)
    cleaned_all = _finalize(all_map)
    # 优先品牌相关信源；不足时用去噪后的全量补齐，避免证据链空窗
    rich_sources = list(branded_sources)
    if len(rich_sources) < 8:
        seen = {str(r.get("url") or r.get("title") or "") for r in rich_sources}
        for row in cleaned_all:
            key = str(row.get("url") or row.get("title") or "")
            if key in seen:
                continue
            rich_sources.append(row)
            seen.add(key)
            if len(rich_sources) >= 12:
                break
    source_count = len(branded_map) if branded_map else len(all_map)

    evidence_index = []
    for sample in evidence["brand_evidence"]:
        evidence_index.append(
            {
                "role": "成绩样本",
                "platform": sample.get("platform"),
                "prompt": sample.get("prompt"),
                "rank": sample.get("rank"),
                "reference_count": sample.get("reference_count"),
                "screenshot_url": sample.get("screenshot_url"),
                "sentiment": sample.get("sentiment"),
            }
        )
    # 2026-08-04 - 去掉挑战区展示 - evidence_index 不再收录竞品领先样本

    mention_trend = _build_trend_points(db, tenant_id, period_start, period_end)
    period_comparison = _build_period_comparison(db, tenant_id, period_start, period_end)
    # 2026-08-05 - 结案内容增强：词级成绩/风险/初峰末/词组/后续建议（叠在原 pack 上）
    prompt_scorecard = build_prompt_scorecard(candidates)
    prompt_risks = classify_prompt_risks(prompt_scorecard)
    groups = active_keyword_groups(db, tenant_id)
    group_scorecard = build_keyword_group_scorecard(prompt_scorecard, groups)
    lifecycle = build_lifecycle_milestones(mention_trend, period_comparison)
    next_actions = build_next_actions(
        prompt_risks,
        platform_highlights=list(period_comparison.get("highlights") or [])[:2],
    )

    return {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "brand_evidence": evidence["brand_evidence"],
        "challenge_evidence": evidence["challenge_evidence"],
        "evidence_index": evidence_index,
        "prompt_scope": prompt_scope,
        "platform_scope": platform_scope,
        "mention_trend": mention_trend,
        "assets": {
            "completed_count": completed_count,
            "screenshot_count": screenshot_count,
            "citation_count": citation_count,
            "source_count": source_count or int(kpis.get("source_count") or len(top_sources) or 0),
            # 2026-08-04 - §01 覆盖平台为 0 - 用周期内实际有样本的平台数，勿只信 snapshot.platform_count
            "platform_count": len(platform_counter) or int(snap.get("platform_count") or len(platform_stats) or 0),
            "prompt_count": len(prompt_counter),
            "snapshot_retention_rate": retention,
            "result_fill_rate": fill_rate,
            "mentioned_count": int(round(completed_count * float(kpis.get("mention_rate") or 0) / 100))
            if completed_count
            else 0,
            "top3_count": int(round(completed_count * float(kpis.get("top3_rate") or 0) / 100))
            if completed_count
            else 0,
            "brand_evidence_count": len(evidence["brand_evidence"]),
            "challenge_evidence_count": len(evidence["challenge_evidence"]),
            "risk_prompt_count": sum(1 for r in prompt_risks if r.get("risk_level") in {"P0", "P1"}),
        },
        "competitors": competitor_names,
        "platform_stats": platform_stats,
        "top_sources": rich_sources or top_sources,
        # 2026-08-04 - 结项方案 C：首末 7 日窗 + 分平台升降
        "period_comparison": period_comparison,
        "prompt_scorecard": prompt_scorecard,
        "prompt_risks": prompt_risks,
        "keyword_group_scorecard": group_scorecard,
        "lifecycle_milestones": lifecycle,
        "next_actions": next_actions,
    }


def attach_completion_pack(
    db: Session,
    tenant_id: int,
    content: dict[str, Any],
    *,
    period_start: date,
    period_end: date,
) -> dict[str, Any]:
    """写入 report_content_json.completion_pack。"""
    snapshot = {
        "kpis": content.get("kpis") or {},
        "platform_stats": (content.get("monitor_snapshot") or {}).get("platform_stats") or [],
        "top_sources": (content.get("monitor_snapshot") or {}).get("top_sources") or [],
        "platform_count": (content.get("monitor_snapshot") or {}).get("platform_count"),
        "competitor_count": (content.get("monitor_snapshot") or {}).get("competitor_count"),
    }
    pack = build_completion_pack(
        db,
        tenant_id,
        period_start=period_start,
        period_end=period_end,
        snapshot=snapshot,
    )
    updated = dict(content)
    updated["completion_pack"] = pack
    updated["competitors"] = pack.get("competitors") or []
    return updated
