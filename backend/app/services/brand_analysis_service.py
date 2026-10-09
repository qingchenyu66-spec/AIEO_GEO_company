"""Brand analysis dashboard: DeepSeek sentiment/description + platform buckets."""

from __future__ import annotations

import json
import logging
import re
import hashlib
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, load_only
from sqlalchemy.orm.attributes import flag_modified

from app.api.dependencies import CurrentSession
from app.models.monitor import GeoMonitorScheduleRun, GeoMonitorSubtask, GeoMonitorTask
from app.core.platform_order import sort_platform_codes
from app.services.brand_service import (
    get_brand_asset,
    keyword_group_platforms,
    list_brand_word_groups,
    tenant_purchased_platforms,
)
from app.services.deepseek_client import DeepseekApiError, DeepseekClient
from app.services.monitor_service import (
    _answer_excerpt,
    _hydrate_subtasks_in_id_order,
    _normalize_sentiment_label,
    _ordered_subtask_ids,
    _resolve_workspace_brief_tenant_id,
    _subtask_answer_plaintext,
)
from app.services.molizhishu_catalog_service import get_supported_platform_catalog
from app.services.media_proxy_service import public_screenshot_url

logger = logging.getLogger(__name__)

# 2026-07-28 - 正负面：v2 过严正面归零；v3 适中口径，打开页会重判
BA_SENTIMENT_SOURCE = "deepseek-v3"
# 2026-07-30 - 竞品情绪趋势：模力近全中性 - 无 DeepSeek 时用规则二次标，source 独立勿冒充 LLM
BA_SENTIMENT_RULE_SOURCE = "rule-v1"
# 2026-07-29 - 要点级情感 deepseek-v3；旧 v2 无 sentiment 字段视为未抽，打开页 parse 会重抽
# （已弃用 v2 仅字符串列表：组标签继承整段情感，吊销要点会被并进正面）
BA_DESC_SOURCE = "deepseek-v3"
BA_SENTIMENT_BATCH = 12
BA_SENTIMENT_MAX_PER_REQUEST = 24
BA_DESC_BATCH = 10
BA_DESC_MAX_PER_REQUEST = 24
SENTIMENT_KEYS = ("positive", "neutral", "negative")
# 软上限 8（prompt 引导）；确有更多独立要点可到硬上限 16
BA_DESC_SOFT_MAX = 8
BA_DESC_HARD_MAX = 16
# ponytail: SequenceMatcher on short CN text; 0.60 + LCS 门闩合并近义、少误并不同业务点。
# Ceiling: 仍可能漏并换词大的近义；upgrade path: embedding / DeepSeek cluster.
BA_DESC_SIMILARITY = 0.60
# 2026-07-30 - 品牌分析首屏 ~11s - 近义合并改 bigram 候选，避免 400+ 桶 O(n²) 全比
# 2026-09-07 - 上期+本期双次归并再拖到 ~8s - 候选帽再收，上期改精确计数
BA_DESC_MERGE_CANDIDATE_CAP = 12
BA_DESC_LCS_NEED = 6
# 列表接口每组最多嵌套多少条 answers（sample_count 仍计全量）
BA_DESC_ANSWERS_IN_LIST = 40
_DESC_PUNCT_RE = re.compile(r"[\s、。，；：！？\"'“”‘’（）()\[\]【】《》·\-—_/\\|＋+]+")
# 2026-07-29 - 工商/合规硬风险：归并禁与非风险并，旧数据无要点情感时回退为负面
_RISK_DESC_RE = re.compile(
    r"吊销|注销|撤销登记|经营异常|列入异常|行政处罚|严重违法|失信被执行|"
    r"强制清算|不具备合法经营|风险极高|被处罚|弄虚作假|营业执照被"
)
# 2026-08-04 - 「无行政处罚」误命中风险词 - 否定前缀清风险
_CLEARED_RISK_RE = re.compile(
    r"(?:无|未|没有|并无|无任何|暂无|不存在|未见)"
    r"[^。；;！!？?]{0,16}?"
    r"(?:吊销|注销|撤销登记|经营异常|列入异常|行政处罚|严重违法|失信|处罚|强制清算)"
)
# 2026-08-04 - 纯主体/业务介绍勿因整段负面误标（勿用「有限公司」等泛匹配）
_ENTITY_FACT_RE = re.compile(
    r"(?:核心主体|成立于|总部位于|注册资本|一站式(?:解决方案)?|主营业务|"
    r"提供.{2,24}(?:解决方案|服务))"
)
_NEG_EVAL_CUE_RE = re.compile(
    r"(?:不推荐|避雷|投诉|翻车|坑|虚假|欺诈|差评|槽点|硬伤|割韭菜|被处罚|弄虚作假)"
)


def _platform_name_map() -> dict[str, str]:
    return {
        str(item.get("code") or ""): str(item.get("name") or item.get("code") or "")
        for item in get_supported_platform_catalog()
    }


def _brand_word_group_platforms(db: Session, tenant_id: int) -> list[str]:
    """启用中的品牌词组勾选平台汇总。"""
    asset = get_brand_asset(db, tenant_id)
    union: set[str] = set()
    for group in list_brand_word_groups(db, tenant_id):
        if not group.status or group.deleted:
            continue
        union.update(keyword_group_platforms(group, asset))
    return sort_platform_codes(list(union)) if union else []


def _purchased_platforms_for_brand_words(db: Session, tenant_id: int) -> list[str]:
    """品牌分析「已购」展示：监测词组优先；仅品牌词企业回退品牌词组勾选。

    2026-08-28 - 载望升学无监测词组时已购显示 0 - 品牌词组有端仍回退，勿用空已购误导
    """
    asset = get_brand_asset(db, tenant_id)
    geo = tenant_purchased_platforms(db, tenant_id, asset) if asset else []
    if geo:
        return geo
    return _brand_word_group_platforms(db, tenant_id)


def _has_deepseek_sentiment(subtask: GeoMonitorSubtask) -> bool:
    raw = subtask.raw_result_json if isinstance(subtask.raw_result_json, dict) else {}
    return str(raw.get("_ba_sentiment_source") or "") == BA_SENTIMENT_SOURCE


def _has_secondary_sentiment(subtask: GeoMonitorSubtask) -> bool:
    """DeepSeek 或规则二次标均算已解析（竞品趋势优先用二次标）。"""
    raw = subtask.raw_result_json if isinstance(subtask.raw_result_json, dict) else {}
    return str(raw.get("_ba_sentiment_source") or "") in {BA_SENTIMENT_SOURCE, BA_SENTIMENT_RULE_SOURCE}


def _mark_deepseek_sentiment(subtask: GeoMonitorSubtask, sentiment: str) -> None:
    raw = dict(subtask.raw_result_json) if isinstance(subtask.raw_result_json, dict) else {}
    raw["_ba_sentiment_source"] = BA_SENTIMENT_SOURCE
    raw["_ba_sentiment"] = sentiment
    subtask.raw_result_json = raw
    flag_modified(subtask, "raw_result_json")
    subtask.sentiment = sentiment


def _mark_rule_sentiment(subtask: GeoMonitorSubtask, sentiment: str) -> None:
    raw = dict(subtask.raw_result_json) if isinstance(subtask.raw_result_json, dict) else {}
    raw["_ba_sentiment_source"] = BA_SENTIMENT_RULE_SOURCE
    raw["_ba_sentiment"] = sentiment
    subtask.raw_result_json = raw
    flag_modified(subtask, "raw_result_json")
    subtask.sentiment = sentiment


_RULE_NEG_RE = re.compile(
    r"吊销|注销|经营异常|行政处罚|失信|投诉|翻车|不推荐|避雷|虚假|欺诈|风险极高|严重违法"
)
_RULE_POS_RE = re.compile(
    r"推荐|首选|领先|优势|口碑好|值得信赖|王牌|开创|专精特新|头部品牌|优质|认可"
)


def rule_classify_brand_sentiment(text: str, brand_name: str | None = None) -> str:
    """轻量规则二次情感；无 API 时兜底。有品牌名时要求正文出现品牌片段才抬正/负。"""
    body = str(text or "")
    if len(body.strip()) < 8:
        return "neutral"
    brand = str(brand_name or "").strip()
    if brand and len(brand) >= 2:
        # 公司全称过长时用前 4 字做弱提及判断
        needle = brand[:4] if len(brand) >= 4 else brand
        if needle not in body and brand not in body:
            return "neutral"
    neg = len(_RULE_NEG_RE.findall(body))
    pos = len(_RULE_POS_RE.findall(body))
    if neg > pos and neg > 0:
        return "negative"
    if pos > neg and pos > 0:
        return "positive"
    return "neutral"


def effective_monitor_sentiment(subtask: GeoMonitorSubtask) -> str | None:
    """竞品/洞察读口径：二次标（DeepSeek>规则）优先，否则模力原标。"""
    raw = subtask.raw_result_json if isinstance(subtask.raw_result_json, dict) else {}
    source = str(raw.get("_ba_sentiment_source") or "")
    secondary = str(raw.get("_ba_sentiment") or "").strip().lower()
    if source == BA_SENTIMENT_SOURCE and secondary in SENTIMENT_KEYS:
        return secondary
    if source == BA_SENTIMENT_RULE_SOURCE and secondary in SENTIMENT_KEYS:
        return secondary
    text = str(subtask.sentiment or "").strip().lower()
    mapping = {
        "positive": "positive",
        "negative": "negative",
        "neutral": "neutral",
        "正向": "positive",
        "负向": "negative",
        "中立": "neutral",
        "正面": "positive",
        "负面": "negative",
        "中性": "neutral",
    }
    return mapping.get(text)


