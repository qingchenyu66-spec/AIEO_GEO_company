"""算力预扣 / 结算 / 释放 单测（B5）。"""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.credit import TenantCreditLedger
from app.models.tenant import Tenant
from app.services.credit_service import (
    finalize_schedule_submit,
    release_reserve,
    reserve_credits,
    scan_stale_reserves,
    settle_credits,
    settle_open_credit_reserves,
    tenant_available_credits,
)




# 2026-09-09 - 租户种子只 flush；commit 已由 credit_db 夹具降级
def _seed_credit_tenant(db, *, balance: Decimal = Decimal("100")) -> Tenant:
    suffix = uuid4().hex[:8]
    tenant = Tenant(
        name=f"CR-{suffix}",
        code=f"CR{suffix}",
        status=True,
        billing_mode="credit",
        credit_balance=balance,
        credit_reserved=Decimal("0"),
        platform_whitelist_json=["doubao"],
    )
    db.add(tenant)
    db.flush()
    return tenant


def test_reserve_fails_when_insufficient(db):
    tenant = _seed_credit_tenant(db, balance=Decimal("5"))
    ok = reserve_credits(db, tenant, Decimal("10"), ref_id="r1", ref_type="reserve_batch")
    assert ok is False
    db.refresh(tenant)
    assert tenant.credit_reserved == Decimal("0")


def test_reserve_settle_release_chain(db):
    tenant = _seed_credit_tenant(db, balance=Decimal("50"))
    ref = "batch-1"
    assert reserve_credits(db, tenant, Decimal("12"), ref_id=ref, ref_type="reserve_batch", window_key="20260827-09")
    db.refresh(tenant)
    assert tenant.credit_reserved == Decimal("12")
    assert tenant_available_credits(tenant) == Decimal("38")

    settle_credits(db, tenant_id=tenant.id, ref_id=ref, credits=Decimal("10"), platform_code="doubao")
    db.refresh(tenant)
    assert tenant.credit_balance == Decimal("40")
    assert tenant.credit_reserved == Decimal("0")

    rows = list(
        db.scalars(
            select(TenantCreditLedger).where(
                TenantCreditLedger.tenant_id == tenant.id,
                TenantCreditLedger.ref_id == ref,
            )
        )
    )
    types = {row.entry_type for row in rows}
    assert "reserve" in types
    assert "settle" in types


def test_list_credit_ledger_exclude_internal(db):
    from app.services.credit_service import list_credit_ledger

    tenant = _seed_credit_tenant(db, balance=Decimal("50"))
    ref = "batch-filter"
    assert reserve_credits(db, tenant, Decimal("12"), ref_id=ref, ref_type="reserve_batch", window_key="20260827-09")
    settle_credits(db, tenant_id=tenant.id, ref_id=ref, credits=Decimal("10"), platform_code="doubao")
    db.flush()

    full = list_credit_ledger(db, tenant_id=tenant.id, page=1, page_size=20, exclude_internal=False)
    visible = list_credit_ledger(db, tenant_id=tenant.id, page=1, page_size=20, exclude_internal=True)
    full_types = {row["entry_type"] for row in full["items"]}
    visible_types = {row["entry_type"] for row in visible["items"]}
    assert {"reserve", "release"} & full_types
    assert "reserve" not in visible_types
    assert "release" not in visible_types
    assert "settle" in visible_types


def test_list_credit_ledger_tenant_name_filter(db):
    from app.services.credit_service import list_credit_ledger

    tenant = _seed_credit_tenant(db, balance=Decimal("10"))
    tenant.name = "艾迪亚控股集团有限公司"
    db.add(
        TenantCreditLedger(
            tenant_id=tenant.id,
            amount=Decimal("10"),
            balance_after=Decimal("10"),
            entry_type="recharge",
            ref_type="manual",
            reason="test",
        )
    )
    db.flush()

    hit = list_credit_ledger(db, tenant_name="艾迪亚", page=1, page_size=20)
    miss = list_credit_ledger(db, tenant_name="不存在企业名", page=1, page_size=20)
    assert len(hit["items"]) >= 1
    assert hit["items"][0]["tenant_name"] == "艾迪亚控股集团有限公司"
    assert miss["items"] == []


def test_double_reserve_same_ref_is_idempotent(db):
    tenant = _seed_credit_tenant(db, balance=Decimal("30"))
    ref = "dup-ref"
    assert reserve_credits(db, tenant, Decimal("10"), ref_id=ref, ref_type="reserve_batch")
    assert reserve_credits(db, tenant, Decimal("10"), ref_id=ref, ref_type="reserve_batch")
    db.refresh(tenant)
    assert tenant.credit_reserved == Decimal("10")
    assert tenant_available_credits(tenant) == Decimal("20")


def test_finalize_keeps_reserve_on_submitted(db):
    """提交成功只保留预扣，不在此刻整批 settle。"""
    tenant = _seed_credit_tenant(db, balance=Decimal("50"))
    ref = "multi-platform-batch"
    reserved = Decimal("12")
    assert reserve_credits(db, tenant, reserved, ref_id=ref, ref_type="reserve_batch")
    finalize_schedule_submit(
        db,
        tenant,
        reserve_ref=ref,
        reserved_credits=reserved,
        submit_status="submitted",
    )
    db.refresh(tenant)
    assert tenant.credit_balance == Decimal("50")
    assert tenant.credit_reserved == Decimal("12")


