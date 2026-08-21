"""售前诊断扩展分析：对齐模力指数报告的语义词排名、提及率、信源与趋势。"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from app.models.lead_diagnosis import LeadDiagnosis, LeadDiagnosisRun
from app.models.monitor import GeoMonitorSubtask
from app.core.region_catalog import region_display_name, normalize_region_codes
from app.services.monitor_sample_metrics import SUCCESS_STATUSES
from app.services.ranking_parser import (
    normalize_structured_rankings,
    ranking_entry_explicit_rank,
    ranking_entry_name,
)


def _normalize_name_key(name: str | None) -> str:
    text = str(name or "").strip().lower()
    return re.sub(r"\s+", "", text)


_ADMIN_OR_GENERIC_PREFIXES = frozenset({
    "北京", "上海", "广州", "深圳", "杭州", "成都", "重庆", "天津", "苏州", "南京",
    "武汉", "西安", "青岛", "大连", "厦门", "宁波", "合肥", "郑州", "长沙", "济南",
    "中国", "全国", "集团", "股份", "有限", "公司", "传媒", "广告", "媒体",
})


def names_match(left: str | None, right: str | None) -> bool:
    """实体同一家：全名 / 短名子串（禁行政区两字）/ 共享 ≥3 字品牌词干。"""
    return _strict_entity_match(left, right)


def _strict_entity_match(left: str | None, right: str | None) -> bool:
    a = _normalize_name_key(left)
    b = _normalize_name_key(right)
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if shorter in longer:
        if len(shorter) >= 3:
            return True
        if len(shorter) == 2 and shorter not in _ADMIN_OR_GENERIC_PREFIXES:
            return True
    # 「艾迪亚传媒」↔「艾迪亚控股…」：共享前缀词干（须同为名称开头，禁止中缀误撞）
    if len(a) >= 3 and len(b) >= 3:
        for n in (4, 3):
            if len(a) < n or len(b) < n:
                continue
            if a[:2] in _ADMIN_OR_GENERIC_PREFIXES:
                continue
            if a[:n] == b[:n]:
                return True
    return False


def _find_entity_rank(entries: list[dict[str, Any]], entity_name: str) -> float | None:
    for entry in entries:
        if names_match(ranking_entry_name(entry), entity_name):
            rank = ranking_entry_explicit_rank(entry)
            if rank is not None:
                return float(rank)
    return None


def _entity_mentioned(entries: list[dict[str, Any]], entity_name: str) -> bool:
    return any(names_match(ranking_entry_name(entry), entity_name) for entry in entries)


def _source_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc or urlparse(f"https://{url}").netloc
    except Exception:
        return ""
    return host.lower().removeprefix("www.")


def _round_rate(mention_count: int, sample_count: int) -> float:
    if not sample_count:
        return 0.0
    return round(mention_count / sample_count * 100, 1)


def _entity_flags(name: str, brand: str, competitors: list[str]) -> dict[str, bool]:
    return {
        "is_brand": names_match(name, brand),
        "is_competitor": any(names_match(name, item) for item in competitors),
    }


def _is_tracked_entity(name: str, brand: str, competitors: list[str]) -> bool:
    if names_match(name, brand):
        return True
    return any(_strict_entity_match(name, item) for item in competitors)


def _acquisition_subtasks_for_competitor_mining(
    subtasks: list[Any],
    *,
    brand: str,
    aliases: list[str] | None = None,
    prompts: list[str] | None = None,
) -> list[Any]:
    """筛出可用于竞品共现统计的非品牌词有效样本。"""
    from app.services.report_diagnosis_cockpit_taxonomy import classify_prompt

    prompt_filter = {str(p).strip() for p in (prompts or []) if str(p).strip()} or None
    rows: list[Any] = []
    for item in subtasks or []:
        if str(getattr(item, "status", "") or "") not in SUCCESS_STATUSES:
            continue
        if not str(getattr(item, "answer_content", "") or "").strip():
            continue
        prompt = str(getattr(item, "prompt", "") or "").strip()
        if not prompt or (prompt_filter is not None and prompt not in prompt_filter):
            continue
        if classify_prompt(prompt, brand=brand, aliases=aliases).get("lane") == "acquisition":
            rows.append(item)
    return rows


def mine_competitors_from_acquisition_prompts(
    subtasks: list[Any],
    *,
    brand: str,
    aliases: list[str] | None = None,
    prompts: list[str] | None = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """从非品牌词获客问法的结构化榜挖掘竞品（频次 / 获客样本 → 共现率）。

    2026-08-14 - 驾驶舱竞品栏勿只吃建单库；主 KPI 已按获客问法，竞品同源
    """
    brand_text = str(brand or "").strip()
    alias_list = [str(x).strip() for x in (aliases or []) if str(x).strip()]
    exclude = _brand_exclude_terms(brand_text, alias_list)
    acq_rows = _acquisition_subtasks_for_competitor_mining(
        subtasks,
        brand=brand_text,
        aliases=alias_list,
        prompts=prompts,
    )

    sample_total = len(acq_rows)
    if sample_total <= 0:
        return []

    # canonical_key -> {name, hit_samples: set(id)}
    buckets: dict[str, dict[str, Any]] = {}
    for item in acq_rows:
        item_id = id(item)
        seen_keys: set[str] = set()
        entries = normalize_structured_rankings(getattr(item, "all_rankings_json", None) or [])
        for entry in entries:
            category = str(entry.get("category") or "").strip()
            if _is_non_brand_ranking_category(category):
                continue
            raw_name = ranking_entry_name(entry)
            name = _clean_mined_competitor_name(raw_name)
            if not name or not _looks_like_competitor_name(name):
                continue
            if any(names_match(name, ex) for ex in exclude if ex):
                continue
            # 本品牌短 token 子串兜底（空别名时「伟星股份 SAB」勿进竞品）
            if _name_hits_brand_token(name, exclude):
                continue
            matched_key: str | None = None
            for key, bucket in buckets.items():
                if names_match(name, bucket["name"]):
                    matched_key = key
                    break
            if matched_key is None:
                key = _normalize_name_key(name)
                if not key:
                    continue
                buckets[key] = {"name": name, "hit_samples": set()}
                matched_key = key
            else:
                buckets[matched_key]["name"] = _prefer_display_name(buckets[matched_key]["name"], name)
            if matched_key in seen_keys:
                continue
            seen_keys.add(matched_key)
            buckets[matched_key]["hit_samples"].add(item_id)

    ranked: list[dict[str, Any]] = []
    for bucket in buckets.values():
        hit_count = len(bucket["hit_samples"])
        if hit_count <= 0:
            continue
        ranked.append(
            {
                "name": bucket["name"],
                "hit_count": hit_count,
                "sample_total": sample_total,
                "rate": _round_rate(hit_count, sample_total),
            }
        )
    ranked.sort(key=lambda row: (-int(row["hit_count"]), str(row["name"])))
    return ranked[: max(1, int(limit))]


_GENERIC_BRAND_TOKENS = frozenset({
    "拉链", "品牌", "公司", "集团", "股份", "有限", "供应商", "厂家", "推荐",
    "辅料", "服饰", "服装", "系列", "市场", "国际",
})
_PRODUCT_OR_ATTR_NAMES = frozenset({
    "拉链", "纽扣", "钮扣", "花边", "织带", "衬布", "吊牌", "织唛", "缝纫线", "辅料",
    "交期", "账期", "品质", "品控", "产能", "价格", "服务", "口碑", "质量", "不良率",
    "结算方式", "品控流程", "品质能力", "产能匹配", "检测合规能力",
    "东莞", "福建", "浙江", "义乌", "广州", "上海", "北京", "石狮",
})
_COMPETITOR_NOISE_RE = re.compile(
    r"建议|标准|考察|怎么|如何|这几|以下|citation|http|www\.|市场|辅料城|园区|必看|优先|区分|推荐|采购组合|色差|我比较|产业链|羽绒服|棉服|交期|延误|经常",
    re.I,
)
_BAD_RANKING_CATEGORY_RE = re.compile(
    r"标准|步骤|流程|提醒|建议|踩坑|选型|筛选|产业集群|实操|渠道",
)


def _is_non_brand_ranking_category(category: str | None) -> bool:
    text = str(category or "").strip()
    if not text:
        return False
    return bool(_BAD_RANKING_CATEGORY_RE.search(text))


def _brand_exclude_terms(brand: str, aliases: list[str] | None) -> list[str]:
    from app.services.report_diagnosis_cockpit_taxonomy import _normalize_aliases

    terms: list[str] = []
    for raw in _normalize_aliases(brand, aliases):
        text = str(raw or "").strip()
        if text and text not in terms:
            terms.append(text)
        for token in re.findall(r"[A-Za-z]{2,}|\d*[A-Za-z]+|[一-龥]{2,}", text):
            tok = token.strip()
            if not tok or tok in _GENERIC_BRAND_TOKENS:
                continue
            if tok not in terms:
                terms.append(tok)
        # SAB伟星拉链 → 伟星 / 伟星拉：整段中文连写时仍要抠出短词干
        cn = "".join(re.findall(r"[\u4e00-\u9fff]+", text))
        for n in (2, 3):
            if len(cn) >= n:
                stem = cn[:n]
                if stem not in _GENERIC_BRAND_TOKENS and stem not in terms:
                    terms.append(stem)
    return terms


def _clean_mined_competitor_name(name: str | None) -> str:
    text = str(name or "").strip()
    if not text:
        return ""
    text = re.split(r"\[citation", text, maxsplit=1, flags=re.I)[0].strip()
    text = re.split(r"[｜|]", text, maxsplit=1)[0].strip()
    text = re.sub(r"[（(].{0,20}[）)]\s*$", "", text).strip()
    text = re.sub(r"(系列|产品线)$", "", text).strip()
    # YKK Excella → YKK：拉丁主品牌 + 产品线后缀时取首词
    m = re.match(r"^([A-Za-z][A-Za-z0-9]{1,})(?:\s+[A-Za-z0-9].*)?$", text)
    if m and (" " in text or re.search(r"[\u4e00-\u9fff]", text)):
        text = m.group(1)
    # SBS拉链 → SBS
    m2 = re.match(r"^([A-Za-z][A-Za-z0-9]{1,})[\u4e00-\u9fff]+$", text)
    if m2:
        text = m2.group(1)
    return text[:32].strip(" ·-—/")


def _looks_like_competitor_name(name: str) -> bool:
    if len(name) < 2 or len(name) > 24:
        return False
    if name in _PRODUCT_OR_ATTR_NAMES or name in _GENERIC_BRAND_TOKENS:
        return False
    if _COMPETITOR_NOISE_RE.search(name):
        return False
    if re.search(r"[，。；？！、]{2,}", name):
        return False
    if name.count(" ") >= 3:
        return False
    # 纯属性词常见后缀
    if re.fullmatch(r"[\u4e00-\u9fff]{2,6}(率|度|性|能力|流程|方式)", name):
        return False
    # 两字中文且无品牌特征：多为属性/地名（交期/色差/环保）；真两字品牌靠拉丁或 ≥3 字中文
    if re.fullmatch(r"[\u4e00-\u9fff]{2}", name):
        return False
    # 「中高端品牌」「高端品牌选辅料」一类分层标签，不是竞品主体
    if re.search(r"高端|中高|选辅料|选供应", name):
        return False
    if name.endswith("品牌") and not re.search(r"[A-Za-z]", name):
        return False
    if re.search(r"级$", name) or name.upper() in {
        "REACH", "OEKO", "GOTS", "GRS", "OEKO-TEX", "ISO", "CE", "SGS", "CNAS",
        "LOGO", "MOQ", "OEM", "ODM", "SKU", "FOB", "EXW", "QC",
    }:
        return False
    if re.search(r"[0-9%％]", name):
        return False
    if re.match(r"如果|当你|对于|关于|以下", name):
        return False
    return True


def _name_hits_brand_token(name: str, exclude: list[str]) -> bool:
    lowered = _normalize_name_key(name)
    for ex in exclude:
        token = _normalize_name_key(ex)
        if len(token) >= 2 and token in lowered:
            return True
    return False


def _prefer_display_name(current: str, candidate: str) -> str:
    """同实体优先短展示名（YKK Excella → YKK）。"""
    a = str(current or "").strip()
    b = str(candidate or "").strip()
    if not a:
        return b
    if not b:
        return a
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if shorter.casefold() in longer.casefold() and len(shorter) >= 2:
        return shorter
    return a if len(a) <= len(b) else b


def resolve_competitors_with_mining(
    subtasks: list[Any],
    *,
    brand: str,
    aliases: list[str] | None = None,
    prompts: list[str] | None = None,
    configured: list[str] | None = None,
    limit: int = 6,
) -> tuple[list[str], list[dict[str, Any]]]:
    """合并已配置竞品与非品牌词中真实出现的竞品。

    已配置竞品是诊断发起人明确要求对标的对象，不能因为本次挖掘到
    其他品牌就被覆盖；挖掘结果仅作为补充。所有展示分数都来自本次
    非品牌词样本中的实际共现率，未出现的已配置竞品保留为 0%。
    """
    mined = mine_competitors_from_acquisition_prompts(
        subtasks,
        brand=brand,
        aliases=aliases,
        prompts=prompts,
        limit=limit,
    )
    configured_names: list[str] = []
    for raw_name in configured or []:
        name = str(raw_name or "").strip()
        if name and not any(
            _normalize_name_key(name) == _normalize_name_key(existing)
            for existing in configured_names
        ):
            configured_names.append(name)

    remaining = max(0, int(limit))
    sample_total = len(
        _acquisition_subtasks_for_competitor_mining(
            subtasks,
            brand=str(brand or "").strip(),
            aliases=aliases,
            prompts=prompts,
        )
    )
    stats: list[dict[str, Any]] = []
    used_mined_indexes: set[int] = set()
    for name in configured_names[:remaining]:
        matched_index = next(
            (index for index, row in enumerate(mined) if names_match(name, str(row.get("name") or ""))),
            None,
        )
        if matched_index is None:
            stats.append(
                {
                    "name": name,
                    "hit_count": 0,
                    "sample_total": sample_total,
                    "rate": 0.0,
                    "origin": "configured",
                }
            )
            continue
        used_mined_indexes.add(matched_index)
        stats.append({**mined[matched_index], "name": name, "origin": "configured_and_mined"})

    for index, row in enumerate(mined):
        if len(stats) >= remaining:
            break
        if index in used_mined_indexes:
            continue
        stats.append({**row, "origin": "mined"})

    return [str(row["name"]) for row in stats], stats


def canonical_ranking_name(name: str, brand: str, competitors: list[str]) -> str:
    if names_match(name, brand):
        return brand
    for comp in competitors:
        if _strict_entity_match(name, comp):
            return comp
    return str(name or "").strip()


def compact_ranking_rows_for_deck(
    rows: list[dict[str, Any]],
    *,
    only_recent: bool = False,
) -> list[dict[str, Any]]:
    """报告 deck：分类强制「默认分类」，按 (类型, 品牌) 聚合；保留最近/最优/最差。"""
    if not rows:
        return []
    filtered = [
        row
        for row in rows
        if (not only_recent) or str(row.get("type_label") or "") in {"", "最近"}
    ]
    if not filtered:
        filtered = list(rows)
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for row in filtered:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        label = str(row.get("type_label") or "最近").strip() or "最近"
        key = (label, name)
        try:
            rank_val = float(str(row.get("rank_display") or "").strip() or "nan")
        except ValueError:
            rank_val = None
        prev = buckets.get(key)
        if prev is None:
            buckets[key] = {
                **row,
                "type_label": label,
                "category": "默认分类",
                "rank_display": row.get("rank_display") or "—",
                "_rank_vals": [rank_val] if rank_val is not None else [],
            }
            continue
        if rank_val is not None:
            prev.setdefault("_rank_vals", []).append(rank_val)
    out: list[dict[str, Any]] = []
    for item in buckets.values():
        vals = [v for v in item.pop("_rank_vals", []) if v is not None]
        if vals:
            rank_value = round(sum(vals) / len(vals), 1)
            item["rank_display"] = (
                str(int(rank_value)) if float(rank_value).is_integer() else str(rank_value)
            )
        item["category"] = "默认分类"
        out.append(item)
    type_order = {"最近": 0, "最近/最优": 0, "最优": 1, "最差": 2}
    out.sort(
        key=lambda row: (
            type_order.get(str(row.get("type_label") or ""), 9),
            0 if row.get("is_brand") else 1,
            float(str(row.get("rank_display") or "999") or 999),
            str(row.get("name") or ""),
        )
    )
    return out


def _mention_row(
    name: str,
    *,
    brand: str,
    competitors: list[str],
    sample_count: int,
    mention_count: int,
    ranks: list[float],
) -> dict[str, Any]:
    flags = _entity_flags(name, brand, competitors)
    return {
        "name": name,
        **flags,
        "sample_count": sample_count,
        "mention_count": mention_count,
        "mention_rate": _round_rate(mention_count, sample_count),
        "avg_rank": round(sum(ranks) / len(ranks), 1) if ranks else None,
    }


def _build_prompt_mention_table(
    rows: list[GeoMonitorSubtask],
    *,
    brand: str,
    competitors: list[str],
    aliases: list[str] | None = None,
) -> list[dict[str, Any]]:
    # 2026-08-21 - 品牌行与格级共用 resolve_subtask_brand_rank，避免样本/格级两套判定
    from app.services.lead_brand_match import matchable_brand_terms, resolve_subtask_brand_rank

    sample_count = len(rows)
    brand_name = str(brand or "").strip()
    tracked = [brand_name, *competitors] if brand_name else list(competitors)
    stats: dict[str, dict[str, Any]] = {
        name: {"mention_count": 0, "ranks": []} for name in tracked
    }
    brand_terms = matchable_brand_terms(brand_name, aliases or [])

    for item in rows:
        entries = normalize_structured_rankings(item.all_rankings_json or [])
        for name in tracked:
            if brand_name and names_match(name, brand_name):
                rank = resolve_subtask_brand_rank(item, brand_name, brand_terms)
                if rank is None:
                    continue
                stats[name]["mention_count"] += 1
                stats[name]["ranks"].append(rank)
                continue
            mentioned = _entity_mentioned(entries, name)
            rank = _find_entity_rank(entries, name)
            if not mentioned:
                continue
            stats[name]["mention_count"] += 1
            if rank is not None:
                stats[name]["ranks"].append(rank)

    table = [
        _mention_row(
            name,
            brand=brand,
            competitors=competitors,
            sample_count=sample_count,
            mention_count=stats[name]["mention_count"],
            ranks=stats[name]["ranks"],
        )
        for name in tracked
    ]
    table.sort(key=lambda row: (-row["mention_rate"], row["avg_rank"] or 999))
    return table


def _build_prompt_ranking_list(
    rows: list[GeoMonitorSubtask],
    *,
    brand: str,
    competitors: list[str],
    task_run_map: dict[str, LeadDiagnosisRun] | None = None,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    # 按诊断批次聚合，避免 max(updated_at) 毫秒差只剩一条
    if task_run_map:
        by_exec = _group_rows_by_execution(rows, task_run_map)
        if by_exec:
            latest_key = sorted(by_exec.keys(), key=_execution_sort_key)[-1]
            latest_rows = by_exec[latest_key]
        else:
            latest_rows = rows[-1:]
    else:
        latest_time = max((item.updated_at or datetime.min) for item in rows)
        # 1 分钟容差：同批平台写库时间差不致被踢掉
        latest_rows = [
            item for item in rows
            if item.updated_at and (latest_time - item.updated_at).total_seconds() <= 60
        ] or rows[-1:]
    aggregated: dict[tuple[str, str | None], dict[str, Any]] = {}
    for item in latest_rows:
        for entry in normalize_structured_rankings(item.all_rankings_json or []):
            name = ranking_entry_name(entry)
            if not name or not _is_tracked_entity(name, brand, competitors):
                continue
            category = entry.get("category")
            key = (name, category)
            rank = ranking_entry_explicit_rank(entry)
            bucket = aggregated.setdefault(
                key,
                {
                    "name": name,
                    "category": category or "默认分类",
                    "ranks": [],
                    **_entity_flags(name, brand, competitors),
                },
            )
            if rank is not None:
                bucket["ranks"].append(float(rank))
    result = []
    for bucket in aggregated.values():
        ranks = bucket["ranks"]
        result.append(
            {
                "name": bucket["name"],
                "category": bucket["category"],
                "rank": round(min(ranks), 1) if ranks else None,
                "is_brand": bucket["is_brand"],
                "is_competitor": bucket["is_competitor"],
            }
        )
    result.sort(key=lambda row: (row["rank"] is None, row["rank"] or 999))
    return result[:15]


def _format_collect_time(value: datetime | None) -> str:
    if not value:
        return "—"
    return value.strftime("%y-%m-%d %H:%M")


def _execution_key_from_run(
    run: LeadDiagnosisRun | None,
    *,
    updated_at: datetime | None = None,
) -> str:
    """批次键保留到分钟，避免同一天三次被压成一天。优先 schedule_key / 实际完成时间。"""
    if run is None:
        return updated_at.strftime("%Y-%m-%d %H:%M") if updated_at else "时间数据缺失"
    key = str(run.schedule_key or "").strip()
    # YYYYMMDD-HHMM（售前诊断常见）
    dashed = re.match(r"^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})$", key)
    if dashed:
        return (
            f"{dashed.group(1)}-{dashed.group(2)}-{dashed.group(3)} "
            f"{dashed.group(4)}:{dashed.group(5)}"
        )
    # YYYYMMDDHHMM / YYYYMMDDHHMMSS
    digits = re.sub(r"\D", "", key)
    if len(digits) >= 12:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]} {digits[8:10]}:{digits[10:12]}"
    finished = getattr(run, "finished_at", None) or getattr(run, "updated_at", None) or updated_at
    label = str(run.schedule_label or "").strip()
    if finished is not None:
        return finished.strftime("%Y-%m-%d %H:%M")
    if len(label) >= 16:
        return label[:16]
    if len(label) >= 10 and updated_at is not None:
        return f"{label[:10]} {updated_at.strftime('%H:%M')}"
    if label:
        return label
    if updated_at is not None:
        return updated_at.strftime("%Y-%m-%d %H:%M")
    return key or "时间数据缺失"


def _execution_sort_key(value: str) -> tuple[int, datetime | str]:
    text = str(value or "").strip()
    for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return (0, datetime.strptime(text[: len(datetime.now().strftime(pattern))], pattern))
        except ValueError:
            continue
    return (1, text)


def _group_rows_by_execution(
    rows: list[GeoMonitorSubtask],
    task_run_map: dict[str, LeadDiagnosisRun],
) -> dict[str, list[GeoMonitorSubtask]]:
    grouped: dict[str, list[GeoMonitorSubtask]] = {}
    for item in rows:
        run = task_run_map.get(item.task_id or "")
        execution_key = _execution_key_from_run(run, updated_at=item.updated_at)
        grouped.setdefault(execution_key, []).append(item)
    return grouped


def _day_key_from_execution(value: str) -> str:
    """执行批次键 → 自然日（YYYY-MM-DD），排名明细只按天展示。"""
    text = str(value or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return text or "时间数据缺失"


def _group_rows_by_day(
    rows: list[GeoMonitorSubtask],
    task_run_map: dict[str, LeadDiagnosisRun],
) -> dict[str, list[GeoMonitorSubtask]]:
    """按自然日合并同日多时段抓取，供排名明细均位。"""
    by_day: dict[str, list[GeoMonitorSubtask]] = {}
    for execution_key, batch in _group_rows_by_execution(rows, task_run_map).items():
        day = _day_key_from_execution(execution_key)
        by_day.setdefault(day, []).extend(batch)
    return by_day


def _tracked_day_ranks(
    batch: list[GeoMonitorSubtask],
    *,
    brand: str,
    competitors: list[str],
) -> dict[str, float]:
    """单日追踪实体均位：显式 rank 均值；品牌无榜时回退 mention_position。

    不用 normalize_structured_rankings：有 category 时会被改写成出场序，和明细表要展示的存库位次不一致。
    """
    aggregated: dict[str, list[float]] = {}
    for item in batch:
        brand_hit = False
        for entry in item.all_rankings_json or []:
            if not isinstance(entry, dict):
                continue
            name = ranking_entry_name(entry)
            if not name or not _is_tracked_entity(name, brand, competitors):
                continue
            rank = ranking_entry_explicit_rank(entry)
            if rank is None:
                continue
            canonical = canonical_ranking_name(name, brand, competitors)
            aggregated.setdefault(canonical, []).append(float(rank))
            if names_match(canonical, brand):
                brand_hit = True
        if not brand_hit and item.mention_position:
            try:
                aggregated.setdefault(brand, []).append(float(item.mention_position))
            except (TypeError, ValueError):
                pass
    return {
        name: round(sum(vals) / len(vals), 1)
        for name, vals in aggregated.items()
        if vals
    }


def _build_molizhishu_ranking_rows(
    rows: list[GeoMonitorSubtask],
    *,
    brand: str,
    competitors: list[str],
    task_run_map: dict[str, LeadDiagnosisRun],
) -> list[dict[str, Any]]:
    """最近 / 最优 / 最差：按自然日均位；分类一律「默认分类」（贴金样一词一页）。"""
    if not rows or not task_run_map:
        return []

    by_day = _group_rows_by_day(rows, task_run_map)
    day_keys = sorted(by_day.keys(), key=_execution_sort_key)
    if not day_keys:
        return []

    # 2026-08-11 - 排名明细「最优」差于「最近」- 选日与展表共用显式日均位，避免两套口径
    day_entity_ranks: dict[str, dict[str, float]] = {
        day: _tracked_day_ranks(by_day[day], brand=brand, competitors=competitors)
        for day in day_keys
    }
    # 实体 → {日: 均位}
    entity_days: dict[str, dict[str, float]] = {}
    for day, ranks in day_entity_ranks.items():
        for name, rank_value in ranks.items():
            entity_days.setdefault(name, {})[day] = rank_value

    latest_day = day_keys[-1]

    def _append(
        result: list[dict[str, Any]],
        seen: set[tuple[Any, ...]],
        *,
        name: str,
        label: str,
        day: str,
        muted: bool,
    ) -> None:
        ranks = day_entity_ranks.get(day) or {}
        if name not in ranks:
            return
        rank_value = ranks[name]
        dedupe = (label, name, rank_value, day)
        if dedupe in seen:
            return
        seen.add(dedupe)
        flags = _entity_flags(name, brand, competitors)
        rank_display = str(int(rank_value)) if float(rank_value).is_integer() else str(rank_value)
        result.append(
            {
                "name": name,
                "type_label": label,
                "type_muted": muted,
                "category": "默认分类",
                "rank_display": rank_display,
                **flags,
                "collected_at": day,
            }
        )

    # 2026-08-11 - 最优/最差按「每个品牌自己的日均」选日，避免竞品挂在本品牌最优日上出现「最差位次反而更好」
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    # 稳定顺序：本品牌优先，其余按名称
    names = sorted(
        entity_days.keys(),
        key=lambda n: (0 if names_match(n, brand) else 1, n),
    )
    for name in names:
        days = entity_days[name]
        best_day = min(days, key=days.get)
        worst_day = max(days, key=days.get)
        on_latest = latest_day in days

        if on_latest:
            label = "最近/最优" if best_day == latest_day else "最近"
            _append(result, seen, name=name, label=label, day=latest_day, muted=False)

        if best_day != latest_day or not on_latest:
            if not (on_latest and best_day == latest_day):
                _append(result, seen, name=name, label="最优", day=best_day, muted=True)

        # 最差：与最优日不同，且不是已展示的「最近」日，避免同日重复行
        if worst_day != best_day and not (on_latest and worst_day == latest_day):
            _append(result, seen, name=name, label="最差", day=worst_day, muted=False)

    type_order = {"最近": 0, "最近/最优": 0, "最优": 1, "最差": 2}
    result.sort(
        key=lambda row: (
            type_order.get(str(row.get("type_label") or ""), 9),
            0 if row.get("is_brand") else 1,
            float(str(row.get("rank_display") or "999") or 999),
            str(row.get("name") or ""),
        )
    )
    return result


def _build_date_prompt_matrix(prompt_analytics: list[dict[str, Any]]) -> dict[str, Any]:
    """按自然日汇总各语义词均位（同日多时段取均值），不展示每个抓取时点。"""
    prompts = [str(row.get("prompt") or "") for row in prompt_analytics if row.get("prompt")]
    # day -> prompt -> [ranks]
    day_map: dict[str, dict[str, list[float]]] = {}
    for prompt, block in zip(prompts, prompt_analytics):
        for point in block.get("round_trend") or []:
            label = str(point.get("schedule_label") or point.get("schedule_key") or "").strip()
            if not label:
                continue
            day_key = label[:10] if len(label) >= 10 else label
            rank = point.get("avg_rank")
            if rank is None:
                continue
            try:
                value = float(rank)
            except (TypeError, ValueError):
                continue
            day_map.setdefault(day_key, {}).setdefault(prompt, []).append(value)
    rows = []
    for day_key in sorted(day_map, key=_execution_sort_key):
        cells = []
        for prompt in prompts:
            vals = day_map[day_key].get(prompt) or []
            cells.append(round(sum(vals) / len(vals), 1) if vals else None)
        rows.append({"label": day_key, "cells": cells})
    return {"prompts": prompts, "rows": rows}


def _build_city_prompt_matrix(
    lead: LeadDiagnosis,
    subtasks: list[GeoMonitorSubtask],
    prompts: list[str],
    *,
    brand: str,
    task_region_map: dict[str, list[str] | None] | None = None,
) -> dict[str, Any]:
    completed = [item for item in subtasks if item.status in SUCCESS_STATUSES and item.answer_content]
    aliases = [str(x).strip() for x in (getattr(lead, "brand_aliases_json", None) or []) if str(x).strip()]
    grouped: dict[str, dict[str, list[GeoMonitorSubtask]]] = {}
    for item in completed:
        region = region_display_name(_subtask_region_code(item, task_region_map=task_region_map, lead=lead)) or "全部区域"
        grouped.setdefault(region, {}).setdefault(item.prompt, []).append(item)
    rows = []
    for region in sorted(grouped):
        cells = []
        for prompt in prompts:
            batch = grouped[region].get(prompt) or []
            cells.append(
                _avg_rank_for_entity_in_batch(
                    batch, brand, is_brand=True, brand_aliases=aliases
                )
                if batch
                else None
            )
        rows.append({"label": region, "cells": cells})
    return {"prompts": prompts, "rows": rows}


def _avg_rank_for_entity_in_batch(
    batch: list[GeoMonitorSubtask],
    entity_name: str,
    *,
    is_brand: bool = False,
    brand_aliases: list[str] | None = None,
) -> float | None:
    # 2026-08-21 - 品牌均排与格级共用 resolve，避免城市矩阵与热力分叉
    from app.services.lead_brand_match import matchable_brand_terms, resolve_subtask_brand_rank

    ranks: list[float] = []
    brand_terms = matchable_brand_terms(entity_name, brand_aliases or []) if is_brand else []
    for item in batch:
        if is_brand:
            rank = resolve_subtask_brand_rank(item, entity_name, brand_terms)
            if rank is not None:
                ranks.append(rank)
            continue
        entries = normalize_structured_rankings(item.all_rankings_json or [])
        mentioned = _entity_mentioned(entries, entity_name)
        rank = _find_entity_rank(entries, entity_name)
        if mentioned and rank is not None:
            ranks.append(rank)
    return round(sum(ranks) / len(ranks), 1) if ranks else None


def _tracked_entities(brand: str, competitors: list[str], *, limit: int = 4) -> list[str]:
    names = [brand]
    for name in competitors:
        cleaned = str(name).strip()
        if cleaned and not any(names_match(cleaned, existing) for existing in names):
            names.append(cleaned)
        if len(names) >= limit:
            break
    return names


def _build_prompt_round_trend(
    rows: list[GeoMonitorSubtask],
    *,
    brand: str,
    task_run_map: dict[str, LeadDiagnosisRun],
    competitors: list[str] | None = None,
) -> list[dict[str, Any]]:
    grouped = _group_rows_by_execution(rows, task_run_map)

    tracked = _tracked_entities(brand, competitors or [])
    trend: list[dict[str, Any]] = []
    for day_key in sorted(grouped.keys(), key=_execution_sort_key):
        batch = grouped[day_key]
        if not batch:
            continue
        mention_count = 0
        ranks: list[float] = []
        for item in batch:
            entries = normalize_structured_rankings(item.all_rankings_json or [])
            if _entity_mentioned(entries, brand) or item.mention_position:
                mention_count += 1
                rank = _find_entity_rank(entries, brand) or (
                    float(item.mention_position) if item.mention_position else None
                )
                if rank is not None:
                    ranks.append(rank)
        entities = {
            name: _avg_rank_for_entity_in_batch(batch, name, is_brand=names_match(name, brand))
            for name in tracked
        }
        brand_rank = entities.get(brand)
        trend.append(
            {
                "schedule_key": day_key,
                "schedule_label": day_key,
                "sample_count": len(batch),
                "mention_count": mention_count,
                "mention_rate": _round_rate(mention_count, len(batch)),
                "avg_rank": brand_rank if brand_rank is not None else (
                    round(sum(ranks) / len(ranks), 1) if ranks else None
                ),
                "entities": entities,
            }
        )
    return trend


def build_source_analysis(
    rows: list[GeoMonitorSubtask],
    *,
    brand: str,
) -> dict[str, Any]:
    from app.services.report_source_label_service import pick_site_label_from_votes

    domain_map: dict[str, dict[str, Any]] = {}
    brand_linked = 0
    total_refs = 0
    for item in rows:
        entries = normalize_structured_rankings(item.all_rankings_json or [])
        brand_mentioned = _entity_mentioned(entries, brand) or bool(item.mention_position)
        for source in item.reference_list_json or []:
            url = str(source.get("url") or source.get("site") or "").strip()
            if not url:
                continue
            total_refs += 1
            domain = _source_domain(url) or url
            bucket = domain_map.setdefault(
                domain,
                {
                    "domain": domain,
                    "count": 0,
                    "brand_related_count": 0,
                    "platforms": [],
                    "site_votes": {},
                },
            )
            bucket["count"] += 1
            if brand_mentioned:
                bucket["brand_related_count"] += 1
                brand_linked += 1
            if item.platform and item.platform not in bucket["platforms"]:
                bucket["platforms"].append(item.platform)
            # 对齐门户信源：累计引用 site 中文票
            site_raw = str(source.get("site") or "").strip()
            if site_raw:
                votes = bucket.setdefault("site_votes", {})
                votes[site_raw] = int(votes.get(site_raw) or 0) + 1

    domain_stats = sorted(domain_map.values(), key=lambda row: row["count"], reverse=True)[:15]
    for bucket in domain_stats:
        votes = dict(bucket.get("site_votes") or {})
        best = pick_site_label_from_votes(votes, brand=brand)
        if best:
            bucket["site"] = best
        # 保留 site_votes 供 enrich；体积很小
    coverage_note = (
        f"共采集 {len(rows)} 条有效回答、{total_refs} 条引用；"
        f"其中 {brand_linked} 条引用出现在品牌被提及的样本中。"
    )
    if not domain_stats:
        coverage_note = "当前样本中尚未形成可统计的引用网站分布，建议补充垂直行业内容部署。"
    return {
        "total_samples": len(rows),
        "total_references": total_refs,
        "brand_related_references": brand_linked,
        "coverage_note": coverage_note,
        "domain_stats": domain_stats,
    }


def build_rule_report_sections(
    *,
    brand: str,
    competitors: list[str],
    prompt_analytics: list[dict[str, Any]],
    source_analysis: dict[str, Any],
    kpis: dict[str, Any],
) -> dict[str, str]:
    competitor_text = "、".join(competitors) if competitors else "未配置竞品"
    visible_prompts = [row for row in prompt_analytics if row.get("brand_mention_rate", 0) > 0]
    invisible_prompts = [row for row in prompt_analytics if row.get("brand_mention_rate", 0) <= 0]

    industry = (
        f"监测覆盖 {len(prompt_analytics)} 个核心语义词，品牌为「{brand}」，竞品包括 {competitor_text}。"
        f"整体提及率 {kpis.get('mention_rate')}%，平均排名 {kpis.get('avg_rank') or '—'}，"
        "AI 回答呈现头部品牌集中、分场景露出差异明显的特征。"
    )
    if visible_prompts:
        best = min(
            visible_prompts,
            key=lambda row: (row.get("brand_avg_rank") or 999, -row.get("brand_mention_rate", 0)),
        )
        ranking = (
            f"品牌在「{best['prompt']}」表现最好，平均排名 {best.get('brand_avg_rank') or '—'}，提及率 {best.get('brand_mention_rate')}%。"
            f"但在 {len(invisible_prompts)} 个语义词中未进入推荐列表，整体仍受头部机构挤压。"
        )
    else:
        ranking = "品牌在所有监测语义词中均未进入 AI 推荐前排，需优先补齐结构化内容与第三方引用。"

    mention = (
        f"整体品牌提及率 {kpis.get('mention_rate')}%，Top3 露出率 {kpis.get('top3_rate')}%。"
        "分语义词看，头部竞品提及率通常显著高于目标品牌，说明 AI 训练语料中的品牌关联仍不足。"
    )
    source = source_analysis.get("coverage_note") or "引用信源数据不足。"
    actions = (
        "<p style=\"color:#ffcc00;font-weight:bold;\">针对不同引用网站类型的优化建议：</p>"
        "<ul>"
        "<li><strong style=\"color:#ff6666;\">垂直行业/报告类网站：</strong>"
        "发布可被 AI 引用的行业榜单、白皮书与场景选购指南。</li>"
        "<li><strong style=\"color:#ff6666;\">问答/自媒体平台：</strong>"
        "用列表/表格结构回答「哪家好」「推荐」类问题，覆盖监测语义词。</li>"
        "<li><strong style=\"color:#ff6666;\">门户/资讯站：</strong>"
        "发布品牌案例与权威数据，强化第三方背书。</li>"
        "<li><strong style=\"color:#ff6666;\">视频/内容平台：</strong>"
        "制作场景化评测短视频，标题对齐核心语义词。</li>"
        "</ul>"
    )
    return {
        "industry_analysis": industry,
        "ranking_analysis": ranking,
        "mention_analysis": mention,
        "source_analysis": source,
        "action_recommendations": actions,
    }


def _subtask_region_code(
    subtask: GeoMonitorSubtask,
    *,
    task_region_map: dict[str, list[str] | None] | None,
    lead: LeadDiagnosis,
) -> str:
    codes = (task_region_map or {}).get(subtask.task_id or "")
    if codes:
        first = str(codes[0] or "").strip()
        if first:
            return first
    fallback_codes = normalize_region_codes(lead.region_codes_json or [])
    if len(fallback_codes) == 1:
        return fallback_codes[0]
    return ""


def _build_brand_city_rankings(
    lead: LeadDiagnosis,
    subtasks: list[GeoMonitorSubtask],
    *,
    competitors: list[str] | None = None,
    task_region_map: dict[str, list[str] | None] | None = None,
) -> list[dict[str, Any]]:
    """按监测地区汇总品牌与竞品平均排名、提及率（对齐外部报告「品牌城市排名」）。"""
    completed = [
        item for item in subtasks
        if item.status in SUCCESS_STATUSES and item.answer_content
    ]
    if not completed:
        return []

    brand = lead.brand_name
    aliases = [str(x).strip() for x in (getattr(lead, "brand_aliases_json", None) or []) if str(x).strip()]
    competitor_names = competitors or [
        str(item).strip() for item in (lead.competitors_json or []) if str(item).strip()
    ]
    grouped: dict[str, list[GeoMonitorSubtask]] = {}
    for item in completed:
        region_code = _subtask_region_code(item, task_region_map=task_region_map, lead=lead)
        grouped.setdefault(region_code, []).append(item)

    blocks: list[dict[str, Any]] = []
    for region_code, rows in grouped.items():
        mention_table = _build_prompt_mention_table(
            rows, brand=brand, competitors=competitor_names, aliases=aliases
        )
        blocks.append({
            "region_code": region_code or None,
            "region_name": region_display_name(region_code),
            "sample_count": len(rows),
            "rows": mention_table,
        })
    blocks.sort(key=lambda block: (-block["sample_count"], block["region_name"]))
    return blocks


def build_lead_diagnosis_analytics(
    lead: LeadDiagnosis,
    subtasks: list[GeoMonitorSubtask],
    runs: list[LeadDiagnosisRun],
    *,
    competitors: list[str] | None = None,
    task_region_map: dict[str, list[str] | None] | None = None,
) -> dict[str, Any]:
    completed = [item for item in subtasks if item.status in SUCCESS_STATUSES and item.answer_content]
    brand = lead.brand_name
    configured = competitors or [
        str(item).strip() for item in (lead.competitors_json or []) if str(item).strip()
    ]
    prompts = [str(item).strip() for item in (lead.prompts_json or []) if str(item).strip()]
    aliases = [str(x).strip() for x in (getattr(lead, "brand_aliases_json", None) or []) if str(x).strip()]
    # 2026-08-14 - 竞品优先从获客问法榜挖掘；建单库仅兜底
    competitors, competitor_stats = resolve_competitors_with_mining(
        completed,
        brand=str(brand or "").strip(),
        aliases=aliases,
        prompts=prompts,
        configured=configured,
    )
    competitors_mined = [row for row in competitor_stats if int(row.get("hit_count") or 0) > 0]
    task_run_map = {run.task_id: run for run in (runs or []) if run.task_id}

    prompt_analytics: list[dict[str, Any]] = []
    for prompt in prompts:
        rows = [item for item in completed if item.prompt == prompt]
        mention_table = _build_prompt_mention_table(
            rows, brand=brand, competitors=competitors, aliases=aliases
        )
        brand_row = next((row for row in mention_table if row["is_brand"]), None)
        prompt_analytics.append(
            {
                "prompt": prompt,
                "sample_count": len(rows),
                "brand_mention_count": brand_row["mention_count"] if brand_row else 0,
                "brand_mention_rate": brand_row["mention_rate"] if brand_row else 0.0,
                "brand_avg_rank": brand_row["avg_rank"] if brand_row else None,
                "mention_table": mention_table,
                "ranking_list": _build_prompt_ranking_list(
                    rows, brand=brand, competitors=competitors, task_run_map=task_run_map,
                ),
                "molizhishu_ranking_rows": _build_molizhishu_ranking_rows(
                    rows,
                    brand=brand,
                    competitors=competitors,
                    task_run_map=task_run_map,
                ),
                "round_trend": _build_prompt_round_trend(
                    rows,
                    brand=brand,
                    competitors=competitors,
                    task_run_map=task_run_map,
                ),
            }
        )

    source_analysis = build_source_analysis(completed, brand=brand)
    rank_trend = _build_prompt_round_trend(
        completed,
        brand=brand,
        competitors=competitors,
        task_run_map=task_run_map,
    )
    tracked = _tracked_entities(brand, competitors)
    brand_city_rankings = _build_brand_city_rankings(
        lead,
        subtasks,
        competitors=competitors,
        task_region_map=task_region_map,
    )
    brand_date_matrix = _build_date_prompt_matrix(prompt_analytics)
    brand_city_matrix = _build_city_prompt_matrix(
        lead,
        subtasks,
        prompts,
        brand=brand,
        task_region_map=task_region_map,
    )
    return {
        "prompt_analytics": prompt_analytics,
        "source_analysis": source_analysis,
        "rank_trend": rank_trend,
        "tracked_entities": tracked,
        "competitors": competitors,
        "competitors_mined": competitors_mined,
        "competitor_stats": competitor_stats,
        "brand_city_rankings": brand_city_rankings,
        "brand_date_matrix": brand_date_matrix,
        "brand_city_matrix": brand_city_matrix,
    }


def refresh_daily_rank_fields_in_diagnosis_result(
    lead: LeadDiagnosis,
    subtasks: list[GeoMonitorSubtask],
    result: dict[str, Any],
    *,
    competitors: list[str] | None = None,
    task_region_map: dict[str, list[str] | None] | None = None,
) -> dict[str, Any]:
    """用现算「按天均位」覆盖快照中的排名明细与日期矩阵。

    诊断 finalize 时写入的 monitor_snapshot 会过期；导出若直读快照会继续带 16:30 时段。
    """
    if not isinstance(result, dict):
        return result
    analytics = build_lead_diagnosis_analytics(
        lead,
        subtasks,
        list(lead.runs or []),
        competitors=competitors,
        task_region_map=task_region_map,
    )
    snap = result.setdefault("monitor_snapshot", {})
    if not isinstance(snap, dict):
        snap = {}
        result["monitor_snapshot"] = snap
    live_by_prompt = {
        str(block.get("prompt") or ""): block
        for block in (analytics.get("prompt_analytics") or [])
        if str(block.get("prompt") or "").strip()
    }
    refreshed: list[dict[str, Any]] = []
    for block in snap.get("prompt_analytics") or []:
        if not isinstance(block, dict):
            continue
        prompt = str(block.get("prompt") or "")
        live = live_by_prompt.get(prompt)
        if live is None:
            refreshed.append(block)
            continue
        updated = dict(block)
        updated["molizhishu_ranking_rows"] = list(live.get("molizhishu_ranking_rows") or [])
        updated["ranking_list"] = list(live.get("ranking_list") or [])
        updated["round_trend"] = list(live.get("round_trend") or [])
        refreshed.append(updated)
    if refreshed:
        snap["prompt_analytics"] = refreshed
    snap["brand_date_matrix"] = analytics.get("brand_date_matrix") or snap.get("brand_date_matrix") or {}
    snap["rank_trend"] = analytics.get("rank_trend") or snap.get("rank_trend") or []
    snap["brand_city_matrix"] = analytics.get("brand_city_matrix") or snap.get("brand_city_matrix") or {}
    snap["brand_city_rankings"] = (
        analytics.get("brand_city_rankings") or snap.get("brand_city_rankings") or []
    )
    # 2026-08-14 - 导出刷新时同步挖掘竞品，旧 ready 单不必整单重跑汇总
    competitors = list(analytics.get("competitors") or [])
    competitor_stats = list(analytics.get("competitor_stats") or [])
    competitors_mined = list(analytics.get("competitors_mined") or [])
    result["competitors"] = competitors
    result["competitor_stats"] = competitor_stats
    result["competitors_mined"] = competitors_mined
    snap["competitors"] = competitors
    snap["competitor_stats"] = competitor_stats
    snap["competitors_mined"] = competitors_mined
    return result