def _has_deepseek_description(subtask: GeoMonitorSubtask) -> bool:
    raw = subtask.raw_result_json if isinstance(subtask.raw_result_json, dict) else {}
    return str(raw.get("_ba_description_source") or "") == BA_DESC_SOURCE


def _normalize_description_list(items: list[Any] | None) -> list[str]:
    """清洗要点列表：去空、截断、去重；硬上限 BA_DESC_HARD_MAX。"""
    return [row["text"] for row in _normalize_description_items(items)]


def _sentiment_key_from_any(raw: str | None) -> str:
    label = _normalize_sentiment_label(raw)
    return {
        "正面": "positive",
        "中性": "neutral",
        "负面": "negative",
    }.get(label, "unknown")


def _is_cleared_risk_description(text: str) -> bool:
    """「无行政处罚 / 未列入异常」等否定合规表述，不算硬风险。"""
    return bool(_CLEARED_RISK_RE.search(str(text or "")))


def _is_risk_description(text: str) -> bool:
    s = str(text or "")
    # 2026-08-04 - 先排除否定合规，再匹配风险词
    if _is_cleared_risk_description(s):
        return False
    return bool(_RISK_DESC_RE.search(s))


def _is_neutral_entity_fact(text: str) -> bool:
    """主体/业务介绍且无负向评价线索 → 宜中性。"""
    s = str(text or "")
    if not s or _is_risk_description(s) or _NEG_EVAL_CUE_RE.search(s):
        return False
    return bool(_ENTITY_FACT_RE.search(s))


def _normalize_description_items(
    items: list[Any] | None,
    *,
    fallback_sentiment: str | None = None,
) -> list[dict[str, str]]:
    """清洗要点：支持 str 或 {text/description, sentiment}；硬上限 BA_DESC_HARD_MAX。"""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    fallback = (fallback_sentiment or "").strip().lower()
    if fallback not in SENTIMENT_KEYS:
        fallback = "unknown"
    for item in items or []:
        sentiment = fallback
        explicit = False
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("description") or "").strip()
            raw_sent = str(item.get("sentiment") or "").strip().lower()
            if raw_sent in SENTIMENT_KEYS:
                sentiment = raw_sent
                explicit = True
        else:
            text = str(item or "").strip()
        text = re.sub(r"\s+", "", text)
        if len(text) < 4:
            continue
        if len(text) > 60:
            text = text[:60]
        key = _normalize_description_key(text)
        if not key or key in seen:
            continue
        # 2026-07-29 - 风险要点强制负面，避免整段正面污染单条标签
        if _is_risk_description(text):
            sentiment = "negative"
        elif _is_cleared_risk_description(text):
            # 2026-08-04 - 「无行政处罚」勿强制/保留负面
            if sentiment == "negative":
                sentiment = "neutral"
        elif not explicit and sentiment == "negative" and not _is_risk_description(text):
            # 2026-08-04 - 非风险要点勿继承整段负面
            sentiment = "neutral"
        elif explicit and sentiment == "negative" and _is_neutral_entity_fact(text):
            # 2026-08-04 - LLM 把公司介绍标负 - 读为中性
            sentiment = "neutral"
        seen.add(key)
        out.append({"text": text, "sentiment": sentiment})
        if len(out) >= BA_DESC_HARD_MAX:
            break
    return out


def _ba_descriptions(subtask: GeoMonitorSubtask) -> list[str]:
    """读多条要点；兼容旧字段单句 _ba_description。"""
    return [row["text"] for row in _ba_description_items(subtask)]


def _ba_description_items(subtask: GeoMonitorSubtask) -> list[dict[str, str]]:
    """读要点+情感；无 _ba_description_items 时用旧字符串列表 + 父情感/风险回退。"""
    raw = subtask.raw_result_json if isinstance(subtask.raw_result_json, dict) else {}
    parent = _sentiment_key_from_any(
        str(raw.get("_ba_sentiment") or subtask.sentiment or "") or None
    )
    stored = raw.get("_ba_description_items")
    if isinstance(stored, list) and stored:
        return _normalize_description_items(stored, fallback_sentiment=parent)
    multi = raw.get("_ba_descriptions")
    if isinstance(multi, list) and multi:
        return _normalize_description_items(multi, fallback_sentiment=parent)
    single = str(raw.get("_ba_description") or "").strip()
    return _normalize_description_items([single] if single else [], fallback_sentiment=parent)


def _ba_description(subtask: GeoMonitorSubtask) -> str:
    rows = _ba_description_items(subtask)
    return rows[0]["text"] if rows else ""


def _mark_deepseek_description(subtask: GeoMonitorSubtask, description: str) -> None:
    _mark_deepseek_descriptions(subtask, [description] if description else [])


def _mark_deepseek_descriptions(subtask: GeoMonitorSubtask, descriptions: list[Any]) -> None:
    parent = _sentiment_key_from_any(subtask.sentiment)
    cleaned = _normalize_description_items(descriptions, fallback_sentiment=parent)
    raw = dict(subtask.raw_result_json) if isinstance(subtask.raw_result_json, dict) else {}
    texts = [row["text"] for row in cleaned]
    raw["_ba_description_source"] = BA_DESC_SOURCE
    raw["_ba_descriptions"] = texts
    raw["_ba_description_items"] = cleaned
    # 兼容旧读者：首条仍写单字段
    raw["_ba_description"] = texts[0] if texts else ""
    subtask.raw_result_json = raw
    flag_modified(subtask, "raw_result_json")


def _normalize_description_key(text: str) -> str:
    s = _DESC_PUNCT_RE.sub("", str(text or "").strip().lower())
    s = s.replace("全媒体", "全媒")
    return s


def _brand_aliases(*names: str | None) -> list[str]:
    """品牌/公司名变体，供去主体后再比相似。"""
    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        text = str(name or "").strip()
        if not text:
            continue
        variants = [text]
        for suf in ("股份有限公司", "有限责任公司", "有限公司", "集团有限公司", "集团"):
            if text.endswith(suf) and len(text) > len(suf) + 1:
                variants.append(text[: -len(suf)])
        for item in variants:
            key = _normalize_description_key(item)
            if len(key) < 2 or key in seen:
                continue
            seen.add(key)
            out.append(item)
    out.sort(key=lambda x: len(_normalize_description_key(x)), reverse=True)
    return out


def _core_description_key(text: str, brand_aliases: list[str] | None = None) -> str:
    """去掉主体名壳后再比相似，避免「同公司不同事实」靠长前缀误并。"""
    s = _normalize_description_key(text)
    if not s:
        return ""
    for alias in brand_aliases or []:
        na = _normalize_description_key(alias)
        if len(na) >= 4 and na in s:
            s = s.replace(na, "")
            continue
        # 艾迪亚控股集团有限公司 ↔ 艾迪亚北京控股集团有限公司
        m = re.match(
            r"^(.+?)((?:控股)?集团有限公司|股份有限公司|有限责任公司|有限公司)$",
            na,
        )
        if m and len(m.group(1)) >= 2:
            pat = re.compile(re.escape(m.group(1)) + r".{0,6}" + re.escape(m.group(2)))
            s = pat.sub("", s)
    return s


