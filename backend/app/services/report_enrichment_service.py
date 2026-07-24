"""售前诊断报告内容 enrich：规则叙事、竞品汇总、摘录与实体归并。"""

from __future__ import annotations

import re
from typing import Any

from app.models.monitor import GeoMonitorSubtask
from app.services.monitor_service import TERMINAL_STATUSES

_EXCERPT_MAX = 220
_DOMAIN_TIPS: dict[str, str] = {
    "zhihu.com": "在知乎发布对比评测与选购指南类回答，覆盖监测语义词。",
    "baijiahao.baidu.com": "通过百家号发布行业榜单与场景化推荐文章。",
    "docin.com": "豆丁网：上传可引用的行业白皮书/研究报告 PDF。",
    "douban.com": "补充垂直社区中的品牌案例与口碑讨论。",
    "baike.baidu.com": "完善百度百科品牌词条：荣誉、案例、覆盖城市与可核验事实分段写入。",
    "weibo.com": "微博侧用话题+长文沉淀案例，标题含场景词与品牌全称，便于智搜引用。",
    "cnblogs.com": "在博客园发布可复现的行业方法文或项目复盘，强化专业信源权重。",
    "sohu.com": "门户新闻稿写清项目规模、场景与结果指标，避免空泛品牌软文。",
    "163.com": "网易等资讯站优先投「榜单/盘点」体裁，首段给出可被摘录的结论句。",
    "quark.cn": "夸克侧补结构化品牌介绍与 FAQ，标题对齐监测问法。",
}

_SITE_PLAYBOOKS: list[tuple[str, str]] = [
    ("baike", "百科类：把资质、案例、覆盖范围写成可核验条目，减少口号式介绍。"),
    ("zhihu|zhidao|wenwen", "问答类：按「痛点→对比维度→适用场景→品牌证据」写答，避免硬广口吻。"),
    ("weibo|xiaohongshu|bilibili|douyin", "社交/视频类：用案例故事带出可引用结论，标题与标签对齐场景词。"),
    ("docin|doc88|cnki|pdf", "文档库：上传白皮书/方案 PDF，首页摘要含品牌名与场景词。"),
    ("baijiahao|toutiao|sohu|163|sina", "资讯门户：优先榜单/盘点/案例体裁，首段给可摘录结论。"),
    ("blog|cnblogs|csdn|jianshu", "专业博客：写方法复盘与选型对比，提升被模型当作「专业信源」的概率。"),
]


def _playbook_for_domain(domain: str) -> str | None:
    text = domain.lower()
    for pattern, tip in _SITE_PLAYBOOKS:
        if re.search(pattern, text):
            return tip
    return None


