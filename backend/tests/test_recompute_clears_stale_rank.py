"""recompute_subtask_rank_from_answer must not keep stale api/llm ranks."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.monitor_service import BrandRankResolution, recompute_subtask_rank_from_answer


def test_recompute_clears_stale_mention_before_auto_parse(monkeypatch) -> None:
    """2026-07-29 - 留空补录仍吃旧位次4 - 自动解析前清 mention_position / rank_resolution。"""
    subtask = SimpleNamespace(
        mention_position=4,
        mention_context=None,
        raw_result_json={
            "source": "manual_snapshot",
            "manual_rank_locked": False,
            "rank_resolution": {"rank": 4, "source": "api", "mentioned": True, "confidence": 0.6},
        },
        answer_content="二、选型建议\n首选推荐\t备选\n大国品牌\t君智",
        all_rankings_json=[],
        prompt="打造头部品牌的服务商推荐",
    )
    task = SimpleNamespace(tenant_id=None, monitor_keywords="大国品牌", raw_request_json={})
    seen: dict = {}

    def fake_normalize(st) -> None:
        return None

    def fake_optional_llm(*, subtask, task, resolution, brand_terms, asset):
        seen["mp_during_resolve"] = subtask.mention_position
        seen["raw"] = dict(subtask.raw_result_json or {})
        return BrandRankResolution(rank=1, mentioned=True, source="llm", confidence=0.95)

    def fake_persist(st, resolution) -> None:
        raw = dict(st.raw_result_json or {})
        raw["rank_resolution"] = {
            "rank": resolution.rank,
            "source": resolution.source,
            "mentioned": resolution.mentioned,
            "confidence": resolution.confidence,
        }
        st.raw_result_json = raw

    monkeypatch.setattr("app.services.monitor_service._normalize_subtask_rankings_on_write", fake_normalize)
    monkeypatch.setattr("app.services.rank_llm_service.resolve_rank_with_optional_llm", fake_optional_llm)
    monkeypatch.setattr("app.services.rank_llm_service.persist_rank_resolution", fake_persist)

    recompute_subtask_rank_from_answer(
        MagicMock(), subtask, task, override_mention_position=None, force=True
    )

    assert seen["mp_during_resolve"] is None
    assert "rank_resolution" not in seen["raw"]
    assert seen["raw"].get("manual_rank_locked") is False
    assert subtask.mention_position == 1
    assert subtask.raw_result_json.get("rank_resolution", {}).get("rank") == 1


def test_recompute_llm_engine_merges_better_rule(monkeypatch) -> None:
    """2026-08-31 - 方案A：rank_engine=llm 仍跑规则，更靠前时压过 LLM。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "rank_engine", "llm")
    subtask = SimpleNamespace(
        mention_position=9,
        raw_result_json={},
        answer_content="1. 竞品A\n2. 鸿联九五",
        all_rankings_json=[],
        prompt="BPO公司推荐",
        mention_context=None,
    )
    task = SimpleNamespace(tenant_id=None, monitor_keywords="鸿联九五", raw_request_json={})

    def fake_rules(*_args, **_kwargs):
        return BrandRankResolution(rank=2, mentioned=True, source="appearance", confidence=0.7)

    def fake_llm(*, subtask, task, resolution, brand_terms, asset):
        assert resolution.rank == 2
        # 模拟 LLM 虚高；合并后应保留规则
        from app.services.rank_llm_service import apply_llm_rank_fallback, LlmBrandRankResult

        return apply_llm_rank_fallback(
            resolution,
            LlmBrandRankResult(
                rank=9,
                mentioned=True,
                category="中国市场",
                rank_basis="section_list",
                confidence=0.9,
                evidence=None,
            ),
        )

    def fake_persist(st, resolution) -> None:
        raw = dict(st.raw_result_json or {})
        raw["rank_resolution"] = {"rank": resolution.rank, "source": resolution.source}
        st.raw_result_json = raw

    monkeypatch.setattr("app.services.monitor_service._normalize_subtask_rankings_on_write", lambda st: None)
    monkeypatch.setattr("app.services.monitor_service._resolve_brand_rank_detail", fake_rules)
    monkeypatch.setattr("app.services.rank_llm_service.resolve_rank_with_optional_llm", fake_llm)
    monkeypatch.setattr("app.services.rank_llm_service.persist_rank_resolution", fake_persist)
    recompute_subtask_rank_from_answer(MagicMock(), subtask, task, force=True)
    assert subtask.mention_position == 2
    assert subtask.raw_result_json["rank_resolution"]["source"] == "appearance"


