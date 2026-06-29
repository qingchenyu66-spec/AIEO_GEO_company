"""Repair Aidiya tenant text and keep one active tenant without clearing monitor results."""

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.brand import BrandAsset, BrandCompetitor
from app.models.monitor import GeoMonitorTask
from app.models.tenant import Tenant
from app.models.user_identity import UserIdentity

AIDIYA_NAME = "北京艾迪亚控股集团有限公司"
AIDIYA_CODE = "AIDIYA_REAL"


def main() -> None:
    db = SessionLocal()
    try:
        primary = db.scalar(select(Tenant).where(Tenant.code == AIDIYA_CODE))
        if primary is None:
            primary = Tenant(name=AIDIYA_NAME, code=AIDIYA_CODE)
            db.add(primary)
            db.flush()
        primary.name = AIDIYA_NAME
        primary.code = AIDIYA_CODE
        primary.status = True
        primary.deleted = False

        duplicate_tenants = db.scalars(
            select(Tenant).where(Tenant.id != primary.id, Tenant.deleted.is_(False))
        ).all()
        for duplicate in duplicate_tenants:
            if duplicate.code == "AIEO_DEMO" or duplicate.name == AIDIYA_NAME or set(duplicate.name) == {"?"}:
                db.query(UserIdentity).filter(UserIdentity.tenant_id == duplicate.id).update(
                    {UserIdentity.tenant_id: primary.id},
                    synchronize_session=False,
                )
                db.query(GeoMonitorTask).filter(GeoMonitorTask.tenant_id == duplicate.id).update(
                    {GeoMonitorTask.tenant_id: primary.id},
                    synchronize_session=False,
                )
                db.query(BrandCompetitor).filter(BrandCompetitor.tenant_id == duplicate.id).update(
                    {BrandCompetitor.deleted: True, BrandCompetitor.status: False},
                    synchronize_session=False,
                )
                asset = db.scalar(select(BrandAsset).where(BrandAsset.tenant_id == duplicate.id))
                if asset:
                    asset.deleted = True
                    asset.status = False
                duplicate.status = False
                duplicate.deleted = True

        asset = db.scalar(select(BrandAsset).where(BrandAsset.tenant_id == primary.id, BrandAsset.deleted.is_(False)))
        if asset:
            asset.company_full_name = AIDIYA_NAME
            asset.brand_name = "艾迪亚"
            asset.brand_short_name = "艾迪亚"
            asset.monitor_keywords_json = ["艾迪亚", "艾迪亚控股", AIDIYA_NAME, "GEO优化"]
            asset.aliases_json = ["AIDIYA", "艾迪亚集团", "北京艾迪亚"]

        for username in ("client", "demo"):
            identities = db.scalars(
                select(UserIdentity)
                .where(UserIdentity.identity_type == "CUSTOMER", UserIdentity.deleted.is_(False))
                .where(UserIdentity.user.has(username=username))
            ).all()
            for identity in identities:
                identity.tenant_id = primary.id
                identity.identity_name = "艾迪亚 企业管理员"

        db.commit()
        print(f"repaired tenant: {primary.id} {primary.name} {primary.code}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