def build_rule_source_tips(
    source_analysis: dict[str, Any],
    top_sources: list[dict[str, Any]],
) -> list[str]:
    tips: list[str] = []
    seen_domains: set[str] = set()
    for index, row in enumerate(source_analysis.get("domain_stats") or []):
        if len(tips) >= 10:
            break
        domain = str(row.get("domain") or "").lower().removeprefix("www.")
        if not domain or domain in seen_domains:
            continue
        seen_domains.add(domain)
        count = int(row.get("count") or 0)
        brand_n = int(row.get("brand_related_count") or 0)
        playbook = _playbook_for_domain(domain)

        for key, tip in _DOMAIN_TIPS.items():
            if key in domain:
                tips.append(
                    f"{tip.rstrip('。')}（本报告该站约 {count} 次引用"
                    + (f"，品牌相关 {brand_n} 次" if brand_n else "")
                    + "）；优先补可被模型直接摘录的事实句与对比结论。"
                )
                break
        else:
            if brand_n == 0 and count >= 3:
                tips.append(
                    f"{domain} 引用约 {count} 次但品牌相关为 0：模型采信该站时几乎带不到品牌；"
                    f"建议产出带完整品牌名的资料页/白皮书/案例长文，标题与首段露出场景词。"
                    + (f"内容形态参考：{playbook}" if playbook else "")
                )
            elif brand_n > 0 and count >= 5:
                ratio = brand_n / max(count, 1)
                if ratio < 0.25:
                    tips.append(
                        f"{domain} 引用体量大（约 {count} 次）但品牌相关仅 {brand_n} 次，占比偏低；"
                        f"把通稿改成「场景词 + 品牌证据」结构，提高被摘录时带品牌的概率。"
                        + (f"{playbook}" if playbook else "")
                    )
                elif index % 2 == 0:
                    tips.append(
                        f"{domain} 已是有效采信通道（约 {count} 次引用，品牌相关 {brand_n}）；"
                        f"维持更新节奏，用对比表、覆盖城市、项目结果刷新旧稿，防止引用权重下滑。"
                    )
                else:
                    tips.append(
                        f"巩固 {domain}：在既有 {brand_n} 次品牌相关引用基础上，"
                        f"按监测短板语义词各补 1 篇可核验材料，形成「问法→证据」一一对应。"
                        + (f"{playbook}" if playbook else "")
                    )
            elif playbook:
                tips.append(f"{domain}（约 {count} 次引用）：{playbook}")

    if not tips and top_sources:
        tips.append(
            "高频信源偏资讯聚合页，品牌可核验材料不足；"
            "建议同步产出榜单、行业报告摘要与场景问答，提高品牌相关引用占比。"
        )
    if source_analysis.get("brand_related_references", 0) == 0:
        tips.append(
            "全量高频域名中品牌相关引用偏弱：先在垂直行业站建立可验证资料页，"
            "再向问答与百科延伸，形成交叉采信。"
        )
    domain_n = len(source_analysis.get("domain_stats") or [])
    if domain_n and domain_n < 5:
        tips.append(
            f"有效高频域名仅约 {domain_n} 个，信源覆盖面偏窄；"
            f"向百科、问答、垂直媒体扩展可引用素材，降低对单一聚合站的依赖。"
        )
    tips.append(
        "电梯、高铁、机场等场景词应分开建内容资产与标题体系，"
        "避免一份通稿在多问法下被模型判定同质而降低露出。"
    )
    tips.append(
        "对已领先平台保持更新频率，同时把验证有效的答法迁移到低提及平台，"
        "用「优势答法复用」代替「同一渠道重复加码」。"
    )
    # 去重保序
    deduped: list[str] = []
    for tip in tips:
        tip = tip.strip()
        if tip and tip not in deduped:
            deduped.append(tip)
    return deduped[:10]


def _names_match(left: str | None, right: str | None) -> bool:
    """与售前诊断同一套严格实体匹配，禁止两字前缀互撞。"""
    from app.services.lead_diagnosis_analytics import names_match

    return names_match(left, right)


def _strict_entity_match(left: str | None, right: str | None) -> bool:
    return _names_match(left, right)


def canonical_ranking_name(name: str, brand: str, competitors: list[str]) -> str:
    if _names_match(name, brand):
        return brand
    for comp in competitors:
        if _strict_entity_match(name, comp):
            return comp
    return str(name or "").strip()


def build_competitor_landscape(
    prompt_analytics: list[dict[str, Any]],
    *,
    brand: str,
    competitors: list[str],
) -> list[dict[str, Any]]:
    tracked = [brand, *competitors]
    stats: dict[str, dict[str, Any]] = {
        name: {"name": name, "mention_total": 0, "sample_total": 0, "ranks": [], "is_brand": _names_match(name, brand)}
        for name in tracked
    }
    for block in prompt_analytics:
        sample_count = int(block.get("sample_count") or 0)
        for row in block.get("mention_table") or []:
            row_name = str(row.get("name") or "")
            target = None
            for name in tracked:
                if _names_match(row_name, name) or _strict_entity_match(row_name, name):
                    target = name
                    break
            if target is None:
                continue
            bucket = stats[target]
            bucket["mention_total"] += int(row.get("mention_count") or 0)
            bucket["sample_total"] += sample_count
            avg_rank = row.get("avg_rank")
            if avg_rank is not None:
                bucket["ranks"].append(float(avg_rank))
    rows = []
    for name in tracked:
        bucket = stats[name]
        sample_total = bucket["sample_total"] or 1
        ranks = bucket["ranks"]
        rows.append(
            {
                "name": name,
                "is_brand": bucket["is_brand"],
                "mention_rate": round(bucket["mention_total"] / sample_total * 100, 1),
                "avg_rank": round(sum(ranks) / len(ranks), 1) if ranks else None,
            }
        )
    rows.sort(key=lambda row: (-row["mention_rate"], row["avg_rank"] or 999))
    return rows


