"""诊断驾驶舱：问法场景/意图/获客分层打标。

2026-08-12 - 诊断改驾驶舱 - 场景优先否则意图；含品牌名=品牌防守，否则=非品牌词获客
"""

from __future__ import annotations

import re
from typing import Any

# (code, label, keywords) — 命中任一关键词即归类
SCENE_RULES: list[tuple[str, str, tuple[str, ...]]] = [
    ("elevator", "电梯", ("电梯",)),
    ("airport", "机场", ("机场",)),
    ("hsr", "高铁", ("高铁", "动车")),
    ("transit", "公交地铁", ("公交", "地铁", "轨道交通")),
    ("led", "LED", ("LED", "led", "大屏", "电子屏")),
]

INTENT_RULES: list[tuple[str, str, tuple[str, ...]]] = [
    # 2026-08-13 - 「哪家比较靠谱」应归推荐名单，勿被「比较」抢成竞品对比
    # 2026-08-21 - 对齐换皮版-G 可见意图：无「选型标准/选型路径」类；怎么选并入推荐名单
    (
        "recommend",
        "推荐名单",
        (
            "推荐",
            "哪家好",
            "哪家强",
            "哪家比较",
            "哪家靠谱",
            "哪家更",
            "服务商哪家",
            "排行",
            "排名",
            "top",
            "TOP",
            "名单",
            "值得推荐",
            "怎么选",
            "如何选",
            "选购",
            "供应商怎么选",
            # 2026-10-29 - 「有哪些 / 哪个公司可以做」是采购名单，不能掉进默认品牌认知
            "有哪些",
            "哪个公司",
            "哪家公司",
            "哪些公司",
        ),
    ),
    ("compare", "竞品对标", ("对比", "vs", "VS", "还是", "和谁", "竞品", "哪家更好")),
    ("reputation", "口碑评价", ("靠谱吗", "怎么样", "好不好", "评价", "口碑", "坑", "靠不靠谱", "客户评价")),
    ("awareness", "品牌认知", ("是什么", "介绍", "了解", "品牌", "公司简介")),
]

SCENE_LABELS = {code: label for code, label, _ in SCENE_RULES}
INTENT_LABELS = {code: label for code, label, _ in INTENT_RULES}


def _normalize_aliases(brand: str, aliases: list[str] | None) -> list[str]:
    names: list[str] = []
    raw_brand = str(brand or "").strip()
    candidates = [raw_brand, *(aliases or [])]
    # 2026-08-12 - 公司全称问法常只写短名 - 剥常见后缀作别名参与品牌词判定
    for suffix in (
        "股份有限公司",
        "控股集团有限公司",
        "集团有限公司",
        "有限责任公司",
        "有限公司",
        "控股集团",
        "集团",
        "公司",
    ):
        if raw_brand.endswith(suffix) and len(raw_brand) > len(suffix) + 1:
            candidates.append(raw_brand[: -len(suffix)].strip())
            break
    for raw in candidates:
        text = str(raw or "").strip()
        if text and text not in names:
            names.append(text)
    # 2026-09-03 - 全称带地域/供应链时问法常只写短名（菜万家）- 抽核心词干参与品牌词判定
    core = str(brand or "").strip()
    for prefix in ("广东", "北京", "上海", "深圳", "浙江", "江苏", "四川", "湖南", "湖北", "河南", "山东"):
        if core.startswith(prefix) and len(core) > len(prefix) + 2:
            core = core[len(prefix) :].strip()
            break
    for mid in ("供应链", "传媒", "科技", "控股", "集团"):
        if mid in core:
            head = core.split(mid, 1)[0].strip()
            if len(head) >= 3 and head not in names:
                names.append(head)
            break
    return names


def prompt_contains_brand(prompt: str, brand: str, aliases: list[str] | None = None) -> bool:
    """问法是否含本品牌名/别名（大小写不敏感；中文按子串）。"""
    text = str(prompt or "")
    if not text:
        return False
    lower = text.casefold()
    for name in _normalize_aliases(brand, aliases):
        if not name:
            continue
        if name.casefold() in lower:
            return True
    return False


def detect_scene(prompt: str) -> tuple[str | None, str | None]:
    text = str(prompt or "")
    for code, label, keys in SCENE_RULES:
        if any(k in text for k in keys):
            return code, label
    return None, None


def detect_intent(prompt: str) -> tuple[str, str]:
    text = str(prompt or "")
    for code, label, keys in INTENT_RULES:
        if any(k in text for k in keys):
            return code, label
    return "awareness", INTENT_LABELS["awareness"]


def classify_prompt(
    prompt: str,
    *,
    brand: str,
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    """单条问法打标。

    filter_dim: scene 命中时用 scene，否则 intent（供第二筛选轴）。
    lane: acquisition=非品牌词获客；brand_defense=品牌防守/口碑承接。
    """
    text = str(prompt or "").strip()
    scene_code, scene_label = detect_scene(text)
    intent_code, intent_label = detect_intent(text)
    is_brand_word = prompt_contains_brand(text, brand, aliases)
    if scene_code:
        filter_dim = "scene"
        filter_code = scene_code
        filter_label = scene_label or scene_code
    else:
        filter_dim = "intent"
        filter_code = intent_code
        filter_label = intent_label
    return {
        "prompt": text,
        "lane": "brand_defense" if is_brand_word else "acquisition",
        "is_brand_word": is_brand_word,
        "scene_code": scene_code,
        "scene_label": scene_label,
        "intent_code": intent_code,
        "intent_label": intent_label,
        "filter_dim": filter_dim,
        "filter_code": filter_code,
        "filter_label": filter_label,
    }


def resolve_filter_mode(tagged_prompts: list[dict[str, Any]]) -> str:
    """报告级第二轴：任一条有场景 → 场景筛选，否则意图筛选。"""
    if any(row.get("scene_code") for row in tagged_prompts):
        return "scene"
    return "intent"


def heat_class(mention_rate: float | None, *, good: float = 35.0, watch: float = 15.0) -> str:
    try:
        value = float(mention_rate or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value >= good:
        return "heat-good"
    if value >= watch:
        return "heat-watch"
    return "heat-gap"


_SPACE_RE = re.compile(r"\s+")


def compact_prompt_label(prompt: str, *, max_len: int = 28) -> str:
    text = _SPACE_RE.sub(" ", str(prompt or "").strip())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"