def test_finalize_release_on_failed_submit(db):
    tenant = _seed_credit_tenant(db, balance=Decimal("40"))
    ref = "fail-batch"
    assert reserve_credits(db, tenant, Decimal("8"), ref_id=ref, ref_type="reserve_batch")
    finalize_schedule_submit(
        db,
        tenant,
        reserve_ref=ref,
        reserved_credits=Decimal("8"),
        submit_status="failed",
    )
    db.refresh(tenant)
    assert tenant.credit_reserved == Decimal("0")
    assert tenant.credit_balance == Decimal("40")


def test_estimate_schedule_submit_credits(db):
    from app.services.credit_service import estimate_schedule_submit_credits

    tenant = _seed_credit_tenant(db, balance=Decimal("100"))
    credits = estimate_schedule_submit_credits(
        db,
        tenant,
        platform_codes=["doubao", "kimi"],
        prompt_count=3,
    )
    # 单价 1 → 同格预扣份额 min(1×1, cap2)=1；2 平台 ×3 词 = 6
    assert credits == Decimal("6")


def test_has_open_reserve_after_partial_cell_settle(db):
    from types import SimpleNamespace

    from app.services.credit_service import (
        finalize_monitor_cell_credit,
        has_open_credit_reserve,
        reserve_credits,
    )

    tenant = _seed_credit_tenant(db, balance=Decimal("20"))
    ref = "partial-open"
    assert reserve_credits(
        db,
        tenant,
        Decimal("4"),
        ref_id=ref,
        ref_type="reserve_batch",
        detail_json={"shares_by_platform": {"doubao": 2.0}, "default_cell_share": 2.0},
    )
    billed = SimpleNamespace(
        subtask_id="st-1",
        platform="doubao",
        prompt="词1",
        status="completed",
        amount=Decimal("0.1"),
        auto_retry_status=None,
        auto_retry_count=0,
        answer_content="ok",
        error_message=None,
        raw_result_json=None,
    )
    assert finalize_monitor_cell_credit(db, tenant, origin=billed, batch_ref=ref) is True
    assert has_open_credit_reserve(db, tenant.id, ref) is True
    assert reserve_credits(db, tenant, Decimal("4"), ref_id=ref, ref_type="reserve_batch") is True
    db.refresh(tenant)
    # 不得叠扣第二笔预扣
    assert tenant.credit_reserved == Decimal("2")


def test_finalize_rolls_back_claim_when_settle_raises(db, monkeypatch):
    """claim 与 settle 同 savepoint：settle 失败不得留下永久 claim 导致漏扣。"""
    from types import SimpleNamespace

    from app.models.credit import TenantCreditCellFinalize
    from app.services.credit_service import (
        cell_credit_already_finalized,
        finalize_monitor_cell_credit,
        reserve_credits,
    )

    tenant = _seed_credit_tenant(db, balance=Decimal("20"))
    ref = "claim-rollback"
    assert reserve_credits(
        db,
        tenant,
        Decimal("4"),
        ref_id=ref,
        ref_type="reserve_batch",
        detail_json={"shares_by_platform": {"doubao": 2.0}, "default_cell_share": 2.0},
    )
    billed = SimpleNamespace(
        subtask_id="st-rollback",
        platform="doubao",
        prompt="词1",
        status="completed",
        amount=Decimal("0.1"),
        auto_retry_status=None,
        auto_retry_count=0,
        answer_content="ok",
        error_message=None,
        raw_result_json=None,
    )

    def _boom(*_a, **_k):
        raise RuntimeError("settle boom")

    monkeypatch.setattr("app.services.credit_service.settle_credits", _boom)
    with pytest.raises(RuntimeError, match="settle boom"):
        finalize_monitor_cell_credit(db, tenant, origin=billed, batch_ref=ref)
    assert cell_credit_already_finalized(
        db, tenant_id=tenant.id, batch_ref=ref, origin_subtask_id="st-rollback"
    ) is False
    assert (
        db.scalar(
            select(TenantCreditCellFinalize).where(
                TenantCreditCellFinalize.tenant_id == tenant.id,
                TenantCreditCellFinalize.batch_ref == ref,
                TenantCreditCellFinalize.origin_subtask_id == "st-rollback",
            )
        )
        is None
    )


def test_cell_settle_releases_unbilled_and_charges_billed(db):
    from types import SimpleNamespace

    from app.services.credit_service import finalize_monitor_cell_credit, maybe_release_batch_reserve_remainder

    tenant = _seed_credit_tenant(db, balance=Decimal("20"))
    ref = "cell-batch"
    assert reserve_credits(
        db,
        tenant,
        Decimal("4"),
        ref_id=ref,
        ref_type="reserve_batch",
        detail_json={"shares_by_platform": {"doubao": 2.0}, "default_cell_share": 2.0},
    )

    unbilled = SimpleNamespace(
        subtask_id="st-unbilled",
        platform="doubao",
        prompt="词A",
        status="failed",
        amount=Decimal("0"),
        auto_retry_status="failed",
        auto_retry_count=1,
        answer_content=None,
        error_message="timeout",
        raw_result_json=None,
    )
    billed = SimpleNamespace(
        subtask_id="st-billed",
        platform="doubao",
        prompt="词B",
        status="completed",
        amount=Decimal("0.12"),
        auto_retry_status=None,
        auto_retry_count=0,
        answer_content="ok",
        error_message=None,
        raw_result_json=None,
    )
    assert finalize_monitor_cell_credit(db, tenant, origin=unbilled, batch_ref=ref) is True
    assert finalize_monitor_cell_credit(db, tenant, origin=billed, batch_ref=ref) is True
    assert finalize_monitor_cell_credit(db, tenant, origin=billed, batch_ref=ref) is False
    maybe_release_batch_reserve_remainder(db, tenant, batch_ref=ref, origins=[unbilled, billed])

    db.refresh(tenant)
    assert tenant.credit_reserved == Decimal("0")
    assert tenant.credit_balance == Decimal("19")