def _description_similarity(a: str, b: str) -> float:
    na = _normalize_description_key(a)
    nb = _normalize_description_key(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def _lcs_run_len(a: str, b: str, *, need: int = BA_DESC_LCS_NEED) -> int:
    """最长连续公共子串长度（短中文要点够用）；达到 need 可提前结束。"""
    if not a or not b:
        return 0
    if need <= 0:
        need = BA_DESC_LCS_NEED
    prev = [0] * (len(b) + 1)
    best = 0
    for ca in a:
        cur = [0] * (len(b) + 1)
        for j, cb in enumerate(b, start=1):
            if ca == cb:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
                    if best >= need:
                        return best
        prev = cur
    return best


def _char_bigrams(text: str) -> set[str]:
    if not text:
        return set()
    if len(text) < 2:
        return {text}
    return {text[i : i + 2] for i in range(len(text) - 1)}


def _descriptions_similar(
    a: str,
    b: str,
    *,
    threshold: float = BA_DESC_SIMILARITY,
    brand_aliases: list[str] | None = None,
    core_a: str | None = None,
    core_b: str | None = None,
) -> bool:
    """近义合并：全等直接并；其余在去主体名后比；风险/非风险互不并。"""
    na = _normalize_description_key(a)
    nb = _normalize_description_key(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # 2026-07-29 - 吊销等硬风险不得与成立/资质类非风险并成一组
    if _is_risk_description(a) != _is_risk_description(b):
        return False
    ca = core_a if core_a is not None else _core_description_key(a, brand_aliases)
    cb = core_b if core_b is not None else _core_description_key(b, brand_aliases)
    # 去主体后过短：只靠公司名撞车，不并
    if len(ca) < 4 or len(cb) < 4:
        return False
    shorter, longer = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
    # 2026-07-28 - 「总部位于北京」vs「2008年成立总部位于北京」类包含句应合并
    if len(shorter) >= 6 and shorter in longer:
        return True
    # 长度差过大且无包含关系时，近义概率极低，跳过昂贵比对
    if min(len(ca), len(cb)) / max(len(ca), len(cb)) < 0.45:
        return False
    ratio = SequenceMatcher(None, ca, cb).ratio()
    if ratio >= 0.85:
        return True
    if ratio < threshold:
        return False
    # 2026-07-28 - 0.60~0.85 易把短视频/户外等不同要点并掉 - 加连续公共子串门闩
    return _lcs_run_len(ca, cb, need=BA_DESC_LCS_NEED) >= BA_DESC_LCS_NEED


def _dominant_sent_key(
    tally: dict[str, int],
    *,
    prefer_any_negative: bool = False,
) -> str:
    if not tally:
        return "unknown"
    # 2026-07-29 - 硬风险组：有负面则优先负面，避免多数正面盖住风险
    # 2026-08-04 - 非风险组改多数决，避免中性介绍被单条负面拖黑
    if prefer_any_negative and int(tally.get("negative") or 0) > 0:
        return "negative"
    tie = {"negative": 3, "positive": 2, "neutral": 1, "unknown": 0}
    return max(tally.items(), key=lambda kv: (kv[1], tie.get(kv[0], 0)))[0]


def _sentiments_mergeable(a: str, b: str) -> bool:
    """正/负不互并；中性/未知可与任一侧合并。"""
    if a == b:
        return True
    hard = {"positive", "negative"}
    return a not in hard or b not in hard


def _merge_similar_description_buckets(
    buckets: list[dict[str, Any]],
    *,
    threshold: float = BA_DESC_SIMILARITY,
    brand_aliases: list[str] | None = None,
) -> list[dict[str, Any]]:
    if len(buckets) <= 1:
        return buckets
    parent = list(range(len(buckets)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    # 预计算 core + bigram 倒排，只对共享字串的候选做近义比对（O(n·k) 代替 O(n²)）
    cores = [_core_description_key(str(b.get("description") or ""), brand_aliases) for b in buckets]
    # 归并候选用组标签：风险组仍「有负即负」，非风险多数决
    sent_keys = [
        _dominant_sent_key(
            b["_sent_tally"],
            prefer_any_negative=_is_risk_description(str(b.get("description") or "")),
        )
        for b in buckets
    ]
    gram_lists = [list(_char_bigrams(core) or ({core[:1]} if core else set())) for core in cores]
    gram_index: dict[str, list[int]] = {}
    for i, grams in enumerate(gram_lists):
        for gram in grams:
            gram_index.setdefault(gram, []).append(i)

    cap = max(8, int(BA_DESC_MERGE_CANDIDATE_CAP))
    for i in range(len(buckets)):
        core = cores[i]
        if not core:
            continue
        share_count: dict[int, int] = {}
        for gram in gram_lists[i]:
            for j in gram_index.get(gram, ()):
                if j > i:
                    share_count[j] = share_count.get(j, 0) + 1
        # 长句要求 ≥2 个 bigram 重叠，砍掉「的/公司」类弱碰撞；短句仍放宽
        min_share = 2 if len(core) >= 8 else 1
        cand = [j for j, cnt in share_count.items() if cnt >= min_share]
        if not cand:
            continue
        if len(cand) > cap:
            cand = sorted(
                cand,
                key=lambda j: (-share_count[j], abs(len(cores[j]) - len(core)), j),
            )[:cap]
        else:
            cand.sort()
        sent_i = sent_keys[i]
        desc_i = buckets[i]["description"]
        for j in cand:
            if not _sentiments_mergeable(sent_i, sent_keys[j]):
                continue
            if _descriptions_similar(
                desc_i,
                buckets[j]["description"],
                threshold=threshold,
                brand_aliases=brand_aliases,
                core_a=core,
                core_b=cores[j],
            ):
                union(i, j)

    merged: dict[int, dict[str, Any]] = {}
    for index, bucket in enumerate(buckets):
        root = find(index)
        target = merged.get(root)
        if target is None:
            merged[root] = {
                "description": bucket["description"],
                "answers": list(bucket["answers"]),
                "_sent_tally": dict(bucket["_sent_tally"]),
                "_platforms": set(bucket["_platforms"]),
            }
            continue
        # 近义组合并时按 subtask 去重，避免多样本要点并组后样本数虚高
        existing = {str(a.get("subtask_id") or "") for a in target["answers"]}
        for answer in bucket["answers"]:
            sid = str(answer.get("subtask_id") or "")
            if sid and sid in existing:
                continue
            target["answers"].append(answer)
            if sid:
                existing.add(sid)
            label = str(answer.get("sentiment") or "")
            sent_key = {
                "正面": "positive",
                "中性": "neutral",
                "负面": "negative",
            }.get(label, "unknown")
            # 上面跳过重复后才加 tally；用 answers 情感近似（与分组时一致）
            tally = target["_sent_tally"]
            tally[sent_key] = int(tally.get(sent_key, 0)) + 1
            code = str(answer.get("platform") or "").strip()
            if code:
                target["_platforms"].add(code)
        if len(str(bucket["description"])) > len(str(target["description"])):
            target["description"] = bucket["description"]
    return list(merged.values())


def preserve_brand_analysis_sentiment_on_upsert(
    subtask: GeoMonitorSubtask,
    incoming: dict[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    """同步远端时保留 DeepSeek/规则二次解析结果（情感 + AI 描述）。返回 (sentiment, raw_json)。"""
    prev = subtask.raw_result_json if isinstance(subtask.raw_result_json, dict) else {}
    prev_source = str(prev.get("_ba_sentiment_source") or "")
    keep = prev_source in {BA_SENTIMENT_SOURCE, BA_SENTIMENT_RULE_SOURCE}
    kept_value = str(prev.get("_ba_sentiment") or subtask.sentiment or "").strip().lower()
    raw = dict(incoming) if isinstance(incoming, dict) else {}
    remote_sentiment = incoming.get("sentiment") if isinstance(incoming, dict) else None
    if keep and kept_value in SENTIMENT_KEYS:
        raw["_ba_sentiment_source"] = prev_source
        raw["_ba_sentiment"] = kept_value
        sentiment_out: str | None = kept_value
    else:
        sentiment_out = str(remote_sentiment).strip() if remote_sentiment is not None else None
    if str(prev.get("_ba_description_source") or "") == BA_DESC_SOURCE:
        raw["_ba_description_source"] = BA_DESC_SOURCE
        raw["_ba_description"] = str(prev.get("_ba_description") or "").strip()
        prev_multi = prev.get("_ba_descriptions")
        prev_items = prev.get("_ba_description_items")
        if isinstance(prev_items, list) and prev_items:
            cleaned_items = _normalize_description_items(
                prev_items,
                fallback_sentiment=kept_value if keep else None,
            )
            raw["_ba_description_items"] = cleaned_items
            raw["_ba_descriptions"] = [row["text"] for row in cleaned_items]
            if cleaned_items:
                raw["_ba_description"] = cleaned_items[0]["text"]
        elif isinstance(prev_multi, list):
            cleaned_items = _normalize_description_items(
                prev_multi,
                fallback_sentiment=kept_value if keep else None,
            )
            raw["_ba_descriptions"] = [row["text"] for row in cleaned_items]
            raw["_ba_description_items"] = cleaned_items
        elif raw["_ba_description"]:
            cleaned_items = _normalize_description_items(
                [raw["_ba_description"]],
                fallback_sentiment=kept_value if keep else None,
            )
            raw["_ba_descriptions"] = [row["text"] for row in cleaned_items]
            raw["_ba_description_items"] = cleaned_items
    return sentiment_out, raw


def parse_brand_word_sentiments_with_deepseek(
    db: Session,
    *,
    tenant_id: int,
    brand_name: str,
    subtasks: list[GeoMonitorSubtask],
    max_items: int = BA_SENTIMENT_MAX_PER_REQUEST,
    upgrade_rule: bool = True,
) -> dict[str, Any]:
    """对尚未二次解析的回答调用 DeepSeek，写回 sentiment；无 Key 时规则兜底。"""
    client = DeepseekClient()
    pending: list[GeoMonitorSubtask] = []
    for item in subtasks:
        # DeepSeek 已标跳过；规则标默认可升级，竞品读路径可关以免反复打 LLM
        if _has_deepseek_sentiment(item):
            continue
        if not upgrade_rule and _has_secondary_sentiment(item):
            continue
        if not _subtask_answer_plaintext(item).strip():
            continue
        pending.append(item)
        if len(pending) >= max_items:
            break

    if not pending:
        left = sum(
            1
            for item in subtasks
            if (
                (not _has_deepseek_sentiment(item) if upgrade_rule else not _has_secondary_sentiment(item))
                and _subtask_answer_plaintext(item).strip()
            )
        )
        return {"parsed": 0, "pending_left": left, "errors": [], "source": "none"}

    if not client.api_key:
        # 2026-07-30 - 无 DeepSeek Key 时规则二次标，避免竞品趋势长期锁死模力中性
        for item in pending:
            sentiment = rule_classify_brand_sentiment(
                _subtask_answer_plaintext(item),
                brand_name,
            )
            _mark_rule_sentiment(item, sentiment)
        db.commit()
        return {
            "parsed": len(pending),
            "pending_left": 0,
            "errors": [],
            "source": BA_SENTIMENT_RULE_SOURCE,
        }

    parsed = 0
    errors: list[str] = []
    for offset in range(0, len(pending), BA_SENTIMENT_BATCH):
        batch = pending[offset:offset + BA_SENTIMENT_BATCH]
        payload = [
            {"id": item.subtask_id, "text": _subtask_answer_plaintext(item)[:1200]}
            for item in batch
        ]
        try:
            rows = client.classify_brand_answer_sentiments(brand_name=brand_name, items=payload)
        except DeepseekApiError as exc:
            logger.warning("monitor sentiment parse failed tenant=%s error=%s", tenant_id, exc)
            errors.append(str(exc))
            # DeepSeek 失败：对本批改规则兜底，避免整页继续全中性
            for item in batch:
                if _has_deepseek_sentiment(item):
                    continue
                _mark_rule_sentiment(
                    item,
                    rule_classify_brand_sentiment(_subtask_answer_plaintext(item), brand_name),
                )
                parsed += 1
            break
        by_id = {row["id"]: row["sentiment"] for row in rows}
        for item in batch:
            sentiment = by_id.get(item.subtask_id)
            if sentiment not in SENTIMENT_KEYS:
                sentiment = rule_classify_brand_sentiment(
                    _subtask_answer_plaintext(item),
                    brand_name,
                )
                _mark_rule_sentiment(item, sentiment)
                parsed += 1
                continue
            _mark_deepseek_sentiment(item, sentiment)
            parsed += 1
    if parsed:
        db.commit()
    left = sum(
        1
        for item in subtasks
        if (
            (not _has_deepseek_sentiment(item) if upgrade_rule else not _has_secondary_sentiment(item))
            and _subtask_answer_plaintext(item).strip()
        )
    )
    return {
        "parsed": parsed,
        "pending_left": left,
        "errors": errors,
        "source": BA_SENTIMENT_SOURCE,
    }


def parse_brand_word_descriptions_with_deepseek(
    db: Session,
    *,
    tenant_id: int,
    brand_name: str,
    subtasks: list[GeoMonitorSubtask],
    max_items: int = BA_DESC_MAX_PER_REQUEST,
) -> dict[str, Any]:
    """对尚未抽取 AI 描述的品牌词回答调用 DeepSeek，写回 raw_json。"""
    client = DeepseekClient()
    if not client.api_key:
        return {"parsed": 0, "skipped": len(subtasks), "error": "未配置 DeepSeek API Key"}

    pending: list[GeoMonitorSubtask] = []
    for item in subtasks:
        if _has_deepseek_description(item):
            continue
        if not _subtask_answer_plaintext(item).strip():
            continue
        pending.append(item)
        if len(pending) >= max_items:
            break

    parsed = 0
    errors: list[str] = []
    for offset in range(0, len(pending), BA_DESC_BATCH):
        batch = pending[offset:offset + BA_DESC_BATCH]
        payload = [
            {"id": item.subtask_id, "text": _subtask_answer_plaintext(item)[:1200]}
            for item in batch
        ]
        try:
            rows = client.extract_brand_answer_descriptions(brand_name=brand_name, items=payload)
        except (DeepseekApiError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("brand analysis description parse failed tenant=%s error=%s", tenant_id, exc)
            errors.append(str(exc))
            break
        by_id = {
            row["id"]: list(row.get("descriptions") or [])
            for row in rows
            if row.get("id")
        }
        for item in batch:
            if item.subtask_id not in by_id:
                continue
            _mark_deepseek_descriptions(item, by_id[item.subtask_id])
            parsed += 1
    if parsed:
        db.commit()
    return {
        "parsed": parsed,
        "pending_left": max(0, len(pending) - parsed),
        "errors": errors,
    }


def _group_ai_descriptions(
    subtasks: list[GeoMonitorSubtask],
    *,
    platform_names: dict[str, str],
    brand_aliases: list[str] | None = None,
) -> list[dict[str, Any]]:
    """相同/语义相近短描述归并；空描述跳过。一快照可贡献多条要点。点击卡片看组内全部快照。"""
    label_of = {
        "positive": "正面",
        "neutral": "中性",
        "negative": "负面",
        "unknown": "未知",
    }
    groups: dict[str, dict[str, Any]] = {}
    for item in subtasks:
        for point in _ba_description_items(item):
            desc = point["text"]
            key = _normalize_description_key(desc)
            if not key:
                continue
            code = str(item.platform or "").strip()
            sent_key = point.get("sentiment") or "unknown"
            if sent_key not in SENTIMENT_KEYS:
                sent_key = "unknown"
            label = label_of.get(sent_key, "未知")
            excerpt = _answer_excerpt(item.mention_context or _subtask_answer_plaintext(item), 160)
            # 2026-09-07 - 列表不嵌 page_screenshot，详情点开再拉子任务
            answer = {
                "subtask_id": item.subtask_id,
                "task_id": item.task_id,
                "platform": code,
                "platform_name": platform_names.get(code) or code,
                "prompt": item.prompt,
                "excerpt": excerpt,
                "sentiment": label,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
            bucket = groups.get(key)
            if bucket is None:
                groups[key] = {
                    "description": desc,
                    "answers": [answer],
                    "_sent_tally": {sent_key: 1},
                    "_platforms": {code} if code else set(),
                    "_seen_subtasks": {item.subtask_id},
                }
                continue
            seen = bucket["_seen_subtasks"]
            if item.subtask_id in seen:
                if len(desc) > len(str(bucket.get("description") or "")):
                    bucket["description"] = desc
                continue
            seen.add(item.subtask_id)
            bucket["answers"].append(answer)
            tally = bucket["_sent_tally"]
            tally[sent_key] = int(tally.get(sent_key, 0)) + 1
            if code:
                bucket["_platforms"].add(code)
            if len(desc) > len(str(bucket.get("description") or "")):
                bucket["description"] = desc

    # 上期环比已改精确计数；本期仍近义合并（跳过会组数暴涨、翻页变差）
    buckets = _merge_similar_description_buckets(
        list(groups.values()),
        brand_aliases=brand_aliases,
    )

    rows: list[dict[str, Any]] = []
    for bucket in buckets:
        tally: dict[str, int] = bucket.pop("_sent_tally")
        platforms: set[str] = bucket.pop("_platforms")
        bucket.pop("_seen_subtasks", None)
        desc_text = str(bucket.get("description") or "")
        dominant = _dominant_sent_key(
            tally,
            prefer_any_negative=_is_risk_description(desc_text),
        )
        answers = sorted(
            bucket["answers"],
            key=lambda row: str(row.get("updated_at") or ""),
            reverse=True,
        )
        sample_count = len(answers)
        if sample_count > BA_DESC_ANSWERS_IN_LIST:
            answers = answers[:BA_DESC_ANSWERS_IN_LIST]
        rows.append({
            "description": bucket["description"],
            "sentiment": label_of.get(dominant, "未知"),
            "sample_count": sample_count,
            "platforms": [
                {"code": code, "name": platform_names.get(code) or code}
                for code in sorted(platforms, key=lambda c: platform_names.get(c) or c)
            ],
            "answers": answers,
        })
    rows.sort(key=lambda row: (-int(row["sample_count"]), str(row["description"])))
    return rows


# 2026-09-07 - B+ 总览：等长窗口，上期可选周/月/季/年
# 2026-09-24 - 截止日锚定最近品牌词抓取，避免日历日滚动导致未抓取也变数
COMPARE_PERIOD_DAYS: dict[str, int] = {
    "week": 7,
    "month": 30,
    "quarter": 90,
    "year": 365,
}
COMPARE_PERIOD_LABELS: dict[str, str] = {
    "week": "周",
    "month": "月",
    "quarter": "季",
    "year": "年",
}
COMPARE_LOAD_LIMIT: dict[str, int] = {
    "week": 400,
    "month": 600,
    "quarter": 1200,
    "year": 2000,
}
# 2026-09-07 - 不做「满 N 组才环比」魔法门槛：上期空=不比；上期有数=如实比
COMPARE_MIN_PREV_GROUPS = 1
BRAND_FREEZE_TASK_STATUSES = frozenset({"completed", "partial_completed"})
BRAND_FREEZE_SUBTASK_STATUSES = frozenset(
    {"completed", "partial_completed", "failed", "stopped"}
)


def resolve_brand_compare_period(raw: str | None) -> str:
    key = str(raw or "month").strip().lower()
    return key if key in COMPARE_PERIOD_DAYS else "month"


def resolve_brand_analysis_anchor(db: Session, tenant_id: int) -> datetime | None:
    """优先以最近完整品牌词批次为锚点，避免半批数据进入展示窗口。"""
    complete_source = _brand_analysis_freeze_source(db, tenant_id)
    if complete_source is not None:
        source_created_at = complete_source.get("source_task_created_at")
        if source_created_at:
            return datetime.fromisoformat(str(source_created_at))
    return db.scalar(
        select(func.max(GeoMonitorTask.created_at)).where(
            GeoMonitorTask.tenant_id == int(tenant_id),
            GeoMonitorTask.purpose == "brand_word",
            GeoMonitorTask.deleted.is_(False),
            func.json_extract(
                GeoMonitorTask.raw_request_json,
                "$._geo_auto_retry",
            ).is_(None),
        )
    )


def brand_analysis_filter_fp(platform_codes: list[str] | None) -> str:
    codes = sorted({str(c or "").strip() for c in (platform_codes or []) if str(c or "").strip()})
    if not codes:
        return "default"
    return hashlib.md5("|".join(codes).encode("utf-8")).hexdigest()


def brand_compare_windows(anchor: datetime, compare_period: str) -> dict[str, Any]:
    """按最近抓取日切自然日窗口，本期/上期均为左闭右开。

    任务创建时间只负责确定抓取日。窗口上界取该日次日零点，避免任务
    创建后才完成的子任务被排除，也避免上一抓取日的任务落入本期。
    """
    days = COMPARE_PERIOD_DAYS[compare_period]
    anchor_day_start = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    range_end = anchor_day_start + timedelta(days=1)
    current_start = range_end - timedelta(days=days)
    previous_start = current_start - timedelta(days=days)
    label = COMPARE_PERIOD_LABELS[compare_period]
    current_end_date = (range_end - timedelta(microseconds=1)).date()
    previous_end_date = (current_start - timedelta(microseconds=1)).date()
    return {
        "compare_period": compare_period,
        "compare_period_label": label,
        "days": days,
        "current_start": current_start,
        "previous_start": previous_start,
        "range_end": range_end,
        "current_label": f"{current_start.date().isoformat()} ~ {current_end_date.isoformat()}",
        "previous_label": f"{previous_start.date().isoformat()} ~ {previous_end_date.isoformat()}",
    }


def _brand_analysis_parse_settled(parse_meta: dict[str, Any]) -> bool:
    return int(parse_meta.get("pending_left") or 0) <= 0 and int(
        parse_meta.get("description_pending_left") or 0
    ) <= 0


def _brand_task_is_auto_retry(task: GeoMonitorTask) -> bool:
    raw = task.raw_request_json if isinstance(task.raw_request_json, dict) else {}
    return isinstance(raw.get("_geo_auto_retry"), dict)


def _brand_task_freeze_counts(
    db: Session,
    task: GeoMonitorTask,
) -> tuple[int, int, int] | None:
    if str(task.status or "") not in BRAND_FREEZE_TASK_STATUSES:
        return None
    subtasks = list(
        db.scalars(
            select(GeoMonitorSubtask).where(
                GeoMonitorSubtask.task_id == task.task_id,
            )
        )
    )
    actual_total = len(subtasks)
    expected_total = max(int(task.total_items or 0), actual_total)
    terminal_total = sum(
        1
        for subtask in subtasks
        if str(subtask.status or "") in BRAND_FREEZE_SUBTASK_STATUSES
    )
    usable = [
        subtask
        for subtask in subtasks
        if str(subtask.status or "") in {"completed", "partial_completed"}
    ]
    if (
        expected_total <= 0
        or actual_total < expected_total
        or terminal_total < expected_total
        or any(
            not _has_deepseek_sentiment(subtask)
            or not _has_deepseek_description(subtask)
            for subtask in usable
        )
    ):
        return None
    return expected_total, terminal_total, len(usable)


def _brand_analysis_freeze_source(db: Session, tenant_id: int) -> dict[str, Any] | None:
    """返回最近一个全部进入终态的品牌词调度批次来源元数据。"""
    candidates = list(
        db.scalars(
            select(GeoMonitorTask)
            .where(
                GeoMonitorTask.tenant_id == int(tenant_id),
                GeoMonitorTask.purpose == "brand_word",
                GeoMonitorTask.deleted.is_(False),
                func.json_extract(
                    GeoMonitorTask.raw_request_json,
                    "$._geo_auto_retry",
                ).is_(None),
            )
            .order_by(GeoMonitorTask.created_at.desc(), GeoMonitorTask.id.desc())
            .limit(200)
        )
    )
    seen_batches: set[str] = set()
    skipped_newer_batch = False
    for candidate in candidates:
        run = db.scalar(
            select(GeoMonitorScheduleRun).where(
                GeoMonitorScheduleRun.tenant_id == int(tenant_id),
                GeoMonitorScheduleRun.task_id == candidate.task_id,
            )
        )
        if run is None or "-kw" not in str(run.schedule_key or ""):
            batch_key = f"task:{candidate.task_id}"
            tasks = [candidate]
        else:
            batch_key = str(run.schedule_key).split("-kw", 1)[0]
            if batch_key in seen_batches:
                continue
            seen_batches.add(batch_key)
            batch_runs = list(
                db.scalars(
                    select(GeoMonitorScheduleRun).where(
                        GeoMonitorScheduleRun.tenant_id == int(tenant_id),
                        GeoMonitorScheduleRun.schedule_key.startswith(f"{batch_key}-kw"),
                    )
                )
            )
            if not batch_runs or any(
                str(item.status or "") != "submitted" or not item.task_id
                for item in batch_runs
            ):
                skipped_newer_batch = True
                continue
            task_ids = [str(item.task_id) for item in batch_runs]
            tasks = list(
                db.scalars(
                    select(GeoMonitorTask).where(
                        GeoMonitorTask.task_id.in_(task_ids),
                        GeoMonitorTask.deleted.is_(False),
                    )
                )
            )
            if len(tasks) != len(task_ids) or any(
                _brand_task_is_auto_retry(task) for task in tasks
            ):
                skipped_newer_batch = True
                continue

        total_items = 0
        terminal_items = 0
        usable_items = 0
        batch_complete = True
        for task in tasks:
            counts = _brand_task_freeze_counts(db, task)
            if counts is None:
                batch_complete = False
                break
            total_items += counts[0]
            terminal_items += counts[1]
            usable_items += counts[2]
        if not batch_complete:
            skipped_newer_batch = True
            continue
        if usable_items <= 0:
            skipped_newer_batch = True
            continue

        source_task = max(tasks, key=lambda task: (task.created_at, task.id))
        source_created_at = source_task.created_at
        if source_created_at is None:
            skipped_newer_batch = True
            continue
        source_task_ids = sorted(str(task.task_id) for task in tasks)
        return {
            "source_batch_key": batch_key,
            "source_task_id": source_task.task_id,
            "source_task_ids": source_task_ids,
            "source_task_created_at": source_created_at.isoformat(),
            "source_task_status": source_task.status,
            "source_task_statuses": {
                str(task.task_id): str(task.status or "") for task in tasks
            },
            "source_task_total_items": total_items,
            "source_task_terminal_items": terminal_items,
            "source_task_usable_items": usable_items,
            "source_is_latest_batch": not skipped_newer_batch,
        }
    return None


def _snapshot_payload_from_dashboard(data: dict[str, Any]) -> dict[str, Any]:
    """冻结整块看板（含描述列表），去掉瞬时 parse 噪声。"""
    payload = dict(data)
    payload["frozen"] = True
    payload["parse"] = {
        "parsed": 0,
        "pending_left": 0,
        "errors": [],
        "description_parsed": 0,
        "description_pending_left": 0,
        "description_errors": [],
    }
    return payload


def _try_load_brand_analysis_snapshot(
    db: Session,
    *,
    tenant_id: int,
    grain: str,
    as_of: date,
    filter_fp: str,
) -> dict[str, Any] | None:
    from app.services.window_snapshot_service import BRAND_ANALYSIS_KIND, get_window_snapshot

    snap = get_window_snapshot(
        db,
        tenant_id=tenant_id,
        kind=BRAND_ANALYSIS_KIND,
        window_days=COMPARE_PERIOD_DAYS[grain],
        as_of_date=as_of,
        filter_fp=filter_fp,
    )
    if not snap:
        return None
    freeze_source = _brand_analysis_freeze_source(db, tenant_id)
    if freeze_source is not None:
        snapshot_source = str(snap.get("source_batch_key") or "").strip()
        current_source = str(freeze_source.get("source_batch_key") or "").strip()
        keep_legacy_while_newer_batch_is_incomplete = (
            not snapshot_source and not bool(freeze_source.get("source_is_latest_batch"))
        )
        if snapshot_source != current_source and not keep_legacy_while_newer_batch_is_incomplete:
            return None
    out = dict(snap)
    out["frozen"] = True
    out["data_as_of"] = as_of.isoformat()
    out["compare_period"] = grain
    out["compare_period_label"] = COMPARE_PERIOD_LABELS[grain]
    out["generated_at"] = datetime.now().isoformat(timespec="seconds")
    return align_platform_sentiment_shares(out)


def _try_freeze_brand_analysis_snapshot(
    db: Session,
    *,
    tenant_id: int,
    grain: str,
    as_of: date,
    filter_fp: str,
    data: dict[str, Any],
    parse_meta: dict[str, Any],
) -> bool:
    if not _brand_analysis_parse_settled(parse_meta):
        return False
    if int(data.get("sample_count") or 0) <= 0:
        return False

    freeze_source = _brand_analysis_freeze_source(db, tenant_id)
    if freeze_source is None:
        return False
    source_created_at = freeze_source.get("source_task_created_at")
    if source_created_at and datetime.fromisoformat(str(source_created_at)).date() != as_of:
        return False

    snapshot_data = dict(data)
    snapshot_data.update(freeze_source)
    from app.services.window_snapshot_service import (
        BRAND_ANALYSIS_KIND,
        upsert_window_snapshot_if_newer_source,
    )

    return upsert_window_snapshot_if_newer_source(
        db,
        tenant_id=tenant_id,
        kind=BRAND_ANALYSIS_KIND,
        window_days=COMPARE_PERIOD_DAYS[grain],
        payload=_snapshot_payload_from_dashboard(snapshot_data),
        as_of_date=as_of,
        filter_fp=filter_fp,
        source_version=str(freeze_source["source_batch_key"]),
        source_created_at=datetime.fromisoformat(str(freeze_source["source_task_created_at"])),
    )


def _empty_sentiment_counts() -> dict[str, int]:
    return {"正面": 0, "中性": 0, "负面": 0, "未知": 0}


def _tally_sentiment_counts(subtasks: list[GeoMonitorSubtask]) -> dict[str, int]:
    counts = _empty_sentiment_counts()
    for item in subtasks:
        label = _normalize_sentiment_label(item.sentiment)
        counts[label] = counts.get(label, 0) + 1
    return counts


def _tally_description_group_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """与前端情感筛选角标同口径：按 AI 描述归并组计数。"""
    counts = _empty_sentiment_counts()
    for row in rows:
        label = str(row.get("sentiment") or "未知").strip() or "未知"
        if label not in counts:
            label = "未知"
        counts[label] = counts.get(label, 0) + 1
    return counts


def _tally_description_counts_exact(subtasks: list[GeoMonitorSubtask]) -> dict[str, int]:
    """上期环比：精确描述 key → 组情感 → 计数（不做近义合并/不建 answers）。

    2026-09-07 - 上期也跑完整 _group_ai_descriptions 把首屏拖到数秒 - 环比只需占比
    """
    label_of = {
        "positive": "正面",
        "neutral": "中性",
        "negative": "负面",
        "unknown": "未知",
    }
    groups: dict[str, tuple[dict[str, int], str]] = {}
    for item in subtasks:
        for point in _ba_description_items(item):
            desc = str(point.get("text") or "").strip()
            key = _normalize_description_key(desc)
            if not key:
                continue
            sent_key = point.get("sentiment") or "unknown"
            if sent_key not in SENTIMENT_KEYS:
                sent_key = "unknown"
            row = groups.get(key)
            if row is None:
                groups[key] = ({sent_key: 1}, desc)
                continue
            tally, prev_desc = row
            tally[sent_key] = int(tally.get(sent_key, 0)) + 1
            if len(desc) > len(prev_desc):
                groups[key] = (tally, desc)
    counts = _empty_sentiment_counts()
    for tally, desc in groups.values():
        dominant = _dominant_sent_key(
            tally,
            prefer_any_negative=_is_risk_description(desc),
        )
        label = label_of.get(dominant, "未知")
        counts[label] = counts.get(label, 0) + 1
    return counts


def align_platform_sentiment_shares(data: dict[str, Any]) -> dict[str, Any]:
    """平台条与左侧描述组同一口径：按平台计描述归并组，不按整篇回答情感。

    一组描述跨多个平台时，每个平台各计一次。没有描述组时保留原回答级占比。
    """
    groups = data.get("ai_descriptions") or []
    platforms = data.get("platforms") or []
    if not isinstance(groups, list) or not isinstance(platforms, list) or not groups:
        return data
    by_code: dict[str, dict[str, int]] = {}
    for row in groups:
        if not isinstance(row, dict):
            continue
        label = str(row.get("sentiment") or "").strip()
        if label not in ("正面", "中性", "负面"):
            continue
        for plat in row.get("platforms") or []:
            if not isinstance(plat, dict):
                continue
            code = str(plat.get("code") or "").strip()
            if not code:
                continue
            bucket = by_code.setdefault(code, {"正面": 0, "中性": 0, "负面": 0})
            bucket[label] += 1
    for platform in platforms:
        if not isinstance(platform, dict):
            continue
        code = str(platform.get("code") or "").strip()
        counts = by_code.get(code)
        if not counts or (counts["正面"] + counts["中性"] + counts["负面"]) <= 0:
            continue
        platform["sentiment_share"] = _sentiment_share_pct(counts)
    return data


def _sentiment_share_pct(counts: dict[str, int]) -> dict[str, float]:
    """正/中/负占比；分母不含未知，三段合计约 100%。"""
    labeled = int(counts.get("正面") or 0) + int(counts.get("中性") or 0) + int(counts.get("负面") or 0)
    if labeled <= 0:
        return {"正面": 0.0, "中性": 0.0, "负面": 0.0}
    return {
        "正面": round(100.0 * int(counts.get("正面") or 0) / labeled, 1),
        "中性": round(100.0 * int(counts.get("中性") or 0) / labeled, 1),
        "负面": round(100.0 * int(counts.get("负面") or 0) / labeled, 1),
    }


def _prev_compare_insufficient(prev_groups: int, cur_groups: int) -> tuple[bool, str | None]:
    """仅上期完全无数据时禁止环比；禁止用空上期伪造「全是上升」。"""
    _ = cur_groups
    if prev_groups <= 0:
        return True, "empty"
    return False, None


def _description_compare_block(
    *,
    current_counts: dict[str, int],
    previous_counts: dict[str, int],
    current_share: dict[str, float],
    previous_share: dict[str, float],
) -> dict[str, Any]:
    # 2026-09-07 - 比例/环比跟情感筛选同一套描述组数，不用样本条数
    prev_groups = sum(int(previous_counts.get(k) or 0) for k in ("正面", "中性", "负面", "未知"))
    cur_groups = sum(int(current_counts.get(k) or 0) for k in ("正面", "中性", "负面", "未知"))
    insufficient, reason = _prev_compare_insufficient(prev_groups, cur_groups)
    deltas: dict[str, float | None] = {
        "正面_pt": None,
        "中性_pt": None,
        "负面_pt": None,
        "group_pct": None,
    }
    if not insufficient:
        deltas["正面_pt"] = round(float(current_share["正面"]) - float(previous_share["正面"]), 1)
        deltas["中性_pt"] = round(float(current_share["中性"]) - float(previous_share["中性"]), 1)
        deltas["负面_pt"] = round(float(current_share["负面"]) - float(previous_share["负面"]), 1)
        deltas["group_pct"] = round(100.0 * (cur_groups - prev_groups) / prev_groups, 1)
    return {
        "group_count": prev_groups,
        "description_counts": previous_counts,
        "description_share": previous_share,
        "deltas": deltas,
        "insufficient": insufficient,
        "min_groups": COMPARE_MIN_PREV_GROUPS,
        "reason": reason,
    }


def _subtask_event_at(item: GeoMonitorSubtask) -> datetime | None:
    """监测发生时间：勿用 updated_at（情感/描述补解析会刷新，上期会被掏空）。"""
    remote = getattr(item, "remote_time", None)
    if remote is not None:
        try:
            ms = int(remote)
            if ms > 10_000_000_000:  # ms
                return datetime.fromtimestamp(ms / 1000.0)
            if ms > 0:
                return datetime.fromtimestamp(ms)
        except (TypeError, ValueError, OSError, OverflowError):
            pass
    task = getattr(item, "task", None)
    created = getattr(task, "created_at", None) if task is not None else None
    if created is not None:
        return created
    return getattr(item, "updated_at", None)


def _subtask_in_window(item: GeoMonitorSubtask, start: datetime, end: datetime, *, end_exclusive: bool) -> bool:
    ts = _subtask_event_at(item)
    if ts is None:
        return False
    if ts < start:
        return False
    if end_exclusive:
        return ts < end
    return ts <= end


def _build_platform_rows(
    *,
    purchased: list[str],
    purchased_set: set[str],
    names: dict[str, str],
    current_subtasks: list[GeoMonitorSubtask],
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, int]]:
    sentiment_counts = _empty_sentiment_counts()
    platform_counts: dict[str, int] = {code: 0 for code in purchased}
    buckets: dict[str, dict[str, list[dict[str, Any]]]] = {
        code: {"positive": [], "neutral": [], "negative": [], "unknown": []}
        for code in purchased
    }
    for item in current_subtasks:
        code = str(item.platform or "").strip()
        if purchased_set and code not in purchased_set:
            continue
        if code not in buckets:
            buckets[code] = {"positive": [], "neutral": [], "negative": [], "unknown": []}
            platform_counts[code] = 0
        label = _normalize_sentiment_label(item.sentiment)
        sentiment_counts[label] = sentiment_counts.get(label, 0) + 1
        platform_counts[code] = platform_counts.get(code, 0) + 1
        key = {
            "正面": "positive",
            "中性": "neutral",
            "负面": "negative",
        }.get(label, "unknown")
        excerpt = _answer_excerpt(item.mention_context or _subtask_answer_plaintext(item), 160)
        buckets[code][key].append({
            "subtask_id": item.subtask_id,
            "task_id": item.task_id,
            "prompt": item.prompt,
            "excerpt": excerpt,
            "sentiment": label,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            "page_screenshot": public_screenshot_url(item.page_screenshot),
        })

    resolved_purchased = purchased
    if not resolved_purchased:
        resolved_purchased = sort_platform_codes(
            [code for code, count in platform_counts.items() if count > 0]
        )

    platform_rows: list[dict[str, Any]] = []
    for code in resolved_purchased or sorted(buckets.keys()):
        count = platform_counts.get(code, 0)
        if count <= 0:
            continue
        pos = buckets.get(code, {}).get("positive") or []
        neu = buckets.get(code, {}).get("neutral") or []
        neg = buckets.get(code, {}).get("negative") or []
        unk = buckets.get(code, {}).get("unknown") or []
        labeled = len(pos) + len(neu) + len(neg)
        share = {
            "正面": round(100.0 * len(pos) / labeled, 1) if labeled else 0.0,
            "中性": round(100.0 * len(neu) / labeled, 1) if labeled else 0.0,
            "负面": round(100.0 * len(neg) / labeled, 1) if labeled else 0.0,
        }
        platform_rows.append({
            "code": code,
            "name": names.get(code) or code,
            "sample_count": count,
            "positive": pos,
            "neutral": neu,
            "negative": neg,
            "unknown": unk,
            "sentiment_share": share,
        })
    return platform_rows, sentiment_counts, platform_counts


def _load_brand_word_subtasks(
    db: Session,
    *,
    tenant_id: int,
    lookback_start: datetime,
    range_end: datetime,
    limit: int = 400,
) -> list[GeoMonitorSubtask]:
    # 拉取上界用 now：锚点之后情感/描述补解析会刷 updated_at，不能按抓取锚点截掉
    load_end = max(range_end, datetime.now())
    stmt = (
        select(GeoMonitorSubtask)
        .join(GeoMonitorTask, GeoMonitorTask.task_id == GeoMonitorSubtask.task_id)
        .where(
            GeoMonitorTask.deleted.is_(False),
            GeoMonitorTask.tenant_id == tenant_id,
            GeoMonitorTask.purpose == "brand_word",
            func.json_extract(
                GeoMonitorTask.raw_request_json,
                "$._geo_auto_retry",
            ).is_(None),
            GeoMonitorSubtask.status.in_(("completed", "partial_completed")),
            or_(
                GeoMonitorSubtask.updated_at >= lookback_start,
                GeoMonitorTask.created_at >= lookback_start,
            ),
            GeoMonitorSubtask.updated_at <= load_end,
        )
        .order_by(GeoMonitorSubtask.updated_at.desc())
        .limit(limit)
    )
    # 2026-07-30 - 1038 类风险 - 品牌分析 ORDER BY 勿带 answer/raw/screenshot，id-first 再 hydrate
    ordered_ids = _ordered_subtask_ids(db, stmt)
    return _hydrate_subtasks_in_id_order(
        db,
        ordered_ids,
        joinedload(GeoMonitorSubtask.task).load_only(
            GeoMonitorTask.monitor_keywords,
            GeoMonitorTask.created_at,
            GeoMonitorTask.purpose,
        ),
        load_only(
            GeoMonitorSubtask.subtask_id,
            GeoMonitorSubtask.task_id,
            GeoMonitorSubtask.platform,
            GeoMonitorSubtask.prompt,
            GeoMonitorSubtask.status,
            GeoMonitorSubtask.answer_content,
            GeoMonitorSubtask.mention_context,
            GeoMonitorSubtask.page_screenshot,
            GeoMonitorSubtask.sentiment,
            GeoMonitorSubtask.raw_result_json,
            GeoMonitorSubtask.remote_time,
            GeoMonitorSubtask.updated_at,
        ),
    )


def build_brand_analysis_dashboard(
    db: Session,
    current: CurrentSession,
    *,
    tenant_id: int | None = None,
    parse_sentiments: bool = False,
    compare_period: str | None = None,
) -> dict[str, Any]:
    """品牌分析：描述要点比例 + 上期环比（周/月/季/年）+ AI 描述列表。

    默认不在读路径调 DeepSeek；同步写路径 / 显式 parse=true 再补齐。
    口碑块按最近品牌词抓取日锚定，并在解析齐后 write-once 冻结。
    """
    resolved = _resolve_workspace_brief_tenant_id(current, tenant_id)
    asset = get_brand_asset(db, resolved)
    brand_name = (
        (asset.company_full_name if asset else None)
        or (asset.brand_name if asset else None)
        or "监测品牌"
    )
    # 2026-08-28 - 已购/筛选同口径：监测词组 → 品牌词组勾选，勿用历史样本端冒充当前配置
    purchased = _purchased_platforms_for_brand_words(db, resolved)
    # 2026-08-07 - 观察号品牌分析仅 kimi/元宝
    from app.services.observer_account import narrow_platform_codes, observer_platforms_for_session

    purchased = narrow_platform_codes(purchased, observer_platforms_for_session(current))
    purchased_set = set(purchased)
    names = _platform_name_map()

    grain = resolve_brand_compare_period(compare_period)
    now = datetime.now()
    anchor = resolve_brand_analysis_anchor(db, resolved) or now
    as_of = anchor.date()
    filter_fp = brand_analysis_filter_fp(purchased)
    if not parse_sentiments:
        frozen = _try_load_brand_analysis_snapshot(
            db,
            tenant_id=resolved,
            grain=grain,
            as_of=as_of,
            filter_fp=filter_fp,
        )
        if frozen is not None:
            return frozen

    windows = brand_compare_windows(anchor, grain)
    current_start: datetime = windows["current_start"]
    previous_start: datetime = windows["previous_start"]
    range_end: datetime = windows["range_end"]
    load_limit = COMPARE_LOAD_LIMIT[grain]

    # 一次拉满上期起点～抓取锚点，再按窗口切开（避免 limit 截断上期）
    subtasks = _load_brand_word_subtasks(
        db,
        tenant_id=resolved,
        lookback_start=previous_start,
        range_end=range_end,
        limit=load_limit,
    )
    if purchased_set:
        subtasks = [item for item in subtasks if item.platform in purchased_set]

    parse_meta: dict[str, Any] = {
        "parsed": 0,
        "pending_left": 0,
        "errors": [],
        "description_parsed": 0,
        "description_pending_left": 0,
        "description_errors": [],
    }
    if parse_sentiments and subtasks:
        # 2026-07-28 - parse=true 时 LLM/JSON 异常曾整接口 400，前端吞错一直停在旧单句
        try:
            sent_meta = parse_brand_word_sentiments_with_deepseek(
                db,
                tenant_id=resolved,
                brand_name=str(brand_name),
                subtasks=subtasks,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("brand analysis sentiment parse crashed tenant=%s", resolved)
            sent_meta = {"parsed": 0, "pending_left": len(subtasks), "errors": [str(exc)]}
        subtasks = _load_brand_word_subtasks(
            db,
            tenant_id=resolved,
            lookback_start=previous_start,
            range_end=range_end,
            limit=load_limit,
        )
        if purchased_set:
            subtasks = [item for item in subtasks if item.platform in purchased_set]
        try:
            desc_meta = parse_brand_word_descriptions_with_deepseek(
                db,
                tenant_id=resolved,
                brand_name=str(brand_name),
                subtasks=subtasks,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("brand analysis description parse crashed tenant=%s", resolved)
            desc_meta = {"parsed": 0, "pending_left": len(subtasks), "errors": [str(exc)]}
        parse_meta = {
            "parsed": int(sent_meta.get("parsed") or 0),
            "pending_left": int(sent_meta.get("pending_left") or 0),
            "errors": list(sent_meta.get("errors") or []),
            "error": sent_meta.get("error") or desc_meta.get("error"),
            "description_parsed": int(desc_meta.get("parsed") or 0),
            "description_pending_left": int(desc_meta.get("pending_left") or 0),
            "description_errors": list(desc_meta.get("errors") or []),
        }
        subtasks = _load_brand_word_subtasks(
            db,
            tenant_id=resolved,
            lookback_start=previous_start,
            range_end=range_end,
            limit=load_limit,
        )
        if purchased_set:
            subtasks = [item for item in subtasks if item.platform in purchased_set]
    elif subtasks:
        # 读路径默认不调 LLM，仍回报待解析量供前端决定是否二次请求
        parse_meta["pending_left"] = sum(1 for item in subtasks if not _has_deepseek_sentiment(item))
        parse_meta["description_pending_left"] = sum(
            1 for item in subtasks if not _has_deepseek_description(item)
        )

    current_subtasks = [
        item for item in subtasks
        if _subtask_in_window(item, current_start, range_end, end_exclusive=True)
    ]
    previous_subtasks = [
        item for item in subtasks
        if _subtask_in_window(item, previous_start, current_start, end_exclusive=True)
    ]

    platform_rows, sentiment_counts, platform_counts = _build_platform_rows(
        purchased=purchased,
        purchased_set=purchased_set,
        names=names,
        current_subtasks=current_subtasks,
    )
    if not purchased:
        purchased = sort_platform_codes(
            [code for code, count in platform_counts.items() if count > 0]
        )

    base_pie = [
        {"name": "正面", "value": sentiment_counts["正面"]},
        {"name": "中性", "value": sentiment_counts["中性"]},
        {"name": "负面", "value": sentiment_counts["负面"]},
    ]
    if sentiment_counts["未知"]:
        base_pie.append({"name": "未知", "value": sentiment_counts["未知"]})

    platform_pie = [
        {
            "name": names.get(code) or code,
            "code": code,
            "value": platform_counts.get(code, 0),
        }
        for code in (purchased or list(platform_counts.keys()))
        if platform_counts.get(code, 0) > 0
    ]

    aliases = _brand_aliases(
        str(brand_name),
        str(asset.brand_name) if asset and asset.brand_name else None,
        str(asset.company_full_name) if asset and asset.company_full_name else None,
    )
    ai_descriptions = _group_ai_descriptions(
        current_subtasks,
        platform_names=names,
        brand_aliases=aliases,
    )
    # 2026-09-07 - 上期只算占比，不做近义归并/嵌套 answers
    prev_description_counts = _tally_description_counts_exact(previous_subtasks)
    description_counts = _tally_description_group_counts(ai_descriptions)
    description_share = _sentiment_share_pct(description_counts)
    prev_description_share = _sentiment_share_pct(prev_description_counts)
    description_compare = _description_compare_block(
        current_counts=description_counts,
        previous_counts=prev_description_counts,
        current_share=description_share,
        previous_share=prev_description_share,
    )

    sample_count = sum(platform_counts.values())
    result = {
        "tenant_id": resolved,
        "brand_name": brand_name,
        "company_name": asset.company_full_name if asset else brand_name,
        "period_label": windows["current_label"],
        "compare_period": grain,
        "compare_period_label": windows["compare_period_label"],
        "previous_period_label": windows["previous_label"],
        "purchased_platforms": purchased,
        "sample_count": sample_count,
        "sentiment_counts": sentiment_counts,
        "sentiment_pie": base_pie,
        "platform_pie": platform_pie,
        "platforms": platform_rows,
        # 2026-09-07 - 比例跟情感筛选：描述归并组数，不是样本条数
        "description_counts": description_counts,
        "description_share": description_share,
        "description_compare": description_compare,
        "ai_descriptions": ai_descriptions,
        "parse": parse_meta,
        "generated_at": now.isoformat(timespec="seconds"),
        "data_as_of": as_of.isoformat(),
        "frozen": False,
    }
    align_platform_sentiment_shares(result)
    _try_freeze_brand_analysis_snapshot(
        db,
        tenant_id=resolved,
        grain=grain,
        as_of=as_of,
        filter_fp=filter_fp,
        data=result,
        parse_meta=parse_meta,
    )
    return result


def maybe_freeze_brand_analysis_after_brand_word(db: Session, tenant_id: int) -> dict[str, Any]:
    """品牌词同步+解析后尝试 write-once 冻结各环比粒度。"""
    purchased = _purchased_platforms_for_brand_words(db, int(tenant_id))
    filter_fp = brand_analysis_filter_fp(purchased)
    anchor = resolve_brand_analysis_anchor(db, int(tenant_id)) or datetime.now()
    as_of = anchor.date()
    frozen_grains: list[str] = []
    skipped: list[str] = []
    for grain in COMPARE_PERIOD_DAYS:
        existing = _try_load_brand_analysis_snapshot(
            db,
            tenant_id=int(tenant_id),
            grain=grain,
            as_of=as_of,
            filter_fp=filter_fp,
        )
        if existing is not None:
            skipped.append(grain)
            continue
        try:
            data = build_brand_analysis_dashboard_for_tenant(
                db,
                tenant_id=int(tenant_id),
                purchased=purchased,
                compare_period=grain,
                parse_sentiments=False,
            )
            if _try_freeze_brand_analysis_snapshot(
                db,
                tenant_id=int(tenant_id),
                grain=grain,
                as_of=as_of,
                filter_fp=filter_fp,
                data=data,
                parse_meta=data.get("parse") or {},
            ):
                frozen_grains.append(grain)
            else:
                skipped.append(grain)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "freeze brand analysis failed tenant=%s grain=%s error=%s",
                tenant_id,
                grain,
                exc,
            )
            skipped.append(grain)
            try:
                db.rollback()
            except Exception:
                pass
    return {
        "tenant_id": int(tenant_id),
        "as_of": as_of.isoformat(),
        "frozen": frozen_grains,
        "skipped": skipped,
    }


def build_brand_analysis_dashboard_for_tenant(
    db: Session,
    *,
    tenant_id: int,
    purchased: list[str] | None = None,
    compare_period: str | None = None,
    parse_sentiments: bool = False,
) -> dict[str, Any]:
    """无会话物化：供抓取后冻结；平台列表用已购品牌词端，不做观察号收窄。"""
    resolved = int(tenant_id)
    asset = get_brand_asset(db, resolved)
    brand_name = (
        (asset.company_full_name if asset else None)
        or (asset.brand_name if asset else None)
        or "监测品牌"
    )
    purchased = list(purchased) if purchased is not None else _purchased_platforms_for_brand_words(db, resolved)
    purchased_set = set(purchased)
    names = _platform_name_map()
    grain = resolve_brand_compare_period(compare_period)
    now = datetime.now()
    anchor = resolve_brand_analysis_anchor(db, resolved) or now
    as_of = anchor.date()
    filter_fp = brand_analysis_filter_fp(purchased)
    windows = brand_compare_windows(anchor, grain)
    current_start: datetime = windows["current_start"]
    previous_start: datetime = windows["previous_start"]
    range_end: datetime = windows["range_end"]
    load_limit = COMPARE_LOAD_LIMIT[grain]
    subtasks = _load_brand_word_subtasks(
        db,
        tenant_id=resolved,
        lookback_start=previous_start,
        range_end=range_end,
        limit=load_limit,
    )
    if purchased_set:
        subtasks = [item for item in subtasks if item.platform in purchased_set]
    parse_meta: dict[str, Any] = {
        "parsed": 0,
        "pending_left": sum(1 for item in subtasks if not _has_deepseek_sentiment(item)),
        "errors": [],
        "description_parsed": 0,
        "description_pending_left": sum(1 for item in subtasks if not _has_deepseek_description(item)),
        "description_errors": [],
    }
    current_subtasks = [
        item for item in subtasks
        if _subtask_in_window(item, current_start, range_end, end_exclusive=True)
    ]
    previous_subtasks = [
        item for item in subtasks
        if _subtask_in_window(item, previous_start, current_start, end_exclusive=True)
    ]
    platform_rows, sentiment_counts, platform_counts = _build_platform_rows(
        purchased=purchased,
        purchased_set=purchased_set,
        names=names,
        current_subtasks=current_subtasks,
    )
    if not purchased:
        purchased = sort_platform_codes(
            [code for code, count in platform_counts.items() if count > 0]
        )
    base_pie = [
        {"name": "正面", "value": sentiment_counts["正面"]},
        {"name": "中性", "value": sentiment_counts["中性"]},
        {"name": "负面", "value": sentiment_counts["负面"]},
    ]
    if sentiment_counts["未知"]:
        base_pie.append({"name": "未知", "value": sentiment_counts["未知"]})
    platform_pie = [
        {
            "name": names.get(code) or code,
            "code": code,
            "value": platform_counts.get(code, 0),
        }
        for code in (purchased or list(platform_counts.keys()))
        if platform_counts.get(code, 0) > 0
    ]
    aliases = _brand_aliases(
        str(brand_name),
        str(asset.brand_name) if asset and asset.brand_name else None,
        str(asset.company_full_name) if asset and asset.company_full_name else None,
    )
    ai_descriptions = _group_ai_descriptions(
        current_subtasks,
        platform_names=names,
        brand_aliases=aliases,
    )
    prev_description_counts = _tally_description_counts_exact(previous_subtasks)
    description_counts = _tally_description_group_counts(ai_descriptions)
    description_share = _sentiment_share_pct(description_counts)
    prev_description_share = _sentiment_share_pct(prev_description_counts)
    description_compare = _description_compare_block(
        current_counts=description_counts,
        previous_counts=prev_description_counts,
        current_share=description_share,
        previous_share=prev_description_share,
    )
    sample_count = sum(platform_counts.values())
    result = {
        "tenant_id": resolved,
        "brand_name": brand_name,
        "company_name": asset.company_full_name if asset else brand_name,
        "period_label": windows["current_label"],
        "compare_period": grain,
        "compare_period_label": windows["compare_period_label"],
        "previous_period_label": windows["previous_label"],
        "purchased_platforms": purchased,
        "sample_count": sample_count,
        "sentiment_counts": sentiment_counts,
        "sentiment_pie": base_pie,
        "platform_pie": platform_pie,
        "platforms": platform_rows,
        "description_counts": description_counts,
        "description_share": description_share,
        "description_compare": description_compare,
        "ai_descriptions": ai_descriptions,
        "parse": parse_meta,
        "generated_at": now.isoformat(timespec="seconds"),
        "data_as_of": as_of.isoformat(),
        "frozen": False,
    }
    return align_platform_sentiment_shares(result)


def parse_sentiments_after_brand_word_sync(db: Session, task: GeoMonitorTask) -> None:
    """监测任务同步完成后二次解析情感；品牌词另抽 AI 描述。"""
    purpose = str(getattr(task, "purpose", "") or "")
    if purpose not in {"brand_word", "geo"} or not task.tenant_id:
        return
    asset = get_brand_asset(db, task.tenant_id)
    brand_name = (asset.company_full_name if asset else None) or (asset.brand_name if asset else None) or "监测品牌"
    subtasks = list(
        db.scalars(
            select(GeoMonitorSubtask).where(
                GeoMonitorSubtask.task_id == task.task_id,
                GeoMonitorSubtask.status.in_(("completed", "partial_completed")),
            )
        )
    )
    if not subtasks:
        return
    # 2026-07-30 - GEO 同步后补二次情感，竞品情绪趋势不再只信模力中性
    parse_brand_word_sentiments_with_deepseek(
        db,
        tenant_id=task.tenant_id,
        brand_name=str(brand_name),
        subtasks=subtasks,
        max_items=BA_SENTIMENT_MAX_PER_REQUEST if purpose == "brand_word" else 48,
        upgrade_rule=True,
    )
    if purpose != "brand_word":
        return
    parse_brand_word_descriptions_with_deepseek(
        db,
        tenant_id=task.tenant_id,
        brand_name=str(brand_name),
        subtasks=subtasks,
    )
    try:
        maybe_freeze_brand_analysis_after_brand_word(db, int(task.tenant_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "maybe_freeze_brand_analysis_after_brand_word failed tenant=%s error=%s",
            task.tenant_id,
            exc,
        )
