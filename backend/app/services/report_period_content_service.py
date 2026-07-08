"""周期/诊断报告 8 大模块正文与 Premium 导出块（规则模板 + AI 补全）。"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.services.molizhishu_catalog_service import get_supported_platform_catalog

PERIODIC_REPORT_TYPES = frozenset({"weekly", "monthly", "quarterly", "annual"})
ALL_RICH_REPORT_TYPES = PERIODIC_REPORT_TYPES | {"diagnosis"}
REPORT_MODULE_SCHEMA_VERSION = 2

_DIAGNOSIS_COVER_TITLE = "GEO企业诊断报告"
_TITLE_PAREN_MARKERS = ("（", " (", "(")


def format_diagnosis_display_title(title: str | None) -> str:
    """诊断报告封面/列表标题：去掉末尾周期说明括号，周期在 period_range 单独展示。"""
    text = (title or "").strip()
    if not text:
        return _DIAGNOSIS_COVER_TITLE
    cut = len(text)
    for marker in _TITLE_PAREN_MARKERS:
        pos = text.find(marker)
        if pos != -1:
            cut = min(cut, pos)
    if cut < len(text):
        text = text[:cut].strip()
    return text or _DIAGNOSIS_COVER_TITLE

_SENTIMENT_COUNT_ALIASES: dict[str, str] = {
    "positive": "正面",
    "pos": "正面",
    "neutral": "中性",
    "negative": "负面",
    "neg": "负面",
    "unknown": "未知",
    "正面": "正面",
    "中性": "中性",
    "负面": "负面",
    "未知": "未知",
}


def normalize_sentiment_counts(counts: dict[str, int] | None) -> dict[str, int]:
    """统一售前诊断(英文键)与监测快照(中文键)的情绪计数。"""
    merged = {"正面": 0, "中性": 0, "负面": 0, "未知": 0}
    for raw_key, raw_value in (counts or {}).items():
        key = str(raw_key or "").strip().lower()
        label = _SENTIMENT_COUNT_ALIASES.get(key, str(raw_key or "").strip())
        if label not in merged:
            merged[label] = 0
        merged[label] += int(raw_value or 0)
    return merged


def sentiment_summary_from_counts(
    counts: dict[str, int],
    *,
    diagnosis: dict[str, Any] | None = None,
) -> str:
    diagnosis = diagnosis or {}
    total = sum(int(v) for v in counts.values())
    if total <= 0:
        return str(diagnosis.get("sentiment_summary") or "暂无有效舆情样本。")
    positive = int(counts.get("正面") or 0)
    neutral = int(counts.get("中性") or 0)
    negative = int(counts.get("负面") or 0)
    unknown = int(counts.get("未知") or 0)
    positive_pct = round(positive * 100 / total, 1)
    neutral_pct = round(neutral * 100 / total, 1)
    negative_pct = round(negative * 100 / total, 1)
    tone = "良好" if positive_pct >= 60 else "有待提升"
    parts = [
        f"正面 {positive_pct}%（{positive} 条）",
        f"中性 {neutral_pct}%（{neutral} 条）",
        f"负面 {negative_pct}%（{negative} 条）",
    ]
    if unknown:
        unknown_pct = round(unknown * 100 / total, 1)
        parts.append(f"未识别 {unknown_pct}%（{unknown} 条）")
    return f"有效舆情样本 {total} 条：" + "、".join(parts) + f"；整体口碑{tone}。"

_TYPE_META: dict[str, dict[str, str]] = {
    "weekly": {
        "label": "监测周报",
        "scope": "本周",
        "next": "下一周",
        "cadence": "周度",
        "plan_title": "下一周品牌传播行动规划",
    },
    "monthly": {
        "label": "监测月报",
        "scope": "本月",
        "next": "下一月",
        "cadence": "月度",
        "plan_title": "下一月品牌传播行动规划",
    },
    "quarterly": {
        "label": "监测季报",
        "scope": "本季度",
        "next": "下一季度",
        "cadence": "季度",
        "plan_title": "下一季度品牌传播行动规划",
    },
    "annual": {
        "label": "监测年报",
        "scope": "本年度",
        "next": "下一年度",
        "cadence": "年度",
        "plan_title": "下一年度品牌传播目标与行动规划",
    },
    "diagnosis": {
        "label": "企业诊断报告",
        "scope": "诊断周期",
        "next": "后续周期",
        "cadence": "诊断",
        "plan_title": "",
    },
}


def _platform_label_map() -> dict[str, str]:
    return {
        str(item.get("code") or ""): str(item.get("name") or item.get("code") or "")
        for item in get_supported_platform_catalog()
    }


def _format_period_range(
    period_label: str,
    period_start: date | None,
    period_end: date | None,
) -> str:
    if period_start and period_end:
        return f"{period_start.strftime('%Y.%m.%d')}-{period_end.strftime('%Y.%m.%d')}"
    return period_label or "—"


def _normalize_sentiment_layers(
    *,
    completed: int,
    sentiment_counts: dict[str, int],
    positive_rate: Any,
    diagnosis: dict[str, Any],
) -> list[dict[str, Any]]:
    counts = normalize_sentiment_counts(sentiment_counts)
    if not counts and completed > 0 and positive_rate is not None:
        try:
            positive_pct = float(positive_rate)
        except (TypeError, ValueError):
            positive_pct = 68.0
        positive = int(completed * positive_pct / 100)
        negative = max(1, int(completed * 0.08))
        neutral = max(0, completed - positive - negative)
        counts = {"正面": positive, "中性": neutral, "负面": negative}

    total = sum(int(v) for v in counts.values()) or completed or 1
    weakness = str(diagnosis.get("weakness_points") or "").strip()
    strength = str(diagnosis.get("strength_points") or "").strip()

    layers: list[dict[str, Any]] = []
    for label in ("正面", "中性", "负面"):
        count = int(counts.get(label, 0))
        percent = round(count * 100 / total, 1) if total else 0.0
        layer: dict[str, Any] = {"label": label, "count": count, "percent": percent}
        if label == "正面":
            layer["summary"] = (
                strength
                or f"近 {percent}% 监测样本呈正向倾向，品牌基础口碑认可度高；"
                "正面内容多集中在综合实力、行业资质与合作稳定性等维度。"
            )
        elif label == "中性":
            layer["summary"] = (
                "多为客观行业科普、参数对比或无主观倾向的渠道收录；"
                "可通过结构化内容运营转化为正向种草素材。"
            )
        else:
            pain_points = []
            if "服务" in weakness or "响应" in weakness:
                pain_points.append("服务端：售前/售后响应速度慢、咨询反馈周期长")
            if "价格" in weakness or "定价" in weakness:
                pain_points.append("价格端：定价体系不透明、套餐区分模糊，用户比价成本高")
            if not pain_points:
                pain_points = [
                    "服务端：高权重渠道存在服务体验相关负向表述",
                    "价格端：部分场景下价格/套餐信息不够清晰，影响决策效率",
                ]
            layer["pain_points"] = pain_points
            layer["summary"] = weakness or "负面样本占比较低，但多集中在高权重专业信源，需重点整改。"
            layer["risk_note"] = (
                "负面内容虽占比不高，但在知乎等高权重渠道长期留存会持续影响潜在客户决策，需专项对冲。"
            )
            layer["is_risk"] = True
        layers.append(layer)
    return layers


def _health_interpretation(score: Any, mention_rate: Any, top3_rate: Any) -> str:
    try:
        value = int(score)
    except (TypeError, ValueError):
        return "健康分反映品牌在全平台的综合 GEO 表现，需结合提及率、排名与舆情综合研判。"
    if value >= 85:
        return f"品牌健康分 {value} 分，处于优秀区间，基础曝光与口碑表现均衡，可重点冲击头部推荐位。"
    if value >= 75:
        return (
            f"品牌健康分 {value} 分，处于中等偏上区间，基础曝光稳定；"
            "但负面舆情、多渠道布局不均衡等问题仍拉低上限，距离优秀梯队（85 分以上）存在差距。"
        )
    if value >= 60:
        return (
            f"品牌健康分 {value} 分，处于中等区间，品牌已被部分场景提及（提及率 {mention_rate}%），"
            f"Top3 露出率 {top3_rate}%，需系统性补齐内容与信源短板。"
        )
    return f"品牌健康分 {value} 分，整体 GEO 基础薄弱，建议优先完成核心语义词覆盖与权威信源部署。"


def _platform_rows_with_positioning(
    platform_stats: list[dict[str, Any]],
    mention_rate: Any,
) -> tuple[list[dict[str, Any]], str]:
    names = _platform_label_map()
    rows: list[dict[str, Any]] = []
    for item in platform_stats:
        code = str(item.get("platform") or "")
        rows.append(
            {
                "code": code,
                "name": names.get(code) or code,
                "completed": int(item.get("completed") or item.get("total") or 0),
                "total": int(item.get("total") or item.get("completed") or 0),
                "mention_rate": item.get("mention_rate"),
                "avg_rank": item.get("avg_rank"),
            }
        )
    if not rows:
        return [], "暂无分平台监测明细，建议扩大平台覆盖后复盘。"

    try:
        avg_mention = float(mention_rate) if mention_rate is not None else sum(float(r["mention_rate"] or 0) for r in rows) / len(rows)
    except (TypeError, ValueError, ZeroDivisionError):
        avg_mention = 0.0

    best = max(rows, key=lambda r: float(r.get("mention_rate") or 0))
    worst = min(rows, key=lambda r: float(r.get("mention_rate") or 0))

    for row in rows:
        rate = float(row.get("mention_rate") or 0)
        rank = row.get("avg_rank")
        is_best = row is best
        is_worst = row is worst and len(rows) > 1
        if is_best:
            positioning = (
                f"核心优势渠道，曝光与排名双维度领先，用户触达效率最优，"
                f"建议作为{row['name']}重点深耕阵地。"
            )
        elif is_worst:
            positioning = (
                f"相对短板渠道，提及率、排名均偏弱，头部曝光能力待提升，"
                "需补充优质问答与行业科普内容拉升排名。"
            )
        else:
            positioning = "中等优势渠道，具备稳定曝光潜力，可维持常规内容投放并缩小与领跑平台差距。"
        row["positioning"] = positioning
        row["is_leading"] = is_best
        row["is_weak"] = is_worst
        row["mention_gap"] = round(rate - avg_mention, 1)

    best_name = best["name"]
    best_rate = best.get("mention_rate")
    conclusion = (
        f"{best_name} 是当前品牌传播最优阵地，提及率 {best_rate}% "
        f"（{'高于' if float(best_rate or 0) >= avg_mention else '接近'}全域均值 {round(avg_mention, 1)}%）；"
        "但各平台数据分化明显，渠道布局不均衡，存在流量短板，需分层运营。"
    )
    return rows, conclusion


def _source_value_analysis(title: str, count: int) -> str:
    text = str(title or "")
    if "知乎" in text:
        return (
            "长效专业流量渠道，行业用户决策核心参考；"
            "若负面舆情集中于此，应作为整改与正向对冲的核心阵地。"
        )
    if "官网" in text or "官方" in text:
        return "品牌权威背书源头，所有外部渠道引用基础；可持续丰富案例、报价与服务板块内容。"
    if "媒体" in text or "评测" in text:
        return "行业精准人群渠道，公信力强，适合投放专业测评与合作案例提升正面声量。"
    return f"累计引用 {count} 次的高权重渠道，具备持续曝光与背书价值，建议保持内容更新频率。"


def _action_plan_for_type(
    report_type: str,
    *,
    health_score: Any,
    mention_rate: Any,
    period_end: date | None,
) -> dict[str, Any]:
    meta = _TYPE_META.get(report_type, _TYPE_META["monthly"])
    try:
        health = int(health_score or 75)
    except (TypeError, ValueError):
        health = 75
    try:
        mention = float(mention_rate or 57)
    except (TypeError, ValueError):
        mention = 57.0

    if report_type == "weekly":
        goals = [
            f"周度健康分维持 {max(health, 70)} 分以上",
            f"品牌提及率稳定在 {mention:.1f}% 以上",
            "短板平台完成 1 轮语义词内容补充",
            "负面舆情占比控制在 10% 以内",
        ]
        actions = [
            "渠道分层：优势平台维持高频问答更新，短板平台补 2-3 篇结构化内容",
            "知乎/问答渠道：针对当周负面痛点发布 1 篇权威科普对冲",
            "口碑素材：统一服务响应、价格套餐对外口径",
            "监测复盘：周末输出简报，调整下周投放重点",
        ]
    elif report_type == "monthly":
        goals = [
            f"月度健康分提升至 {min(health + 3, 90)} 分以上",
            f"品牌提及率突破 {min(mention + 3, 70):.1f}%",
            "三大平台平均排名稳定进入 TOP3",
            "负面舆情占比控制在 8% 以内",
        ]
        actions = [
            "渠道分层运营：资源倾斜优势平台，补齐短板平台内容",
            "知乎长效运营：建立月度行业指南更新机制",
            "口碑素材储备：产出价格、服务相关标准化宣传内容",
            "月度监测复盘：输出月报并动态调整内容策略",
        ]
    elif report_type == "quarterly":
        goals = [
            f"季度健康分提升至 {min(health + 5, 92)} 分以上",
            f"品牌提及率突破 {min(mention + 5, 72):.1f}%",
            "各平台排名差距缩小至 1 位以内",
            "负面舆情占比控制在 6% 以内",
        ]
        actions = [
            "季度渠道战役：优势平台冲击 TOP1，短板平台专项拉升",
            "信源建设：合作 1-2 篇垂直媒体深度评测",
            "舆情整改：完成知乎等高权重渠道负面对冲体系",
            "季度复盘：对照 KPI 调整下季度内容与投放预算",
        ]
    elif report_type == "diagnosis":
        # 诊断报告不再输出「30 天行动规划」模块，优化建议见 risk_and_strategy。
        goals = []
        actions = []
    else:
        next_year = (period_end.year + 1) if period_end else 2026
        goals = [
            f"全域品牌健康分提升至 {max(85, health + 10)} 分以上",
            f"全域平均品牌提及率突破 {min(65, mention + 8):.0f}%",
            "三大 AI 平台平均排名稳定进入 TOP2",
            "负面舆情占比控制在 5% 以内",
        ]
        actions = [
            f"渠道分层运营：资源倾斜优势平台，补齐 DeepSeek 等内容短板",
            "知乎长效运营：建立月度行业指南更新机制，常态化对冲负面",
            "口碑素材储备：产出价格、服务相关标准化宣传内容，统一全渠道口径",
            f"月度监测复盘：依托 GEO Monitor 每月输出简报，动态调整 {next_year} 内容策略",
        ]

    return {
        "title": meta["plan_title"],
        "period_label": meta["next"],
        "goals": goals,
        "actions": actions,
    }


def sanitize_report_modules_for_type(modules: dict[str, Any], report_type: str) -> dict[str, Any]:
    """诊断报告不展示「30 天行动规划」页；兼容历史已存模块。"""
    if report_type != "diagnosis":
        return modules
    cleaned = dict(modules)
    cleaned["action_plan"] = None
    cleaned["toc"] = [
        {"page": 2, "title": "报告前言（监测范围与口径说明）"},
        {"page": 3, "title": "集团全域品牌监测总览"},
        {"page": 4, "title": "全域舆情情绪深度拆解"},
        {"page": 5, "title": "主流 AI 平台对标分析"},
        {"page": 6, "title": "核心信源传播影响力分析"},
        {"page": 7, "title": "风险诊断与分维度优化策略"},
        {"page": 8, "title": "报告备注说明"},
    ]
    preface = dict(cleaned.get("preface") or {})
    preface["report_title"] = format_diagnosis_display_title(preface.get("report_title"))
    cleaned["preface"] = preface
    return cleaned


def build_report_modules(
    *,
    brand_name: str,
    company_name: str | None,
    report_type: str,
    period_label: str,
    period_start: date | None = None,
    period_end: date | None = None,
    kpis: dict[str, Any],
    platform_stats: list[dict[str, Any]],
    sentiment_counts: dict[str, int],
    top_sources: list[dict[str, Any]],
    competitor_names: list[str],
    diagnosis: dict[str, Any] | None = None,
    highlights: list[str] | None = None,
) -> dict[str, Any]:
    """生成 8 大模块结构化正文（周报/月报/季报/年报/诊断通用）。"""
    diagnosis = diagnosis or {}
    highlights = highlights or []
    meta = _TYPE_META.get(report_type, _TYPE_META["monthly"])
    completed = int(kpis.get("completed_count") or kpis.get("subtask_count") or 0)
    mention_rate = kpis.get("mention_rate")
    avg_rank = kpis.get("avg_rank")
    top3_rate = kpis.get("top3_rate")
    positive_rate = kpis.get("positive_rate")
    source_count = int(kpis.get("source_count") or len(top_sources) or 0)
    health_score = diagnosis.get("health_score") or kpis.get("health_score")
    platform_count = len(platform_stats)
    period_range = _format_period_range(period_label, period_start, period_end)
    publisher = company_name or brand_name
    competitor_text = "、".join(competitor_names) if competitor_names else "未配置竞品"
    if report_type == "diagnosis":
        cover_report_title = f"GEO{meta['label']}"
    else:
        cover_report_title = f"GEO{meta['label']}（{period_label}）"

    preface = {
        "report_title": cover_report_title,
        "publisher": publisher,
        "monitor_tool": "GEO Monitor 售前诊断引擎",
        "period_range": period_range,
        "sample_description": (
            f"{meta['scope']}累计完成 {completed} 条全域品牌监测子任务，"
            f"覆盖 {platform_count or 3} 大主流 AI 问答平台及知乎、行业垂直媒体、企业官网等多渠道；"
            "通过网络多轮数据抓取、语义矩阵建模、多信源交叉校验机制，确保数据真实可追溯。"
        ),
        "core_dimensions": [
            "品牌提及率",
            "搜索推荐平均排名",
            "用户舆情情绪",
            "渠道引用频次",
            "品牌健康综合评分",
        ],
        "purpose": (
            "用于品牌竞争力对标、市场口碑诊断、"
            f"{meta['cadence']}传播策略复盘与{meta['next']}营销内容布局决策参考。"
        ),
        "competitors": competitor_text,
    }

    overview = {
        "kpi_table": {
            "health_score": health_score,
            "mention_rate": mention_rate,
            "avg_rank": avg_rank,
            "source_count": source_count,
            "top3_rate": top3_rate,
            "completed_count": completed,
        },
        "interpretations": [
            {
                "title": "品牌健康分",
                "body": _health_interpretation(health_score, mention_rate, top3_rate),
            },
            {
                "title": "全域品牌提及率",
                "body": (
                    f"{meta['scope']}品牌提及率 {mention_rate}%，"
                    f"{'超半数' if mention_rate and float(mention_rate) >= 50 else '部分'}监测场景下「{brand_name}」被主动提及，"
                    "基础品牌认知度已成型，但不同 AI 平台渠道分化明显，需分层运营。"
                ),
            },
            {
                "title": "平均推荐排名",
                "body": (
                    f"平均推荐排名 #{avg_rank or '—'}，整体接近行业 TOP3 曝光位置，"
                    f"{meta['scope']} {top3_rate}% 场景可进入头部推荐位，流量获取基础较好。"
                ),
            },
            {
                "title": "有效引用信源",
                "body": (
                    f"识别 {source_count} 类有效引用信源，品牌可被行业指南、媒体、官网等多渠道佐证，"
                    "专业背书基础充足；信源质量直接影响跨平台一致露出。"
                ),
            },
        ],
    }

    sentiment_layers = _normalize_sentiment_layers(
        completed=completed,
        sentiment_counts=normalize_sentiment_counts(sentiment_counts),
        positive_rate=positive_rate,
        diagnosis=diagnosis,
    )
    normalized_counts = normalize_sentiment_counts(sentiment_counts)
    sentiment = {
        "total_samples": sum(normalized_counts.values()) or sum(layer["count"] for layer in sentiment_layers) or completed,
        "layers": sentiment_layers,
        "summary": sentiment_summary_from_counts(normalized_counts, diagnosis=diagnosis)
        if sum(normalized_counts.values()) > 0
        else (
            diagnosis.get("sentiment_summary")
            or f"正面情绪占比 {positive_rate}%，整体口碑{'良好' if positive_rate and float(positive_rate) >= 60 else '有待提升'}，需关注高权重渠道负向表述。"
        ),
    }

    platform_rows, platform_conclusion = _platform_rows_with_positioning(platform_stats, mention_rate)
    platform_benchmark = {
        "intro": (
            f"{meta['scope']}各平台监测任务样本量统一（共 {completed} 条），数据具备对标参考性。"
            if platform_rows
            else "当前周期平台样本较少，建议扩大监测覆盖面。"
        ),
        "rows": platform_rows,
        "conclusion": platform_conclusion,
    }

    source_rows = []
    for index, item in enumerate(top_sources[:8], start=1):
        title = str(item.get("title") or item.get("url") or "—")
        count = int(item.get("count") or 0)
        source_rows.append(
            {
                "index": index,
                "title": title,
                "count": count,
                "value_analysis": _source_value_analysis(title, count),
                "platforms": item.get("platforms") or [],
            }
        )
    top_title = source_rows[0]["title"] if source_rows else "高权重渠道"
    source_influence = {
        "rows": source_rows,
        "conclusion": (
            f"「{top_title}」为代表的高权重引用渠道，专业影响力突出，"
            "既是品牌正向背书来源，也可能是负面舆情高发渠道，机遇与风险并存。"
            if source_rows
            else "当前周期高频信源尚未形成稳定格局，建议加强官网与垂直媒体内容部署。"
        ),
    }

    weak_platform = next((r["name"] for r in platform_rows if r.get("is_weak")), "部分平台")
    problems = [
        f"渠道不均衡：{weak_platform} 曝光、排名表现偏弱，未充分挖掘 AI 全域流量",
        "舆情隐患：知乎等高权重渠道可能存在服务、价格相关负向表述，持续影响客户转化",
        "内容短板：服务响应、价格透明化相关素材不足，难以对冲负面舆论",
        "内容布局单一：过度依赖少数渠道，缺少常态化 AI 问答优质内容填充",
    ]
    if diagnosis.get("weakness_points"):
        problems[1] = f"舆情与体验：{diagnosis['weakness_points']}"

    risk_and_strategy = {
        "problems": problems,
        "dimensions": [
            {
                "title": "AI 问答平台分层运营策略",
                "actions": [
                    f"{r['name']}（{'核心阵地' if r.get('is_leading') else '短板渠道' if r.get('is_weak') else '稳定渠道'}）："
                    f"维持/提升 {r.get('mention_rate')}% 提及率，均位 #{r.get('avg_rank') or '—'}；"
                    f"{r.get('positioning', '')}"
                    for r in platform_rows
                ]
                or [
                    "豆包（核心阵地）：加大优质问答、行业方案与客户案例产出，维持高提及率",
                    "Kimi（稳定渠道）：保持常规内容更新，缩小与领跑平台差距",
                    "DeepSeek（短板渠道）：批量输出行业科普与产品答疑，拉升排名",
                ],
            },
            {
                "title": "知乎高权重渠道专项整改",
                "actions": [
                    "负面清理&对冲：针对服务响应、价格透明度痛点，产出官方权威科普回答",
                    "常态化种草：定期更新行业选购指南，植入标准化服务流程与清晰价格体系",
                ],
            },
            {
                "title": "舆情口碑优化（解决核心负面痛点）",
                "actions": [
                    "服务端：优化客户咨询响应机制，同步输出「极速售后响应流程」宣传素材",
                    "价格端：官网与各 AI 平台统一标准化套餐报价，清晰区分产品档位",
                ],
            },
            {
                "title": "权威信源内容补强",
                "actions": [
                    "官网：扩充品牌实力、服务保障、公开报价板块，夯实基础背书",
                    "垂直行业媒体：合作深度评测与标杆案例，提升正面引用量",
                ],
            },
        ],
    }

    action_plan = None
    if report_type != "diagnosis":
        action_plan = _action_plan_for_type(
            report_type,
            health_score=health_score,
            mention_rate=mention_rate,
            period_end=period_end,
        )

    disclaimer = {
        "notes": [
            f"本报告数据周期为 {period_range}，基于 {completed} 条监测子任务，经多轮抓取、语义矩阵、多信源交叉校验生成",
            f"数据覆盖 {platform_count or 3} 大 AI 平台及知乎、垂直行业媒体、企业官网等渠道，不含短视频、线下等其他传播渠道",
            "报告仅供企业内部售前研判、品牌传播策略决策使用，禁止对外商用、转载",
            "指标释义：品牌提及率=监测任务中出现品牌名称的占比；平均排名=AI 推荐列表平均位次；引用次数=外部渠道引用品牌相关内容频次",
        ],
    }

    legacy_sections = {
        "industry_analysis": " ".join(p["body"] for p in overview["interpretations"][:2]),
        "ranking_analysis": platform_conclusion,
        "mention_analysis": sentiment["summary"],
        "source_analysis": source_influence["conclusion"],
        "action_recommendations": " ".join(
            f"{index + 1}. {dim['title']}：{'；'.join(dim['actions'][:2])}"
            for index, dim in enumerate(risk_and_strategy["dimensions"])
        ),
    }

    toc = [
        {"page": 2, "title": "报告前言（监测范围与口径说明）"},
        {"page": 3, "title": "集团全域品牌监测总览"},
        {"page": 4, "title": "全域舆情情绪深度拆解"},
        {"page": 5, "title": "主流 AI 平台对标分析"},
        {"page": 6, "title": "核心信源传播影响力分析"},
        {"page": 7, "title": "风险诊断与分维度优化策略"},
    ]
    if action_plan:
        toc.append({"page": 8, "title": action_plan["title"]})
        toc.append({"page": 9, "title": "报告备注说明"})
    else:
        toc.append({"page": 8, "title": "报告备注说明"})

    return {
        "schema_version": REPORT_MODULE_SCHEMA_VERSION,
        "preface": preface,
        "overview": overview,
        "sentiment": sentiment,
        "platform_benchmark": platform_benchmark,
        "source_influence": source_influence,
        "risk_and_strategy": risk_and_strategy,
        "action_plan": action_plan,
        "disclaimer": disclaimer,
        "toc": toc,
        "highlights": highlights,
        "legacy_sections": legacy_sections,
    }


def build_periodic_report_sections(
    *,
    brand_name: str,
    company_name: str | None,
    report_type: str,
    period_label: str,
    kpis: dict[str, Any],
    platform_stats: list[dict[str, Any]],
    sentiment_counts: dict[str, int],
    top_sources: list[dict[str, Any]],
    competitor_names: list[str],
    period_start: date | None = None,
    period_end: date | None = None,
    diagnosis: dict[str, Any] | None = None,
) -> dict[str, str]:
    modules = build_report_modules(
        brand_name=brand_name,
        company_name=company_name,
        report_type=report_type,
        period_label=period_label,
        period_start=period_start,
        period_end=period_end,
        kpis=kpis,
        platform_stats=platform_stats,
        sentiment_counts=sentiment_counts,
        top_sources=top_sources,
        competitor_names=competitor_names,
        diagnosis=diagnosis,
    )
    return dict(modules["legacy_sections"])


def build_premium_content(
    *,
    brand_name: str,
    report_type: str,
    period_label: str,
    kpis: dict[str, Any],
    platform_stats: list[dict[str, Any]],
    diagnosis: dict[str, Any],
    report_sections: dict[str, str],
    executive_summary: str | None,
    highlights: list[str],
    report_modules: dict[str, Any] | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    sentiment_counts: dict[str, int] | None = None,
    top_sources: list[dict[str, Any]] | None = None,
    competitor_names: list[str] | None = None,
    company_name: str | None = None,
) -> dict[str, Any]:
    """Premium PDF 专用：8 大模块 + 兼容旧字段。"""
    modules = report_modules or build_report_modules(
        brand_name=brand_name,
        company_name=company_name,
        report_type=report_type,
        period_label=period_label,
        period_start=period_start,
        period_end=period_end,
        kpis=kpis,
        platform_stats=platform_stats,
        sentiment_counts=sentiment_counts or {},
        top_sources=top_sources or [],
        competitor_names=competitor_names or [],
        diagnosis=diagnosis,
        highlights=highlights,
    )

    health = kpis.get("health_score") or diagnosis.get("health_score")
    mention_rate = kpis.get("mention_rate")
    strategies = [
        {
            "index": index + 1,
            "title": dim["title"],
            "body": "；".join(dim["actions"][:2]),
        }
        for index, dim in enumerate(modules["risk_and_strategy"]["dimensions"])
    ]

    visibility_summary = executive_summary or (
        f"「{brand_name}」{period_label} GEO 健康分 {health or '—'} 分，"
        f"品牌提及率 {mention_rate}%，{modules['platform_benchmark']['conclusion']}"
    )

    plan_goals = (modules.get("action_plan") or {}).get("goals") or []
    outlook = " ".join(plan_goals[:2])
    if not outlook and modules.get("risk_and_strategy", {}).get("dimensions"):
        first_dim = modules["risk_and_strategy"]["dimensions"][0]
        outlook = f"{first_dim['title']}：{'；'.join(first_dim['actions'][:2])}"

    return {
        "schema_version": REPORT_MODULE_SCHEMA_VERSION,
        "modules": modules,
        "visibility_summary": visibility_summary,
        "strategies": strategies,
        "outlook": outlook,
        "toc": modules["toc"],
    }


def merge_report_sections(
    *,
    ai_sections: dict[str, str] | None,
    rule_sections: dict[str, str],
) -> dict[str, str]:
    merged = dict(rule_sections)
    if ai_sections:
        for key, value in ai_sections.items():
            if str(value or "").strip():
                merged[key] = str(value).strip()
    return merged


def merge_report_modules(
    *,
    rule_modules: dict[str, Any],
    ai_modules: dict[str, Any] | None,
) -> dict[str, Any]:
    """AI 模块优先覆盖对应段落，保留规则生成的结构化数据（表格/TOC）。"""
    if not ai_modules:
        return rule_modules
    merged = dict(rule_modules)
    for key in ("preface", "overview", "sentiment", "platform_benchmark", "source_influence", "risk_and_strategy", "action_plan"):
        ai_block = ai_modules.get(key)
        if isinstance(ai_block, dict) and ai_block:
            base = dict(merged.get(key) or {})
            base.update(ai_block)
            merged[key] = base
    if ai_modules.get("legacy_sections"):
        merged["legacy_sections"] = merge_report_sections(
            ai_sections=ai_modules["legacy_sections"],
            rule_sections=merged.get("legacy_sections") or {},
        )
    return merged