def test_completed_without_amount_does_not_finalize_until_amount_lands(db):
    """完成态但模力 amount 仍空时不 finalize，避免晚到金额被误释放。"""
    from types import SimpleNamespace

    from app.models.credit import TenantCreditCellFinalize
    from app.services.credit_service import finalize_monitor_cell_credit

    tenant = _seed_credit_tenant(db, balance=Decimal("10"))
    ref = "amount-lag"
    assert reserve_credits(
        db,
        tenant,
        Decimal("1"),
        ref_id=ref,
        ref_type="reserve_batch",
        detail_json={"shares_by_platform": {"doubao": 1.0}, "default_cell_share": 1.0},
    )
    origin = SimpleNamespace(
        subtask_id="st-amount-lag",
        platform="doubao",
        prompt="词晚到",
        status="completed",
        amount=None,
        auto_retry_status=None,
        auto_retry_count=0,
        answer_content="已有正文",
        error_message=None,
        raw_result_json={"status": "completed"},
    )
    assert finalize_monitor_cell_credit(db, tenant, origin=origin, batch_ref=ref) is False
    db.refresh(tenant)
    assert tenant.credit_reserved == Decimal("1")
    assert tenant.credit_balance == Decimal("10")
    assert db.scalar(select(TenantCreditCellFinalize.id).where(TenantCreditCellFinalize.origin_subtask_id == "st-amount-lag")) is None

    origin.amount = Decimal("0.18")
    origin.raw_result_json = {"status": "completed", "amount": 0.18}
    assert finalize_monitor_cell_credit(db, tenant, origin=origin, batch_ref=ref) is True
    db.refresh(tenant)
    assert tenant.credit_reserved == Decimal("0")
    assert tenant.credit_balance == Decimal("9")
    settle = db.scalar(
        select(TenantCreditLedger).where(
            TenantCreditLedger.tenant_id == tenant.id,
            TenantCreditLedger.ref_id == ref,
            TenantCreditLedger.entry_type == "settle",
        )
    )
    assert settle is not None
    assert settle.amount == Decimal("-1")


def test_backfill_false_unbilled_releases_charges_late_amount(db):
    """误释放后 amount 晚到：补扣 settle，余额减 1，finalize 改为 settle。"""
    from types import SimpleNamespace

    from app.models.credit import TenantCreditCellFinalize
    from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
    from app.services.credit_service import backfill_false_unbilled_releases, finalize_monitor_cell_credit

    tenant = _seed_credit_tenant(db, balance=Decimal("10"))
    ref = "backfill-lag"
    task_id = f"task-{uuid4().hex[:12]}"
    assert reserve_credits(
        db,
        tenant,
        Decimal("1"),
        ref_id=ref,
        ref_type="reserve_batch",
        detail_json={"shares_by_platform": {"doubao": 1.0}, "default_cell_share": 1.0},
    )
    # 旧逻辑：完成态无 amount 会 release；这里用硬失败先落一条 release finalize
    origin_early = SimpleNamespace(
        subtask_id="st-backfill",
        platform="doubao",
        prompt="词补扣",
        status="failed",
        amount=Decimal("0"),
        auto_retry_status="failed",
        auto_retry_count=1,
        answer_content=None,
        error_message="timeout",
        raw_result_json=None,
    )
    assert finalize_monitor_cell_credit(db, tenant, origin=origin_early, batch_ref=ref) is True
    db.refresh(tenant)
    assert tenant.credit_reserved == Decimal("0")
    assert tenant.credit_balance == Decimal("10")

    db.add(
        GeoMonitorTask(
            task_id=task_id,
            tenant_id=tenant.id,
            status="completed",
            total_items=1,
            completed_items=1,
            failed_items=0,
            prompts_json=["词补扣"],
            platforms_json=[{"platform": "doubao"}],
            raw_request_json={},
            raw_response_json={},
        )
    )
    db.add(
        GeoMonitorSubtask(
            subtask_id="st-backfill",
            task_id=task_id,
            platform="doubao",
            mode="search",
            prompt="词补扣",
            status="completed",
            amount=Decimal("0.18"),
            answer_content="ok",
            raw_result_json={"amount": 0.18, "status": "completed"},
        )
    )
    db.flush()

    result = backfill_false_unbilled_releases(db, tenant_id=tenant.id, batch_ref=ref)
    assert result["ok"] is True
    assert result["settled"] == ["st-backfill"]
    db.refresh(tenant)
    assert tenant.credit_balance == Decimal("9")
    claim = db.scalar(
        select(TenantCreditCellFinalize).where(
            TenantCreditCellFinalize.tenant_id == tenant.id,
            TenantCreditCellFinalize.batch_ref == ref,
            TenantCreditCellFinalize.origin_subtask_id == "st-backfill",
        )
    )
    assert claim is not None
    assert claim.entry_type == "settle"
    assert claim.credits == Decimal("1")
    # 幂等：已改成 settle 后不再匹配 release claim
    again = backfill_false_unbilled_releases(db, tenant_id=tenant.id, batch_ref=ref)
    assert again["settled"] == []
    assert again["skipped"] == []
    db.refresh(tenant)
    assert tenant.credit_balance == Decimal("9")
    # 再造一条已 settle 的 release 场景：手动把 claim 拨回 release，应命中 already_settled
    claim.entry_type = "release"
    claim.credits = Decimal("0")
    db.flush()
    third = backfill_false_unbilled_releases(db, tenant_id=tenant.id, batch_ref=ref)
    assert third["settled"] == []
    assert third["skipped"][0]["reason"] == "already_settled"
    db.refresh(tenant)
    assert tenant.credit_balance == Decimal("9")


