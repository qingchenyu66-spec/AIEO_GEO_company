"""企业配置/品牌词/竞品变更审计（ponytail 自检）。"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.api.dependencies import CurrentSession
from app.services.brand_service import (
    _filter_change_rows,
    _format_brand_config_change_description,
    _log_brand_asset_config_changes,
    _log_competitor_change,
)


def test_format_brand_config_change_description_joins_keyword_diff() -> None:
    text = _format_brand_config_change_description(
        [
            {
                "field": "词组「综合」监测词",
                "before": "LED广告公司推荐、公交广告公司哪家好",
                "after": "商圈LED大屏广告公司推荐、公交广告公司哪家好",
                "kind": "update",
            }
        ]
    )
    assert "词组「综合」监测词" in text
    assert "LED广告公司推荐" in text
    assert "商圈LED大屏广告公司推荐" in text


def test_filter_change_rows_limits_to_schedule_fields() -> None:
    rows = [
        {"field": "监测时段", "before": "09:30", "after": "09:30,13:30"},
        {"field": "词组「综合」监测词", "before": "A", "after": "B"},
    ]
    filtered = _filter_change_rows(rows, ("监测时段", "调度", "执行"))
    assert len(filtered) == 1
    assert filtered[0]["field"] == "监测时段"


def test_log_brand_asset_config_changes_writes_keyword_diff() -> None:
    db = MagicMock()
    tenant = SimpleNamespace(name="艾迪亚控股集团有限公司")
    db.get.return_value = tenant
    current = CurrentSession(
        user=SimpleNamespace(id=250, username="王春宇"),
        identity=SimpleNamespace(id=1, identity_type="PLATFORM"),
    )
    rows = [
        {
            "field": "词组「综合」监测词",
            "before": "LED广告公司推荐",
            "after": "商圈LED大屏广告公司推荐",
            "kind": "update",
        },
        {"field": "监测时段", "before": "09:30", "after": "09:30,13:30", "kind": "update"},
    ]
    with patch("app.services.approval_preview_service._brand_changes", return_value=rows):
        with patch("app.services.operation_log_service.write_operation_log") as write_log:
            _log_brand_asset_config_changes(
                db,
                current,
                6,
                {"keyword_groups": []},
                scopes={"keywords": True, "schedule": False},
            )
    write_log.assert_called_once()
    assert "商圈LED大屏广告公司推荐" in write_log.call_args.args[3]
    assert "监测时段" not in write_log.call_args.args[3]
    assert write_log.call_args.kwargs["target_module"] == "企业配置"


def test_log_competitor_change_delete() -> None:
    db = MagicMock()
    db.get.return_value = SimpleNamespace(name="艾迪亚")
    current = CurrentSession(
        user=SimpleNamespace(id=1, username="ops"),
        identity=SimpleNamespace(id=1, identity_type="PLATFORM"),
    )
    with patch("app.services.operation_log_service.write_operation_log") as write_log:
        _log_competitor_change(db, current, 6, action="delete", name="竞品A")
    assert "删除竞品「竞品A」" in write_log.call_args.args[3]
    assert write_log.call_args.args[2] == "竞品"