def test_recompute_skips_manual_snapshot_unless_forced() -> None:
    """2026-08-12 - 补录勿洗 - 无 force 时保留 manual_snapshot 原位次。"""
    subtask = SimpleNamespace(
        mention_position=3,
        raw_result_json={"source": "manual_snapshot", "manual_rank_locked": False},
        answer_content="万唯听力不错",
        all_rankings_json=[],
        prompt="教辅推荐",
    )
    task = SimpleNamespace(tenant_id=None, monitor_keywords="万唯", raw_request_json={})
    recompute_subtask_rank_from_answer(MagicMock(), subtask, task)
    assert subtask.mention_position == 3
    assert subtask.raw_result_json.get("source") == "manual_snapshot"


def test_preferred_column_table_rank_first_row() -> None:
    from app.services.monitor_service import _preferred_column_table_rank, _resolve_brand_rank_detail

    answer = (
        "二、按企业需求场景的选型建议\n"
        "企业发展阶段\t核心品牌目标\t首选推荐\t备选\n"
        "行业龙头/千亿级企业\t巩固领导地位\t大国品牌（国家级平台型）+ 奥美（国际4A）\t君智\n"
        "成长型头部企业（10-100亿）\t突破区域限制\t君智战略咨询\t华与华 / 松鼠跃动\n"
        "细分领域隐形冠军（B2B）\t从B端走向大众\t中网B2B战略咨询\t大国品牌\n"
    )
    assert _preferred_column_table_rank(answer, ["大国品牌"]) == 1

    subtask = SimpleNamespace(
        prompt="打造头部品牌的服务商推荐",
        answer_content=answer,
        mention_context=None,
        all_rankings_json=[],
        mention_position=None,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(subtask, "大国品牌（kimi）", ["大国品牌"], asset=None)
    assert detail.rank == 1
    assert detail.rank_basis == "preferred_column"


def test_preferred_column_ignores_prose_can_prefer_bullet() -> None:
    """2026-07-30 - 「可以首选松下」总结句不得当首选列表头，否则霍尼韦尔被数成第5。"""
    from app.services.monitor_service import _preferred_column_table_rank, _resolve_brand_rank_detail

    answer = """
### 主流品牌速览与定位
| 品牌类型 | 代表品牌与系列 | 核心特点 |
| --- | --- | --- |
| 日系 | **松下 (Panasonic)** <br>ZDP | 稳 |
| 欧美 | **霍尼韦尔 (Honeywell)** | 性价比 |
| 国产 | **格力 (GREE)** | 除霾 |

### 总结建议
*   **追求稳妥**：可以首选**松下**，产品成熟。
*   雾霾严重 → **格力**
*   母婴 → **空气堡**
*   节能 → **布朗**
*   **预算有限**：可以关注**霍尼韦尔**等性价比高的品牌。
"""
    assert _preferred_column_table_rank(answer, ["霍尼韦尔"]) is None

    subtask = SimpleNamespace(
        prompt="新风系统品牌推荐",
        answer_content=answer,
        mention_context=None,
        all_rankings_json=[],
        mention_position=5,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(subtask, "新风系统品牌推荐", ["霍尼韦尔"], asset=None)
    # 2026-08-12 - B/类内：「预算有限」下点名霍尼韦尔 → section_local 第1，优于旧全文虚高
    assert detail.mentioned is True
    assert detail.rank == 1
    assert detail.rank_basis in {"section_local", "secondary_section_local"}


def test_recompute_override_syncs_rank_resolution(monkeypatch) -> None:
    """2026-09-04 - 覆盖位次时同步 rank_resolution，避免识别元数据仍停在脏第1。"""
    subtask = SimpleNamespace(
        mention_position=1,
        raw_result_json={
            "source": "manual_snapshot",
            "manual_rank_locked": True,
            "rank_resolution": {
                "rank": 1,
                "source": "appearance",
                "rank_basis": "section_local",
                "category": "适合全屋柜体，预算中等家庭。",
                "mentioned": True,
                "confidence": 0.72,
            },
        },
        answer_content="1. 兔宝宝\n2. 千年舟\n3. 大王椰",
        all_rankings_json=[],
        prompt="环保板材品牌哪个好",
    )
    task = SimpleNamespace(tenant_id=None, monitor_keywords="大王椰", raw_request_json={})

    monkeypatch.setattr(
        "app.services.monitor_service._normalize_subtask_rankings_on_write",
        lambda _st: None,
    )

    def fake_persist(st, resolution) -> None:
        raw = dict(st.raw_result_json or {})
        raw["rank_resolution"] = {
            "rank": resolution.rank,
            "source": resolution.source,
            "rank_basis": resolution.rank_basis,
            "mentioned": resolution.mentioned,
            "confidence": resolution.confidence,
        }
        st.raw_result_json = raw

    monkeypatch.setattr("app.services.rank_llm_service.persist_rank_resolution", fake_persist)

    recompute_subtask_rank_from_answer(
        MagicMock(), subtask, task, override_mention_position=3, force=False
    )

    assert subtask.mention_position == 3
    rr = subtask.raw_result_json.get("rank_resolution") or {}
    assert rr.get("rank") == 3
    assert rr.get("source") == "manual"
    assert rr.get("rank_basis") == "override"