def test_cell_settle_retry_still_one_credit(db):
    """产品：重试免费，即使 attempt 列表有两次计费也只收 1 格。"""
    from types import SimpleNamespace

    from app.services.credit_service import finalize_monitor_cell_credit

    tenant = _seed_credit_tenant(db, balance=Decimal("10"))
    ref = "retry-cap"
    assert reserve_credits(
        db,
        tenant,
        Decimal("1"),
        ref_id=ref,
        ref_type="reserve_batch",
        detail_json={"shares_by_platform": {"doubao": 1.0}, "default_cell_share": 1.0},
    )
    origin = SimpleNamespace(
        subtask_id="st-retry",
        platform="doubao",
        prompt="词C",
        status="completed",
        amount=Decimal("0.2"),
        auto_retry_status="succeeded",
        auto_retry_count=1,
        answer_content="ok",
        error_message=None,
        raw_result_json={"_credit_attempt_amounts": [0.1, 0.2]},
    )
    assert finalize_monitor_cell_credit(db, tenant, origin=origin, batch_ref=ref) is True
    db.refresh(tenant)
    # 单价 1 × 1 次 = 1
    assert tenant.credit_balance == Decimal("9")
    assert tenant.credit_reserved == Decimal("0")


def test_can_submit_platform_always_allows(db, monkeypatch):
    """方案乙：真金不足也不硬拦。"""
    from app.services import credit_service

    monkeypatch.setattr(
        credit_service,
        "fetch_molizhishu_balance",
        lambda: {"available": True, "current_balance": 1.0},
    )
    monkeypatch.setattr(
        credit_service,
        "get_cached_platform_window_estimate",
        lambda: {"estimated_yuan": 1000.0},
    )
    monkeypatch.setattr(credit_service, "_config_decimal", lambda k, d: Decimal("500"))
    monkeypatch.setattr(credit_service, "_config_int", lambda k, d: 1)
    ok, balance, estimate = credit_service.can_submit_platform(db)
    assert ok is True
    assert balance == Decimal("1")
    sufficient, _, _ = credit_service.evaluate_platform_runway(db)
    assert sufficient is False


def test_can_submit_platform_reads_molizhishu_current_balance(db, monkeypatch):
    from app.services import credit_service

    monkeypatch.setattr(
        credit_service,
        "fetch_molizhishu_balance",
        lambda: {"available": True, "current_balance": 2000.0},
    )
    monkeypatch.setattr(
        credit_service,
        "get_cached_platform_window_estimate",
        lambda: {"estimated_yuan": 100.0},
    )
    ok, balance, estimate = credit_service.can_submit_platform(db)
    assert ok is True
    assert balance == Decimal("2000")
    assert estimate == Decimal("100")
    sufficient, _, _ = credit_service.evaluate_platform_runway(db)
    assert sufficient is True


def test_customer_ledger_balance_coherent_when_internal_hidden(db):
    from app.services.credit_service import list_credit_ledger, recharge_credits

    tenant = _seed_credit_tenant(db, balance=Decimal("100"))
    ref = "hide-internal"
    assert reserve_credits(db, tenant, Decimal("50"), ref_id=ref, ref_type="reserve_batch")
    settle_credits(db, tenant_id=tenant.id, ref_id=ref, credits=Decimal("10"))
    release_reserve(db, tenant_id=tenant.id, ref_id=ref, reason="cleanup")
    recharge_credits(db, tenant, Decimal("5"), operator_user_id=1, reason="topup")
    db.flush()

    visible = list_credit_ledger(db, tenant_id=tenant.id, page=1, page_size=20, exclude_internal=True)
    items = visible["items"]
    by_type = {item["entry_type"]: item for item in items}
    assert "recharge" in by_type and "settle" in by_type
    recharge = by_type["recharge"]
    settle = by_type["settle"]
    assert recharge["id"] > settle["id"]
    assert Decimal(str(recharge["balance_after"])) - Decimal(str(recharge["amount"])) == Decimal(str(settle["balance_after"]))


def test_scan_stale_reserves_releases_expired(db, monkeypatch):
    tenant = _seed_credit_tenant(db, balance=Decimal("20"))
    ref = "stale-ref"
    assert reserve_credits(db, tenant, Decimal("6"), ref_id=ref, ref_type="reserve_batch")
    row = db.scalar(
        select(TenantCreditLedger).where(
            TenantCreditLedger.tenant_id == tenant.id,
            TenantCreditLedger.ref_id == ref,
            TenantCreditLedger.entry_type == "reserve",
        )
    )
    assert row is not None
    row.reserve_expires_at = datetime.now() - timedelta(minutes=5)
    db.flush()

    released = scan_stale_reserves(db)
    assert released >= 1
    tenant = db.get(Tenant, tenant.id)
    assert tenant is not None
    assert tenant.credit_reserved == Decimal("0")


