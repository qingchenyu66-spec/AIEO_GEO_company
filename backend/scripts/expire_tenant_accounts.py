"""一次性/运维：扫描到期企业并禁用关联客户账号。"""

from __future__ import annotations

from app.core.database import SessionLocal
from app.services.tenant_account_service import expire_overdue_tenant_services


def main() -> None:
    db = SessionLocal()
    try:
        handled = expire_overdue_tenant_services(db)
        db.commit()
        print(f"expired_tenants_handled={handled}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