def build_prompt_platform_matrix(
    matrix_rows: list[dict[str, Any]],
    *,
    prompts: list[str],
    platform_names: dict[str, str],
) -> dict[str, Any]:
    platforms: list[str] = []
    for row in matrix_rows:
        code = str(row.get("platform") or "")
        if code and code not in platforms:
            platforms.append(code)
    cell_map: dict[tuple[str, str], dict[str, Any]] = {}
    for row in matrix_rows:
        prompt = str(row.get("prompt") or "")
        platform = str(row.get("platform") or "")
        if prompt and platform:
            cell_map[(prompt, platform)] = row
    matrix = []
    for prompt in prompts:
        cells = []
        for platform in platforms:
            cell = cell_map.get((prompt, platform)) or {}
            cells.append(
                {
                    "mention_rate": cell.get("mention_rate"),
                    "avg_rank": cell.get("avg_rank"),
                }
            )
        matrix.append({"prompt": prompt, "cells": cells})
    return {
        "prompts": prompts,
        "platforms": [platform_names.get(code) or code for code in platforms],
        "platform_codes": platforms,
        "rows": matrix,
    }


def build_rule_prompt_comments(
    prompt_analytics: list[dict[str, Any]],
    *,
    brand: str,
    competitors: list[str],
    matrix_rows: list[dict[str, Any]],
) -> list[dict[str, str]]:
    comments: list[dict[str, str]] = []
    for block in prompt_analytics:
        prompt = str(block.get("prompt") or "")
        rate = float(block.get("brand_mention_rate") or 0)
        rank = block.get("brand_avg_rank")
        rank_text = f"{float(rank):.1f}" if rank is not None else "—"
        prompt_matrix = [row for row in matrix_rows if row.get("prompt") == prompt]
        best_platform = None
        worst_platform = None
        if prompt_matrix:
            mentioned = [row for row in prompt_matrix if float(row.get("mention_rate") or 0) > 0]
            if mentioned:
                best_platform = max(mentioned, key=lambda row: float(row.get("mention_rate") or 0))
                worst_platform = min(mentioned, key=lambda row: float(row.get("mention_rate") or 0))
        top_competitor = None
        for row in block.get("mention_table") or []:
            if row.get("is_brand") or row.get("is_competitor"):
                if not row.get("is_brand"):
                    top_competitor = row
                    break
        parts = [f"「{prompt}」提及率 {rate:.1f}%，平均排名 {rank_text}"]
        if rate <= 0:
            parts.append("品牌尚未进入 AI 推荐列表，需优先补齐该场景内容")
        elif rank is not None and float(rank) <= 3:
            parts.append("排名靠前，建议维持更新频率巩固优势")
        else:
            parts.append("排名仍有提升空间，建议对标头部竞品优化表述")
        if top_competitor:
            parts.append(
                f"竞品「{top_competitor.get('name')}」提及率 {float(top_competitor.get('mention_rate') or 0):.1f}%"
            )
        if best_platform and worst_platform and best_platform.get("platform") != worst_platform.get("platform"):
            parts.append(
                f"平台差异：{best_platform.get('platform')} 提及率较高，"
                f"{worst_platform.get('platform')} 偏低"
            )
        comments.append({"prompt": prompt, "comment": "；".join(parts) + "。"})
    return comments