def test_apply_schedule_credit_gate_skips_hosted(db):
    from app.services.credit_service import apply_schedule_credit_gate

    suffix = uuid4().hex[:8]
    tenant = Tenant(name=f"H-{suffix}", code=f"H{suffix}", status=True, billing_mode="hosted")
    db.add(tenant)
    db.flush()
    gate = apply_schedule_credit_gate(
        db,
        tenant,
        group_key="20260904-0930-kw0",
        schedule_key="20260904-0930",
        platform_codes=["doubao"],
        prompt_count=3,
    )
    assert gate.allowed is True
    assert gate.reserved_credits is None


def test_apply_schedule_credit_gate_blocks_insufficient_balance(db, monkeypatch):
    from app.services.credit_service import apply_schedule_credit_gate

    monkeypatch.setattr("app.services.credit_service.pending_terms_block", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "app.services.credit_service.can_submit_platform",
        lambda *_a, **_k: (True, Decimal("9999"), Decimal("0")),
    )
    tenant = _seed_credit_tenant(db, balance=Decimal("0"))
    gate = apply_schedule_credit_gate(
        db,
        tenant,
        group_key="20260904-0930-kw0",
        schedule_key="20260904-0930",
        platform_codes=["doubao"],
        prompt_count=3,
    )
    assert gate.allowed is False
    assert gate.reason == "tenant_credit"
    db.refresh(tenant)
    assert tenant.credit_reserved == Decimal("0")


def test_preflight_reuses_open_reserve_when_available_low(db, monkeypatch):
    """坑1：钱已锁在同 ref 预扣里，可用额不够时重试仍应放行。"""
    from app.services.credit_service import preflight_schedule_submit

    monkeypatch.setattr("app.services.credit_service.pending_terms_block", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "app.services.credit_service.can_submit_platform",
        lambda *_a, **_k: (True, Decimal("9999"), Decimal("0")),
    )
    tenant = _seed_credit_tenant(db, balance=Decimal("10"))
    ref = "reuse-open-ref"
    assert reserve_credits(db, tenant, Decimal("10"), ref_id=ref, ref_type="reserve_batch")
    db.refresh(tenant)
    assert tenant_available_credits(tenant) == Decimal("0")

    gate = preflight_schedule_submit(
        db,
        tenant,
        window_key="20260907-10",
        reserve_ref=ref,
        credits_needed=Decimal("10"),
    )
    assert gate.allowed is True
    assert gate.reserve_ref == ref
    assert Decimal(str(gate.reserved_credits or 0)) == Decimal("10")
    db.refresh(tenant)
    assert tenant.credit_reserved == Decimal("10")


def test_normal_batch_close_does_not_block_late_cell_settle(db):
    """坑2：正常清尾的 batch_close 不得当成运营强制关，晚到格子仍可补扣。"""
    from types import SimpleNamespace

    from app.services.credit_service import (
        batch_force_closed,
        finalize_monitor_cell_credit,
        maybe_release_batch_reserve_remainder,
    )

    tenant = _seed_credit_tenant(db, balance=Decimal("20"))
    ref = "late-cell-batch"
    assert reserve_credits(
        db,
        tenant,
        Decimal("4"),
        ref_id=ref,
        ref_type="reserve_batch",
        detail_json={"shares_by_platform": {"doubao": 2.0}, "default_cell_share": 2.0},
    )
    early = SimpleNamespace(
        subtask_id="st-early",
        platform="doubao",
        prompt="词早",
        status="completed",
        amount=Decimal("0.1"),
        auto_retry_status=None,
        auto_retry_count=0,
        answer_content="ok",
        error_message=None,
        raw_result_json=None,
    )
    assert finalize_monitor_cell_credit(db, tenant, origin=early, batch_ref=ref) is True
    # 人为只带一格清尾（模拟 origins 不全），打上 batch_close
    maybe_release_batch_reserve_remainder(db, tenant, batch_ref=ref, origins=[early])
    assert batch_force_closed(db, tenant.id, ref) is False

    late = SimpleNamespace(
        subtask_id="st-late",
        platform="doubao",
        prompt="词晚",
        status="completed",
        amount=Decimal("0.1"),
        auto_retry_status=None,
        auto_retry_count=0,
        answer_content="ok",
        error_message=None,
        raw_result_json=None,
    )
    assert finalize_monitor_cell_credit(db, tenant, origin=late, batch_ref=ref) is True
    db.refresh(tenant)
    # 两格各扣 1
    assert tenant.credit_balance == Decimal("18")


def test_ops_force_close_still_blocks_late_settle(db):
    from types import SimpleNamespace

    from app.services.credit_service import batch_force_closed, finalize_monitor_cell_credit

    tenant = _seed_credit_tenant(db, balance=Decimal("20"))
    ref = "force-close-batch"
    assert reserve_credits(db, tenant, Decimal("4"), ref_id=ref, ref_type="reserve_batch")
    release_reserve(
        db,
        tenant_id=tenant.id,
        ref_id=ref,
        reason="运营手工释放",
        detail_json={"batch_force_closed": True},
    )
    assert batch_force_closed(db, tenant.id, ref) is True
    late = SimpleNamespace(
        subtask_id="st-force-late",
        platform="doubao",
        prompt="词",
        status="completed",
        amount=Decimal("0.1"),
        auto_retry_status=None,
        auto_retry_count=0,
        answer_content="ok",
        error_message=None,
        raw_result_json=None,
    )
    assert finalize_monitor_cell_credit(db, tenant, origin=late, batch_ref=ref) is False
    db.refresh(tenant)
    assert tenant.credit_balance == Decimal("20")


