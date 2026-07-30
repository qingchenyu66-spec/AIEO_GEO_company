"""platforms/matrix health aggregation must not SELECT full subtask rows."""

from sqlalchemy.dialects import mysql

from app.services.platform_matrix_service import _today_global_platform_health


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self):
        self.last_stmt = None

    def execute(self, stmt):
        self.last_stmt = stmt
        return _FakeResult([])


def test_today_global_platform_health_uses_group_by_not_order_by_full_rows():
    db = _FakeSession()
    assert _today_global_platform_health(db) == {}
    sql = str(
        db.last_stmt.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": False})
    ).lower()
    assert "group by" in sql
    assert "geo_monitor_subtask.answer_content" not in sql
    assert "geo_monitor_subtask.raw_result_json" not in sql
    # 允许无 order by；即使有也不该靠整表 sort 大字段
    assert "order by" not in sql
