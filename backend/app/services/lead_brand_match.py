"""售前品牌露出：共用匹配词与子任务位次解析。

2026-08-21 - 格级/样本两套算法不一致 - 统一弱别名门槛与位次解析入口
"""

from __future__ import annotations

import re
from typing import Any, Iterable


def is_weak_brand_alias(term: str | None) -> bool:
    """短别名默认不进自动匹配：纯拉丁/数字 ≤3，或其它长度 <3。

    强别名需入口显式配置（当前无单独开关时一律按弱别名过滤）。
    """
    text = str(term or "").strip()
    if not text:
        return True
    if re.fullmatch(r"[A-Za-z0-9]+", text) and len(text) <= 3:
        return True
    return len(text) < 3


def matchable_brand_terms(brand: str | None, aliases: Iterable[str] | None = None) -> list[str]:
    """可参与露出匹配的词：品牌全称强制保留，弱别名剔除。"""
    out: list[str] = []
    seen: set[str] = set()

    def _add(value: str | None, *, force: bool = False) -> None:
        text = str(value or "").strip()
        if not text or text in seen:
            return
        if not force and is_weak_brand_alias(text):
            return
        seen.add(text)
        out.append(text)

    _add(brand, force=True)
    for alias in aliases or []:
        _add(alias, force=False)
    return out


def resolve_subtask_brand_rank(
    item: Any,
    brand: str,
    brand_terms: list[str],
) -> float | None:
    """子任务品牌位次：信任已写 mention_position，否则按匹配词解析榜单。

    与热力格/样本表共用，避免各算各的。
    """
    if getattr(item, "mention_position", None) is not None:
        try:
            return float(item.mention_position)
        except (TypeError, ValueError):
            pass
    from app.services.monitor_service import _resolve_brand_rank

    terms = matchable_brand_terms(brand, brand_terms)
    if not terms:
        return None
    rank, mentioned = _resolve_brand_rank(item, "", terms, None)
    if mentioned and rank is not None:
        try:
            return float(rank)
        except (TypeError, ValueError):
            return None
    return None