def test_scan_stale_skips_when_cells_not_finalized(db):
    """坑3：主任务已终态但格子未 settle / 等自动重试时，TTL 不得退预扣。"""
    from app.models.monitor import GeoMonitorScheduleRun, GeoMonitorSubtask, GeoMonitorTask

    tenant = _seed_credit_tenant(db, balance=Decimal("20"))
    ref = f"stale-keep-{uuid4().hex[:8]}"
    task_id = f"task-{uuid4().hex[:12]}"
    assert reserve_credits(db, tenant, Decimal("6"), ref_id=ref, ref_type="reserve_batch")
    row = db.scalar(
        select(TenantCreditLedger).where(
            TenantCreditLedger.tenant_id == tenant.id,
            TenantCreditLedger.ref_id == ref,
            TenantCreditLedger.entry_type == "reserve",
        )
    )
    assert row is not None
    row.reserve_expires_at = datetime.now() - timedelta(minutes=5)

    db.add(
        GeoMonitorTask(
            task_id=task_id,
            tenant_id=tenant.id,
            status="completed",
            total_items=1,
            completed_items=1,
            failed_items=0,
            prompts_json=["词"],
            platforms_json=[{"platform": "doubao"}],
            raw_request_json={"_geo_credit": {"reserve_ref": ref}},
            raw_response_json={},
        )
    )
    db.add(
        GeoMonitorScheduleRun(
            tenant_id=tenant.id,
            schedule_key=ref,
            task_id=task_id,
            status="submitted",
            prompt_count=1,
            platform_count=1,
        )
    )
    db.add(
        GeoMonitorSubtask(
            subtask_id=f"st-{uuid4().hex[:10]}",
            task_id=task_id,
            platform="doubao",
            mode="search",
            prompt="词",
            status="failed",
            amount=Decimal("0"),
            auto_retry_status="pending",
            auto_retry_count=1,
            raw_result_json={},
        )
    )
    db.flush()

    released = scan_stale_reserves(db)
    assert released == 0
    db.refresh(tenant)
    assert tenant.credit_reserved == Decimal("6")


def test_submit_locked_skips_molizhishu_when_credit_gate_blocks(monkeypatch):
    """闸拦下时不得打模力：这是本 bug 的回归钉。"""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from app.schemas.monitor import MonitorTaskCreateRequest, PlatformConfig
    from app.services.credit_service import SubmitGateResult
    from app.services.schedule_service import DueScheduleGroup, _submit_schedule_group_locked

    payload = MonitorTaskCreateRequest(
        tenant_id=1,
        prompts=["测试词"],
        platforms=[PlatformConfig(platform="doubao")],
        monitor_keywords="测试词",
    )
    monkeypatch.setattr(
        "app.services.schedule_service.active_keyword_groups",
        lambda *_a, **_k: [{"id": 0, "sort_order": 0}],
    )
    monkeypatch.setattr("app.services.schedule_service.build_scheduled_payload", lambda *_a, **_k: payload)
    monkeypatch.setattr("app.services.schedule_service.get_schedule_run", lambda *_a, **_k: None)
    submit_hits: list[int] = []
    monkeypatch.setattr(
        "app.services.schedule_service.submit_monitor_task",
        lambda *_a, **_k: submit_hits.append(1),
    )
    monkeypatch.setattr(
        "app.services.credit_service.apply_schedule_credit_gate",
        lambda *_a, **_k: SubmitGateResult(False, "tenant_credit", "算力不足，请联系销售充值"),
    )

    db = MagicMock()
    db.scalars.return_value = []
    item = DueScheduleGroup(
        tenant_id=1,
        schedule_key="20260904-0930",
        group_key="20260904-0930-kw0",
        max_prompts=50,
        keyword="测试词",
    )
    current = SimpleNamespace(user=SimpleNamespace(id=1))
    asset = SimpleNamespace(tenant_id=1, deleted=False, status=True)
    tenant = SimpleNamespace(id=1, billing_mode="credit")
    result = _submit_schedule_group_locked(db, current, item, asset, tenant)
    assert result["status"] == "skipped"
    assert "算力不足" in (result.get("message") or "")
    assert submit_hits == []


def test_release_reserve_none_amount_does_not_steal_other_batch(db):
    """同租户多 batch：整批 settle / 重复 release 不得清掉邻批预扣。"""
    tenant = _seed_credit_tenant(db, balance=Decimal("100"))
    assert reserve_credits(db, tenant, Decimal("20"), ref_id="batch-a", ref_type="reserve_batch")
    assert reserve_credits(db, tenant, Decimal("30"), ref_id="batch-b", ref_type="reserve_batch")
    db.refresh(tenant)
    assert tenant.credit_reserved == Decimal("50")

    settle_credits(db, tenant_id=tenant.id, ref_id="batch-a", credits=Decimal("20"), platform_code="doubao")
    db.refresh(tenant)
    assert tenant.credit_reserved == Decimal("30")
    assert tenant.credit_balance == Decimal("80")

    release_reserve(db, tenant_id=tenant.id, ref_id="batch-a", amount=None, reason="重复释放")
    db.refresh(tenant)
    assert tenant.credit_reserved == Decimal("30")

    # 本批少扣时只释放本 ref 残余，邻批仍在
    assert reserve_credits(db, tenant, Decimal("10"), ref_id="batch-c", ref_type="reserve_batch")
    settle_credits(db, tenant_id=tenant.id, ref_id="batch-c", credits=Decimal("4"), platform_code="doubao")
    db.refresh(tenant)
    assert tenant.credit_reserved == Decimal("30")
    assert tenant.credit_balance == Decimal("76")


