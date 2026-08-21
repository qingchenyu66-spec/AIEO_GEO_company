"""诊断报告 AI 可见度驾驶舱：1:1 参考壳数据注入。

2026-08-12 - 诊断驾驶舱照抄参考 HTML 壳 - 仅 cockpit_json 换数；缺省指标为 0
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.services.molizhishu_catalog_service import get_supported_platform_catalog
from app.schemas.lead_diagnosis import normalize_lead_context
from app.services.report_source_label_service import enrich_domain_rows
from app.services.report_diagnosis_cockpit_taxonomy import (
    INTENT_LABELS,
    SCENE_LABELS,
    SCENE_RULES,
    classify_prompt,
    compact_prompt_label,
    resolve_filter_mode,
)

_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "report_diagnosis_cockpit"

# 意图矩阵展示顺序（对齐换皮版-G 可见意图：无 criteria/选型）
_INTENT_CARD_ORDER = ("awareness", "recommend", "compare", "reputation")
_INTENT_CARD_TITLE = {
    "awareness": "认知承接",
    "recommend": "入围名单",
    "compare": "对比说服",
    "reputation": "口碑承接",
}

# 2026-08-13 - 无户外场景词时用通用 6 卡补齐版式，禁止空场景「暂无数据」占位
# 2026-08-20 - 去掉「选型标准」空壳卡：顶栏已是竞品对标，无样本时再塞选型标准会误导
# 2026-08-21 - 与换皮版-G 一致：不再保留选型意图；客户可见禁「选型标准/选型路径」品类文案
_FORBIDDEN_CUSTOMER_PHRASES = ("选型标准", "选型路径", "选择标准")
_PHRASE_REWRITE = {
    "选型标准问法": "推荐类问法",
    "选型路径问法": "推荐类问法",
    "选择标准类问法": "推荐类问法",
    "选择标准问法": "推荐类问法",
    "选型标准意图": "推荐意图",
    "选型路径意图": "推荐意图",
    "选型标准": "推荐名单",
    "选型路径": "推荐名单",
    "选择标准": "推荐名单",
    "竞品对比": "竞品对标",
    "技术选型": "竞品对标",
}
_QUOTED_PROMPT_RE = re.compile(r"「[^」]*」|'[^']*'|\"[^\"]*\"")


def _scrub_customer_facing_text(text: str) -> str:
    """客户可见文案 scrub：禁「选型标准」等；引号内原问法原文保留（证据链）。"""
    out = str(text or "")
    protected: list[str] = []

    def _protect(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"\x00Q{len(protected) - 1}\x00"

    out = _QUOTED_PROMPT_RE.sub(_protect, out)
    for old, new in _PHRASE_REWRITE.items():
        if old in out:
            out = out.replace(old, new)
    for idx, chunk in enumerate(protected):
        out = out.replace(f"\x00Q{idx}\x00", chunk)
    return out


def _scrub_narrative_customer_copy(narrative: dict[str, Any]) -> dict[str, Any]:
    """洗 priority / risk / actions / stage 里残留的禁词。"""
    out = dict(narrative or {})

    def _scrub_dict(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
        cleaned = dict(row)
        for key in keys:
            if key in cleaned and cleaned[key] is not None:
                cleaned[key] = _scrub_customer_facing_text(str(cleaned[key]))
        return cleaned

    stage = out.get("stage_copy")
    if isinstance(stage, dict):
        out["stage_copy"] = {
            k: _scrub_dict(v, ("label", "title", "summary")) if isinstance(v, dict) else v
            for k, v in stage.items()
        }
    for list_key, fields in (
        ("priority_items", ("level", "tone_label", "title", "body")),
        ("risk_rows", ("topic", "models", "impact", "evidence", "priority")),
        ("actions", ("level", "impact", "title", "body")),
    ):
        rows = out.get(list_key)
        if not isinstance(rows, list):
            continue
        cleaned_rows = []
        for row in rows:
            if not isinstance(row, dict):
                cleaned_rows.append(row)
                continue
            item = _scrub_dict(row, fields)
            bullets = item.get("bullets")
            if isinstance(bullets, list):
                item["bullets"] = [_scrub_customer_facing_text(str(x)) for x in bullets]
            cleaned_rows.append(item)
        out[list_key] = cleaned_rows
    return out


_GENERIC_PORTFOLIO_CARDS: list[tuple[str, str, str]] = [
    ("recommend", "推荐名单", "入围与推荐"),
    ("compare", "竞品对标", "对标概览"),
    ("brand_rank", "品牌排名", "品牌词防守排名"),
    ("reputation", "口碑评价", "口碑与评价"),
    ("geo_source", "GEO / 官网信源建设", "信源可引用性"),
    ("awareness", "品牌认知", "认知承接"),
]

# 与参考稿五槽一致；监测出现其它平台时再追加
_SLOT_ORDER = ("doubao", "deepseek", "qwen", "yuanbao", "wenxin", "kimi")
_SLOT_NAMES = {
    "doubao": "豆包",
    "deepseek": "DeepSeek",
    "qwen": "千问",
    "yuanbao": "元宝",
    "wenxin": "百度AI+",
    "chatgpt": "ChatGPT",
    "kimi": "Kimi",
    "quark": "夸克",
    "baiduai": "百度AI+",
    "qianwen": "千问",
}
_SLOT_ALIASES: dict[str, tuple[str, ...]] = {
    "doubao": ("doubao", "doubao_mobile"),
    "deepseek": ("deepseek", "deepseek_mobile"),
    "qwen": ("qianwen", "qwen", "qianwen_mobile"),
    "yuanbao": ("yuanbao",),
    "wenxin": ("baiduai", "wenxin", "wenxin_yiyan"),
    "chatgpt": ("chatgpt", "openai"),
    "kimi": ("kimi",),
    "quark": ("quark",),
}
_PREFERRED_SLOT_ORDER = _SLOT_ORDER + ("chatgpt", "quark")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _avg(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 1)


def _canonical_platform(code: str) -> str:
    raw = str(code or "").strip().lower()
    if not raw:
        return ""
    for slot, aliases in _SLOT_ALIASES.items():
        if raw == slot or raw in aliases:
            return slot
    return raw


def _slot_label(code: str, platform_names: dict[str, str] | None = None) -> str:
    if platform_names:
        for key in (code, *( _SLOT_ALIASES.get(code) or () )):
            if key in platform_names and platform_names[key]:
                return str(platform_names[key])
    return _SLOT_NAMES.get(code, code)


def _monitored_slots(
    platform_stats: list[dict[str, Any]],
    matrix_rows: list[dict[str, Any]],
) -> list[str]:
    """只展示实际有监测样本的平台，避免未跑的固定五槽全 0 误导。

    2026-08-13 - SAB 只跑 chatgpt/doubao 时固定五槽全空 - 改为按样本动态列
    """
    seen: set[str] = set()
    for item in platform_stats or []:
        if not isinstance(item, dict):
            continue
        code = _canonical_platform(str(item.get("platform") or item.get("code") or ""))
        total = int(item.get("total") or item.get("completed") or 0)
        if code and (total > 0 or _f(item.get("mention_rate"), 0.0) > 0 or item.get("avg_rank") is not None):
            seen.add(code)
    for item in matrix_rows or []:
        if not isinstance(item, dict):
            continue
        code = _canonical_platform(str(item.get("platform") or ""))
        if code and int(item.get("sample_count") or 0) > 0:
            seen.add(code)
        elif code and (
            item.get("avg_rank") is not None or _f(item.get("mention_rate"), 0.0) > 0
        ):
            seen.add(code)
    ordered = [s for s in _PREFERRED_SLOT_ORDER if s in seen]
    extras = sorted(seen - set(ordered))
    return ordered + extras


def _pick_slot_stats(
    platform_stats: list[dict[str, Any]],
    *,
    slots: list[str] | None = None,
) -> dict[str, dict[str, float]]:
    by_code: dict[str, dict[str, Any]] = {}
    for item in platform_stats or []:
        code = _canonical_platform(str(item.get("platform") or item.get("code") or ""))
        if code:
            by_code[code] = item
    target_slots = slots or list(_SLOT_ORDER)
    out: dict[str, dict[str, float]] = {}
    for slot in target_slots:
        aliases = _SLOT_ALIASES.get(slot, (slot,))
        mentions: list[float] = []
        ranks: list[float] = []
        decisions: list[float] = []
        row = by_code.get(slot)
        if not row:
            for alias in aliases:
                # alias may already be canonical; also accept raw keys in by_code
                cand = by_code.get(_canonical_platform(alias)) or by_code.get(alias)
                if cand:
                    row = cand
                    break
        if row:
            mentions.append(_f(row.get("mention_rate"), 0.0))
            if row.get("avg_rank") is not None:
                ranks.append(_f(row.get("avg_rank"), 0.0))
            # 无分平台 Top3 时用提及率近似决策正向，缺省 0
            decisions.append(_f(row.get("top3_rate"), _f(row.get("mention_rate"), 0.0)))
        out[slot] = {
            "visibility": _avg(mentions) if mentions else 0.0,
            "rank": _avg(ranks) if ranks else 0.0,
            "negative": 0.0,
            "decision": _avg(decisions) if decisions else 0.0,
        }
    return out


def _heat_rank_value(avg_rank: Any) -> int:
    """热力格：有均排则四舍五入为名次；无则 0（前端展示 —）。"""
    if avg_rank is None or avg_rank == "":
        return 0
    try:
        value = float(avg_rank)
    except (TypeError, ValueError):
        return 0
    if value <= 0:
        return 0
    return int(round(value))


def _empty_cell_counts() -> dict[str, Any]:
    return {"total_cells": 0, "mention_cells": 0, "top3_cells": 0, "rank_sum": 0.0}


def _add_cell(counts: dict[str, Any], rank: int) -> None:
    counts["total_cells"] = int(counts["total_cells"]) + 1
    if rank > 0:
        counts["mention_cells"] = int(counts["mention_cells"]) + 1
        counts["rank_sum"] = float(counts["rank_sum"]) + float(rank)
        if rank <= 3:
            counts["top3_cells"] = int(counts["top3_cells"]) + 1


def _metrics_from_cell_counts(counts: dict[str, Any]) -> dict[str, Any]:
    """A+ 格级派生：露出/Top3 分母=total_cells；均排分母=mention_cells。

    2026-08-13 - null/0：分母0→null；分母>0且命中0→rate/top3=0、均排null
    """
    total = int(counts.get("total_cells") or 0)
    mention = int(counts.get("mention_cells") or 0)
    top3 = int(counts.get("top3_cells") or 0)
    rank_sum = float(counts.get("rank_sum") or 0.0)
    if total <= 0:
        return {
            "mention_rate": None,
            "avg_rank": None,
            "top3_rate": None,
            "available": False,
        }
    return {
        "mention_rate": round(100.0 * mention / total, 1),
        "avg_rank": round(rank_sum / mention, 1) if mention > 0 else None,
        "top3_rate": round(100.0 * top3 / total, 1),
        "available": True,
    }


def derive_rates_from_counts(lane: dict[str, Any] | None) -> dict[str, Any]:
    """仅由计数器派生 rate/rank/top3（校验与展示共用）。"""
    return _metrics_from_cell_counts(_counts_only(lane))


def _blob_claims_no_acquisition(obj: Any) -> bool:
    """文案是否把「无获客分母」说成主 KPI 暂无（有获客分母时属矛盾）。"""
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    needles = (
        "获客问法条数为 0",
        "获客问法为 0",
        "非品牌词获客样本数为 0",
        "非品牌词获客问法条数为 0",
        "问法全部为品牌词",
        "获客主 KPI 暂无",
        "获客主KPI暂无",
        "主 KPI 暂无",
        "主KPI暂无",
        "获客提及率 / 平均推荐位 / Top3 率均为暂无",
        "无法评估自然获客可见度",
    )
    return any(n in text for n in needles)


def _blob_claims_acquisition_zero_as_na(obj: Any) -> bool:
    """有分母的 0% 被写成暂无。"""
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return bool(
        re.search(r"非品牌词获客提及率[^。；\n]{0,16}暂无", text)
        or re.search(r"Top3[^。；\n]{0,12}暂无", text)
    )


def validate_cockpit_html_export(
    html: str,
    *,
    brand: str,
    filter_mode: str,
) -> list[str]:
    """出厂校验：禁静态旧客户/旧行业污染；无获客分母禁 null→0 文案。

    2026-08-13 - 客户单 HTML 禁 JS 也不得露出旧客户/旧行业壳
    """
    issues: list[str] = []
    brand_s = str(brand or "").strip()
    if "艾迪亚" not in brand_s and "艾迪亚" in html:
        issues.append("shell_pollution:艾迪亚")
    # 2026-08-20 - 模板曾写死 imtcmkj；非该客户报告禁残留旧官网
    if "艾迪亚" not in brand_s and "imtcmkj" in html.lower():
        issues.append("shell_pollution:imtcmkj")
    if filter_mode != "scene":
        for term in ("机场", "高铁", "电梯", "户外广告"):
            if term in html:
                issues.append(f"industry_pollution:{term}")

    cockpit = None
    m = re.search(r"const __COCKPIT__ = (\{.*?\});\s*\n", html, flags=re.S)
    if m:
        try:
            cockpit = json.loads(m.group(1))
        except json.JSONDecodeError:
            cockpit = None
    all_pd = ((cockpit or {}).get("platformData") or {}).get("all") if isinstance(cockpit, dict) else {}
    vis = all_pd.get("visibility") if isinstance(all_pd, dict) else None
    no_acq = not bool(all_pd.get("primary_kpi_available")) if isinstance(all_pd, dict) else False

    if no_acq or vis is None:
        if brand_s and re.search(rf"{re.escape(brand_s)}\s*0(\.0)?%\s*参考\s*60", html):
            issues.append("benchmark_null_as_zero")
        bm = re.search(r'id="benchmarkBrand">([^<]*)<', html)
        if bm and re.search(r"0(\.0)?%", bm.group(1)):
            issues.append("benchmark_brand_zero_label")
        for title in ("意图选型说服力", "场景选型说服力", "项目采购信任", "自然获客候选池"):
            if re.search(rf"{title}[^<]{{0,80}}0\s*/\s*100", html):
                issues.append(f"insight_null_as_zero:{title}")

    if "nonbrand_rank_sum" not in html or "brand_rank_sum" not in html:
        issues.append("slices_missing_rank_sum")
    return issues


def validate_cockpit_null0(cockpit: dict[str, Any]) -> list[str]:
    """遍历 __COCKPIT__：kpi_basis 计数器 ↔ platformData 的 null/0 规则。"""
    issues: list[str] = []
    kb = cockpit.get("kpi_basis") if isinstance(cockpit.get("kpi_basis"), dict) else {}
    pd = cockpit.get("platformData") if isinstance(cockpit.get("platformData"), dict) else {}

    def _check(label: str, slice_obj: dict[str, Any], nb: dict[str, Any], bd: dict[str, Any]) -> None:
        exp_nb = derive_rates_from_counts(nb)
        exp_bd = derive_rates_from_counts(bd)
        vis, rank, dec = slice_obj.get("visibility"), slice_obj.get("rank"), slice_obj.get("decision")
        bdef = slice_obj.get("brand_defense")
        avail = slice_obj.get("primary_kpi_available")
        if not exp_nb["available"]:
            if vis is not None or rank is not None or dec is not None:
                issues.append(f"{label}: total_cells=0 但 KPI 非 null ({vis}/{rank}/{dec})")
            if avail is not False:
                issues.append(f"{label}: primary_kpi_available 应为 false")
        else:
            if avail is not True:
                issues.append(f"{label}: primary_kpi_available 应为 true")
            if vis != exp_nb["mention_rate"]:
                issues.append(f"{label}: visibility {vis} != {exp_nb['mention_rate']}")
            if rank != exp_nb["avg_rank"]:
                issues.append(f"{label}: rank {rank} != {exp_nb['avg_rank']}")
            if dec != exp_nb["top3_rate"]:
                issues.append(f"{label}: top3 {dec} != {exp_nb['top3_rate']}")
            if int(nb.get("mention_cells") or 0) == 0:
                if vis not in (0, 0.0):
                    issues.append(f"{label}: mention=0 时 visibility 应为 0，得 {vis}")
                if rank is not None:
                    issues.append(f"{label}: mention=0 时 rank 应为 null，得 {rank}")
                if dec not in (0, 0.0):
                    issues.append(f"{label}: mention=0 时 top3 应为 0，得 {dec}")
        if int(bd.get("total_cells") or 0) <= 0:
            if bdef is not None:
                issues.append(f"{label}: brand_total=0 但 brand_defense={bdef}")
        elif bdef != exp_bd["mention_rate"]:
            issues.append(f"{label}: brand_defense {bdef} != {exp_bd['mention_rate']}")

    all_pd = pd.get("all") if isinstance(pd.get("all"), dict) else {}
    _check("all", all_pd, kb.get("nonbrand") or {}, kb.get("brand") or {})
    for slot, lanes in (kb.get("platforms") or {}).items():
        if not isinstance(lanes, dict):
            continue
        _check(f"plat:{slot}", pd.get(slot) or {}, lanes.get("nonbrand") or {}, lanes.get("brand") or {})
    all_slices = all_pd.get("slices") if isinstance(all_pd.get("slices"), dict) else {}
    for dim in ("intents", "scenes"):
        for code, lanes in (kb.get(dim) or {}).items():
            if code not in all_slices or not isinstance(lanes, dict):
                continue
            _check(f"all/{dim}:{code}", all_slices[code], lanes.get("nonbrand") or {}, lanes.get("brand") or {})

    # 文案：有获客分母时，管理层摘要/风险/行动不得声称主 KPI 暂无
    has_acq = bool(all_pd.get("primary_kpi_available"))
    stage_all = ((cockpit.get("stageCopy") or {}).get("all") if isinstance(cockpit.get("stageCopy"), dict) else {}) or {}
    if has_acq and _blob_claims_no_acquisition(stage_all):
        issues.append("stageCopy.all: 有获客分母却声称主 KPI 暂无/无获客问法")
    if has_acq and all_pd.get("visibility") in (0, 0.0) and _blob_claims_acquisition_zero_as_na(stage_all):
        issues.append("stageCopy.all: 获客 0% 被写成暂无")
    for key in ("risks", "actions"):
        blob = cockpit.get(key)
        if has_acq and _blob_claims_no_acquisition(blob):
            issues.append(f"{key}: 有获客分母却声称主 KPI 暂无/无获客问法")

    sb = cockpit.get("sample_basis") if isinstance(cockpit.get("sample_basis"), dict) else {}
    if sb.get("basis_type") != "run_sample":
        issues.append("sample_basis.basis_type 应为 run_sample")
    return issues



def _pack_lane_counts(counts: dict[str, Any]) -> dict[str, Any]:
    return {**counts, **_metrics_from_cell_counts(counts)}


def _counts_only(lane: dict[str, Any] | None) -> dict[str, Any]:
    """对外发布的格级计数器：只保留四字段，不含派生率。"""
    row = lane if isinstance(lane, dict) else {}
    return {
        "total_cells": int(row.get("total_cells") or 0),
        "mention_cells": int(row.get("mention_cells") or 0),
        "top3_cells": int(row.get("top3_cells") or 0),
        "rank_sum": float(row.get("rank_sum") or 0.0),
    }


def publish_kpi_basis(kpi_basis: dict[str, Any]) -> dict[str, Any]:
    """__COCKPIT__.kpi_basis 正规化结构（计数器底座）。"""
    platforms_in = kpi_basis.get("platforms") if isinstance(kpi_basis.get("platforms"), dict) else {}
    intents_in = kpi_basis.get("intents") if isinstance(kpi_basis.get("intents"), dict) else {}
    scenes_in = kpi_basis.get("scenes") if isinstance(kpi_basis.get("scenes"), dict) else {}

    def _lane_pair(block: dict[str, Any]) -> dict[str, Any]:
        return {
            "nonbrand": _counts_only(block.get("nonbrand") if isinstance(block, dict) else None),
            "brand": _counts_only(block.get("brand") if isinstance(block, dict) else None),
        }

    out: dict[str, Any] = {
        "basis_type": "question_platform_cell",
        "top3_denominator": "total_cells",
        "nonbrand": _counts_only(kpi_basis.get("nonbrand") if isinstance(kpi_basis.get("nonbrand"), dict) else None),
        "brand": _counts_only(kpi_basis.get("brand") if isinstance(kpi_basis.get("brand"), dict) else None),
        "platforms": {str(k): _lane_pair(v if isinstance(v, dict) else {}) for k, v in platforms_in.items()},
        "intents": {str(k): _lane_pair(v if isinstance(v, dict) else {}) for k, v in intents_in.items()},
    }
    if scenes_in:
        out["scenes"] = {str(k): _lane_pair(v if isinstance(v, dict) else {}) for k, v in scenes_in.items()}
    return out


def _matrix_cell_map(matrix_rows: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    cell: dict[tuple[str, str], int] = {}
    for row in matrix_rows or []:
        if not isinstance(row, dict):
            continue
        prompt = str(row.get("prompt") or "").strip()
        slot = _canonical_platform(str(row.get("platform") or ""))
        if not prompt or not slot:
            continue
        cell[(prompt, slot)] = _heat_rank_value(row.get("avg_rank"))
    return cell


def build_kpi_basis(
    tagged: list[dict[str, Any]],
    matrix_rows: list[dict[str, Any]],
    slots: list[str],
) -> dict[str, Any]:
    """主报告唯一底座：问法×平台格计数（与热力图同源）。

    2026-08-13 - A+：主 KPI/平台/意图全部由此派生；样本级另见 sample_basis
    """
    cell = _matrix_cell_map(matrix_rows)
    nonbrand = _empty_cell_counts()
    brand = _empty_cell_counts()
    platforms: dict[str, dict[str, dict[str, Any]]] = {
        s: {"nonbrand": _empty_cell_counts(), "brand": _empty_cell_counts()} for s in slots
    }
    intents: dict[str, dict[str, dict[str, Any]]] = {}
    scenes: dict[str, dict[str, dict[str, Any]]] = {}

    def _bucket(store: dict[str, dict[str, dict[str, Any]]], code: str | None) -> dict[str, dict[str, Any]] | None:
        if not code:
            return None
        key = str(code)
        if key not in store:
            store[key] = {"nonbrand": _empty_cell_counts(), "brand": _empty_cell_counts()}
        return store[key]

    for p in tagged:
        prompt = str(p.get("prompt") or "").strip()
        if not prompt:
            continue
        is_brand = p.get("lane") == "brand_defense" or bool(p.get("is_brand_word"))
        lane = "brand" if is_brand else "nonbrand"
        intent_b = _bucket(intents, str(p.get("intent_code") or "") or None)
        scene_b = _bucket(scenes, str(p.get("scene_code") or "") or None)
        for slot in slots:
            rank = cell.get((prompt, slot), 0)
            _add_cell(brand if is_brand else nonbrand, rank)
            if slot in platforms:
                _add_cell(platforms[slot][lane], rank)
            if intent_b is not None:
                _add_cell(intent_b[lane], rank)
            if scene_b is not None:
                _add_cell(scene_b[lane], rank)

    def _pack_dim(raw: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for code, lanes in raw.items():
            out[code] = {
                "nonbrand": _pack_lane_counts(lanes["nonbrand"]),
                "brand": _pack_lane_counts(lanes["brand"]),
            }
        return out

    return {
        "basis_type": "question_platform_cell",
        "top3_denominator": "total_cells",
        "nonbrand": _pack_lane_counts(nonbrand),
        "brand": _pack_lane_counts(brand),
        "platforms": {
            slot: {
                "nonbrand": _pack_lane_counts(lanes["nonbrand"]),
                "brand": _pack_lane_counts(lanes["brand"]),
            }
            for slot, lanes in platforms.items()
        },
        "intents": _pack_dim(intents),
        "scenes": _pack_dim(scenes),
    }


def build_sample_basis(tagged: list[dict[str, Any]]) -> dict[str, Any]:
    """跨日/多次运行样本级，仅稳定性观察，不参与主 KPI。

    2026-08-21 - 对外称「回答命中率」，禁止与格级「提及率」混名
    """
    acq = [p for p in tagged if p.get("lane") == "acquisition"]
    defense = [p for p in tagged if p.get("lane") == "brand_defense"]
    acq_m = _lane_metric_block(acq)
    def_m = _lane_metric_block(defense)
    samples = [int(p.get("sample_count") or 0) for p in tagged if int(p.get("sample_count") or 0) > 0]
    avg_n = round(sum(samples) / len(samples), 1) if samples else None
    sample_size = int(sum(samples)) if samples else 0
    return {
        "basis_type": "run_sample",
        "enabled": True,
        "note": "跨日/多次运行回答命中率，仅用于稳定性观察，不参与主 KPI（提及率）",
        "brand_mention_rate": def_m.get("mention_rate"),
        "nonbrand_mention_rate": acq_m.get("mention_rate"),
        "brand_answer_hit_rate": def_m.get("mention_rate"),
        "nonbrand_answer_hit_rate": acq_m.get("mention_rate"),
        "brand_prompt_count": len(defense),
        "nonbrand_prompt_count": len(acq),
        "avg_samples_per_prompt": avg_n,
        "sample_size": sample_size,
        "question_run_count": sample_size,
    }


def _slice_metrics_from_lanes(
    nonbrand: dict[str, Any],
    brand: dict[str, Any],
    *,
    negative: float | None,
    citation: float | None,
) -> dict[str, Any]:
    """从格级 nonbrand/brand 打包前端 metric 字段。

    2026-08-13 - slices 补 rank_sum，便于单看 slices 审计 null/0
    """
    has_acq = bool(nonbrand.get("available")) and int(nonbrand.get("total_cells") or 0) > 0
    return {
        "visibility": nonbrand.get("mention_rate") if has_acq else None,
        "rank": nonbrand.get("avg_rank") if has_acq else None,
        "decision": nonbrand.get("top3_rate") if has_acq else None,
        "brand_defense": brand.get("mention_rate") if int(brand.get("total_cells") or 0) > 0 else None,
        "negative": negative,
        "citation": citation,
        "primary_kpi_available": has_acq,
        "nonbrand_total_cells": int(nonbrand.get("total_cells") or 0),
        "nonbrand_mention_cells": int(nonbrand.get("mention_cells") or 0),
        "nonbrand_top3_cells": int(nonbrand.get("top3_cells") or 0),
        "nonbrand_rank_sum": float(nonbrand.get("rank_sum") or 0.0),
        "brand_total_cells": int(brand.get("total_cells") or 0),
        "brand_mention_cells": int(brand.get("mention_cells") or 0),
        "brand_rank_sum": float(brand.get("rank_sum") or 0.0),
    }


def _build_heat_scenarios(
    tagged: list[dict[str, Any]],
    matrix_rows: list[dict[str, Any]],
    slots: list[str],
    *,
    evidence_map: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """问法 × 平台均排矩阵（附品牌词/意图/场景分类 + 快照入口）。

    2026-08-13 - 热力曾写死全 0 → 全 —；改为吃 matrix_rows
    2026-08-13 - scenarios 补 is_brand_query / intent / scene / 主 KPI 是否计入
    2026-08-13 - 每格附 snapshot 证据，不参与 KPI
    2026-08-21 - 格主展示露出/均排；matrix.mention_rate 降级为 answer_hit_rate 进详情
    """
    cell: dict[tuple[str, str], int] = {}
    hit: dict[tuple[str, str], float | None] = {}
    for row in matrix_rows or []:
        if not isinstance(row, dict):
            continue
        prompt = str(row.get("prompt") or "").strip()
        slot = _canonical_platform(str(row.get("platform") or ""))
        if not prompt or not slot:
            continue
        cell[(prompt, slot)] = _heat_rank_value(row.get("avg_rank"))
        # 兼容旧字段 mention_rate；优先显式 answer_hit_rate
        raw_hit = row.get("answer_hit_rate")
        if raw_hit is None:
            raw_hit = row.get("mention_rate")
        try:
            hit[(prompt, slot)] = float(raw_hit) if raw_hit is not None else None
        except (TypeError, ValueError):
            hit[(prompt, slot)] = None

    evid = evidence_map if isinstance(evidence_map, dict) else {}

    scenarios: list[dict[str, Any]] = []
    for p in tagged:
        prompt = str(p.get("prompt") or "").strip()
        if not prompt:
            continue
        is_brand = p.get("lane") == "brand_defense" or bool(p.get("is_brand_word"))
        scene_code = p.get("scene_code")
        scene = str(p.get("scene_label") or scene_code or "none")
        if not scene_code:
            scene = "none"
        snapshots: list[dict[str, Any]] = []
        values = [cell.get((prompt, slot), 0) for slot in slots]
        hit_vals = [hit.get((prompt, slot)) for slot in slots]
        for slot in slots:
            key = f"{prompt}||{slot}"
            raw = evid.get(key) if isinstance(evid.get(key), dict) else {}
            rank = cell.get((prompt, slot), 0)
            mentioned = bool(rank and rank > 0)
            share = str(raw.get("share_url") or raw.get("snapshot_url") or "").strip()
            shot = str(raw.get("screenshot_url") or raw.get("page_screenshot") or "").strip()
            summary = str(raw.get("answer_summary") or "").strip()
            refs = raw.get("references") if isinstance(raw.get("references"), list) else []
            if share:
                kind = "link"
                label = "查看快照"
            elif shot:
                kind = "image"
                label = "查看截图"
            else:
                kind = "none"
                label = "本次无快照，仅保留文本摘要"
            snapshots.append(
                {
                    "slot": slot,
                    "kind": kind,
                    "label": label,
                    "share_url": share,
                    "screenshot_url": shot,
                    "prompt": prompt,
                    "mentioned": mentioned,
                    "exposed": mentioned,
                    "rank": rank if rank > 0 else None,
                    "top3": bool(rank and 0 < rank <= 3),
                    "answer_hit_rate": hit.get((prompt, slot)),
                    "answer_summary": summary[:400],
                    "references": [str(x) for x in refs[:8] if str(x).strip()],
                    "is_brand_query": is_brand,
                }
            )
        # 问法级回答命中：优先样本表；否则格内命中均值
        prompt_hit = p.get("brand_mention_rate")
        if prompt_hit is None:
            nums = [float(x) for x in hit_vals if x is not None]
            prompt_hit = round(sum(nums) / len(nums), 1) if nums else None
        scenarios.append(
            {
                "question": prompt,
                "values": values,
                "answer_hit_rates": hit_vals,
                "answer_hit_rate": prompt_hit,
                "is_brand_query": is_brand,
                "query_intent": str(p.get("intent_label") or p.get("intent_code") or ""),
                "scene": scene,
                "is_primary_kpi_included": not is_brand,
                "exclude_reason": "品牌词问法，不计入获客主 KPI" if is_brand else "",
                "snapshots": snapshots,
            }
        )
    if not scenarios:
        scenarios = [
            {
                "question": "（暂无问法样本）",
                "values": [0 for _ in slots],
                "answer_hit_rates": [None for _ in slots],
                "answer_hit_rate": None,
                "is_brand_query": False,
                "query_intent": "",
                "scene": "none",
                "is_primary_kpi_included": False,
                "exclude_reason": "暂无问法样本",
                "snapshots": [],
            }
        ]
    return scenarios


def _html_esc(value: Any) -> str:
    text = str(value or "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _clip_text(value: Any, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _fmt_pct_or_dash(value: Any) -> str:
    if value is None:
        return "暂无"
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "暂无"


def _fmt_num_or_dash(value: Any) -> str:
    if value is None:
        return "暂无"
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return "暂无"


def _render_all_priority_html(priority_items: list[dict[str, Any]]) -> str:
    """方案 A 切回全平台时还原 priority-band 的 HTML 快照。"""
    parts: list[str] = []
    for item in priority_items or []:
        if not isinstance(item, dict):
            continue
        parts.append(
            '<article class="priority-item">'
            f'<div class="priority-top"><span class="priority-level {_html_esc(item.get("level_class"))}">'
            f'{_html_esc(item.get("level"))}</span>'
            f'<span class="status-pill {_html_esc(item.get("tone"))}">{_html_esc(item.get("tone_label"))}</span></div>'
            f'<h3>{_html_esc(item.get("title"))}</h3><p>{_html_esc(item.get("body"))}</p></article>'
        )
    return "".join(parts)


def _looks_geo_drift(text: str) -> bool:
    """答法落到无地铁/错误县域，而非全国或目标城短名单。"""
    t = text or ""
    needles = (
        "暂无地铁",
        "没有地铁",
        "本地不存在",
        "暂无明确的地铁",
        "本地替代方案",
        "定西",
        "和田",
        "本地模拟",
    )
    return any(n in t for n in needles)


def _looks_same_name_steal(text: str, brand: str) -> bool:
    """首段落到同名其它主体（动漫/游戏等），目标控股/主品牌被挤后。"""
    t = text or ""
    head = t[:140]
    # 桌面豆包：括号/首段直接落到南京动漫或游戏美术
    steal_heads = (
        "南京艾迪亚数字娱乐",
        "南京艾迪亚动漫",
        "游戏美术CG",
        "两家重名公司",
    )
    return any(s in head for s in steal_heads)


def _looks_subject_locked(text: str, brand: str) -> bool:
    """已点名目标主体为最核心，不宜再标同名先拆。"""
    t = text or ""
    b = (brand or "").strip()
    cues = (
        "最核心的是",
        "最活跃、最核心",
        "全称：艾迪亚控股",
        "老牌营销科技集团",
        "以下是主要公司",
        "两大领域",
    )
    if any(c in t for c in cues):
        return True
    if b and f"最核心的是{b}" in t:
        return True
    return False


def _looks_same_name_split(text: str) -> bool:
    t = text or ""
    return any(
        tok in t
        for tok in (
            "两家",
            "多家",
            "不止一个",
            "不是唯一",
            "先看具体是哪一家",
            "重名",
            "分别梳理",
            "业务完全不一样",
            "业务差异很大",
            "您可能指的是",
        )
    )


def _looks_classify_frame(text: str) -> bool:
    t = text or ""
    return any(
        tok in t
        for tok in (
            "分为",
            "可分",
            "按资源",
            "资源归属",
            "全国头部",
            "官方独家",
            "本地独家",
            "整合代理",
            "三类",
            "两类",
            "不同模式对应",
            "全国多城联动",
        )
    )


def _looks_auth_frame(text: str) -> bool:
    t = text or ""
    return any(
        tok in t
        for tok in ("独家经营", "一手代理", "一手资源", "官方直签", "官方/一手", "授权运营", "资源授权")
    )


def _looks_survey_pack(text: str) -> bool:
    t = text or ""
    return any(
        tok in t
        for tok in (
            "行业调研",
            "最新调研",
            "根据20",
            "年度调研",
            "调研，我为您整理",
            "以下是20",
            "年国内",
        )
    )


def _looks_demand_split(text: str) -> bool:
    t = text or ""
    return any(
        tok in t
        for tok in ("取决于你的具体需求", "你的需求通常分为以下", "需求通常分为")
    )


def _quote_tag_and_diag(
    *,
    brand: str,
    rank: int,
    is_brand: bool,
    summary: str,
) -> tuple[str, str]:
    """2026-08-20 - 对齐桌面 G：弱=未进/≥6/地域跑偏，中=4–5，强=前三+结构标签。"""
    text = summary or ""
    # 地域跑偏优先于位次（桌面通义 rank=0/11 仍标地域跑偏）
    if _looks_geo_drift(text):
        extra = ""
        if not is_brand and rank <= 0 and brand and brand not in text:
            extra = "且未提及品牌。"
        return "地域跑偏", f"把投放需求落到错误地域，没有全国/目标城短名单。{extra}".rstrip()

    if is_brand:
        steal = _looks_same_name_steal(text, brand)
        split = _looks_same_name_split(text)
        locked = _looks_subject_locked(text, brand)
        # 目录式介绍（两大领域/主要公司）不算抢戏
        if steal and not locked:
            return "同名抢戏", "首段落到同名其它主体，目标主体被挤到后面。"
        if split and not locked:
            return "同名先拆", "先拆同名主体再评价，可引用但缺适用谁/不适合谁。"

    if rank <= 0:
        return "未进入推荐", "该问法×平台未进入推荐，优先补权威答案与证据。"
    if rank >= 6:
        return "位次偏弱", f"第 {rank} 名：进了候选但位次偏后，需补强对比与案例。"
    if rank >= 4:
        return "未进前三", f"第 {rank} 名：进了候选池但未进前三。"

    # 强档：分类框架优先于需求三分/授权（桌面同款优先序）
    if _looks_classify_frame(text):
        return "分类框架", f"已进前三（第 {rank} 名）。按资源类型分档，结构可摘抄。"
    if _looks_demand_split(text):
        return "需求三分", f"已进前三（第 {rank} 名）。按投放范围拆服务商。"
    if _looks_auth_frame(text):
        return "授权口径", f"已进前三（第 {rank} 名）。核心判断是官方/一手资源。"
    if _looks_survey_pack(text):
        return "调研包装", f"已进前三（第 {rank} 名）。年度调研口吻列名单，素材可用但要核验时效表述。"
    return "已进前三", f"已进前三（第 {rank} 名）。"


def _pick_snapshot_for_col(item: dict[str, Any], col: int, slot_key: str) -> dict[str, Any]:
    snaps = item.get("snapshots") if isinstance(item.get("snapshots"), list) else []
    for snap in snaps:
        if isinstance(snap, dict) and str(snap.get("slot") or "") == slot_key:
            return snap
    if 0 <= col < len(snaps) and isinstance(snaps[col], dict):
        return snaps[col]
    return {}


def _build_platform_quotes(
    scenarios: list[dict[str, Any]],
    *,
    brand: str,
    col: int,
    slot_key: str,
) -> list[dict[str, Any]]:
    quotes: list[dict[str, Any]] = []
    for item in scenarios or []:
        if not isinstance(item, dict):
            continue
        values = item.get("values") if isinstance(item.get("values"), list) else []
        if col < 0 or col >= len(values):
            continue
        try:
            rank = int(values[col] or 0)
        except (TypeError, ValueError):
            rank = 0
        snap = _pick_snapshot_for_col(item, col, slot_key)
        summary = str(snap.get("answer_summary") or "")
        is_brand = bool(item.get("is_brand_query"))
        tag, diag = _quote_tag_and_diag(
            brand=brand, rank=rank, is_brand=is_brand, summary=summary
        )
        mentioned = bool(snap.get("mentioned")) if "mentioned" in snap else rank > 0
        quotes.append(
            {
                "q": str(item.get("question") or ""),
                "rank": rank,
                "brand": is_brand,
                "txt": "未进入推荐" if rank <= 0 else f"第 {rank} 名",
                "mentioned": mentioned,
                "quote": _clip_text(summary or "（无文本摘要）", 180),
                "diag": diag,
                "tag": tag,
            }
        )
    return quotes


def _quote_severity(q: dict[str, Any]) -> int:
    """选主标签：地域/未进/同名抢戏 > 未进前三/同名先拆 > 结构强档。"""
    tag = str(q.get("tag") or "")
    rank = int(q.get("rank") or 0)
    if tag == "地域跑偏":
        return 6
    if tag in {"未进入推荐", "位次偏弱"} or rank <= 0 or rank >= 6:
        return 5
    if tag == "同名抢戏":
        return 5
    if tag == "未进前三" or 4 <= rank <= 5:
        return 4
    if tag == "同名先拆":
        return 4
    return 1 if tag else 0


def _bucket_quote_strength(quotes: list[dict[str, Any]]) -> tuple[int, int, int, dict[str, Any] | None]:
    weak = mid = strong = 0
    worst: dict[str, Any] | None = None
    worst_score = -1
    for q in quotes:
        rank = int(q.get("rank") or 0)
        tag = str(q.get("tag") or "")
        if not bool(q.get("brand")):
            # 2026-08-20 - 桌面 G：弱含地域跑偏；中=4–5；强=前三
            if tag == "地域跑偏" or rank <= 0 or rank >= 6:
                weak += 1
            elif rank >= 4:
                mid += 1
            else:
                strong += 1
        score = _quote_severity(q)
        if score > worst_score:
            worst_score = score
            worst = q
    if worst is None and quotes:
        worst = quotes[0]
    return weak, mid, strong, worst


def _build_one_platform_view(
    *,
    brand: str,
    slot_key: str,
    col: int,
    plat_name: str,
    plat_kpi: dict[str, Any],
    stage_copy: dict[str, Any],
    scenarios: list[dict[str, Any]],
    risk_rows: list[dict[str, Any]],
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    # 2026-08-20 - 对齐换皮版-G：标签/英雄标题/四阶段摘要与桌面同结构，规则派生不贴样例
    quotes = _build_platform_quotes(scenarios, brand=brand, col=col, slot_key=slot_key)
    weak, mid, strong, worst = _bucket_quote_strength(quotes)
    vis = plat_kpi.get("visibility")
    rank = plat_kpi.get("rank")
    decision = plat_kpi.get("decision")
    brand_defense = plat_kpi.get("brand_defense")
    main_tag = str((worst or {}).get("tag") or "监测切片")
    worst_q = str((worst or {}).get("q") or "")
    worst_diag = str((worst or {}).get("diag") or "")
    worst_quote = str((worst or {}).get("quote") or "")
    worst_rank = int((worst or {}).get("rank") or 0)

    if main_tag == "地域跑偏":
        hero_title = f"{plat_name}：答法跑偏，<span>先纠地域</span>"
        hero_focus = "答法纠偏"
    elif main_tag == "同名抢戏":
        hero_title = f"{plat_name}：获客已稳，<span>主体被抢戏</span>"
        hero_focus = "主体"
    elif main_tag == "同名先拆":
        hero_title = f"{plat_name}：获客已稳，<span>先拆同名再评价</span>"
        hero_focus = "主体边界"
    elif mid > 0 or main_tag == "未进前三":
        hero_title = f"{plat_name}：进了池子，<span>还差前三</span>"
        hero_focus = "冲前三"
    elif weak > 0:
        hero_title = f"{plat_name}：答法有缺口，<span>先补弱问法</span>"
        hero_focus = "答法纠偏"
    else:
        hero_title = f"{plat_name}：获客已稳，<span>巩固前三</span>"
        hero_focus = "巩固优势"

    acq_quotes = [q for q in quotes if not q.get("brand")]
    brand_quotes = [q for q in quotes if q.get("brand")]

    def _stage_label(key: str, fallback: str) -> str:
        row = stage_copy.get(key) if isinstance(stage_copy.get(key), dict) else {}
        return str(row.get("label") or fallback)

    if weak > 0 or mid > 0:
        weak_bits = []
        for q in acq_quotes:
            r = int(q.get("rank") or 0)
            if r <= 0 or r >= 4 or str(q.get("tag")) == "地域跑偏":
                weak_bits.append(f"{q.get('q')} {q.get('txt')}")
        selection_summary = (
            f"本平台非品牌均排 {_fmt_num_or_dash(rank)}、Top3 {_fmt_pct_or_dash(decision)}%。"
            + (
                f"短板问法：{'；'.join(weak_bits[:3])}。"
                if weak_bits
                else "非品牌问法仍有缺口，优先补权威短名单。"
            )
        )
    else:
        selection_summary = (
            f"本平台非品牌均排 {_fmt_num_or_dash(rank)}、Top3 {_fmt_pct_or_dash(decision)}%。"
            "非品牌问法均在前三，重点看答法是否可复制。"
        )

    def _brand_stage_summary(prefer_tags: tuple[str, ...] | None = None) -> str:
        pool = brand_quotes or quotes
        pick = None
        if prefer_tags:
            for q in pool:
                if str(q.get("tag") or "") in prefer_tags:
                    pick = q
                    break
        pick = pick or (pool[0] if pool else None)
        if not pick:
            return f"{plat_name} 暂无品牌词原话切片。"
        return (
            f"「{pick.get('q')}」{pick.get('txt')}。"
            f"{pick.get('diag') or ''} 摘录：「{_clip_text(pick.get('quote') or '', 100)}」"
        )

    procurement_bits = [
        f"「{q.get('q')}」{q.get('txt')}（{_clip_text(q.get('diag') or '', 40)}）"
        for q in acq_quotes[:3]
    ]
    stages: dict[str, Any] = {
        "all": {
            "label": "总览",
            "title": hero_title,
            "summary": (
                f"{plat_name} 获客 {_fmt_pct_or_dash(vis)}，均排 {_fmt_num_or_dash(rank)}，"
                f"Top3 {_fmt_pct_or_dash(decision)}。关键在「{worst_q}」[{main_tag}]："
                f"{worst_diag} 原话：「{_clip_text(worst_quote, 120)}」"
                if worst_q
                else (
                    f"{plat_name} 获客 {_fmt_pct_or_dash(vis)}，均排 {_fmt_num_or_dash(rank)}，"
                    f"Top3 {_fmt_pct_or_dash(decision)}。"
                )
            ),
        },
        "recognition": {
            "label": _stage_label("recognition", "品牌认知"),
            "title": f"{plat_name} · 品牌词怎么被介绍",
            "summary": _brand_stage_summary(("同名抢戏", "同名先拆", "已进前三")),
        },
        "selection": {
            "label": _stage_label("selection", "竞品对标"),
            "title": f"{plat_name} · 同框席位",
            "summary": selection_summary,
        },
        "procurement": {
            "label": _stage_label("procurement", "推荐名单"),
            "title": f"{plat_name} · 进名单质量",
            "summary": " ".join(procurement_bits) if procurement_bits else selection_summary,
        },
        "risk": {
            "label": _stage_label("risk", "口碑评价"),
            "title": f"{plat_name} · 评价可引用性",
            "summary": _brand_stage_summary(("同名抢戏", "同名先拆", "调研包装")),
        },
    }

    if main_tag == "地域跑偏" and worst_q:
        p0_title = f"纠正 {plat_name}「{worst_q}」的地域幻觉"
        p0_body = (
            f"【诊断】{worst_diag} 【原话】{_clip_text(worst_quote, 140)} "
            "【交付】全国/目标城短名单首段，禁止落到未开通地铁的城市。"
        )
    elif main_tag == "同名抢戏":
        p0_title = f"锁 {plat_name} 上的「{brand}」主体"
        p0_body = (
            f"【诊断】{worst_diag} 【原话】{_clip_text(worst_quote, 140)} "
            "【交付】百科/官网首段先写目标主体，易混淆主体放到附录。"
        )
    elif main_tag == "同名先拆":
        p0_title = f"给 {plat_name} 可引用的主体+边界"
        p0_body = (
            f"【诊断】{worst_diag} 【原话】{_clip_text(worst_quote, 140)} "
            "【交付】适用谁/不适合谁/证据一次写齐。"
        )
    elif main_tag == "未进前三" and worst_q:
        p0_title = f"把 {plat_name}「{worst_q}」从第 {worst_rank} 名推进前三"
        p0_body = (
            f"【诊断】{worst_diag} 【原话】{_clip_text(worst_quote, 140)} "
            "【交付】补「哪家好」决策段，不要停在行业综述。"
        )
    elif worst_q:
        p0_title = f"治理 {plat_name}「{worst_q}」"
        p0_body = (
            f"【诊断】{worst_diag} 【原话】{_clip_text(worst_quote, 140)} "
            "【交付】针对本平台原话改首段，完稿即验收。"
        )
    else:
        p0_title = f"巩固 {plat_name} 获客位次"
        p0_body = (
            f"【结论】{plat_name} 获客 {_fmt_pct_or_dash(vis)}。"
            "【交付】把可复制结构固化到官网权威页。"
        )

    priorities = [
        {
            "level": f"P0 · {hero_focus}",
            "level_class": "p0",
            "pill": "优先",
            "pill_class": "status-risk",
            "title": p0_title,
            "body": p0_body,
        },
        {
            "level": "P1 · 评价口径",
            "level_class": "p1",
            "pill": "一次写齐",
            "pill_class": "status-gap",
            "title": f"{plat_name} 侧评价口径一次写齐",
            "body": "【交付】适用谁 / 不适合谁 / 可核验证据 → FAQ + 百科。",
        },
        {
            "level": "P2 · 范围",
            "level_class": "p2",
            "pill": "本视图",
            "pill_class": "status-ok",
            "title": f"本页只治理 {plat_name}",
            "body": f"【证据】弱 {weak} / 中 {mid} / 强 {strong}。【交付】达标后再扩槽位。",
        },
    ]

    plat_risks = [
        r
        for r in (risk_rows or [])
        if isinstance(r, dict) and plat_name in str(r.get("models") or "")
    ]
    if not plat_risks and worst_q:
        plat_risks = [
            {
                "topic": f"{plat_name} · {worst_q} · {main_tag}",
                "models": plat_name,
                "impact": (
                    "丢短名单 / 位次不够"
                    if not (worst or {}).get("brand")
                    else "主体被抢 / 评价不可引用"
                ),
                "evidence": f"{worst_diag} 原话：{_clip_text(worst_quote, 160)}",
                "priority": "P0" if weak or main_tag in {"地域跑偏", "同名抢戏"} else "P1",
                "pill": "risk-high" if weak or main_tag in {"地域跑偏", "同名抢戏"} else "risk-medium",
            }
        ]

    plat_actions = [
        a
        for a in (actions or [])
        if isinstance(a, dict) and plat_name in str(a.get("title") or "") + str(a.get("body") or "")
    ]
    if not plat_actions:
        plat_actions = [
            {
                "level": "P0 · 0–30 天",
                "level_class": "p0",
                "impact": main_tag,
                "title": priorities[0]["title"],
                "body": worst_diag or f"巩固 {plat_name} 表现",
                "bullets": ["针对本平台原话改首段", "完稿即验收", "不以全平台复测为门禁"],
            },
            {
                "level": "P1 · 0–30 天",
                "level_class": "p1",
                "impact": "评价",
                "title": "评价口径一次交付",
                "body": "FAQ + 百科",
                "bullets": ["适用谁", "不适合谁", "证据"],
            },
            {
                "level": "P2 · 31–60 天",
                "level_class": "p2",
                "impact": "扩平台",
                "title": f"{plat_name} 达标后分发",
                "body": "对照弱平台问法逐条替换",
                "bullets": ["弱平台对照表", "分发节奏"],
            },
        ]

    return {
        "name": plat_name,
        "col": col,
        "stages": stages,
        "priorities": priorities,
        "risks": plat_risks,
        "actions": plat_actions,
        "quotes": quotes,
        "insights": [
            {
                "title": f"{plat_name} 获客",
                "score": _fmt_pct_or_dash(vis),
                "body": (
                    f"均排 {_fmt_num_or_dash(rank)} · Top3 {_fmt_pct_or_dash(decision)} · "
                    f"弱{weak} 中{mid} 强{strong}"
                ),
            },
            {
                "title": f"{plat_name} 主标签",
                "score": main_tag,
                "body": worst_diag or "本平台暂无突出缺口标签。",
            },
            {
                "title": f"{plat_name} 品牌防守",
                "score": _fmt_pct_or_dash(brand_defense),
                "body": "格级品牌词防守提及率（不计入获客主 KPI）。",
            },
        ],
        "evidence_chips": [
            f"{plat_name} 获客 {_fmt_pct_or_dash(vis)}",
            f"均排 {_fmt_num_or_dash(rank)}",
            f"Top3 {_fmt_pct_or_dash(decision)}",
            f"防守 {_fmt_pct_or_dash(brand_defense)}",
        ],
        "gap_note": (
            f"{plat_name} 视图：主标签「{main_tag}」。弱{weak} / 中{mid} / 强{strong}。"
            "负面关联与信源引用无平台切片，本页不展示。"
        ),
        "platforms_title": f"本平台差距：{plat_name}",
        "platforms_sub": f"五平台对比条已隐藏（属全平台视图）。以下仅 {plat_name} 获客对标。",
        "diagnosis_title": f"问法×{plat_name}：推荐位与原话诊断",
        "diagnosis_sub": "热力只保留本平台列；问法原话见上方摘录，不重复做卡片。",
        "brand": brand,
    }


def build_platform_views(
    *,
    brand: str,
    platform_rows: list[dict[str, Any]],
    platform_data: dict[str, Any],
    stage_copy: dict[str, Any],
    scenarios: list[dict[str, Any]],
    risk_rows: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    evidence_chips: list[str],
    gap_note: str,
    priority_items: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    """2026-08-20 - 方案 A 平台切片：由格级 KPI + scenarios 原话派生 platformViews，禁止贴桌面样例。"""
    views: dict[str, Any] = {
        "all": {
            "name": "全平台",
            "col": -1,
            "restore": True,
            "stages": stage_copy or {},
            "evidence_chips": list(evidence_chips or []),
            "gap_note": gap_note or "",
        }
    }
    for col, row in enumerate(platform_rows or []):
        if not isinstance(row, dict):
            continue
        slot_key = str(row.get("key") or "").strip()
        if not slot_key:
            continue
        plat_kpi = platform_data.get(slot_key) if isinstance(platform_data.get(slot_key), dict) else {}
        plat_name = str(plat_kpi.get("name") or row.get("name") or slot_key)
        views[slot_key] = _build_one_platform_view(
            brand=brand,
            slot_key=slot_key,
            col=col,
            plat_name=plat_name,
            plat_kpi=plat_kpi,
            stage_copy=stage_copy or {},
            scenarios=scenarios or [],
            risk_rows=risk_rows or [],
            actions=actions or [],
        )
    return views, _render_all_priority_html(priority_items or [])


# 2026-08-13 - A+B+C：单平台禁写未测=0；管理层摘要规则兜底；壳文案随模式
# 2026-08-13 - scope-v2：强弱举例剔品牌词；客户摘要勿复述模型硬约束句
# 2026-08-13 - scope-v3：接入品牌诊断分层提示词（事实→口径→判断→建议）
# 2026-08-13 - scope-v5：全品牌词主 KPI 禁回填；risks/actions 进 cockpit_json
# 2026-08-13 - scope-v7：A+ 格级 kpi_basis；样本级仅稳定性观察
COCKPIT_NARRATIVE_SCHEMA = "scope-v8"  # 2026-08-13 - 意图样本+平台均排进事实包后重生叙事，避免旧包写无样本



def _platform_names_from_rows(platform_rows: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for row in platform_rows or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def build_platform_scope_note(platform_rows: list[dict[str, Any]], *, for_model: bool = False) -> str:
    names = _platform_names_from_rows(platform_rows)
    if not names:
        if for_model:
            return "本窗暂无平台样本。禁止点名任何平台「提及率为 0」；未监测≠表现差。"
        return "本窗暂无平台样本。"
    if len(names) == 1:
        if for_model:
            return (
                f"本窗仅监测 {names[0]}。结论仅对该平台成立。"
                "未出现在监测列表中的平台=未监测，禁止写成提及率 0 或「覆盖缺口」。"
                "扩展其它平台只能作为后续建议，不得当作本窗已测结论。"
            )
        # 2026-08-13 - 客户文案勿复述模型硬约束口吻
        return f"本窗仅监测 {names[0]}，结论仅对该平台成立。"
    joined = "、".join(names)
    if for_model:
        return (
            f"本窗监测平台：{joined}。只能评价上述平台；"
            "未列出的平台=未监测，禁止写成提及率 0 或覆盖缺口。"
        )
    return f"本窗监测平台：{joined}。"


def _acquisition_prompt_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """主口径举例只用非品牌词获客；品牌词不进提及率/排名叙事。"""
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("prompt"):
            continue
        lane = str(row.get("lane") or "").strip()
        if lane == "brand_defense" or row.get("is_brand_word") is True:
            continue
        if lane and lane != "acquisition":
            continue
        # lane 缺失时：若显式 brand 标记已排除，其余视为获客池（兼容旧 facts）
        out.append(row)
    return out


def _lane_metric_block(pool: list[dict[str, Any]]) -> dict[str, Any]:
    """分口径指标；无样本时字段为 None，文案侧写「暂无数据」。"""
    if not pool:
        return {
            "prompt_count": 0,
            "mention_rate": None,
            "avg_rank": None,
            "top3_rate": None,
        }
    ranks = [p["brand_avg_rank"] for p in pool if _f(p.get("brand_avg_rank"), 0.0) > 0]
    return {
        "prompt_count": len(pool),
        "mention_rate": _avg([p["brand_mention_rate"] for p in pool]),
        "avg_rank": _avg(ranks) if ranks else None,
        "top3_rate": _top3_rate_from_prompt_ranks(pool),
    }


def _top3_rate_from_prompt_ranks(pool: list[dict[str, Any]]) -> float | None:
    """回退：无热力矩阵时，用问法 brand_avg_rank 估算 Top3。"""
    if not pool:
        return None
    hit = 0
    for p in pool:
        rank = _heat_rank_value(p.get("brand_avg_rank"))
        if 1 <= rank <= 3:
            hit += 1
    return round(100.0 * hit / len(pool), 1)


def _top3_rate_from_matrix(
    acquisition: list[dict[str, Any]],
    matrix_rows: list[dict[str, Any]],
    slots: list[str],
) -> float | None:
    """非品牌词 Top3：与热力图同口径（问法×平台格，1–3 为命中；—/0 计未进前三）。

    2026-08-13 - PA 跨日均排与热力格不一致时曾算 66.7% 而热力只有 1/3 - 改吃 matrix
    """
    if not acquisition:
        return None
    prompts = {
        str(p.get("prompt") or "").strip()
        for p in acquisition
        if str(p.get("prompt") or "").strip()
    }
    if not prompts:
        return None
    slot_set = {str(s).strip() for s in (slots or []) if str(s).strip()}
    cells: list[int] = []
    seen: set[tuple[str, str]] = set()
    for row in matrix_rows or []:
        if not isinstance(row, dict):
            continue
        prompt = str(row.get("prompt") or "").strip()
        slot = _canonical_platform(str(row.get("platform") or ""))
        if not prompt or prompt not in prompts:
            continue
        if slot_set and slot not in slot_set:
            continue
        key = (prompt, slot)
        if key in seen:
            continue
        seen.add(key)
        cells.append(_heat_rank_value(row.get("avg_rank")))
    if not cells:
        return _top3_rate_from_prompt_ranks(acquisition)
    hit = sum(1 for rank in cells if 1 <= rank <= 3)
    return round(100.0 * hit / len(cells), 1)


def _top3_rate_from_matrix_slot(
    acquisition: list[dict[str, Any]],
    matrix_rows: list[dict[str, Any]],
    slot: str,
) -> float | None:
    """分平台非品牌词 Top3：仅该平台热力格。"""
    return _top3_rate_from_matrix(acquisition, matrix_rows, [slot])


def _fmt_metric(value: Any, *, suffix: str = "") -> str:
    if value is None or value == "":
        return "暂无数据"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "暂无数据"
    if suffix == "%":
        return f"{num:.1f}%"
    return f"{num:.1f}{suffix}"


def platform_version_tag(platform_labels: list[str]) -> str:
    """导出文件名/标题用：ChatGPT单平台 / 豆包+ChatGPT综合。"""
    labels = [str(x).strip() for x in (platform_labels or []) if str(x).strip()]
    if not labels:
        return "未标注平台"
    if len(labels) == 1:
        return f"{labels[0]}单平台"
    return f"{'+'.join(labels)}综合"


def _prompt_cell_metrics(
    prompt: str,
    matrix_rows: list[dict[str, Any]],
    slots: list[str],
) -> tuple[float | None, float | None]:
    """单问法格级提及率/均排（跨已监测平台）。无格时返回 (None, None)。"""
    prompt = str(prompt or "").strip()
    if not prompt or not slots:
        return None, None
    cell = _matrix_cell_map(matrix_rows)
    total = 0
    mention = 0
    ranks: list[float] = []
    for slot in slots:
        total += 1
        rank = int(cell.get((prompt, str(slot)), 0) or 0)
        if rank > 0:
            mention += 1
            ranks.append(float(rank))
    if total <= 0:
        return None, None
    rate = round(100.0 * mention / total, 1)
    avg = round(sum(ranks) / len(ranks), 1) if ranks else None
    return rate, avg


def _prompt_display_rate(row: dict[str, Any]) -> float:
    """主口径排序/举例：优先格级，缺省再回退样本。"""
    if row.get("cell_mention_rate") is not None:
        return _f(row.get("cell_mention_rate"), 0.0)
    return _f(row.get("brand_mention_rate"), 0.0)


def _prompt_display_rank(row: dict[str, Any]) -> float | None:
    if row.get("cell_avg_rank") is not None:
        val = _f(row.get("cell_avg_rank"), 0.0)
        return val if val > 0 else None
    val = _f(row.get("brand_avg_rank"), 0.0)
    return val if val > 0 else None


def diagnosis_export_title(brand: str, platform_labels: list[str]) -> str:
    """售前诊断导出标题/文件名：品牌_平台版本_售前品牌诊断报告。"""
    name = str(brand or "").strip() or "品牌"
    return f"{name}_{platform_version_tag(platform_labels)}_售前品牌诊断报告"


def _kpi_prompt_examples(tagged: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """强弱问法举例：只取非品牌词获客池；数字用格级提及率。

    2026-08-21 - 举例曾吃样本 brand_mention_rate，与主 KPI 打架 - 改吃 cell_*
    """
    pool = [p for p in tagged if p.get("lane") == "acquisition"] or []
    # 无获客问法时不强行用品牌词充数（避免误导主口径）
    weak = [
        {
            "prompt": p["prompt"],
            "mention_rate": _prompt_display_rate(p),
            "avg_rank": _prompt_display_rank(p),
            "answer_hit_rate": _f(p.get("brand_mention_rate"), 0.0),
            "lane": p.get("lane"),
            "is_brand_word": bool(p.get("is_brand_word")),
            "basis": "question_platform_cell",
        }
        for p in sorted(pool, key=_prompt_display_rate)[:6]
    ]
    strong = [
        {
            "prompt": p["prompt"],
            "mention_rate": _prompt_display_rate(p),
            "avg_rank": _prompt_display_rank(p),
            "answer_hit_rate": _f(p.get("brand_mention_rate"), 0.0),
            "lane": p.get("lane"),
            "is_brand_word": bool(p.get("is_brand_word")),
            "basis": "question_platform_cell",
        }
        for p in sorted(pool, key=lambda x: -_prompt_display_rate(x))[:4]
    ]
    return weak, strong


def build_rule_all_summary(
    *,
    brand: str,
    visibility: float | None,
    rank: float | None,
    decision: float | None,
    negative: float | None,
    platform_rows: list[dict[str, Any]],
    weak_prompts: list[dict[str, Any]] | None = None,
    strong_prompts: list[dict[str, Any]] | None = None,
    filter_mode: str = "intent",
    has_acquisition_kpi: bool = True,
    brand_defense_rate: float | None = None,
) -> str:
    """单平台（或需兜底）时的管理层摘要：只谈已测事实 + 非品牌词问法。"""
    names = _platform_names_from_rows(platform_rows)
    plat = names[0] if len(names) == 1 else ("、".join(names) if names else "已监测平台")
    if not has_acquisition_kpi:
        # 2026-08-13 - 全品牌词样本不得回填获客主 KPI
        bd = _fmt_metric(brand_defense_rate, suffix="%")
        parts = [
            f"本窗基于 {plat} 监测样本，但问法全部为品牌词，非品牌词获客样本数为 0，"
            f"无法评估自然获客可见度。非品牌词获客提及率 / 平均推荐位 / Top3 率均为暂无数据。",
            f"本次样本只能评估品牌防守（品牌词防守提及率 {bd}），不能评估自然获客可见度。",
        ]
        if len(names) == 1:
            parts.append(f"以上结论仅适用于 {plat}。")
        return "".join(parts)
    rank_txt = _fmt_metric(rank)
    axis = "意图" if filter_mode == "intent" else "场景"
    strong_pool = _acquisition_prompt_rows(strong_prompts)
    weak_pool = _acquisition_prompt_rows(weak_prompts)
    strong = strong_pool[0] if strong_pool else None
    weak = weak_pool[0] if weak_pool else None
    parts = [
        f"本窗基于 {plat} 监测样本（主口径为非品牌词获客）：{brand} 提及率约 {_fmt_metric(visibility, suffix='%')}，"
        f"均排约 {rank_txt}，Top3 露出约 {_fmt_metric(decision, suffix='%')}，负面关联约 {_fmt_metric(negative, suffix='%')}。"
    ]
    if strong and weak and strong.get("prompt") != weak.get("prompt"):
        parts.append(
            f"非品牌词问法中，相对更好的如「{strong.get('prompt')}」（提及约 {strong.get('mention_rate')}%），"
            f"短板如「{weak.get('prompt')}」（提及约 {weak.get('mention_rate')}%），"
            f"应优先补齐{axis}证据与可引用口径。"
        )
    elif weak:
        parts.append(f"非品牌词短板问法如「{weak.get('prompt')}」，应优先补齐{axis}证据。")
    elif strong:
        parts.append(
            f"非品牌词问法中「{strong.get('prompt')}」表现相对更好（提及约 {strong.get('mention_rate')}%）。"
        )
    # 2026-08-13 - 有均排却无 Top3 时须说明，避免客户追问
    if rank is not None and decision is None:
        parts.append("当前排名明细不足，暂不计算 Top3 率。")
    if len(names) == 1:
        parts.append(f"以上结论仅适用于 {plat}。")
    return "".join(parts)


def _ensure_top3_gap_in_summary(
    summary: str,
    *,
    rank: float | None,
    decision: float | None,
    has_acquisition_kpi: bool,
) -> str:
    """有均排、无 Top3 时在摘要补一句原因。"""
    text = str(summary or "").strip()
    if not has_acquisition_kpi:
        return text
    if rank is None or decision is not None:
        return text
    if "暂不计算 Top3" in text:
        return text
    return text + "当前排名明细不足，暂不计算 Top3 率。"


def build_rule_all_title(
    *,
    brand: str,
    platform_rows: list[dict[str, Any]],
    visibility: float | None,
    has_acquisition_kpi: bool = True,
) -> str:
    names = _platform_names_from_rows(platform_rows)
    plat = names[0] if len(names) == 1 else "已监测平台"
    if not has_acquisition_kpi:
        return f"{brand}本窗仅有品牌词样本，获客主 KPI<span>暂无数据</span>"
    return f"{brand}在 {plat} 非品牌词提及率 {_fmt_metric(visibility, suffix='%')}，仍有<span>提升空间</span>"


def _full_sample_negative_rate(
    sentiment: dict[str, Any] | None,
    *,
    completed_count: int | None = None,
) -> tuple[float | None, int, int]:
    """全样本负面率：neg / 完成样本（含 unknown）。

    2026-08-14 - 方案 B：弃用「仅已标注」分母（曾把 24/270 算成 24/30≈80%）
    """
    raw = sentiment if isinstance(sentiment, dict) else {}
    pos = int(_f(raw.get("positive"), 0.0))
    neu = int(_f(raw.get("neutral"), 0.0))
    neg = int(_f(raw.get("negative"), 0.0))
    unk = int(_f(raw.get("unknown"), 0.0))
    total = int(completed_count or 0) or (pos + neu + neg + unk)
    if total <= 0:
        return None, neg, 0
    return round(100.0 * neg / total, 1), neg, total


def _reputation_high_risk(
    *,
    sample_n: int,
    negative_rate: float | None,
    positive_rate: float | None = None,
) -> bool:
    """全样本负面偏高才判口碑高风险；禁止再用标注子集虚高比例。

    2026-08-14 - 与方案 B 对齐：阈值看 neg/N，不是 neg/(N-unknown)
    """
    if sample_n >= 20 and negative_rate is not None and negative_rate >= 40.0:
        return True
    # 全样本负面已明显偏高时，即使样本略少也门禁「口碑正面」
    if sample_n >= 10 and negative_rate is not None and negative_rate >= 50.0:
        return True
    _ = positive_rate  # 保留参数兼容调用方；正面率另有 KPI，不在此混算负面
    return False


_REPUTATION_POSITIVE_CLAIM_RE = re.compile(
    r"口碑正面|舆情(?:风险)?极低|正面情绪占比\s*高|口碑(?:整体)?良好|口碑与风险可控"
)


def _blob_claims_reputation_positive(blob: Any) -> bool:
    text = ""
    if isinstance(blob, dict):
        text = " ".join(str(blob.get(k) or "") for k in ("title", "summary", "label", "desc", "body"))
    else:
        text = str(blob or "")
    return bool(_REPUTATION_POSITIVE_CLAIM_RE.search(text))


def _sanitize_reputation_stage_copy(
    stage_copy: dict[str, Any],
    *,
    negative_rate: float | None,
    sample_n: int,
) -> dict[str, Any]:
    """全样本负面偏高时，改写风险阶段并剥掉正面口碑措辞。

    2026-08-14 - 文案分母与 KPI 同为全样本
    """
    out = dict(stage_copy or {})
    neg_txt = _fmt_metric(negative_rate, suffix="%") if negative_rate is not None else "偏高"
    risk_fallback = {
        "label": "风险质疑阶段",
        "title": "口碑风险偏高，需优先<span>核查负面关联</span>",
        "summary": (
            f"全样本 {sample_n} 条中，负面占比约 {neg_txt}。"
            f"与监测口径一致，应先核对负面来源与话术，再统一对外口径，勿再写成正面口碑。"
        ),
    }
    for key in ("all", "recognition", "selection", "procurement", "risk"):
        row = out.get(key)
        if not isinstance(row, dict):
            continue
        if key == "risk" or _blob_claims_reputation_positive(row):
            cleaned = dict(row)
            if key == "risk":
                cleaned = dict(risk_fallback)
                if row.get("label"):
                    cleaned["label"] = str(row.get("label") or cleaned["label"])
            else:
                for field in ("title", "summary"):
                    val = str(cleaned.get(field) or "")
                    if _REPUTATION_POSITIVE_CLAIM_RE.search(val):
                        cleaned[field] = _REPUTATION_POSITIVE_CLAIM_RE.sub("口碑风险需关注", val)
            out[key] = cleaned
    return out


_NONBRAND_REPUTATION_GAP_RE = re.compile(
    r"非品牌(?:词)?口碑(?:评价)?(?:无样本|样本(?:为\s*0|缺失|缺失)|格样本为\s*0)|"
    r"非品牌场景下的口碑|"
    r"无法评估自然口碑"
)

# 2026-08-21 - 认知页把「无品牌词防守」错绑成「无法评估口碑」
_RECOGNITION_REPUTATION_CROSS_RE = re.compile(
    r"无法评估(?:品牌)?口碑(?:和品牌(?:词)?排名)?|"
    r"无法全面评估口碑(?:风险)?|"
    r"评估品牌口碑和品牌(?:词)?排名"
)


def _intent_coverage_label(kpi_basis: dict[str, Any]) -> str:
    """顶部「覆盖」=本单已配置（有格）的意图，含提及率 0% 的意图。

    2026-08-21 - 曾按 mention>0 过滤，推荐名单 0% 时覆盖只剩「品牌认知」串台
    """
    intents = kpi_basis.get("intents") if isinstance(kpi_basis.get("intents"), dict) else {}
    parts: list[str] = []
    for code in _INTENT_CARD_ORDER:
        row = intents.get(code) if isinstance(intents.get(code), dict) else {}
        nb = row.get("nonbrand") if isinstance(row.get("nonbrand"), dict) else {}
        bd = row.get("brand") if isinstance(row.get("brand"), dict) else {}
        cells = int(nb.get("total_cells") or 0) + int(bd.get("total_cells") or 0)
        if cells <= 0:
            continue
        parts.append(str(INTENT_LABELS.get(code) or code))
    return " / ".join(parts) or "意图问法矩阵"


def _sanitize_recognition_defense_scope(stage_copy: dict[str, Any]) -> dict[str, Any]:
    """品牌认知阶段：无防守只能谈防守/点名可见度，禁止写成无法评估口碑。"""
    out = dict(stage_copy or {})
    row = out.get("recognition")
    if not isinstance(row, dict):
        return out
    cleaned = dict(row)
    changed = False
    for field in ("title", "summary"):
        val = str(cleaned.get(field) or "")
        if not val or not _RECOGNITION_REPUTATION_CROSS_RE.search(val):
            continue
        new_val = val
        new_val = re.sub(
            r"无法评估品牌口碑和品牌词排名",
            "无法评估品牌词防守提及与点名排名",
            new_val,
        )
        new_val = re.sub(
            r"无法评估品牌口碑和品牌排名",
            "无法评估品牌词防守提及与点名排名",
            new_val,
        )
        new_val = re.sub(r"无法评估品牌口碑", "无法评估品牌词防守表现", new_val)
        new_val = re.sub(r"无法评估口碑", "无法评估品牌词防守表现", new_val)
        new_val = re.sub(r"无法全面评估口碑风险", "口碑评价见对应页；本页聚焦认知与防守", new_val)
        new_val = re.sub(r"无法全面评估口碑", "口碑评价见对应页；本页聚焦认知与防守", new_val)
        new_val = re.sub(
            r"评估品牌口碑和品牌词排名",
            "评估品牌词防守提及与点名排名",
            new_val,
        )
        new_val = re.sub(
            r"评估品牌口碑和品牌排名",
            "评估品牌词防守提及与点名排名",
            new_val,
        )
        if new_val != val:
            cleaned[field] = new_val
            changed = True
    if changed:
        out["recognition"] = cleaned
    return out


def _sanitize_risk_nonbrand_reputation_gap(
    stage_copy: dict[str, Any],
    *,
    brand: str,
    kpi_basis: dict[str, Any],
) -> dict[str, Any]:
    """品牌词口碑已有格时，禁止把「非品牌口碑无样本」写成口碑阶段主结论。

    2026-08-21 - SAB 等单口碑问法本就是品牌防守；非品牌口碑格=0 是问法设计，不是监测失败
    """
    out = dict(stage_copy or {})
    risk = out.get("risk")
    if not isinstance(risk, dict):
        return out
    blob = f"{risk.get('title') or ''}{risk.get('summary') or ''}"
    if not _NONBRAND_REPUTATION_GAP_RE.search(blob):
        return out
    intents = kpi_basis.get("intents") if isinstance(kpi_basis.get("intents"), dict) else {}
    rep = intents.get("reputation") if isinstance(intents.get("reputation"), dict) else {}
    nb = rep.get("nonbrand") if isinstance(rep.get("nonbrand"), dict) else {}
    bd = rep.get("brand") if isinstance(rep.get("brand"), dict) else {}
    nb_cells = int(nb.get("total_cells") or 0)
    bd_cells = int(bd.get("total_cells") or 0)
    if bd_cells <= 0 or nb_cells > 0:
        return out
    mention = bd.get("mention_rate")
    rank = bd.get("avg_rank")
    mention_txt = _fmt_metric(mention, suffix="%")
    rank_txt = _fmt_metric(rank)
    out["risk"] = {
        "label": "口碑评价",
        "title": f"{brand}品牌词口碑已有样本，重点补<span>可引用评价口径</span>",
        "summary": (
            f"监测事实：本窗口碑问法落在品牌词防守（品牌格 {bd_cells}），"
            f"提及率 {mention_txt}，均排 {rank_txt}；本窗未配置不含品牌名的口碑问法。"
            "分析判断：应以品牌词口碑表现为主结论；未覆盖的问法类型不代表监测失败。"
            "优化建议：把适用谁/不适合谁与可核验证据写进官网与百科，便于模型稳定引用。"
        ),
    }
    return out


def apply_narrative_scope_guards(
    narrative: dict[str, Any],
    *,
    brand: str,
    facts: dict[str, Any],
) -> dict[str, Any]:
    """强制 stage.all 与当前 KPI null/0 对齐；全品牌词禁止回填获客数字。

    2026-08-13 - 多平台旧叙事把有分母的获客写成暂无 - 改为始终重写 all 摘要
    """
    out = dict(narrative)
    platform_rows = facts.get("platform_rows") or []
    kpis = facts.get("kpis") if isinstance(facts.get("kpis"), dict) else {}
    has_acq = bool(facts.get("has_acquisition_kpi", True))
    stage = dict(out.get("stage_copy") or {})
    all_row = dict(stage.get("all") or {})
    all_row["summary"] = build_rule_all_summary(
        brand=brand,
        visibility=kpis.get("visibility"),
        rank=kpis.get("rank"),
        decision=kpis.get("decision"),
        negative=_f(kpis.get("negative"), 0.0) if kpis.get("negative") is not None else 0.0,
        platform_rows=platform_rows if isinstance(platform_rows, list) else [],
        weak_prompts=facts.get("weak_prompts") if isinstance(facts.get("weak_prompts"), list) else [],
        strong_prompts=facts.get("strong_prompts") if isinstance(facts.get("strong_prompts"), list) else [],
        filter_mode=str(facts.get("filter_mode") or "intent"),
        has_acquisition_kpi=has_acq,
        brand_defense_rate=kpis.get("brand_defense") if "brand_defense" in kpis else facts.get("brand_defense_rate"),
    )
    all_row["title"] = build_rule_all_title(
        brand=brand,
        platform_rows=platform_rows if isinstance(platform_rows, list) else [],
        visibility=kpis.get("visibility"),
        has_acquisition_kpi=has_acq,
    )
    if not all_row.get("label"):
        all_row["label"] = "管理层摘要"
    stage["all"] = all_row
    # 2026-08-14 - 口碑叙事门禁：全样本负面偏高时禁止保留「口碑正面」
    sample_n = int(facts.get("sentiment_sample_n") or 0)
    neg_rate = facts.get("negative_rate")
    neg_rate_f = float(neg_rate) if neg_rate is not None else None
    if _reputation_high_risk(
        sample_n=sample_n,
        negative_rate=neg_rate_f,
        positive_rate=float(facts["positive_rate"]) if facts.get("positive_rate") is not None else None,
    ):
        stage = _sanitize_reputation_stage_copy(
            stage,
            negative_rate=neg_rate_f,
            sample_n=sample_n,
        )
    # 2026-08-20 - 有竞品共现命中时，禁止 selection 仍写「未见同框/未提供共现」
    stage = _sanitize_selection_competitor_copy(stage, facts=facts, brand=brand)
    # 2026-08-21 - 禁止格级提及率与样本回答命中率在同一段混写成同一口径
    stage = _sanitize_dual_metric_copy(stage, facts=facts)
    # 2026-08-21 - 认知页禁把「无品牌词防守」写成无法评估口碑
    stage = _sanitize_recognition_defense_scope(stage)
    out["stage_copy"] = stage
    rows = platform_rows if isinstance(platform_rows, list) else []
    if len(rows) <= 1:
        items = list(out.get("priority_items") or [])
        if len(items) >= 2 and isinstance(items[1], dict):
            p1 = dict(items[1])
            level = str(p1.get("level") or "")
            if "平台覆盖" in level:
                p1["level"] = "P1 · 问法补强"
            items[1] = p1
            out["priority_items"] = items
    # 2026-08-21 - 旧叙事包 priority 仍写「选型标准问法…」时渲染前 scrub
    out = _scrub_narrative_customer_copy(out)
    out["schema"] = COCKPIT_NARRATIVE_SCHEMA
    return out


def _sanitize_dual_metric_copy(
    stage: dict[str, Any],
    *,
    facts: dict[str, Any],
) -> dict[str, Any]:
    """把问法旁错误样本率改成格级；样本口径强制改称回答命中率。

    2026-08-21 - AI 易写「整体格级0% + 问法样本33%」同称提及率 - 按 facts 纠偏
    """
    out = dict(stage or {})
    rate_by_prompt: dict[str, float] = {}
    for key in ("weak_prompts", "strong_prompts"):
        for row in facts.get(key) or []:
            if not isinstance(row, dict):
                continue
            prompt = str(row.get("prompt") or "").strip()
            if not prompt or row.get("mention_rate") is None:
                continue
            try:
                rate_by_prompt[prompt] = float(row.get("mention_rate"))
            except (TypeError, ValueError):
                continue

    def _fix_text(text: str) -> str:
        s = str(text or "")
        if not s:
            return s
        s = s.replace("跨日样本提及率", "跨日回答命中率")
        s = s.replace("样本提及率", "回答命中率")
        # 具体问法后的「提及率 X%」对齐格级举例
        for prompt, rate in rate_by_prompt.items():
            if prompt not in s:
                continue
            needle = re.escape(prompt)
            s = re.sub(
                rf"({needle}[^。；\n]{{0,40}}?)提及率\s*\d+(?:\.\d+)?%",
                rf"\g<1>提及率{rate:.1f}%",
                s,
            )
        # 整体/非品牌格已给主数字时，禁止同句再塞「但整体…0」类自相矛盾尾巴
        s = re.sub(
            r"(提及率\s*\d+(?:\.\d+)?%[^。；\n]{0,40}?)，?但整体非品牌格提及率为\d+(?:\.\d+)?",
            r"\1",
            s,
        )
        return s

    for key, row in list(out.items()):
        if not isinstance(row, dict):
            continue
        fixed = dict(row)
        for field in ("title", "summary", "body"):
            if field in fixed and isinstance(fixed.get(field), str):
                fixed[field] = _fix_text(str(fixed.get(field) or ""))
        out[key] = fixed
    return out


def _sanitize_selection_competitor_copy(
    stage: dict[str, Any],
    *,
    facts: dict[str, Any],
    brand: str,
) -> dict[str, Any]:
    """有 hit_count>0 的竞品共现时：禁「未见同框」胡说，且摘要须带 top 名+率。

    2026-08-21 - 禁止「不是没有竞品」纠错套话；分析判断改写本品相对竞品差距与优化方向
    """
    stats = facts.get("competitor_stats") if isinstance(facts.get("competitor_stats"), list) else []
    hits = [
        row
        for row in stats
        if isinstance(row, dict)
        and int(row.get("hit_count") or 0) > 0
        and str(row.get("name") or "").strip()
    ]
    if not hits:
        return stage
    out = dict(stage or {})
    sel = dict(out.get("selection") or {})
    blob = f"{sel.get('title') or ''}{sel.get('summary') or ''}"
    summary = str(sel.get("summary") or "")
    deny = ("未见竞品", "未提供竞品", "无竞品共现", "没有竞品同框", "无法评估与", "未见同框", "未见共现", "未提供共现")
    # 旧纠错套话：事实已列竞品时再反驳「没有竞品」，读者会觉得多余
    empty_rhetoric = ("不是「没有竞品」", "不是没有竞品", "并非没有竞品", "不是「无竞品」")
    top = sorted(hits, key=lambda r: float(r.get("rate") or 0.0), reverse=True)[:3]
    bits = [
        f"{str(r.get('name') or '').strip()} {float(r.get('rate') or 0.0):.1f}%（{int(r.get('hit_count') or 0)}/{int(r.get('sample_total') or 0)}）"
        for r in top
    ]
    top_name = str(top[0].get("name") or "").strip() or "高频竞品"
    names_ok = all(str(r.get("name") or "").strip() in summary for r in top)
    rates_ok = all(
        (
            f"{float(r.get('rate') or 0.0):.1f}" in summary
            or f"{float(r.get('rate') or 0.0):.0f}" in summary
            or f"{float(r.get('rate') or 0.0):.1f}%" in summary
            or f"{float(r.get('rate') or 0.0):.0f}%" in summary
        )
        for r in top
    )
    has_deny = any(tok in blob for tok in deny)
    has_rhetoric = any(tok in blob for tok in empty_rhetoric)
    # 名/率齐全且无胡说、无纠错套话 → 保留原文
    if (not has_deny) and (not has_rhetoric) and names_ok and rates_ok:
        return stage
    sel["label"] = str(sel.get("label") or "竞品对标").strip() or "竞品对标"
    if has_deny or not str(sel.get("title") or "").strip():
        sel["title"] = f"{brand}非品牌词获客里已有竞品同框，要<span>抢稳定席位</span>"
    # 门禁回写：事实列共现 → 判断写本品/竞品差距 → 建议写可执行优化（禁反驳「没有竞品」）
    sel["summary"] = (
        "监测事实：非品牌词获客样本中已识别竞品共现，较高的有 "
        + "、".join(bits)
        + "。"
        f"分析判断：相对{brand}，同框更频的是{top_name}等；"
        "差距主要在差异化证据与对比口径不足，容易只被点名却站不稳推荐位。"
        f"优化建议：优先针对{top_name}等补可核验案例与对比话术，先抢同框稳定席位，再扩对比类问法。"
    )
    out["selection"] = sel
    return out


def _shell_static_copy(
    *,
    brand: str,
    filter_mode: str,
    platform_count: int,
    platform_labels: list[str],
) -> dict[str, Any]:
    """方案 C：壳静态文案随意图/场景与平台数切换。"""
    n = max(0, int(platform_count))
    if n <= 0:
        platform_panel_title = "平台表现对比"
        platform_chart_aria = "各 AI 平台非品牌词获客提及率对比"
    elif n == 1:
        label = platform_labels[0] if platform_labels else "已监测平台"
        platform_panel_title = f"{label} 表现"
        # 2026-08-13 - aria 去掉旧词「正面可见度」
        platform_chart_aria = f"{label} 的非品牌词获客提及率、负面关联率与非品牌词 Top3 率"
    else:
        platform_panel_title = f"{n} 平台表现对比"
        platform_chart_aria = f"{n} 个 AI 平台的非品牌词获客提及率、负面关联率与非品牌词 Top3 率对比"

    if filter_mode == "scene":
        gap_note = (
            f"差距主要来自弱场景与低覆盖平台，而非全量零认知。"
            f"应优先补齐「为什么选{brand}」的场景证据。"
        )
        sources_subtitle = (
            "户外广告采购更依赖官网案例、行业媒体、项目证据与效果口径，信源建设应围绕决策可信度展开。"
        )
        methodology_slice = "场景筛选为户外广告问法维度切片。"
        audit_rows = [
            {"title": "品牌与主体信息", "desc": "公司全称、别名与官网入口可追溯", "tone": "status-ok", "tone_label": "基础完善"},
            {"title": "本次场景问法覆盖", "desc": "仅统计本次 prompts 命中的场景，未测场景不展示", "tone": "status-ok", "tone_label": "可用"},
            {"title": "弱场景权威答案", "desc": "提及偏低，需补案例与边界 FAQ", "tone": "status-risk", "tone_label": "优先补齐"},
            {"title": "项目案例证据链", "desc": "需增加点位、成效与可核验出处", "tone": "status-gap", "tone_label": "需结构化"},
            {"title": "低覆盖平台资料", "desc": "已监测弱平台需分发权威内容", "tone": "status-gap", "tone_label": "需补强"},
            {"title": "竞品对标与适用边界", "desc": f"相对{brand}的中立对比指南仍缺", "tone": "status-risk", "tone_label": "关键缺口"},
        ]
        roadmap_mid_title = "打通场景与选型路径"
        roadmap_mid_body = "上线行业场景页、产品选型 FAQ、对比证据和第一批深度项目案例。"
    else:
        # 2026-08-21 - 意图壳对齐换皮版-G：推荐/竞品对标/口碑/认知，不再列选型类
        gap_note = (
            f"差距主要来自弱意图问法与证据不足，而非全量零认知。"
            f"应优先补齐「为什么选{brand}」的推荐理由、对比口径与口碑证据。"
        )
        sources_subtitle = (
            "采购决策更依赖官网事实、行业媒体、项目/产品证据与可核验口径，信源建设应围绕决策可信度展开。"
        )
        methodology_slice = "第二轴按意图切片：品牌认知、推荐名单、竞品对标、口碑评价。"
        audit_rows = [
            {"title": "品牌与主体信息", "desc": "公司全称、别名与官网入口可追溯", "tone": "status-ok", "tone_label": "基础完善"},
            {"title": "意图问法覆盖", "desc": "认知/推荐/竞品对标/口碑问法已配置", "tone": "status-ok", "tone_label": "可用"},
            {"title": "推荐与对标权威答案", "desc": "需补名单理由、对比口径与边界 FAQ", "tone": "status-risk", "tone_label": "优先补齐"},
            {"title": "案例与口碑证据链", "desc": "需增加可核验出处与用户评价承接", "tone": "status-gap", "tone_label": "需结构化"},
            {"title": "已监测平台资料分发", "desc": "把权威页面向已跑平台持续分发", "tone": "status-gap", "tone_label": "需补强"},
            {"title": "竞品对标与适用边界", "desc": f"相对{brand}的中立对比指南仍缺", "tone": "status-risk", "tone_label": "关键缺口"},
        ]
        # 意图模式无推荐/对标口径；场景模式保留换皮版-G「打通场景与选型路径」原句
        roadmap_mid_title = "打通推荐与对标证据"
        roadmap_mid_body = "上线推荐理由、对比证据和第一批可核验案例。"

    scope_line = build_platform_scope_note(
        [{"name": n} for n in platform_labels],
        for_model=False,
    )
    return {
        "platform_panel_title": platform_panel_title,
        "platform_chart_aria": platform_chart_aria,
        "gap_note": gap_note,
        "sources_subtitle": sources_subtitle,
        "methodology_slice": methodology_slice,
        "methodology_scope": scope_line,
        "audit_rows": audit_rows,
        "roadmap_mid_title": roadmap_mid_title,
        "roadmap_mid_body": roadmap_mid_body,
        "heat_empty_note": (
            "格内主数字为均排；「—」=该问法×平台未进入推荐（格未露出），不是未监测。"
            "回答命中率（多次回答中命中占比）仅作补充，见点击详情/稳定性观察。"
        ),
    }


def _dim_mention_map(tagged: list[dict[str, Any]], *, mode: str) -> dict[str, float]:
    """场景或意图维度的格级提及率均值。

    2026-08-21 - 曾平均样本 brand_mention_rate，与主 KPI 分叉 - 改吃 cell_*
    """
    buckets: dict[str, list[float]] = {}
    for row in tagged:
        code = row.get("scene_code") if mode == "scene" else row.get("intent_code")
        if not code:
            continue
        buckets.setdefault(str(code), []).append(_prompt_display_rate(row))
    return {code: _avg(vals) for code, vals in buckets.items()}


def _build_portfolio_dimension(
    *,
    brand: str,
    tagged: list[dict[str, Any]],
    kpi_basis: dict[str, Any],
    filter_mode: str,
    lead_context: dict[str, Any] | None = None,
    competitors: list[str] | None = None,
    competitor_stats: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str], list[dict[str, str]], dict[str, str], dict[str, str]]:
    """场景优先：仅输出本次问法命中的场景卡；不足用通用意图卡补齐到 6 张。

    2026-08-13 - 禁固定输出机场/高铁/LED 空卡与「暂无数据」占位
    """
    lead_ctx = lead_context if isinstance(lead_context, dict) else {}
    configured_competitors = [str(item).strip() for item in (competitors or []) if str(item).strip()]
    normalized_competitor_stats = [
        item for item in (competitor_stats or [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    product_hint = str(lead_ctx.get("product_focus") or "").strip()
    industry_hint = str(lead_ctx.get("industry") or "").strip()
    all_label = "全部问法" if filter_mode == "scene" else "全部问法意图"
    metric_sub = "格级获客提及率"
    nb_all = kpi_basis.get("nonbrand") if isinstance(kpi_basis.get("nonbrand"), dict) else {}
    bd_all = kpi_basis.get("brand") if isinstance(kpi_basis.get("brand"), dict) else {}
    vis_all = nb_all.get("mention_rate")
    brand_mr = bd_all.get("mention_rate")

    slice_labels: dict[str, str] = {"all": all_label}
    product_cards: list[dict[str, Any]] = []
    product_focus_copy: dict[str, str] = {
        "all": f"当前视角：{all_label}。主 KPI 按问法×平台格重算，与热力图同源。"
    }
    filter_options: list[dict[str, str]] = [{"code": "all", "label": all_label}]

    scenes_map = kpi_basis.get("scenes") if isinstance(kpi_basis.get("scenes"), dict) else {}
    intents_map = kpi_basis.get("intents") if isinstance(kpi_basis.get("intents"), dict) else {}

    # 仅统计本次问法实际命中的场景
    hit_scene_codes: list[str] = []
    scene_prompt_samples: dict[str, str] = {}
    for row in tagged:
        code = str(row.get("scene_code") or "").strip()
        if not code or code in hit_scene_codes:
            if code and code not in scene_prompt_samples and row.get("prompt"):
                scene_prompt_samples[code] = str(row.get("prompt") or "")[:48]
            continue
        hit_scene_codes.append(code)
        if row.get("prompt"):
            scene_prompt_samples[code] = str(row.get("prompt") or "")[:48]

    def _scene_card(code: str) -> dict[str, Any]:
        label = SCENE_LABELS.get(code, code)
        name = f"{label}广告" if code != "transit" else "公交/地铁广告"
        title = "枢纽场景" if code == "airport" else f"{label}媒体"
        raw = scenes_map.get(code) if isinstance(scenes_map.get(code), dict) else {}
        lane = raw.get("nonbrand") if isinstance(raw.get("nonbrand"), dict) else {}
        sm = lane.get("mention_rate") if int(lane.get("total_cells") or 0) > 0 else None
        sample = scene_prompt_samples.get(code) or ""
        if sm is None:
            metric = _fmt_metric(vis_all, suffix="%")
            tag = "有问法依据"
            desc = f"本次问法命中「{name}」：{sample or '见监测问法'}。"
        else:
            metric = f"{sm:.1f}%"
            tag = (
                "优先攻坚"
                if sm < max(15.0, float(vis_all or 0))
                else ("优势放大" if sm >= max(float(vis_all or 0), 30) else "覆盖补强")
            )
            desc = f"基于本次「{name}」问法×平台格的切片可见度（与热力同源）。"
        return {
            "code": code,
            "label": name,
            "title": title,
            "metric": metric,
            "metric_sub": metric_sub,
            "desc": desc,
            "tag": tag,
        }

    def _generic_card(code: str, label: str, title: str) -> dict[str, Any]:
        # 2026-08-13 - 品牌排名/口碑走防守口径；通用意图勿回退成全量获客%
        if code == "brand_rank":
            bd_rank = bd_all.get("avg_rank")
            # 2026-08-13 - 勿用「格级获客提及率」标品牌卡；主数字=防守提及+均排
            metric = f"{_fmt_metric(brand_mr, suffix='%')} / 均排 {_fmt_metric(bd_rank)}"
            return {
                "code": code,
                "label": label,
                "title": title,
                "metric": metric,
                "metric_sub": "品牌防守提及率 · 品牌词均排",
                "desc": (
                    f"品牌词防守提及 {_fmt_metric(brand_mr, suffix='%')}，"
                    f"品牌词均排 {_fmt_metric(bd_rank)}。"
                    f"产品焦点：{product_hint or '本次监测'}。"
                ),
                "tag": "品牌防守",
            }
        if code == "geo_source":
            site = str(lead_ctx.get("website_url") or "").strip()
            metric = "官网" if site else "信源"
            return {
                "code": code,
                "label": label,
                "title": title,
                "metric": metric,
                "metric_sub": "入口上下文",
                "desc": (
                    f"官网/信源建设：{site or '未填官网'}。"
                    f"行业：{industry_hint or '本次监测'}。"
                ),
                "tag": "GEO",
            }

        # “竞品对比”不等于提交了直接 A 对 B 的问法。已配置竞品及其非品牌词共现
        # 需要独立展示，避免没有 compare 意图时被错误表述为“暂无有效对标样本”。
        if code == "compare":
            direct_compare_cells = 0
            compare_raw = intents_map.get("compare") if isinstance(intents_map.get("compare"), dict) else {}
            for lane_name in ("nonbrand", "brand"):
                lane = compare_raw.get(lane_name) if isinstance(compare_raw.get(lane_name), dict) else {}
                direct_compare_cells += int(lane.get("total_cells") or 0)

            stat_names = [str(item.get("name") or "").strip() for item in normalized_competitor_stats]
            merged_names: list[str] = []
            for name in configured_competitors + stat_names:
                if name and name not in merged_names:
                    merged_names.append(name)

            if merged_names:
                observed = [
                    item for item in normalized_competitor_stats
                    if int(item.get("hit_count") or 0) > 0
                ]
                top = max(observed, key=lambda item: float(item.get("rate") or 0.0)) if observed else None
                scope_note = (
                    f"直接对比问法覆盖 {direct_compare_cells} 个有效平台样本。"
                    if direct_compare_cells > 0
                    else ""
                )
                evidence_note = (
                    f"共现较多的是 {str(top.get('name') or '').strip()}（{float(top.get('rate') or 0.0):.1f}%）。"
                    if top else "当前有效回答中暂未识别到已配置竞品的共现。"
                )
                return {
                    "code": code,
                    "label": "竞品对标",
                    "title": "对标概览",
                    "metric": f"{len(merged_names)} 家",
                    "metric_sub": "已纳入竞品对标",
                    "desc": f"已纳入：{'、'.join(merged_names[:4])}。{evidence_note}{scope_note}",
                    "tag": "真实共现",
                }

        intent_code = code if code in INTENT_LABELS else code
        raw = intents_map.get(intent_code) if isinstance(intents_map.get(intent_code), dict) else {}
        nb_lane = raw.get("nonbrand") if isinstance(raw.get("nonbrand"), dict) else {}
        bd_lane = raw.get("brand") if isinstance(raw.get("brand"), dict) else {}
        sample = next(
            (
                str(r.get("prompt") or "")[:48]
                for r in tagged
                if str(r.get("intent_code") or "") == intent_code
            ),
            "",
        )
        # 口碑评价：优先品牌防守格；其它意图优先非品牌获客格
        prefer_brand = code == "reputation"
        primary = bd_lane if prefer_brand else nb_lane
        secondary = nb_lane if prefer_brand else bd_lane
        primary_cells = int(primary.get("total_cells") or 0)
        secondary_cells = int(secondary.get("total_cells") or 0)
        if primary_cells > 0:
            lane, use_brand = primary, prefer_brand
        elif secondary_cells > 0:
            lane, use_brand = secondary, not prefer_brand
        else:
            return {
                "code": code,
                "label": label,
                "title": title,
                "metric": "—",
                "metric_sub": "暂无对口样本",
                "desc": (
                    f"本次问法未形成「{label}」对口格级样本。"
                    + (f"相关问法：{sample}。" if sample else "")
                ),
                "tag": "待补问法",
            }
        sm = lane.get("mention_rate")
        rk = lane.get("avg_rank")
        metric = _fmt_metric(sm, suffix="%")
        metric_sub_local = "品牌防守提及率" if use_brand else "格级获客提及率"
        tag = "品牌防守" if use_brand else "有问法依据"
        rank_bit = f"，均排 {_fmt_metric(rk)}" if rk is not None else ""
        desc = (
            f"基于本次「{label}」{'品牌词' if use_brand else '非品牌词'}问法×平台格"
            f"（提及 {_fmt_metric(sm, suffix='%')}{rank_bit}）。"
            + (f"例：{sample}" if sample else "")
        )
        return {
            "code": code,
            "label": label,
            "title": title,
            "metric": metric,
            "metric_sub": metric_sub_local,
            "desc": desc,
            "tag": tag,
        }

    # 1) 命中场景卡
    for code in hit_scene_codes:
        card = _scene_card(code)
        product_cards.append(card)
        slice_labels[code] = card["label"]
        filter_options.append({"code": code, "label": card["label"]})
        product_focus_copy[code] = f"当前视角：{card['label']}。仅统计本次命中该场景的问法格。"

    # 2) 通用卡补齐到 6
    used = {c["code"] for c in product_cards}
    for code, label, title in _GENERIC_PORTFOLIO_CARDS:
        if len(product_cards) >= 6:
            break
        if code in used:
            continue
        card = _generic_card(code, label, title)
        # 2026-08-20 - 无对口样本的意图卡不进矩阵（尤其勿再出现选型标准空壳）
        if card.get("tag") == "待补问法":
            continue
        product_cards.append(card)
        used.add(code)
        slice_labels[code] = card["label"]
        filter_options.append({"code": code, "label": card["label"]})
        product_focus_copy[code] = f"当前视角：{card['label']}。文案来自本次问法 / KPI / 入口上下文。"

    # 兜底：仍不足 6 时用全部问法锚点卡补
    while len(product_cards) < 6:
        filler_code = f"fill_{len(product_cards)}"
        product_cards.append(
            {
                "code": filler_code,
                "label": all_label,
                "title": f"{brand} 能力锚点",
                "metric": _fmt_metric(vis_all, suffix="%"),
                "metric_sub": metric_sub,
                "desc": f"跨问法统一「为什么选{brand}」的决策底稿。",
                "tag": "品牌锚点",
            }
        )

    if hit_scene_codes:
        hit_names = "、".join(SCENE_LABELS.get(c, c) for c in hit_scene_codes)
        section = {
            "nav_label": "场景矩阵",
            "title": "场景矩阵：按本次问法命中的场景承接 AI 选型",
            "subtitle": f"本次命中场景：{hit_names}。未出现的机场/高铁/LED 等不展示。",
            "intro_title": "从媒介认知，升级为场景解决方案认知",
            "intro_body": f"{brand}应把能力放进真实采购问法，并提供可引用的案例与边界说明。",
        }
    else:
        section = {
            "nav_label": "问法意图矩阵",
            "title": "问法意图矩阵：用通用意图卡承接 AI 决策",
            # 2026-08-21 - 禁「选型标准」；六卡口径对齐换皮版-G（推荐/竞品对标/排名/口碑/GEO/认知）
            "subtitle": "本单无电梯/机场/高铁/LED 等固定场景词，以推荐/竞品对标/排名/口碑/GEO/认知六卡稳定版式。",
            "intro_title": "从品牌名出现，升级为采购意图承接",
            "intro_body": f"{brand}应在非品牌词获客与品牌防守问法中，分别补齐推荐理由、对比口径与口碑证据。",
        }
    return product_cards[:6], product_focus_copy, filter_options, section, slice_labels


def _scene_mention_map(tagged: list[dict[str, Any]]) -> dict[str, float]:
    return _dim_mention_map(tagged, mode="scene")


def _priority_items(
    tagged: list[dict[str, Any]],
    platforms: list[dict[str, Any]],
    diagnosis: dict[str, Any],
    *,
    filter_mode: str = "intent",
    platform_labels: list[str] | None = None,
) -> list[dict[str, str]]:
    """固定输出 P0 / P1 / P2；强弱问法只取非品牌词获客。"""
    acq = [p for p in tagged if p.get("lane") == "acquisition"]
    pool = acq if acq else []
    weak = sorted(pool, key=_prompt_display_rate)
    strong = sorted(pool, key=lambda p: -_prompt_display_rate(p))
    low_plat = sorted(platforms, key=lambda p: _f(p.get("positive") if "positive" in p else p.get("visibility"), 0.0))
    plat_scope = "、".join(platform_labels or []) or "已监测平台"
    p0_level = "P0 · 意图攻坚" if filter_mode == "intent" else "P0 · 场景攻坚"
    p1_level = "P1 · 问法补强" if len(platforms) <= 1 else "P1 · 平台覆盖"

    p0_title = "优先拉升非品牌词弱问法"
    p0_body = "暂无非品牌词短板问法样本，先巩固已监测平台基线。"
    if weak:
        w = weak[0]
        p0_title = f"优先拉升「{compact_prompt_label(w['prompt'], max_len=16)}」可见度"
        p0_body = (
            f"【监测事实】非品牌词问法「{w['prompt']}」提及率 {_prompt_display_rate(w):.1f}%，"
            f"均排 {_fmt_metric(_prompt_display_rank(w))}；"
            f"平台范围：{plat_scope}。"
        )

    p1_title = "补齐已监测平台内容分发"
    p1_body = f"【监测事实】平台覆盖较均衡（{plat_scope}），持续分发权威答案页。"
    if low_plat:
        lp = low_plat[0]
        name = str(lp.get("name") or _SLOT_NAMES.get(str(lp.get("key") or ""), lp.get("key") or "平台"))
        raw_vis = lp.get("positive") if "positive" in lp else lp.get("visibility")
        vis_txt = _fmt_metric(raw_vis, suffix="%")
        rk = lp.get("rank")
        p1_title = f"补齐{name}等内容证据"
        p1_body = (
            f"【监测事实】{name}提及率 {vis_txt}，均排 {_fmt_metric(rk if rk not in (None, 0, 0.0) else None)}；"
            f"仅评价已监测平台，不外推未跑平台。"
        )

    p2_title = "巩固非品牌词优势问法"
    p2_body = "【判断】暂无足够优势问法样本可放大。"
    if strong and _prompt_display_rate(strong[0]) >= 20:
        s = strong[0]
        p2_title = f"巩固「{compact_prompt_label(s['prompt'], max_len=16)}」优势"
        p2_body = (
            f"【监测事实】非品牌词问法「{s['prompt']}」提及率 {_prompt_display_rate(s):.1f}%，"
            f"均排 {_fmt_metric(_prompt_display_rank(s))}，适合放大推荐理由。"
        )
    elif str(diagnosis.get("recommendation") or "").strip():
        p2_body = f"【判断】{compact_prompt_label(str(diagnosis.get('recommendation')), max_len=120)}"

    return [
        {
            "level_class": "p0",
            "level": p0_level,
            "tone": "status-risk",
            "tone_label": "缺口明显",
            "title": p0_title,
            "body": p0_body,
        },
        {
            "level_class": "p1",
            "level": p1_level,
            "tone": "status-gap",
            "tone_label": "需结构化",
            "title": p1_title,
            "body": p1_body,
        },
        {
            "level_class": "p2",
            "level": "P2 · 优势放大",
            "tone": "status-ok",
            "tone_label": "基础较强",
            "title": p2_title,
            "body": p2_body,
        },
    ]


def _risk_rows(
    priority: list[dict[str, str]],
    tagged: list[dict[str, Any]],
    *,
    platform_labels: list[str] | None = None,
) -> list[dict[str, str]]:
    """风险表必须引用优先项中的问法与数据证据，禁止空泛模板句。"""
    rows: list[dict[str, str]] = []
    models = "、".join(platform_labels or []) or "已监测平台"
    for item in priority:
        level = item["level"].split("·", 1)[0].strip()
        rows.append(
            {
                "topic": item["title"],
                "models": models,
                "impact": "影响入围与推荐位" if level == "P0" else "影响说服力",
                "evidence": item["body"],
                "priority": level,
                "pill": "risk-high" if level == "P0" else "risk-medium",
            }
        )
    acq = [p for p in tagged if p.get("lane") == "acquisition"]
    if len(rows) < 4 and acq:
        mid = sorted(acq, key=_prompt_display_rate)[0]
        rows.append(
            {
                "topic": f"「{compact_prompt_label(mid['prompt'], max_len=20)}」非品牌词仍偏弱",
                "models": models,
                "impact": "获客主口径提及不足",
                "evidence": (
                    f"【监测事实】提及率 {_prompt_display_rate(mid):.1f}%，"
                    f"均排 {_fmt_metric(_prompt_display_rank(mid))}"
                ),
                "priority": "P1",
                "pill": "risk-medium",
            }
        )
    return rows[:5]


def _data_driven_actions(
    priority: list[dict[str, str]],
    *,
    filter_mode: str,
) -> list[dict[str, Any]]:
    """行动卡绑定优先项证据，禁止无来源泛化 bullets。"""
    axis = "意图" if filter_mode == "intent" else "场景"
    out: list[dict[str, Any]] = []
    defaults = (
        ("p0", "P0 · 30 天", "夯实决策底稿"),
        ("p1", "P1 · 60 天", "提升前三占比"),
        ("p2", "P2 · 90 天", "扩大权威引用"),
    )
    for idx, (level_class, level, impact) in enumerate(defaults):
        base = priority[idx] if idx < len(priority) else {"title": "监测短板", "body": "暂无数据"}
        out.append(
            {
                "level_class": level_class,
                "level": level,
                "impact": impact,
                "title": str(base.get("title") or level),
                "body": str(base.get("body") or "暂无数据"),
                "bullets": [
                    f"要解决的问法/问题：{base.get('title')}",
                    f"内容载体：官网{axis}答案页 + 可核验案例/FAQ",
                    "复测方式：同问法×已监测平台复跑，对比获客提及率/均排/Top3",
                ],
            }
        )
    return out


def build_diagnosis_cockpit_context(
    payload: dict[str, Any],
    platform_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    names_map = platform_names or {
        str(item.get("code") or ""): str(item.get("name") or item.get("code") or "")
        for item in get_supported_platform_catalog()
    }
    brand = str(payload.get("brand_name") or payload.get("tenant_name") or "").strip() or "品牌"
    aliases = [str(x).strip() for x in (payload.get("brand_aliases") or payload.get("aliases") or []) if str(x).strip()]
    company = str(payload.get("company_name") or "").strip()
    diagnosis = payload.get("diagnosis") or {}
    kpis = payload.get("kpis") or {}
    prompt_analytics = payload.get("prompt_analytics") or []
    platform_stats = payload.get("platform_stats") or []
    matrix_rows = payload.get("matrix_rows") or []
    source_analysis = payload.get("source_analysis") or {}
    snap = payload.get("monitor_snapshot") or {}
    if not isinstance(snap, dict):
        snap = {}
    # 2026-08-13 - 售前结果信源/矩阵常在 monitor_snapshot；normalize 后也可能只在顶层
    if not source_analysis:
        source_analysis = snap.get("source_analysis") or {}
    if not prompt_analytics:
        prompt_analytics = snap.get("prompt_analytics") or []
    if not platform_stats:
        platform_stats = snap.get("platform_stats") or []
    if not matrix_rows:
        matrix_rows = snap.get("matrix_rows") or []
    if not payload.get("sentiment_counts") and snap.get("sentiment_counts"):
        payload = {**payload, "sentiment_counts": snap.get("sentiment_counts") or {}}
    top_sources = payload.get("top_sources") or snap.get("top_sources") or []
    competitors = [str(x).strip() for x in (payload.get("competitors") or []) if str(x).strip()]
    competitor_stats = [
        row
        for row in (payload.get("competitor_stats") or [])
        if isinstance(row, dict) and str(row.get("name") or "").strip()
    ]
    # 2026-08-13 - 入口结构化上下文进报告对象，供 HTML/__COCKPIT__ 审计
    lead_context = normalize_lead_context(
        payload.get("lead_context") or payload.get("input_context") or {}
    )
    input_context = lead_context

    tagged: list[dict[str, Any]] = []
    for block in prompt_analytics:
        prompt = str(block.get("prompt") or "").strip()
        if not prompt:
            continue
        meta = classify_prompt(prompt, brand=brand, aliases=aliases)
        tagged.append(
            {
                **meta,
                "brand_mention_rate": _f(block.get("brand_mention_rate"), 0.0),
                "brand_avg_rank": _f(block.get("brand_avg_rank"), 0.0),
                "sample_count": int(block.get("sample_count") or 0),
            }
        )

    # 2026-08-13 - A+：主 KPI 统一问法×平台格；样本级仅稳定性观察
    acquisition = [p for p in tagged if p.get("lane") == "acquisition"]
    defense_pool_early = [p for p in tagged if p.get("lane") == "brand_defense"]
    display_slots = _monitored_slots(platform_stats, matrix_rows) or list(_SLOT_ORDER)
    # 2026-08-21 - 问法主数字改挂格级，样本率仅作回答命中率
    for p in tagged:
        cell_rate, cell_rank = _prompt_cell_metrics(
            str(p.get("prompt") or ""),
            matrix_rows if isinstance(matrix_rows, list) else [],
            display_slots,
        )
        p["cell_mention_rate"] = cell_rate
        p["cell_avg_rank"] = cell_rank
    kpi_basis = build_kpi_basis(tagged, matrix_rows, display_slots)
    sample_basis = build_sample_basis(tagged)
    nb = kpi_basis["nonbrand"]
    bd = kpi_basis["brand"]
    has_acquisition_kpi = bool(nb.get("available")) and int(nb.get("total_cells") or 0) > 0
    visibility = nb.get("mention_rate") if has_acquisition_kpi else None
    rank = nb.get("avg_rank") if has_acquisition_kpi else None
    decision = nb.get("top3_rate") if has_acquisition_kpi else None
    brand_defense_rate = bd.get("mention_rate") if int(bd.get("total_cells") or 0) > 0 else None

    positive_rate = _f(kpis.get("positive_rate"), 0.0)
    sentiment = payload.get("sentiment_counts") or {}
    completed_for_sent = int(_f(kpis.get("completed_count"), 0.0))
    # 2026-08-14 - 方案 B：负面关联率 = neg / 全样本（含 unknown）
    negative, _neg_n, sentiment_sample_n = _full_sample_negative_rate(
        sentiment if isinstance(sentiment, dict) else {},
        completed_count=completed_for_sent or None,
    )
    reputation_high_risk = _reputation_high_risk(
        sample_n=sentiment_sample_n,
        negative_rate=negative,
        positive_rate=positive_rate,
    )

    total_refs = _f(source_analysis.get("total_references"), 0.0)
    brand_refs = _f(source_analysis.get("brand_related_references"), 0.0)
    citation: float | None = round(100.0 * brand_refs / total_refs, 1) if total_refs > 0 else None

    filter_mode = resolve_filter_mode(tagged)
    dim_key = "scenes" if filter_mode == "scene" else "intents"
    dim_map = kpi_basis.get(dim_key) if isinstance(kpi_basis.get(dim_key), dict) else {}
    # 2026-08-13 - 切片轴仅含本次命中场景 + 通用卡 code，勿枚举全部 SCENE_RULES
    hit_scene_codes = []
    for row in tagged:
        code = str(row.get("scene_code") or "").strip()
        if code and code not in hit_scene_codes:
            hit_scene_codes.append(code)
    portfolio_codes = hit_scene_codes + [c for c, _l, _t in _GENERIC_PORTFOLIO_CARDS]
    slice_codes = ["all"] + portfolio_codes

    def _slices_for_platform(slot: str | None) -> dict[str, Any]:
        """平台×切片格级 KPI；slot=None 表示全平台。"""
        out: dict[str, Any] = {}
        if slot is None:
            base_nb, base_bd = nb, bd
            plat_lanes = None
        else:
            plat_lanes = (kpi_basis.get("platforms") or {}).get(slot) or {}
            base_nb = plat_lanes.get("nonbrand") if isinstance(plat_lanes.get("nonbrand"), dict) else {}
            base_bd = plat_lanes.get("brand") if isinstance(plat_lanes.get("brand"), dict) else {}
        out["all"] = _slice_metrics_from_lanes(base_nb, base_bd, negative=negative, citation=citation)
        cell = _matrix_cell_map(matrix_rows)
        for code in slice_codes:
            if code == "all":
                continue
            # brand_rank / geo_source 非 taxonomy 轴：复用 all
            if code in {"brand_rank", "geo_source"}:
                out[code] = dict(out["all"])
                continue
            raw = dim_map.get(code) if isinstance(dim_map.get(code), dict) else {}
            # 意图卡在 scene 模式下仍从 intents 取
            if code in INTENT_LABELS and not (isinstance(raw, dict) and raw):
                intent_dim = kpi_basis.get("intents") if isinstance(kpi_basis.get("intents"), dict) else {}
                raw = intent_dim.get(code) if isinstance(intent_dim.get(code), dict) else {}
            if slot is None:
                out[code] = _slice_metrics_from_lanes(
                    (raw.get("nonbrand") if isinstance(raw.get("nonbrand"), dict) else {}),
                    (raw.get("brand") if isinstance(raw.get("brand"), dict) else {}),
                    negative=negative,
                    citation=citation,
                )
                continue
            cross_nb = _empty_cell_counts()
            cross_bd = _empty_cell_counts()
            for p in tagged:
                prompt = str(p.get("prompt") or "").strip()
                if not prompt:
                    continue
                # 场景切片只吃同场景；意图切片吃同意图
                if code in SCENE_LABELS:
                    if str(p.get("scene_code") or "") != code:
                        continue
                elif code in INTENT_LABELS:
                    if str(p.get("intent_code") or "") != code:
                        continue
                else:
                    continue
                is_brand = p.get("lane") == "brand_defense" or bool(p.get("is_brand_word"))
                rank_v = cell.get((prompt, slot), 0)
                _add_cell(cross_bd if is_brand else cross_nb, rank_v)
            out[code] = _slice_metrics_from_lanes(
                _pack_lane_counts(cross_nb),
                _pack_lane_counts(cross_bd),
                negative=negative,
                citation=citation,
            )
        return out

    platform_data: dict[str, dict[str, Any]] = {
        "all": {
            "name": "全平台",
            **_slice_metrics_from_lanes(nb, bd, negative=negative, citation=citation),
            "risks": 0,
            "slices": _slices_for_platform(None),
        }
    }
    platform_rows: list[dict[str, Any]] = []
    platform_filter_options: list[dict[str, str]] = [{"code": "all", "label": "全平台"}]
    for slot in display_slots:
        plat_lanes = (kpi_basis.get("platforms") or {}).get(slot) or {}
        slice_all = _slice_metrics_from_lanes(
            plat_lanes.get("nonbrand") if isinstance(plat_lanes.get("nonbrand"), dict) else {},
            plat_lanes.get("brand") if isinstance(plat_lanes.get("brand"), dict) else {},
            negative=negative,
            citation=citation,
        )
        label = _slot_label(slot, names_map)
        platform_data[slot] = {
            "name": label,
            **slice_all,
            "risks": 0,
            "slices": _slices_for_platform(slot),
        }
        platform_rows.append(
            {
                "key": slot,
                "name": label,
                "positive": slice_all.get("visibility"),
                # 2026-08-13 - P1 平台风险文案读 rank，漏传会写成「均排暂无数据」
                "rank": slice_all.get("rank"),
                "negative": negative,
                "decision": slice_all.get("decision"),
            }
        )
        platform_filter_options.append({"code": slot, "label": label})

    scene_mentions = _scene_mention_map(tagged)
    intent_mentions = _dim_mention_map(tagged, mode="intent")
    product_cards, product_focus_copy, product_filter_options, portfolio_section, slice_labels = (
        _build_portfolio_dimension(
            brand=brand,
            tagged=tagged,
            kpi_basis=kpi_basis,
            filter_mode=filter_mode,
            lead_context=lead_context,
            competitors=competitors,
            competitor_stats=competitor_stats,
        )
    )

    # 2026-08-13 - 问法×平台快照证据（不参与 KPI）
    evidence_map = payload.get("snapshot_evidence") or snap.get("snapshot_evidence") or {}
    if not isinstance(evidence_map, dict):
        evidence_map = {}
    scenarios = _build_heat_scenarios(tagged, matrix_rows, display_slots, evidence_map=evidence_map)
    heat_model_names = [_slot_label(s, names_map) for s in display_slots]
    heat_detail_default = (
        "当前结论：点击单元格查看该问法×平台的治理建议；弱场景与低覆盖平台优先补证据。"
        if filter_mode == "scene"
        else "当前结论：点击单元格查看该问法×平台的治理建议；弱意图与低覆盖平台优先补证据。"
    )

    domains = source_analysis.get("domain_stats") or source_analysis.get("top_domains") or []
    # 信源图面对客户优先展示中文站点名；域名仍作为内部识别键，不直接占据展示位。
    official_site_labels = payload.get("official_site_labels")
    if not isinstance(official_site_labels, dict):
        official_site_labels = None
    domains = enrich_domain_rows(
        [row for row in domains if isinstance(row, dict)],
        brand=brand,
        use_llm=False,
        official_site_labels=official_site_labels,
    )
    sources: list[dict[str, Any]] = []
    if isinstance(domains, list) and domains:
        max_c = max(int(d.get("count") or 0) for d in domains if isinstance(d, dict)) or 1
        for d in domains[:8]:
            if not isinstance(d, dict):
                continue
            name = str(d.get("site_cn") or d.get("site") or d.get("domain") or d.get("name") or "").strip()
            count = int(d.get("count") or 0)
            if not name:
                continue
            idx = round(100.0 * count / max_c)
            # 展示原始次数 + 归一化权重，避免被读成 100%
            sources.append(
                {
                    "name": name,
                    "value": idx,
                    "count": count,
                    "display": f"{count}次 · 权重{idx}",
                }
            )
    if not sources:
        sources = [{"name": "暂无信源", "value": 0, "count": 0, "display": "0次"}]

    priority = _priority_items(
        tagged,
        platform_rows,
        diagnosis,
        filter_mode=filter_mode,
        platform_labels=heat_model_names,
    )
    platform_data["all"]["risks"] = len([r for r in priority if r["level"].startswith("P0")]) or len(priority)
    for slot in display_slots:
        platform_data[slot]["risks"] = platform_data["all"]["risks"]

    risk_rows = _risk_rows(priority, tagged, platform_labels=heat_model_names)
    actions = _data_driven_actions(priority, filter_mode=filter_mode)

    summary = (
        str(payload.get("executive_summary") or "").strip()
        or str(diagnosis.get("sentiment_summary") or "").strip()
        or str(payload.get("summary") or "").strip()
        or f"{brand} 在监测窗口内的 AI 可见度摘要。弱问法与低覆盖平台是优先补强方向。"
    )
    # 无获客样本或单平台：用规则摘要，禁止全品牌词回填获客数字
    if (not has_acquisition_kpi) or len(platform_rows) <= 1:
        weak_ex, strong_ex = _kpi_prompt_examples(tagged)
        bd_early = _lane_metric_block(defense_pool_early).get("mention_rate")
        summary = build_rule_all_summary(
            brand=brand,
            visibility=visibility,
            rank=rank,
            decision=decision,
            negative=negative,
            platform_rows=platform_rows,
            weak_prompts=weak_ex,
            strong_prompts=strong_ex,
            filter_mode=filter_mode,
            has_acquisition_kpi=has_acquisition_kpi,
            brand_defense_rate=brand_defense_rate,
        )
    stage_copy = {
        "all": {
            "label": "管理层摘要",
            "title": (
                build_rule_all_title(
                    brand=brand,
                    platform_rows=platform_rows,
                    visibility=visibility,
                    has_acquisition_kpi=has_acquisition_kpi,
                )
                if (not has_acquisition_kpi) or len(platform_rows) <= 1
                else "场景优势与短板并存，仍缺<span>明确推荐位</span>"
            ),
            "summary": summary,
        },
        # 2026-08-20 - 阶段条口径对齐桌面 G：竞品对标/推荐名单/口碑评价（禁再写技术选型）
        "recognition": {
            "label": "品牌认知",
            "title": (
                f"从“知道{brand}”升级到<span>理解场景能力</span>"
                if filter_mode == "scene"
                else f"从“知道{brand}”升级到<span>理解品牌能力</span>"
            ),
            "summary": (
                f"AI 已能在部分问法中识别{brand}，但对场景能力的稳定认知仍不完整。应统一品牌能力框架。"
                if filter_mode == "scene"
                else f"AI 已能在部分问法中识别{brand}，但对能力边界与适用场景的稳定认知仍不完整。应统一品牌能力框架。"
            ),
        },
        "selection": {
            "label": "竞品对标",
            "title": f"短名单里，竞品是否比{brand}<span>更常被点名</span>",
            "summary": (
                f"对照已配置竞品在非品牌词回答中的共现与位次，判断{brand}是否被挤出同框。"
                "优先补可核验案例与对比口径，抢同框稳定席位。"
            ),
        },
        "procurement": {
            "label": "推荐名单",
            "title": f"{brand}已能进推荐短名单，下一步是<span>站稳前三</span>",
            "summary": (
                "优势场景具备入围说服力。下一步把最强案例绑到「推荐/哪家好」话术上。"
                if filter_mode == "scene"
                else "优势问法具备入围说服力。下一步把最强案例绑到「推荐/哪家好」话术上。"
            ),
        },
        "risk": {
            "label": "口碑评价",
            "title": "公开负向不多时，仍要补<span>可引用评价口径</span>",
            "summary": "口碑阶段看品牌词评价问法是否可引用：适用谁、不适合谁与证据链。负向共现≠质量结论。",
        },
    }

    defense_pool = defense_pool_early
    brand_defense_display = _fmt_metric(brand_defense_rate, suffix="%")
    # A+：平台切片已含 brand_defense；此处只保证顶层字段一致
    platform_data["all"]["brand_defense"] = brand_defense_rate
    for slot in display_slots:
        if slot in platform_data:
            platform_data[slot]["brand_defense"] = platform_data[slot].get("brand_defense", brand_defense_rate)

    metric_details = {
        "visibility": {
            "title": "非品牌词获客提及率",
            "body": (
                f"<strong>格级口径：</strong>非品牌词问法×已监测平台热力格中，有排名的格占比。"
                f"分子 {int(nb.get('mention_cells') or 0)} / 分母 {int(nb.get('total_cells') or 0)} = "
                f"{_fmt_metric(visibility, suffix='%')}。"
                f"<ul class='dialog-points'><li>与热力图同源；品牌词不计入。</li>"
                f"<li>分母 total_cells=0 → 暂无；分母&gt;0 且命中 0 → 0%。</li>"
                f"<li>跨日回答命中率见「稳定性观察」，不参与本指标。</li></ul>"
            ),
        },
        "rank": {
            "title": "非品牌词平均推荐位",
            "body": (
                f"<strong>格级口径：</strong>有排名的非品牌词格的均排 "
                f"（rank_sum {nb.get('rank_sum') or 0} / mention_cells {int(nb.get('mention_cells') or 0)}）。"
                f"当前 {_fmt_metric(rank)}。"
                f"<ul class='dialog-points'><li>mention_cells=0 时均排为「暂无数据」；"
                f"total_cells&gt;0 且 mention=0 时提及率/Top3 为 0%，不是暂无。</li></ul>"
            ),
        },
        "decision": {
            "title": "非品牌词 Top3 率",
            "body": (
                f"<strong>格级口径：</strong>非品牌词热力格中排名 1–3 的占比"
                f"（分母=total_cells）。分子 {int(nb.get('top3_cells') or 0)} / "
                f"{int(nb.get('total_cells') or 0)} = {_fmt_metric(decision, suffix='%')}。"
                f"<ul class='dialog-points'><li>分母为 0 → 暂无；分母&gt;0 且命中 0 → 0%。</li></ul>"
            ),
        },
        "brand_defense": {
            "title": "品牌词防守提及率",
            "body": (
                f"<strong>格级口径：</strong>品牌词热力格有排名占比。"
                f"分子 {int(bd.get('mention_cells') or 0)} / 分母 {int(bd.get('total_cells') or 0)} = "
                f"{brand_defense_display}。"
                f"<ul class='dialog-points'><li>不计入获客主 KPI。</li>"
                f"<li>brand_total=0 → 暂无；有分母且命中 0 → 0%。</li>"
                f"<li>跨日样本防守率见稳定性观察卡。</li></ul>"
            ),
        },
        "negative": {
            "title": "负面关联率（全量辅助）",
            "body": (
                f"<strong>全量辅助：</strong>监测样本负面情绪占比 {_fmt_metric(negative, suffix='%')}。"
                f"<ul class='dialog-points'><li>未按品牌词/非品牌词细分；来源未拆分时不推断归因。</li>"
                f"<li>无情绪分母时为暂无，不是 0%。</li></ul>"
            ),
        },
        "citation": {
            "title": "品牌信源引用率（全量辅助）",
            "body": (
                f"<strong>全量辅助：</strong>品牌相关引用 / 全部引用 = "
                f"{int(brand_refs)}/{int(total_refs)} ≈ {_fmt_metric(citation, suffix='%')}。"
                f"<ul class='dialog-points'><li>下方域名列表的「权重」为频次归一，不是百分比本身。</li>"
                f"<li>无引用分母时为暂无，不是 0%。</li></ul>"
            ),
        },
    }


    diagnosis_section = (
        {
            "nav_label": "采购场景诊断",
            "index": "03 / SCENARIO",
            "title": f"采购场景诊断：AI 是否能把{brand}放进候选名单",
            "subtitle": "数字代表监测均排（四舍五入），“—”代表该问法×平台未进入推荐。点击单元格可查看治理建议。",
            "side_flow": "平台 → 场景矩阵 → 场景诊断 → 信源 → 风险 → 行动",
        }
        if filter_mode == "scene"
        else {
            "nav_label": "意图诊断",
            "index": "03 / INTENT",
            "title": f"意图诊断：AI 是否能把{brand}放进候选名单",
            "subtitle": "数字代表监测均排（四舍五入），“—”代表该问法×平台未进入推荐。点击单元格可查看治理建议。",
            "side_flow": "平台 → 问法意图矩阵 → 意图诊断 → 信源 → 风险 → 行动",
        }
    )

    acq_n = len([p for p in tagged if p.get("lane") == "acquisition"])
    def_n = len(defense_pool)
    monitor_version_note = (
        f"监测版本说明：平台={('、'.join(heat_model_names) if heat_model_names else '暂无')}；"
        f"问法={len(tagged)}（非品牌词获客 {acq_n} / 品牌词防守 {def_n}）；"
        f"子任务约 {int(_f(kpis.get('completed_count'), 0)) or sum(int(p.get('sample_count') or 0) for p in tagged)}；"
        f"主 KPI 仅基于非品牌词。不同平台组合不可直接横比。"
    )

    competitor_rows: list[dict[str, Any]] = []
    # 2026-08-14 - 竞品条用获客共现率，不再 90-idx*7 假分
    if competitor_stats:
        for row in competitor_stats[:6]:
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            rate = round(float(row.get("rate") or 0.0), 1)
            competitor_rows.append({"name": name, "width": rate, "score": rate})
    else:
        for name in competitors[:6]:
            competitor_rows.append({"name": name, "width": 0.0, "score": 0.0})

    if filter_mode == "scene":
        # 结论区不直接露出公交/地铁等单个场景标签，避免把场景关键词误读为
        # 服务范围或总判断；具体场景只在下方证据卡内呈现。
        evidence_chips = [
            (
                f"非品牌词获客提及率 {_fmt_metric(visibility, suffix='%')}"
                if has_acquisition_kpi
                else "非品牌词获客：暂无数据"
            ),
            f"场景问法 {len(hit_scene_codes)} 类",
            f"品牌词防守 {_fmt_metric(brand_defense_rate, suffix='%')}",
        ]
        # 顶部“覆盖”表达的是诊断范围，不罗列单个场景，避免把公交/地铁等场景词
        # 误读为服务范围或结论标签；具体场景仍保留在对应证据卡内。
        coverage_label = "场景化监测问法"
        insight_mid_title = "场景选型说服力"
        insight_mid_desc = (
            "Top3 露出与弱场景表现。"
            if has_acquisition_kpi
            else "本次无非品牌词样本，不能计算自然获客对标。"
        )
        top_hit = max((scene_mentions.get(c, 0.0) for c in hit_scene_codes), default=0.0)
        insight_mid_score = (
            int(round(min(100, (decision or 0) * 1.2 + top_hit * 0.2)))
            if has_acquisition_kpi
            else None
        )
    else:
        # 2026-08-13 - 非户外单仍展示电梯 chip - 改意图提及摘要
        top_intents = sorted(
            ((INTENT_LABELS.get(c, c), intent_mentions.get(c, 0.0)) for c in _INTENT_CARD_ORDER),
            key=lambda x: x[1],
            reverse=True,
        )
        evidence_chips = [
            (
                f"非品牌词获客提及率 {_fmt_metric(visibility, suffix='%')}"
                if has_acquisition_kpi
                else "非品牌词获客：暂无数据（全品牌词样本）"
            ),
            f"{top_intents[0][0]} {top_intents[0][1]:.0f}%",
            f"品牌词防守 {_fmt_metric(brand_defense_rate, suffix='%')}",
        ]
        coverage_label = _intent_coverage_label(kpi_basis)
        insight_mid_title = "意图选型说服力"
        insight_mid_desc = (
            "Top3 露出与弱意图表现。"
            if has_acquisition_kpi
            else "本次无非品牌词样本，不能计算自然获客对标。"
        )
        insight_mid_score = (
            int(round(min(100, (decision or 0) * 1.2 + top_intents[0][1] * 0.2)))
            if has_acquisition_kpi
            else None
        )

    top_source_names = " · ".join(s["name"] for s in sources[:3]) or "暂无"

    generated = str(payload.get("generated_at") or "").strip()
    try:
        if generated:
            generated = datetime.fromisoformat(generated.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        generated = generated[:10] if generated else datetime.now().strftime("%Y-%m-%d")

    sample_count = int(_f(kpis.get("completed_count"), 0)) or sum(int(p.get("sample_count") or 0) for p in tagged)

    # 2026-08-13 - 依赖非品牌露出/Top3/均排的诊断分：无分母→暂无评估，勿 0/100
    na_acq_desc = "本次无非品牌词样本，不能计算自然获客对标。"
    if has_acquisition_kpi:
        mid_display = f"{insight_mid_score} / 100"
        procure_score = int(round(min(100, max(0, 100 - (rank or 0) * 8)))) if rank is not None else None
        if rank is None:
            # 有非品牌格但 mention=0：均排暂无 → 采购信任也暂无（不是 0 分）
            procure_display = "暂无评估"
            procure_desc = "非品牌词均排暂无，不能计算采购信任分。"
        else:
            procure_display = f"{procure_score} / 100"
            procure_desc = "非品牌词均排越靠前，入围信任越强。"
    else:
        mid_display = "暂无评估"
        procure_score = None
        procure_display = "暂无评估"
        procure_desc = na_acq_desc

    insights = [
        {
            "title": "自然获客候选池",
            "score": int(round(min(100, (visibility or 0) * 1.5))) if has_acquisition_kpi else None,
            "score_display": (
                f"{int(round(min(100, (visibility or 0) * 1.5)))} / 100"
                if has_acquisition_kpi
                else "暂无评估"
            ),
            "desc": (
                "非品牌词获客提及与覆盖情况。"
                if has_acquisition_kpi
                else na_acq_desc
            ),
        },
        {
            "title": insight_mid_title,
            "score": insight_mid_score,
            "score_display": mid_display,
            "desc": insight_mid_desc,
        },
        {
            "title": "项目采购信任",
            "score": procure_score,
            "score_display": procure_display,
            "desc": procure_desc,
        },
        {
            "title": "口碑风险偏高" if reputation_high_risk else "口碑与风险可控",
            "score": int(round(max(0, 100 - float(negative)))) if negative is not None else None,
            "score_display": (
                f"{int(round(max(0, 100 - float(negative))))} / 100"
                if negative is not None
                else "暂无评估"
            ),
            # 2026-08-14 - 高负面时禁止「可控/正面」表述（全样本口径）
            "desc": (
                f"全样本负面占比约 {_fmt_metric(negative, suffix='%')}，口碑风险偏高。"
                if reputation_high_risk and negative is not None
                else ("负面情绪样本占比。" if negative is not None else "本窗无情绪分母，暂无评估。")
            ),
        },
    ]

    # 2026-08-13 - 叙事覆盖后必须用当前 KPI 校正 null/0，避免旧包把 0% 写成暂无
    data_priority = list(priority)
    data_risk_rows = list(risk_rows)
    data_actions = list(actions)
    narrative = payload.get("cockpit_narrative")
    if isinstance(narrative, dict) and narrative.get("stage_copy"):
        weak_ex, strong_ex = _kpi_prompt_examples(tagged)
        facts_guard = {
            "kpis": {
                "visibility": visibility,
                "rank": rank,
                "decision": decision,
                "negative": negative,
                "citation": citation,
                "brand_defense": brand_defense_rate,
            },
            "weak_prompts": weak_ex,
            "strong_prompts": strong_ex,
            "platform_rows": platform_rows,
            "filter_mode": filter_mode,
            "has_acquisition_kpi": has_acquisition_kpi,
            "brand_defense_rate": brand_defense_rate,
            "sentiment_sample_n": sentiment_sample_n,
            "negative_rate": negative,
            "positive_rate": positive_rate,
            # 2026-08-20 - 渲染门禁必须带共现，否则「未见同框」护栏在预览路径空转
            "competitor_stats": competitor_stats,
        }
        narrative = apply_narrative_scope_guards(narrative, brand=brand, facts=facts_guard)
        stage_in = narrative.get("stage_copy") or {}
        if isinstance(stage_in, dict):
            for key in ("all", "recognition", "selection", "procurement", "risk"):
                row = stage_in.get(key)
                if isinstance(row, dict) and row.get("title") and row.get("summary"):
                    stage_copy[key] = {
                        "label": str(row.get("label") or stage_copy[key]["label"]),
                        "title": str(row.get("title")),
                        "summary": str(row.get("summary")),
                    }
        if isinstance(narrative.get("priority_items"), list) and len(narrative["priority_items"]) >= 3:
            cand = [dict(x) for x in narrative["priority_items"][:3] if isinstance(x, dict)]
            # 有获客分母时，禁止叙事仍写「无获客/主 KPI 暂无」
            if has_acquisition_kpi and _blob_claims_no_acquisition(cand):
                priority = data_priority
            else:
                priority = cand
            if not (isinstance(narrative.get("risk_rows"), list) and narrative["risk_rows"]):
                risk_rows = _risk_rows(priority, tagged, platform_labels=heat_model_names)
            if not (isinstance(narrative.get("actions"), list) and len(narrative["actions"]) >= 3):
                actions = _data_driven_actions(priority, filter_mode=filter_mode)
        if isinstance(narrative.get("risk_rows"), list) and narrative["risk_rows"]:
            cand_r = [dict(x) for x in narrative["risk_rows"][:5] if isinstance(x, dict)]
            if has_acquisition_kpi and _blob_claims_no_acquisition(cand_r):
                risk_rows = _risk_rows(priority, tagged, platform_labels=heat_model_names) or data_risk_rows
            else:
                risk_rows = cand_r
        if isinstance(narrative.get("actions"), list) and len(narrative["actions"]) >= 3:
            cand_a = [dict(x) for x in narrative["actions"][:3] if isinstance(x, dict)]
            if has_acquisition_kpi and _blob_claims_no_acquisition(cand_a):
                actions = _data_driven_actions(priority, filter_mode=filter_mode) or data_actions
            else:
                actions = cand_a

    # 始终用当前格级 KPI 重写管理层摘要（null/0 唯一真相）
    weak_ex2, strong_ex2 = _kpi_prompt_examples(tagged)
    stage_copy["all"]["title"] = build_rule_all_title(
        brand=brand,
        platform_rows=platform_rows,
        visibility=visibility,
        has_acquisition_kpi=has_acquisition_kpi,
    )
    stage_copy["all"]["summary"] = build_rule_all_summary(
        brand=brand,
        visibility=visibility,
        rank=rank,
        decision=decision,
        negative=negative,
        platform_rows=platform_rows,
        weak_prompts=weak_ex2,
        strong_prompts=strong_ex2,
        filter_mode=filter_mode,
        has_acquisition_kpi=has_acquisition_kpi,
        brand_defense_rate=brand_defense_rate,
    )
    stage_copy["all"]["summary"] = _ensure_top3_gap_in_summary(
        str(stage_copy["all"].get("summary") or ""),
        rank=rank,
        decision=decision,
        has_acquisition_kpi=has_acquisition_kpi,
    )
    # 其它阶段若仍写「无获客/主 KPI 暂无」而实际有获客分母，回退默认壳文案
    # 2026-08-20 - 默认阶段与顶栏一致（品牌认知/竞品对标/推荐名单/口碑评价）
    _default_stage_shell = {
        "recognition": {
            "label": "品牌认知",
            "title": (
                f"从“知道{brand}”升级到<span>理解场景能力</span>"
                if filter_mode == "scene"
                else f"从“知道{brand}”升级到<span>理解品牌能力</span>"
            ),
            "summary": (
                f"AI 已能在部分问法中识别{brand}，但对场景能力的稳定认知仍不完整。应统一品牌能力框架。"
                if filter_mode == "scene"
                else f"AI 已能在部分问法中识别{brand}，但对能力边界与适用场景的稳定认知仍不完整。应统一品牌能力框架。"
            ),
        },
        "selection": {
            "label": "竞品对标",
            "title": f"短名单里，竞品是否比{brand}<span>更常被点名</span>",
            "summary": (
                f"对照已配置竞品在非品牌词回答中的共现与位次，判断{brand}是否被挤出同框。"
                "优先补可核验案例与对比口径，抢同框稳定席位。"
            ),
        },
        "procurement": {
            "label": "推荐名单",
            "title": f"{brand}已能进推荐短名单，下一步是<span>站稳前三</span>",
            "summary": (
                "优势场景具备入围说服力。下一步把最强案例绑到「推荐/哪家好」话术上。"
                if filter_mode == "scene"
                else "优势问法具备入围说服力。下一步把最强案例绑到「推荐/哪家好」话术上。"
            ),
        },
        "risk": {
            "label": "口碑评价",
            "title": "公开负向不多时，仍要补<span>可引用评价口径</span>",
            "summary": "口碑阶段看品牌词评价问法是否可引用：适用谁、不适合谁与证据链。负向共现≠质量结论。",
        },
    }
    if has_acquisition_kpi:
        for key, fallback in _default_stage_shell.items():
            if _blob_claims_no_acquisition(stage_copy.get(key)):
                stage_copy[key] = fallback
    # 2026-08-20 - 旧叙事包「技术选型/选型标准」与顶栏竞品对标错位：强制 label，错位文案回退
    for key, label in (
        ("recognition", "品牌认知"),
        ("selection", "竞品对标"),
        ("procurement", "推荐名单"),
        ("risk", "口碑评价"),
    ):
        row = stage_copy.get(key)
        if not isinstance(row, dict):
            continue
        blob = f"{row.get('label') or ''} {row.get('title') or ''} {row.get('summary') or ''}"
        if key == "selection" and (
            "选型标准" in blob or "技术选型" in blob or "选型类问题" in blob
        ):
            stage_copy[key] = dict(_default_stage_shell["selection"])
        else:
            stage_copy[key] = {**row, "label": label}    # 2026-08-14 - 无叙事包时也门禁；有叙事时 apply_narrative_scope_guards 已处理，再兜一层
    if reputation_high_risk:
        stage_copy = _sanitize_reputation_stage_copy(
            stage_copy,
            negative_rate=negative,
            sample_n=sentiment_sample_n,
        )
    # 2026-08-21 - 品牌词口碑有格时，勿把「非品牌口碑无样本」写成主结论
    stage_copy = _sanitize_risk_nonbrand_reputation_gap(
        stage_copy, brand=brand, kpi_basis=kpi_basis
    )
    # 2026-08-21 - 渲染兜底：问法提及率对齐格级举例，样本率改称回答命中率
    stage_copy = _sanitize_dual_metric_copy(
        stage_copy,
        facts={"weak_prompts": weak_ex2, "strong_prompts": strong_ex2},
    )
    # 2026-08-21 - 认知页禁把「无品牌词防守」写成无法评估口碑
    stage_copy = _sanitize_recognition_defense_scope(stage_copy)
    # 2026-08-21 - 整单无非品牌问法时，禁止各阶段反复写「非品牌XX无样本/无法评估自然获客」当缺口
    if not has_acquisition_kpi:
        for key in ("recognition", "selection", "procurement", "risk"):
            row = stage_copy.get(key)
            if not isinstance(row, dict):
                continue
            blob = f"{row.get('title') or ''}{row.get('summary') or ''}"
            if "非品牌" in blob and (
                "无样本" in blob or "样本为0" in blob or "样本为 0" in blob or "无法评估自然获客" in blob
            ):
                stage_copy[key] = dict(_default_stage_shell[key])
        cleaned_priority: list[dict[str, Any]] = []
        for item in priority or []:
            if not isinstance(item, dict):
                cleaned_priority.append(item)
                continue
            blob = f"{item.get('title') or ''}{item.get('body') or ''}"
            if "非品牌" in blob and (
                "样本为零" in blob
                or "样本为0" in blob
                or "样本为 0" in blob
                or "问法数=0" in blob
                or "问法数 = 0" in blob
                or "无法评估自然获客" in blob
            ):
                cleaned_priority.append(
                    {
                        **item,
                        "title": f"本窗仅品牌词样本，先巩固{brand}防守口径",
                        "body": (
                            f"监测事实：本窗问法均为品牌词，非品牌词获客主 KPI 按口径记为暂无数据；"
                            f"品牌词防守提及率 {_fmt_metric(brand_defense_rate, suffix='%')}。"
                            "分析判断：这是问法设计结果，不是监测失败。"
                            "优化建议：若要评估自然获客，下期补「行业+推荐/靠谱/哪家好」非品牌问法后再复测。"
                        ),
                    }
                )
            else:
                cleaned_priority.append(item)
        priority = cleaned_priority
    shell_copy = _shell_static_copy(
        brand=brand,
        filter_mode=filter_mode,
        platform_count=len(platform_rows),
        platform_labels=heat_model_names,
    )
    sources_subtitle = str(shell_copy["sources_subtitle"] or "")
    gap_note = str(shell_copy["gap_note"] or "")
    if not has_acquisition_kpi:
        # 2026-08-13 - 全品牌词信源易被当成获客覆盖 - 加口径标注
        note = "品牌词样本信源，不代表非品牌词获客信源覆盖"
        if note not in sources_subtitle:
            sources_subtitle = f"{sources_subtitle.rstrip('。')}。{note}。"
        gap_note = "暂无对标：无非品牌词样本，不能计算自然获客对标。"

    if has_acquisition_kpi:
        platforms_section_title = "模型平台表现：有认知基础，推荐稳定性仍需提升"
        platforms_section_lead = "同时比较获客提及率、负面关联和非品牌词 Top3 率，判断各平台的内容补强顺序。"
    else:
        platforms_section_title = "模型平台表现：仅覆盖品牌词防守，暂不能判断自然获客"
        platforms_section_lead = "本窗问法全部为品牌词，以下平台对比仅供品牌防守参考，不能代表自然获客可见度。"

    # 2026-08-13 - A+ 尾巴：对外只发计数器底座 + 样本观察；productAdjust 已删
    published_kpi = publish_kpi_basis(kpi_basis)
    published_sample = {
        "basis_type": "run_sample",
        "enabled": bool(sample_basis.get("enabled", True)),
        "note": str(
            sample_basis.get("note")
            or "跨日/多次运行回答命中率，仅用于稳定性观察，不参与主 KPI（提及率）"
        ),
        "brand_mention_rate": sample_basis.get("brand_mention_rate"),
        "nonbrand_mention_rate": sample_basis.get("nonbrand_mention_rate"),
        "brand_answer_hit_rate": sample_basis.get("brand_answer_hit_rate"),
        "nonbrand_answer_hit_rate": sample_basis.get("nonbrand_answer_hit_rate"),
        "sample_size": int(sample_basis.get("sample_size") or 0),
        "question_run_count": int(sample_basis.get("question_run_count") or sample_basis.get("sample_size") or 0),
        "brand_prompt_count": int(sample_basis.get("brand_prompt_count") or 0),
        "nonbrand_prompt_count": int(sample_basis.get("nonbrand_prompt_count") or 0),
        "avg_samples_per_prompt": sample_basis.get("avg_samples_per_prompt"),
    }
    stability_card = {
        "title": "稳定性观察（补充证据，不参与主 KPI）",
        "brand_mention_rate": _fmt_metric(sample_basis.get("brand_mention_rate"), suffix="%"),
        "nonbrand_mention_rate": _fmt_metric(sample_basis.get("nonbrand_mention_rate"), suffix="%"),
        "brand_prompt_count": int(sample_basis.get("brand_prompt_count") or 0),
        "nonbrand_prompt_count": int(sample_basis.get("nonbrand_prompt_count") or 0),
        "avg_samples_per_prompt": sample_basis.get("avg_samples_per_prompt"),
        "note": published_sample["note"],
        "body": (
            f"跨日回答命中率：品牌词 {_fmt_metric(sample_basis.get('brand_mention_rate'), suffix='%')}"
            f"（{int(sample_basis.get('brand_prompt_count') or 0)} 条问法"
            f"{' × 约 ' + str(sample_basis.get('avg_samples_per_prompt')) + ' 次/问' if sample_basis.get('avg_samples_per_prompt') else ''}）；"
            f"非品牌词 {_fmt_metric(sample_basis.get('nonbrand_mention_rate'), suffix='%')}。"
            f"用途：判断防守/获客稳定性，不参与顶部主 KPI。"
        ),
    }

    # 2026-08-13 - 意图轴报告禁残留户外行业词（全文字黑名单）
    if filter_mode != "scene":
        banned = ["机场", "高铁", "电梯", "户外广告"]
        if "艾迪亚" not in brand:
            banned.append("艾迪亚")

        def _clean_text(text: str) -> str:
            out = str(text or "")
            for term in banned:
                if term in out:
                    out = out.replace(term, "相关")
            return out

        def _clean_obj(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {k: _clean_obj(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_clean_obj(x) for x in obj]
            if isinstance(obj, str):
                return _clean_text(obj)
            return obj

        priority = _clean_obj(priority)
        risk_rows = _clean_obj(risk_rows)
        actions = _clean_obj(actions)
        insights = _clean_obj(insights)
        stage_copy = _clean_obj(stage_copy)
        product_focus_copy = _clean_obj(product_focus_copy)
        metric_details = _clean_obj(metric_details)
        for key in ("title", "subtitle", "intro_title", "intro_body", "nav_label"):
            if key in portfolio_section:
                portfolio_section[key] = _clean_text(str(portfolio_section.get(key) or ""))
        for key in ("title", "subtitle", "nav_label", "side_flow"):
            if key in diagnosis_section:
                diagnosis_section[key] = _clean_text(str(diagnosis_section.get(key) or ""))
        heat_detail_default = _clean_text(heat_detail_default)
        gap_note = _clean_text(gap_note)
        sources_subtitle = _clean_text(sources_subtitle)
        monitor_version_note = _clean_text(monitor_version_note)
        platforms_section_title = _clean_text(platforms_section_title)
        platforms_section_lead = _clean_text(platforms_section_lead)
        for row in shell_copy.get("audit_rows") or []:
            if isinstance(row, dict):
                row["title"] = _clean_text(str(row.get("title") or ""))
                row["desc"] = _clean_text(str(row.get("desc") or ""))
        shell_copy["roadmap_mid_title"] = _clean_text(str(shell_copy.get("roadmap_mid_title") or ""))
        shell_copy["roadmap_mid_body"] = _clean_text(str(shell_copy.get("roadmap_mid_body") or ""))
        shell_copy["methodology_slice"] = _clean_text(str(shell_copy.get("methodology_slice") or ""))
        shell_copy["sources_subtitle"] = _clean_text(str(shell_copy.get("sources_subtitle") or ""))

    # 2026-08-20 - 方案 A：platformViews 由本单格级 KPI + 原话派生，禁止桌面艾迪亚样例
    platform_views, all_priority_html = build_platform_views(
        brand=brand,
        platform_rows=platform_rows,
        platform_data=platform_data,
        stage_copy=stage_copy,
        scenarios=scenarios,
        risk_rows=risk_rows,
        actions=actions,
        evidence_chips=evidence_chips,
        gap_note=gap_note,
        priority_items=priority,
    )
    if "艾迪亚" not in brand:
        # 复用上方清洗逻辑的子集，避免切片文案带回旧客户名
        def _scrub(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {k: _scrub(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_scrub(x) for x in obj]
            if isinstance(obj, str):
                return obj.replace("艾迪亚", "相关")
            return obj

        platform_views = _scrub(platform_views)
        all_priority_html = str(all_priority_html or "").replace("艾迪亚", "相关")

    cockpit = {
        "schema_version": COCKPIT_NARRATIVE_SCHEMA,
        "brand": brand,
        "lead_context": lead_context,
        "input_context": input_context,
        "platformData": platform_data,
        "sliceLabels": slice_labels,
        "platformRows": platform_rows,
        "scenarios": scenarios,
        "modelNames": heat_model_names,
        "sources": sources,
        "metricDetails": metric_details,
        "stageCopy": stage_copy,
        "productFocusCopy": product_focus_copy,
        "risks": risk_rows,
        "actions": actions,
        "insights": insights,
        "kpi_basis": published_kpi,
        "sample_basis": published_sample,
        "stabilityCard": stability_card,
        "citationMeta": {
            "total_references": int(total_refs),
            "brand_related_references": int(brand_refs),
            "citation_rate": citation,
        },
        "platformViews": platform_views,
        "allPriorityHTML": all_priority_html,
        # 2026-08-20 - 与换皮版-G __COCKPIT__ 键对齐，供方案 A / 阶段显隐消费
        "priority": priority,
        "priority_items": priority,
        "visibleStages": ["all", "recognition", "selection", "procurement", "risk"],
    }

    # 2026-08-13 - 首屏/对标条服务端灌入，禁静态旧客户壳与「品牌 0%」
    slice_name_all = slice_labels.get("all") or ("全场景" if filter_mode == "scene" else "全部问法意图")
    hero_kicker = f"{stage_copy['all'].get('label') or '管理层摘要'} · 全平台 / {slice_name_all}"
    hero_title = str(stage_copy["all"].get("title") or f"{brand} AI 可见度诊断报告")
    hero_summary = str(
        stage_copy["all"].get("summary")
        or "报告数据加载中；若长时间未加载，请联系服务方复核导出文件。"
    )
    if has_acquisition_kpi and visibility is not None:
        gap = float(visibility) - 60.0
        benchmark_gap_number = f"{'+' if gap >= 0 else '-'}{abs(gap):.1f}"
        benchmark_gap_label = "可见度百分点差距"
        benchmark_brand_label = f"{brand} {float(visibility):.1f}%"
        benchmark_ref_label = "参考 60.0%"
        benchmark_bar_width = f"{max(0.0, min(100.0, float(visibility))):.1f}%"
        benchmark_head_display = "block"
        benchmark_head_note = "监测窗口内最强平台槽位可见度参考 60.0%（近似头部基准）"
    else:
        benchmark_gap_number = "—"
        benchmark_gap_label = "暂无对标"
        benchmark_brand_label = "暂无对标：无非品牌词样本"
        benchmark_ref_label = "不能计算自然获客对标"
        benchmark_bar_width = "0%"
        benchmark_head_display = "none"
        benchmark_head_note = "本次无非品牌词样本，暂不对标监测参考基准"

    return {
        "brand": brand,
        "company": company,
        "generated_at": generated,
        "coverage_label": coverage_label,
        # 2026-08-20 - 顶栏官网链读取入口上下文，缺省由模板回退
        "website_url": str((lead_context or {}).get("website_url") or "").strip(),
        "sample_meta": f"{sample_count} 条已完成子任务 · {len(platform_rows)} 个平台槽位 · GEO Monitor",
        "filter_mode": filter_mode,
        "lead_context": lead_context,
        "input_context": input_context,
        "hero_kicker": hero_kicker,
        "hero_title": hero_title,
        "hero_summary": hero_summary,
        "benchmark_gap_number": benchmark_gap_number,
        "benchmark_gap_label": benchmark_gap_label,
        "benchmark_brand_label": benchmark_brand_label,
        "benchmark_ref_label": benchmark_ref_label,
        "benchmark_bar_width": benchmark_bar_width,
        "benchmark_head_display": benchmark_head_display,
        "benchmark_head_note": benchmark_head_note,
        "evidence_scope": f"{len(platform_rows)} 平台 × {len(tagged)} 问法",
        "evidence_sub": " · ".join(heat_model_names),
        "evidence_chips": evidence_chips,
        "top_sources_label": top_source_names,
        "priority_items": priority,
        "product_cards": product_cards,
        "product_filter_options": product_filter_options,
        "product_focus_copy": product_focus_copy,
        "platform_filter_options": platform_filter_options,
        "heat_model_names": heat_model_names,
        "heat_detail_default": heat_detail_default,
        "portfolio_section": portfolio_section,
        "shell_copy": shell_copy,
        "platform_panel_title": shell_copy["platform_panel_title"],
        "platform_chart_aria": shell_copy["platform_chart_aria"],
        "gap_note": gap_note,
        "sources_subtitle": sources_subtitle,
        "platforms_section_title": platforms_section_title,
        "platforms_section_lead": platforms_section_lead,
        "methodology_slice": shell_copy["methodology_slice"],
        "methodology_scope": shell_copy["methodology_scope"],
        "audit_rows": shell_copy["audit_rows"],
        "roadmap_mid_title": shell_copy["roadmap_mid_title"],
        "roadmap_mid_body": shell_copy["roadmap_mid_body"],
        "heat_empty_note": shell_copy["heat_empty_note"],
        "diagnosis_section": diagnosis_section,
        "nav_portfolio_label": portfolio_section.get("nav_label") or ("场景矩阵" if filter_mode == "scene" else "问法意图矩阵"),
        "nav_diagnosis_label": diagnosis_section.get("nav_label") or ("采购场景诊断" if filter_mode == "scene" else "意图诊断"),
        "side_flow_note": diagnosis_section.get("side_flow") or "",
        "monitor_version_note": monitor_version_note,
        "score_label": "非品牌词获客提及率",
        "brand_defense_display": brand_defense_display,
        "portfolio_visibility_label": "非品牌词获客提及率",
        "portfolio_rank_label": "非品牌词平均推荐位",
        "methodology_kpi_map": (
            "主 KPI 统一问法×平台格：获客提及率=mention_cells/total_cells，"
            "均排=rank_sum/mention_cells，Top3=top3_cells/total_cells；"
            "样本级跨日回答命中率仅「稳定性观察」；负面/信源为全量辅助。"
        ),
        "portfolio_visibility": _fmt_metric(visibility, suffix="%"),
        "portfolio_rank": _fmt_metric(rank),
        "competitor_rows": competitor_rows,
        "insights": insights,
        "risk_rows": risk_rows,
        "actions": actions,
        "stability_card": stability_card,
        "kpi_basis": published_kpi,
        "sample_basis": published_sample,
        "platform_version_tag": platform_version_tag(heat_model_names),
        "cockpit_json": json.dumps(cockpit, ensure_ascii=False),
        "_facts_for_narrative": {
            "kpis": {
                "visibility": visibility,
                "rank": rank,
                "decision": decision,
                "negative": negative,
                "citation": citation,
                "brand_defense": brand_defense_rate,
            },
            "has_acquisition_kpi": has_acquisition_kpi,
            "kpi_basis": kpi_basis,
            "sample_basis": sample_basis,
            "kpi_lanes": {
                # 2026-08-13 - 格级 bd/nb 无 prompt_count，模型曾写成「防守问法数=0」却又列品牌问法
                "acquisition": {
                    **nb,
                    "prompt_count": int(sample_basis.get("nonbrand_prompt_count") or len(acquisition)),
                    "label": "非品牌词获客（格级）",
                },
                "brand_defense": {
                    **bd,
                    "prompt_count": int(sample_basis.get("brand_prompt_count") or len(defense_pool_early)),
                    "label": "品牌词防守（格级）",
                },
                "sample_stability": {
                    **sample_basis,
                    "label": "跨日样本稳定性（不参与主 KPI）",
                },
                "all": {
                    "prompt_count": len(tagged),
                    "negative_rate": negative,
                    "citation_rate": citation,
                    "label": "全量辅助",
                },
            },
            "prompt_taxonomy": [
                {
                    "prompt": p["prompt"],
                    "lane": p.get("lane"),
                    "lane_label": "品牌词" if p.get("lane") == "brand_defense" else "非品牌词",
                    "filter_dim": p.get("filter_dim"),
                    "filter_label": p.get("filter_label"),
                    "scene_label": p.get("scene_label"),
                    "intent_label": p.get("intent_label"),
                    # 2026-08-21 - mention_rate=格级；answer_hit_rate=样本，禁止混称
                    "mention_rate": (
                        _prompt_display_rate(p)
                        if p.get("cell_mention_rate") is not None
                        else _f(p.get("brand_mention_rate"), 0.0)
                    ),
                    "avg_rank": _prompt_display_rank(p),
                    "answer_hit_rate": _f(p.get("brand_mention_rate"), 0.0),
                    "sample_count": p.get("sample_count"),
                    "basis": "question_platform_cell",
                }
                for p in tagged
            ],
            # 2026-08-13 - 意图格级样本写入事实包，避免叙事写「选型无样本」却 KPI 有格
            "intent_basis": {
                str(code): {
                    "label": INTENT_LABELS.get(str(code), str(code)),
                    "nonbrand": lanes.get("nonbrand") if isinstance(lanes.get("nonbrand"), dict) else {},
                    "brand": lanes.get("brand") if isinstance(lanes.get("brand"), dict) else {},
                }
                for code, lanes in (kpi_basis.get("intents") or {}).items()
                if isinstance(lanes, dict)
            },
            "weak_prompts": _kpi_prompt_examples(tagged)[0],
            "strong_prompts": _kpi_prompt_examples(tagged)[1],
            "platform_rows": platform_rows,
            "monitored_platforms": heat_model_names,
            "platform_count": len(platform_rows),
            "platform_scope_note": build_platform_scope_note(platform_rows, for_model=True),
            "filter_mode": filter_mode,
            "competitors": competitors,
            # 2026-08-20 - 叙事必须吃到共现率，禁止只给名单却写「未见竞品同框」
            "competitor_stats": [
                {
                    "name": str(row.get("name") or "").strip(),
                    "rate": float(row.get("rate") or 0.0),
                    "hit_count": int(row.get("hit_count") or 0),
                    "sample_total": int(row.get("sample_total") or 0),
                    "origin": str(row.get("origin") or ""),
                }
                for row in competitor_stats[:12]
                if isinstance(row, dict) and str(row.get("name") or "").strip()
            ],
            "summary": summary,
            "schema": COCKPIT_NARRATIVE_SCHEMA,
        },
    }


def build_cockpit_narrative_facts(payload: dict[str, Any]) -> dict[str, Any]:
    """供 DeepSeek 生成驾驶舱叙事的压缩事实包。"""
    ctx = build_diagnosis_cockpit_context(payload)
    return ctx.get("_facts_for_narrative") or {}


def ensure_cockpit_narrative(payload: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """若缺 cockpit_narrative 且 DeepSeek 可用，生成一次并写回 payload。

    2026-08-13 - 方案 B - 预览/导出懒生成；已有包则跳过
    2026-08-13 - A+B - schema=scope-v1 或 force 时重生，避免旧包写未测平台=0
    """
    existing = payload.get("cockpit_narrative")
    schema_ok = (
        isinstance(existing, dict)
        and existing.get("stage_copy")
        and existing.get("priority_items")
        and str(existing.get("schema") or "") == COCKPIT_NARRATIVE_SCHEMA
    )
    if not force and schema_ok:
        return payload
    try:
        from app.services.deepseek_client import DeepseekClient

        client = DeepseekClient()
        if not client.report_enabled:
            return payload
        facts = build_cockpit_narrative_facts(payload)
        brand = str(payload.get("brand_name") or payload.get("tenant_name") or "品牌")
        narrative = client.generate_cockpit_narrative(brand_name=brand, facts=facts)
        payload["cockpit_narrative"] = apply_narrative_scope_guards(
            narrative, brand=brand, facts=facts
        )
    except Exception:
        # ponytail: 叙事失败不阻断 HTML；继续规则文案
        return payload
    return payload


def render_diagnosis_cockpit_html(
    payload: dict[str, Any],
    platform_names: dict[str, str] | None = None,
    *,
    theme: str = "b",
) -> str:
    _ = theme
    # 叙事包由收尾/预览 ensure 写入 payload.cockpit_narrative；此处只消费
    working = dict(payload)

    def _render_once(src: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        context = build_diagnosis_cockpit_context(src, platform_names)
        context.pop("_facts_for_narrative", None)
        env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=select_autoescape(["html", "xml"]),
        )
        html = env.get_template("report.html").render(**context)
        return html, context

    html, ctx = _render_once(working)
    brand = str(ctx.get("brand") or working.get("brand_name") or "")
    filter_mode = str(ctx.get("filter_mode") or "intent")
    issues = validate_cockpit_html_export(html, brand=brand, filter_mode=filter_mode)
    # 2026-08-13 - 叙事包若带回艾迪亚/电梯污染，丢弃叙事重渲
    if issues and working.get("cockpit_narrative"):
        working = {**working, "cockpit_narrative": None}
        html, ctx = _render_once(working)
        filter_mode = str(ctx.get("filter_mode") or filter_mode)
        issues = validate_cockpit_html_export(html, brand=brand, filter_mode=filter_mode)
    if issues:
        # 仍污染则抛出，避免把脏 HTML 交给客户
        raise ValueError(f"cockpit html export validation failed: {issues}")
    return html
