r"""Prepare a clean Aidiya showcase dataset and optionally submit real Molizhishu tasks.

Run from backend:
    $env:PYTHONPATH='D:\py代码\GEO优化\backend'
    .\.venv\Scripts\python.exe scripts\prepare_aidiya_real_data.py --submit
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

from sqlalchemy import select

from app.api.dependencies import CurrentSession
from app.core.database import SessionLocal
from app.models.brand import BrandAsset, BrandCompetitor
from app.models.monitor import GeoMonitorCallbackEvent, GeoMonitorSubtask, GeoMonitorTask
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.schemas.monitor import MonitorTaskCreateRequest, PlatformConfig
from app.services.monitor_service import serialize_task, submit_monitor_task, sync_monitor_task


@dataclass(frozen=True)
class CompetitorSeed:
    name: str
    short_name: str
    aliases: list[str]
    url: str


AIDIYA_NAME = "北京艾迪亚控股集团有限公司"
AIDIYA_CODE = "AIDIYA_REAL"
TEST_MARKERS = ("测试", "接口测试", "codex", "dual", "临时")

COMPETITORS = [
    CompetitorSeed("模力指数", "模力", ["魔力指数", "Molizhishu"], "https://business.molizhishu.com"),
    CompetitorSeed("新榜", "新榜", ["新榜智汇", "Geowise"], "https://www.newrank.cn"),
    CompetitorSeed("秒针系统", "秒针", ["秒针营销科学院"], "https://www.miaozhen.com"),
    CompetitorSeed("智推时代", "智推", ["智推"], "https://app.zhituishidai.com"),
]

PROMPTS = [
    "艾迪亚是做什么的？",
    "北京艾迪亚控股集团有限公司的GEO优化服务怎么样？",
    "GEO优化公司推荐里，艾迪亚和模力指数、新榜、秒针、智推时代怎么比较？",
]

PLATFORMS = [
    PlatformConfig(platform="doubao_mobile", mode="search", screenshot=1),
    PlatformConfig(platform="deepseek_mobile", mode="search", screenshot=1),
    PlatformConfig(platform="yuanbao", mode="search", screenshot=1),
    PlatformConfig(platform="kimi", mode="search", screenshot=1),
    PlatformConfig(platform="baiduai", mode="search", screenshot=1),
]


def clear_old_monitor_rows(db) -> None:
    """Clear manually submitted monitor rows so the dashboard only reflects the new real run."""
    db.query(GeoMonitorCallbackEvent).delete(synchronize_session=False)
    db.query(GeoMonitorSubtask).delete(synchronize_session=False)
    db.query(GeoMonitorTask).delete(synchronize_session=False)


def archive_obvious_test_tenants(db) -> None:
    """Hide tenants created during manual smoke tests without touching core demo accounts."""
    tenants = db.scalars(select(Tenant).where(Tenant.deleted.is_(False))).all()
    for tenant in tenants:
        text = f"{tenant.name} {tenant.code}".lower()
        if any(marker.lower() in text for marker in TEST_MARKERS):
            tenant.deleted = True
            tenant.status = False


def upsert_aidiya_brand(db) -> Tenant:
    """Create or update the showcase tenant, brand asset, schedule and competitors."""
    tenant = db.scalar(select(Tenant).where(Tenant.code == AIDIYA_CODE))
    if tenant is None:
        tenant = db.scalar(select(Tenant).where(Tenant.name == AIDIYA_NAME))
        if tenant is None:
            tenant = Tenant(name=AIDIYA_NAME, code=AIDIYA_CODE)
            db.add(tenant)
            db.flush()
        else:
            tenant.code = AIDIYA_CODE
    tenant.name = AIDIYA_NAME
    tenant.status = True
    tenant.deleted = False
    duplicate_tenants = db.scalars(
        select(Tenant).where(Tenant.name == AIDIYA_NAME, Tenant.id != tenant.id)
    ).all()
    for duplicate in duplicate_tenants:
        duplicate.status = False
        duplicate.deleted = True

    asset = db.scalar(select(BrandAsset).where(BrandAsset.tenant_id == tenant.id))
    if asset is None:
        asset = BrandAsset(
            tenant_id=tenant.id,
            company_full_name=AIDIYA_NAME,
            brand_name="艾迪亚",
            brand_short_name="艾迪亚",
            monitor_keywords_json=[],
            aliases_json=[],
            product_keywords_json=[],
            schedule_times_json=[],
            schedule_weekdays_json=[],
            schedule_month_days_json=[],
        )
        db.add(asset)
    asset.company_full_name = AIDIYA_NAME
    asset.brand_name = "艾迪亚"
    asset.brand_short_name = "艾迪亚"
    asset.monitor_keywords_json = ["艾迪亚", "艾迪亚控股", AIDIYA_NAME, "GEO优化"]
    asset.aliases_json = ["AIDIYA", "艾迪亚集团", "北京艾迪亚"]
    asset.product_keywords_json = ["GEO优化", "AI平台推广监测", "品牌诊断", "报告交付"]
    asset.official_url = "https://www.aieo.cn"
    asset.description = "用于真实接口演示的艾迪亚品牌资产，系统会按计划自动提交GEO监测。"
    asset.schedule_type = "daily_times"
    asset.schedule_frequency = 3
    asset.schedule_times_json = ["09:30", "14:30", "20:30"]
    asset.schedule_weekdays_json = []
    asset.schedule_month_days_json = []
    asset.status = True
    asset.deleted = False

    for seed in COMPETITORS:
        row = db.scalar(
            select(BrandCompetitor).where(
                BrandCompetitor.tenant_id == tenant.id,
                BrandCompetitor.name == seed.name,
            )
        )
        if row is None:
            row = BrandCompetitor(tenant_id=tenant.id, name=seed.name, aliases_json=[])
            db.add(row)
        row.short_name = seed.short_name
        row.aliases_json = seed.aliases
        row.website_url = seed.url
        row.category = "核心竞品"
        row.status = True
        row.deleted = False
    return tenant


def bind_demo_customer_identities(db, tenant: Tenant) -> None:
    """Point existing demo customer identities to Aidiya for one-click customer-side review."""
    identities = db.scalars(
        select(UserIdentity).where(
            UserIdentity.identity_type == "CUSTOMER",
            UserIdentity.deleted.is_(False),
        )
    ).all()
    for identity in identities:
        if identity.user and identity.user.username in {"demo", "client"}:
            identity.tenant_id = tenant.id
            identity.identity_name = "艾迪亚 企业管理员"


def platform_current_session(db) -> CurrentSession:
    """Use the existing platform admin account to submit real monitor tasks."""
    user = db.scalar(select(User).where(User.username == "platform", User.deleted.is_(False)))
    if user is None:
        user = db.scalar(select(User).where(User.username == "demo", User.deleted.is_(False)))
    if user is None:
        raise RuntimeError("No platform or demo user exists. Run seed_demo.py first.")
    identity = db.scalar(
        select(UserIdentity).where(
            UserIdentity.user_id == user.id,
            UserIdentity.identity_type == "PLATFORM",
            UserIdentity.deleted.is_(False),
        )
    )
    if identity is None:
        raise RuntimeError("The selected user has no PLATFORM identity.")
    return CurrentSession(user=user, identity=identity)


def submit_and_poll(db, tenant: Tenant, max_rounds: int, interval_seconds: int) -> str:
    """Submit one bounded real Molizhishu task batch, then poll status a few times."""
    payload = MonitorTaskCreateRequest(
        tenant_id=tenant.id,
        prompts=PROMPTS,
        platforms=PLATFORMS,
    )
    current = platform_current_session(db)
    task = submit_monitor_task(db, payload, current)
    print(f"submitted task: {task.task_id}")
    for round_no in range(max_rounds):
        time.sleep(interval_seconds)
        task = sync_monitor_task(db, task.task_id, current)
        print(f"poll {round_no + 1}/{max_rounds}: {serialize_task(task)}")
        if task.status in {"completed", "partial_completed", "failed", "stopped"}:
            break
    return task.task_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submit", action="store_true", help="Submit a real Molizhishu task after preparing data.")
    parser.add_argument("--poll-rounds", type=int, default=8)
    parser.add_argument("--poll-interval", type=int, default=20)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        clear_old_monitor_rows(db)
        archive_obvious_test_tenants(db)
        tenant = upsert_aidiya_brand(db)
        bind_demo_customer_identities(db, tenant)
        db.commit()
        print(f"prepared tenant: {tenant.id} {tenant.name} {tenant.code}")
        if args.submit:
            submit_and_poll(db, tenant, args.poll_rounds, args.poll_interval)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