def test_prepaid_share_cannot_steal_other_batch_reserved(db):
    """按格显式 prepaid_share 超过本 ref 剩余时，不得吞邻批预扣。"""
    tenant = _seed_credit_tenant(db, balance=Decimal("100"))
    assert reserve_credits(db, tenant, Decimal("8"), ref_id="share-a", ref_type="reserve_batch")
    assert reserve_credits(db, tenant, Decimal("40"), ref_id="share-b", ref_type="reserve_batch")
    db.refresh(tenant)
    assert tenant.credit_reserved == Decimal("48")

    settle_credits(
        db,
        tenant_id=tenant.id,
        ref_id="share-a",
        credits=Decimal("3"),
        platform_code="doubao",
        prepaid_share=Decimal("50"),
    )
    db.refresh(tenant)
    assert tenant.credit_reserved == Decimal("40")
    assert tenant.credit_balance == Decimal("97")

    release_reserve(
        db,
        tenant_id=tenant.id,
        ref_id="share-a",
        amount=Decimal("20"),
        reason="超额释放也应夹紧",
    )
    db.refresh(tenant)
    assert tenant.credit_reserved == Decimal("40")


def test_settle_credits_allows_negative_balance(db):
    """余额不足时仍按应扣全额结算，允许余额为负。"""
    tenant = _seed_credit_tenant(db, balance=Decimal("5"))
    assert reserve_credits(db, tenant, Decimal("5"), ref_id="cap-1", ref_type="reserve_batch")
    settle_credits(db, tenant_id=tenant.id, ref_id="cap-1", credits=Decimal("12"), platform_code="doubao")
    db.refresh(tenant)
    assert tenant.credit_balance == Decimal("-7")
    assert tenant.credit_reserved == Decimal("0")
    row = db.scalar(
        select(TenantCreditLedger)
        .where(
            TenantCreditLedger.tenant_id == tenant.id,
            TenantCreditLedger.ref_id == "cap-1",
            TenantCreditLedger.entry_type == "settle",
        )
        .order_by(TenantCreditLedger.id.desc())
    )
    assert row is not None
    assert Decimal(str(row.amount)) == Decimal("-12")
    assert not (row.detail_json or {}).get("balance_capped")


def test_finalize_after_switch_to_hosted_with_open_reserve(db):
    """切回托管后，本批仍有预扣时应继续按格结清。"""
    from types import SimpleNamespace

    from app.services.credit_service import finalize_monitor_cell_credit

    tenant = _seed_credit_tenant(db, balance=Decimal("10"))
    ref = "after-hosted"
    assert reserve_credits(
        db,
        tenant,
        Decimal("1"),
        ref_id=ref,
        ref_type="reserve_batch",
        detail_json={"shares_by_platform": {"doubao": 1.0}, "default_cell_share": 1.0},
    )
    tenant.billing_mode = "hosted"
    db.flush()
    origin = SimpleNamespace(
        subtask_id="st-hosted",
        platform="doubao",
        prompt="词H",
        status="completed",
        amount=Decimal("0.1"),
        auto_retry_status=None,
        auto_retry_count=0,
        answer_content="ok",
        error_message=None,
        raw_result_json=None,
    )
    assert finalize_monitor_cell_credit(db, tenant, origin=origin, batch_ref=ref) is True
    db.refresh(tenant)
    assert tenant.credit_balance == Decimal("9")
    assert tenant.credit_reserved == Decimal("0")


def test_finalize_without_open_reserve_does_not_charge(db):
    """M3：无开放预扣时即使当前是 credit、batch_ref 像 schedule_key，也不追溯扣费。"""
    from types import SimpleNamespace

    from app.services.credit_service import finalize_monitor_cell_credit

    tenant = _seed_credit_tenant(db, balance=Decimal("10"))
    origin = SimpleNamespace(
        subtask_id="st-m3",
        platform="doubao",
        prompt="词M3",
        status="completed",
        amount=Decimal("0.1"),
        auto_retry_status=None,
        auto_retry_count=0,
        answer_content="ok",
        error_message=None,
        raw_result_json=None,
    )
    assert finalize_monitor_cell_credit(db, tenant, origin=origin, batch_ref="hosted-schedule-key") is False
    db.refresh(tenant)
    assert tenant.credit_balance == Decimal("10")