def build_rule_platform_insight(
    platform_stats: list[dict[str, Any]],
    platform_names: dict[str, str],
) -> str:
    if not platform_stats:
        return "暂无分平台样本，无法解读平台差异。"
    sorted_rows = sorted(platform_stats, key=lambda row: float(row.get("mention_rate") or 0), reverse=True)
    top = sorted_rows[0]
    bottom = sorted_rows[-1]
    top_name = platform_names.get(str(top.get("platform") or "")) or top.get("platform")
    bottom_name = platform_names.get(str(bottom.get("platform") or "")) or bottom.get("platform")
    spread = float(top.get("mention_rate") or 0) - float(bottom.get("mention_rate") or 0)
    return (
        f"分平台提及率差距约 {spread:.1f} 个百分点：{top_name} 相对领先"
        f"（约 {float(top.get('mention_rate') or 0):.1f}%），"
        f"{bottom_name} 明显落后（约 {float(bottom.get('mention_rate') or 0):.1f}%）。"
        "低提及平台应优先补齐「场景词 + 可核验证据」组合内容，"
        "并把高提及平台已验证的答法与信源类型迁移过去，缩小平台间曝光落差。"
    )


def build_rule_analysis_tips(
    *,
    brand: str,
    platform_stats: list[dict[str, Any]],
    platform_names: dict[str, str],
    prompt_analytics: list[dict[str, Any]],
    source_analysis: dict[str, Any],
    kpis: dict[str, Any] | None = None,
) -> list[str]:
    """无 LLM 时的分层策略兜底（深度/广度/维度/策略）。"""
    tips: list[str] = []
    kpis = kpis or {}
    mention = float(kpis.get("mention_rate") or 0)
    avg_rank = kpis.get("avg_rank")
    top3 = float(kpis.get("top3_rate") or 0)

    tips.append(f"【深度】围绕「{brand}」补齐可核验案例、报价口径与场景对比，提升回答中的论据厚度。")
    if avg_rank is not None:
        tips.append(f"【深度】当前均位约 {avg_rank}，针对未进 Top3 的语义词做专题页与权威背书，压缩与头部差距。")
    else:
        tips.append("【深度】均位样本不足，先保证核心语义词稳定出答案再谈位次优化。")

    tips.append(f"【广度】品牌提及率 {mention:.1f}%，在低曝光语义词与长尾问法上铺开结构化回答入口。")
    domain_n = len(source_analysis.get("domain_stats") or [])
    tips.append(f"【广度】当前高频域名约 {domain_n} 个，向百科/问答/垂直媒体同步可引用素材，避免只靠聚合页。")

    if platform_stats:
        low = sorted(platform_stats, key=lambda row: float(row.get("mention_rate") or 0))[:2]
        for row in low:
            code = str(row.get("platform") or "")
            name = platform_names.get(code) or code
            rate = float(row.get("mention_rate") or 0)
            tips.append(f"【维度】平台「{name}」提及率 {rate:.1f}%，按该平台内容形态补榜单/对比稿。")
    tips.append(f"【维度】Top3 露出率 {top3:.1f}%，区分「曝光」与「推荐位」两套内容资产分别投放。")

    if prompt_analytics:
        worst = min(
            prompt_analytics,
            key=lambda row: (float(row.get("brand_mention_rate") or 0), float(row.get("brand_avg_rank") or 999)),
        )
        prompt = str(worst.get("prompt") or "")[:28]
        if prompt:
            tips.append(f"【策略】优先攻坚语义词「{prompt}」，30 天内完成内容生产与外链布局。")
    tips.append("【策略】建立周更监测→短板语义词→信源投放闭环，以引用次数与均位双指标验收。")
    tips.append("【策略】竞品高提及场景做对照表（能力/覆盖/合规），引导模型在对比问法中引用品牌。")
    return tips[:10]


