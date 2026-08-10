"""补录截图默认目录应落在 backend/storage 下（生产经软链进数据盘）。"""

from pathlib import Path

from app.services.share_page_screenshot_service import backfill_screenshot_dir


def test_backfill_screenshot_dir_defaults_under_storage(monkeypatch):
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "backfill_screenshot_dir", "")
    path = backfill_screenshot_dir()
    assert path.name == "backfill_screenshots"
    assert path.parent.name == "storage"
    assert path.is_dir()
    # 相对 backend 根
    backend_root = Path(__file__).resolve().parents[1]
    assert path.resolve().is_relative_to(backend_root.resolve())
