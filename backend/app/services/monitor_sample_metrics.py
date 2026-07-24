"""监测样本口径：成功样本 / 排名样本 / 提及样本 / Top3 分母统一定义。

成功样本（SUCCESS）：completed / partial_completed — 计入率类指标分母
终态（TERMINAL）：成功 + failed / stopped — 仅用于任务进度，不作提及率分母
"""

from __future__ import annotations

from typing import Any, Iterable

SUCCESS_STATUSES = frozenset({"completed", "partial_completed"})
FAILED_STATUSES = frozenset({"failed", "stopped"})
TERMINAL_STATUSES = SUCCESS_STATUSES | FAILED_STATUSES


def is_success_status(status: str | None) -> bool:
    return str(status or "").strip() in SUCCESS_STATUSES


def is_terminal_status(status: str | None) -> bool:
    return str(status or "").strip() in TERMINAL_STATUSES


def success_subtasks(rows: Iterable[Any]) -> list[Any]:
    return [item for item in rows if is_success_status(getattr(item, "status", None))]


def compute_brand_rank_rates(
    rows: Iterable[Any],
    *,
    rank_of: Any | None = None,
) -> dict[str, Any]:
    """统一提及率 / Top3 率 / 平均排名。

    mention_rate = 有位次的成功样本 / 成功样本
    top3_rate    = rank<=3 的成功样本 / 成功样本
    avg_rank     = 有名次样本的均值；无名次则 None（不用 0 冒充）

    rank_of: 可选 (item) -> rank；默认读 mention_position。
    """
    def _rank(item: Any) -> Any:
        if rank_of is not None:
            return rank_of(item)
        return getattr(item, "mention_position", None)

    success = success_subtasks(rows)
    mentioned = [item for item in success if _rank(item) is not None]
    top3 = [item for item in mentioned if float(_rank(item)) <= 3]
    success_n = len(success)
    mentioned_n = len(mentioned)
    top3_n = len(top3)
    avg_rank = (
        round(sum(float(_rank(item)) for item in mentioned) / mentioned_n, 1)
        if mentioned_n
        else None
    )
    return {
        "success_count": success_n,
        "mentioned_count": mentioned_n,
        "top3_count": top3_n,
        "mention_rate": round(mentioned_n / success_n * 100, 1) if success_n else 0.0,
        "top3_rate": round(top3_n / success_n * 100, 1) if success_n else 0.0,
        "avg_rank": avg_rank,
    }