def pick_answer_excerpts(
    subtasks: list[GeoMonitorSubtask],
    *,
    brand: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    completed = [
        item for item in subtasks
        if item.status in TERMINAL_STATUSES and item.answer_content and item.mention_position
    ]
    completed.sort(key=lambda row: (row.mention_position or 999, -(len(row.answer_content or ""))))
    excerpts: list[dict[str, Any]] = []
    seen_prompts: set[str] = set()
    for item in completed:
        prompt = str(item.prompt or "")
        if prompt in seen_prompts:
            continue
        text = re.sub(r"\s+", " ", str(item.answer_content or "")).strip()
        if not text:
            continue
        snippet = text[:_EXCERPT_MAX] + ("…" if len(text) > _EXCERPT_MAX else "")
        excerpts.append(
            {
                "prompt": prompt,
                "platform": item.platform,
                "rank": item.mention_position,
                "excerpt": snippet,
            }
        )
        seen_prompts.add(prompt)
        if len(excerpts) >= limit:
            break
    return excerpts


def merge_prompt_commentaries(
    rule_comments: list[dict[str, str]],
    ai_comments: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    ai_map = {
        str(row.get("prompt") or ""): str(row.get("comment") or "").strip()
        for row in (ai_comments or [])
        if str(row.get("prompt") or "").strip() and str(row.get("comment") or "").strip()
    }
    merged: list[dict[str, str]] = []
    for row in rule_comments:
        prompt = row["prompt"]
        merged.append({"prompt": prompt, "comment": ai_map.get(prompt) or row["comment"]})
    return merged


def merge_priority_actions(
    rule_actions: list[dict[str, Any]],
    ai_actions: list[dict[str, Any]] | None,
    *,
    min_count: int = 8,
    max_count: int = 10,
) -> list[dict[str, Any]]:
    """LLM 优先润色，规则引擎补齐到 8~10 条（不瞎编：只保留有 title 的条目）。"""
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _append(item: dict[str, Any]) -> None:
        title = str(item.get("title") or "").strip()
        if not title:
            return
        title = re.sub(r"验收口径[:：]?\s*", "", title).strip()
        key = re.sub(r"\s+", "", title)
        if not key or key in seen:
            return
        priority = str(item.get("priority") or "P2").upper()
        if priority not in {"P0", "P1", "P2"}:
            priority = "P2"
        seen.add(key)
        normalized.append(
            {
                "priority": priority,
                "title": title,
                "timeline": str(item.get("timeline") or "90天").strip(),
            }
        )

    for item in ai_actions or []:
        if isinstance(item, dict):
            _append(item)
    for item in rule_actions or []:
        if len(normalized) >= max_count:
            break
        if isinstance(item, dict):
            _append(item)
    # 仍不足时继续从规则池补（build_priority_actions 已按诊断短板生成）
    if len(normalized) < min_count:
        for item in rule_actions or []:
            if len(normalized) >= min_count:
                break
            if isinstance(item, dict):
                _append(item)
    return normalized[:max_count] if normalized else list(rule_actions or [])[:max_count]


def build_priority_actions(
    prompt_analytics: list[dict[str, Any]],
    platform_stats: list[dict[str, Any]],
    *,
    platform_names: dict[str, str],
    source_analysis: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """按诊断短板生成可落地行动项（供凑满 8~10 条，禁止空话）。"""
    actions: list[dict[str, Any]] = []
    if prompt_analytics:
        ranked = sorted(
            prompt_analytics,
            key=lambda row: (float(row.get("brand_mention_rate") or 0), float(row.get("brand_avg_rank") or 999)),
        )
        for row in ranked[:5]:
            prompt = str(row.get("prompt") or "").strip()
            rate = float(row.get("brand_mention_rate") or 0)
            avg_rank = row.get("brand_avg_rank")
            if not prompt:
                continue
            rank_bit = (
                f"，当前均位约 {float(avg_rank):.1f}"
                if avg_rank not in (None, "")
                else ""
            )
            actions.append(
                {
                    "priority": "P0" if rate < 20 else "P1",
                    "title": (
                        f"围绕语义词「{prompt[:28]}」补场景案例、对比口径与可引用结论"
                        f"（提及率约 {rate:.1f}%{rank_bit}），优先覆盖低露出问法的内容缺口"
                    ),
                    "timeline": "30天" if rate < 20 else "60天",
                }
            )
    if platform_stats:
        low = sorted(platform_stats, key=lambda row: float(row.get("mention_rate") or 0))
        for row in low[:4]:
            rate = float(row.get("mention_rate") or 0)
            if rate >= 40:
                continue
            code = str(row.get("platform") or "")
            name = platform_names.get(code) or code
            actions.append(
                {
                    "priority": "P1",
                    "title": (
                        f"在「{name}」按平台内容形态补榜单/问答/结构化品牌介绍"
                        f"（当前提及率约 {rate:.1f}%），缩小与优势平台的露出差距"
                    ),
                    "timeline": "60天",
                }
            )
        high = sorted(platform_stats, key=lambda row: float(row.get("mention_rate") or 0), reverse=True)
        if high:
            top = high[0]
            top_rate = float(top.get("mention_rate") or 0)
            if top_rate >= 50:
                top_name = platform_names.get(str(top.get("platform") or "")) or top.get("platform")
                actions.append(
                    {
                        "priority": "P2",
                        "title": (
                            f"巩固优势平台「{top_name}」（提及率约 {top_rate:.1f}%）的有效答法与证据链，"
                            f"迁移到短板平台形成统一口径"
                        ),
                        "timeline": "60天",
                    }
                )
    domain_stats = list((source_analysis or {}).get("domain_stats") or [])
    for row in domain_stats[:3]:
        domain = str(row.get("domain") or "").strip()
        count = int(row.get("count") or 0)
        brand_n = int(row.get("brand_related_count") or 0)
        if not domain or count < 2:
            continue
        if brand_n == 0:
            actions.append(
                {
                    "priority": "P1",
                    "title": (
                        f"针对高频域名 {domain}（约 {count} 次引用、品牌相关 0）"
                        f"补带完整品牌名的白皮书/案例页，提高被摘录时带品牌的概率"
                    ),
                    "timeline": "60天",
                }
            )
        elif brand_n / max(count, 1) < 0.3:
            actions.append(
                {
                    "priority": "P2",
                    "title": (
                        f"优化 {domain} 上的品牌相关材料结构（引用约 {count} 次、品牌相关 {brand_n}），"
                        f"用「场景词+可核验结论」替换空泛通稿"
                    ),
                    "timeline": "90天",
                }
            )
    actions.append(
        {
            "priority": "P2",
            "title": "在垂直行业站与问答平台同步投放可核验案例，抬升品牌相关引用密度",
            "timeline": "90天",
        }
    )
    actions.append(
        {
            "priority": "P2",
            "title": "建立「短板平台×短板语义词」周复盘清单，固定内容生产与外链投放节奏",
            "timeline": "90天",
        }
    )
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in actions:
        key = re.sub(r"\s+", "", str(item.get("title") or ""))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:10]


def build_report_enrichment(
    *,
    brand: str,
    competitors: list[str],
    prompt_analytics: list[dict[str, Any]],
    matrix_rows: list[dict[str, Any]],
    platform_stats: list[dict[str, Any]],
    platform_names: dict[str, str],
    source_analysis: dict[str, Any],
    top_sources: list[dict[str, Any]],
    subtasks: list[GeoMonitorSubtask],
    sentiment_counts: dict[str, int],
    positive_rate: float,
) -> dict[str, Any]:
    prompts = [str(row.get("prompt") or "") for row in prompt_analytics if row.get("prompt")]
    return {
        "competitor_landscape": build_competitor_landscape(
            prompt_analytics, brand=brand, competitors=competitors
        ),
        "prompt_platform_matrix": build_prompt_platform_matrix(
            matrix_rows, prompts=prompts, platform_names=platform_names
        ),
        "prompt_commentaries": build_rule_prompt_comments(
            prompt_analytics,
            brand=brand,
            competitors=competitors,
            matrix_rows=matrix_rows,
        ),
        "platform_insight": build_rule_platform_insight(platform_stats, platform_names),
        "source_action_tips": build_rule_source_tips(source_analysis, top_sources),
        "answer_excerpts": pick_answer_excerpts(subtasks, brand=brand),
        "sentiment_counts": sentiment_counts,
        "positive_rate": positive_rate,
        "priority_actions": build_priority_actions(
            prompt_analytics,
            platform_stats,
            platform_names=platform_names,
            source_analysis=source_analysis,
        ),
    }
