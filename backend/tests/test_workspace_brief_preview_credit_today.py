"""预览算力企业：工作台默认周期含今日且有样本。"""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.tenant import Tenant
from app.services.auth_service import create_access_token
from app.models.user import User
from app.models.user_identity import UserIdentity
from sqlalchemy import select

client = TestClient(app)


def test_platform_preview_credit_workspace_7d_includes_today_samples():
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.username == "demo", User.deleted.is_(False)))
        identity = db.scalar(
            select(UserIdentity).where(
                UserIdentity.user_id == user.id,
                UserIdentity.identity_type == "PLATFORM",
                UserIdentity.deleted.is_(False),
            )
        )
        tenant = db.scalar(select(Tenant).where(Tenant.code == "AIDIYA_CREDIT_TEST", Tenant.deleted.is_(False)))
        assert user and identity and tenant
        token = create_access_token(user, identity)
        end = date.today()
        start = end - timedelta(days=6)
        response = client.get(
            "/api/v1/monitor/workspace-brief",
            params={
                "tenant_id": tenant.id,
                "scope": "summary",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["kpis"]["ranking_sample_count"] > 0
    finally:
        db.close()
