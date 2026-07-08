"""Check alembic version and geo_report period_key unique index."""
from sqlalchemy import create_engine, text

from app.core.config import settings

url = (
    f"mysql+pymysql://{settings.database_user}:{settings.database_password}"
    f"@{settings.database_host}:{settings.database_port}/{settings.database_name}"
)
engine = create_engine(url)
with engine.connect() as conn:
    rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    print(f"alembic_version={rev}")
    rows = conn.execute(
        text("SHOW INDEX FROM geo_report WHERE Key_name='uk_geo_report_tenant_type_period'")
    ).fetchall()
    print(f"uk_geo_report_tenant_type_period_columns={len(rows)}")