def test_estimate_brand_words_empty_platforms_on_pydantic_object(db):
    """空 platforms 默认列表不得再走 .get() 导致 500。"""
    from types import SimpleNamespace

    from pydantic import BaseModel, Field

    from app.services.credit_service import estimate_brand_words_immediate_credits

    class G(BaseModel):
        run_immediately: bool = True
        status: bool = True
        platforms: list = Field(default_factory=list)
        monitor_keywords: list[str] = Field(default_factory=lambda: ["词A"])

    tenant = _seed_credit_tenant(db)
    asset = SimpleNamespace(region_codes_json=["110000"])
    out = estimate_brand_words_immediate_credits(db, tenant, asset, [G()])
    assert out["credits"] == 0
    assert out["group_count"] == 0
    out2 = estimate_brand_words_immediate_credits(
        db,
        tenant,
        asset,
        [{"run_immediately": True, "status": True, "platforms": [], "monitor_keywords": ["词B"]}],
    )
    assert out2["group_count"] == 0
    out3 = estimate_brand_words_immediate_credits(
        db,
        tenant,
        asset,
        [SimpleNamespace(run_immediately=True, status=True, platforms=[], monitor_keywords=["词C"])],
    )
    assert out3["group_count"] == 0


def test_settle_open_reserves_charges_late_amount_after_completed(db):
    """根因回归：主任务已 completed、amount 已落库但漏 settle 时，开放预扣扫描应扣到账。"""
    from app.models.monitor import GeoMonitorScheduleRun, GeoMonitorSubtask, GeoMonitorTask

    tenant = _seed_credit_tenant(db, balance=Decimal("20"))
    ref = f"late-open-{uuid4().hex[:8]}"
    task_id = f"task-{uuid4().hex[:12]}"
    assert reserve_credits(
        db,
        tenant,
        Decimal("1"),
        ref_id=ref,
        ref_type="reserve_batch",
        detail_json={"shares_by_platform": {"doubao": 1.0}, "default_cell_share": 1.0},
    )
    db.add(
        GeoMonitorTask(
            task_id=task_id,
            tenant_id=tenant.id,
            status="completed",
            total_items=1,
            completed_items=1,
            failed_items=0,
            prompts_json=["词晚到"],
            platforms_json=[{"platform": "doubao"}],
            raw_request_json={"_geo_credit": {"reserve_ref": ref}},
            raw_response_json={},
        )
    )
    db.add(
        GeoMonitorScheduleRun(
            tenant_id=tenant.id,
            schedule_key=ref,
            task_id=task_id,
            status="submitted",
            prompt_count=1,
            platform_count=1,
        )
    )
    db.add(
        GeoMonitorSubtask(
            subtask_id=f"st-{uuid4().hex[:10]}",
            task_id=task_id,
            platform="doubao",
            mode="search",
            prompt="词晚到",
            status="completed",
            amount=Decimal("0.18"),
            answer_content="ok",
            raw_result_json={"status": "completed", "amount": 0.18},
        )
    )
    db.flush()

    settled = settle_open_credit_reserves(db)
    assert settled >= 1
    db.refresh(tenant)
    assert tenant.credit_balance == Decimal("19")
    assert tenant.credit_reserved == Decimal("0")


def test_callback_settles_when_amount_arrives_after_completed(db):
    """根因回归：回调写入 completed+amount 时必须 settle，不能等已退出队列的 sync。"""
    from unittest.mock import patch

    from app.models.monitor import GeoMonitorSubtask, GeoMonitorTask
    from app.services.molizhishu_callback_service import _apply_callback_payload

    tenant = _seed_credit_tenant(db, balance=Decimal("10"))
    ref = f"cb-late-{uuid4().hex[:8]}"
    task_id = f"task-{uuid4().hex[:12]}"
    sub_id = f"st-{uuid4().hex[:10]}"
    assert reserve_credits(
        db,
        tenant,
        Decimal("1"),
        ref_id=ref,
        ref_type="reserve_batch",
        detail_json={"shares_by_platform": {"doubao": 1.0}, "default_cell_share": 1.0},
    )
    task = GeoMonitorTask(
        task_id=task_id,
        tenant_id=tenant.id,
        status="completed",
        total_items=1,
        completed_items=1,
        failed_items=0,
        prompts_json=["回调晚到"],
        platforms_json=[{"platform": "doubao", "mode": "search"}],
        raw_request_json={"_geo_credit": {"reserve_ref": ref}},
        raw_response_json={},
    )
    db.add(task)
    db.add(
        GeoMonitorSubtask(
            subtask_id=sub_id,
            task_id=task_id,
            platform="doubao",
            mode="search",
            prompt="回调晚到",
            status="completed",
            amount=None,
            answer_content="先有正文",
            raw_result_json={"status": "completed"},
        )
    )
    db.flush()

    payload = {
        "taskId": task_id,
        "status": "completed",
        "totalItems": 1,
        "completedItems": 1,
        "failedItems": 0,
        "subTaskList": [
            {
                "subTaskId": sub_id,
                "platform": "doubao",
                "mode": "search",
                "prompt": "回调晚到",
                "status": "completed",
                "answerContent": "先有正文",
                "amount": 0.18,
            }
        ],
    }
    with (
        patch("app.services.molizhishu_callback_service.fill_missing_subtask_ranks_for_task", return_value=0),
        patch("app.services.monitor_auto_retry_service.apply_auto_retry_results"),
        patch("app.services.monitor_auto_retry_service.launch_auto_retries_for_task"),
        patch("app.services.snapshot_backfill_service.notify_failed_subtasks_for_task"),
    ):
        _apply_callback_payload(db, task, payload)
    db.flush()
    db.refresh(tenant)
    assert tenant.credit_balance == Decimal("9")
    assert tenant.credit_reserved == Decimal("0")
