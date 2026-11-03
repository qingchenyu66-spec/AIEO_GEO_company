"""Isolated regressions: run with unittest, without shared database fixtures."""
import json
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.permission import Position
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.models.monitor import GeoMonitorTask
from app.services.platform_session import load_platform_session
from app.services.monitor_service import _exclude_gap_backfill_tasks


class ScheduleIdentityRegression(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        tables = [User.__table__, Tenant.__table__, Position.__table__,
                  UserIdentity.__table__, GeoMonitorTask.__table__]
        Base.metadata.create_all(self.engine, tables=tables)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def identity(self, number, position, *, enabled=True, default=True):
        user = User(id=number, username=f"user{number}", password_hash="test",
                    display_name="test", status=enabled, deleted=False)
        self.db.add(user)
        item = UserIdentity(id=number, identity_code=f"identity{number}", user=user,
                            identity_type="PLATFORM", identity_name="test",
                            role_code="PLATFORM_OPERATOR", position_id=position,
                            is_default=default, status=True, deleted=False)
        self.db.add(item)
        self.db.flush()
        return item

    def positions(self):
        for number, code in [(1, "PLATFORM_SALES"), (2, "PLATFORM_OPERATION")]:
            self.db.add(Position(id=number, position_code=code, position_name=code,
                                 identity_type="PLATFORM", role_code="PLATFORM_OPERATOR"))
        self.db.flush()

    def test_sales_default_cannot_become_worker(self):
        self.positions()
        self.identity(1, 1)
        self.identity(2, 2, default=False)
        self.assertEqual(load_platform_session(self.db).user.id, 2)

    def test_only_sales_fails_closed(self):
        self.positions()
        self.identity(1, 1)
        with self.assertRaises(RuntimeError):
            load_platform_session(self.db)

    def test_disabled_user_is_not_selected(self):
        self.positions()
        self.identity(1, 2, enabled=False)
        self.identity(2, 2)
        self.assertEqual(load_platform_session(self.db).user.id, 2)

    def test_legacy_operator_without_position_still_works(self):
        self.identity(1, None)
        self.assertEqual(load_platform_session(self.db).user.id, 1)

    def test_gap_placeholders_do_not_hide_real_failures_before_limit(self):
        connection = self.db.connection().connection.driver_connection
        connection.create_function("json_unquote", 1, lambda value: value)
        connection.create_function("json_extract", 2,
                                   lambda value, path: json.loads(value).get("source"))
        for number in range(1, 15):
            self.db.add(GeoMonitorTask(
                task_id=f"task{number}", status="failed", failed_items=1,
                prompts_json=[], platforms_json=[], raw_response_json={},
                raw_request_json={"source": "gap_backfill"} if number > 1 else {},
            ))
        self.db.flush()
        stmt = select(GeoMonitorTask).order_by(GeoMonitorTask.id.desc()).limit(12)
        tasks = list(self.db.scalars(_exclude_gap_backfill_tasks(stmt)))
        self.assertEqual([task.task_id for task in tasks], ["task1"])
        self.assertEqual(tasks[0].failed_items, 1)


if __name__ == "__main__":
    unittest.main()
