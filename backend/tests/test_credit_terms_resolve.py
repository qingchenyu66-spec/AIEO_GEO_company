"""客户条款展示：已生效正式条款；不再按 ack 排队。"""
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.models.credit import CreditTermsVersion
from app.models.tenant import Tenant
from app.services.credit_service import BILLING_MODE_CREDIT, pending_terms_block, resolve_customer_credit_terms




def test_pending_terms_block_always_none(db: Session):
    # 2026-09-08 - 条款不硬闸
    assert pending_terms_block(db, 1) is None


def test_resolve_customer_credit_terms_prefers_latest_formal(db: Session):
    suffix = uuid4().hex[:8]
    tenant = Tenant(name="t", code=f"TERMS{suffix}", billing_mode=BILLING_MODE_CREDIT, status=True)
    db.add(tenant)
    db.flush()
    now = datetime.now()

    older = CreditTermsVersion(
        version_code=f"formal-old-{suffix}",
        title="旧正式条款",
        content_html="<p>old</p>",
        status="published",
        effective_at=now - timedelta(days=10),
        published_at=now - timedelta(days=10),
        notice_days=7,
    )
    newer = CreditTermsVersion(
        version_code=f"formal-new-{suffix}",
        title="新正式条款",
        content_html="<p>new</p>",
        status="published",
        effective_at=now - timedelta(hours=1),
        published_at=now - timedelta(hours=1),
        notice_days=7,
    )
    future = CreditTermsVersion(
        version_code=f"formal-future-{suffix}",
        title="未生效正式条款",
        content_html="<p>future</p>",
        status="published",
        # 未来生效日不得压过当前已生效正式版（验证脚本曾踩坑）
        effective_at=now + timedelta(days=30),
        published_at=now,
        notice_days=7,
    )
    auto = CreditTermsVersion(
        version_code=f"auto-{suffix}",
        title="算力单价调整",
        content_html="<p>1.25</p>",
        status="published",
        effective_at=now,
        published_at=now,
        notice_days=7,
    )
    db.add_all([older, newer, future, auto])
    db.flush()

    resolved = resolve_customer_credit_terms(db, tenant.id)
    assert resolved is not None
    assert resolved.id == newer.id
    assert "auto-" not in (resolved.version_code or "")


def test_publish_policy_change_terms_strips_script(db: Session):
    from app.services.credit_service import publish_policy_change_terms

    row = publish_policy_change_terms(
        db,
        title="测消毒",
        content_html='<p>ok</p><script>alert(1)</script><a href="javascript:alert(1)">x</a>',
        notice_days=1,
    )
    html = row.content_html or ""
    assert "script" not in html.lower()
    assert "javascript:" not in html.lower()
    assert "ok" in html
