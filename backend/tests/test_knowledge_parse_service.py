"""Tests for knowledge DeepSeek parse service."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.knowledge_parse_service import parse_knowledge_file


class _FakeScalars:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value


class _FakeSession:
    def __init__(self, record):
        self.record = record
        self.commits = 0

    def scalar(self, _stmt):
        return self.record

    def commit(self):
        self.commits += 1

    def refresh(self, _record):
        return None


@patch("app.services.knowledge_parse_service.get_brand_asset")
@patch("app.services.knowledge_parse_service.extract_knowledge_text")
@patch("app.services.knowledge_parse_service.settings")
@patch("app.services.knowledge_parse_service.DeepseekClient")
def test_parse_knowledge_file_success(
    client_cls: MagicMock,
    settings_mock: MagicMock,
    extract_mock: MagicMock,
    brand_mock: MagicMock,
    tmp_path: Path,
) -> None:
    settings_mock.deepseek_knowledge_parse_enabled = True
    settings_mock.deepseek_knowledge_parse_max_chars = 12000
    extract_mock.return_value = "艾迪亚是领先的电梯媒体品牌，覆盖全国主要城市。"
    brand_mock.return_value = SimpleNamespace(brand_name="艾迪亚", company_full_name="艾迪亚传媒")

    record = SimpleNamespace(
        id=1,
        tenant_id=6,
        original_name="sample.txt",
        file_ext="txt",
        storage_path="6/sample.txt",
        deleted=False,
        parse_status="none",
        parse_error=None,
        parsed_at=None,
        parse_result_json=None,
    )
    db = _FakeSession(record)

    client = client_cls.return_value
    client.knowledge_enabled = True
    client.model = "deepseek-chat"
    client.parse_knowledge_document.return_value = {
        "source": "deepseek",
        "model": "deepseek-chat",
        "summary": "资料介绍了艾迪亚电梯媒体品牌。",
        "keywords": ["电梯媒体", "品牌"],
        "topics": ["品牌介绍"],
        "geo_points": ["覆盖全国主要城市"],
    }

    with patch("app.services.knowledge_parse_service.STORAGE_ROOT", tmp_path):
        file_path = tmp_path / "6"
        file_path.mkdir(parents=True)
        (file_path / "sample.txt").write_text("正文", encoding="utf-8")
        result = parse_knowledge_file(db, 1)

    assert result.parse_status == "parsed"
    assert result.parse_result_json is not None
    assert result.parse_result_json["summary"].startswith("资料介绍")
    assert result.parse_result_json["extracted_chars"] > 0


@patch("app.services.knowledge_parse_service.settings")
@patch("app.services.knowledge_parse_service.DeepseekClient")
def test_parse_knowledge_file_disabled(client_cls: MagicMock, settings_mock: MagicMock) -> None:
    settings_mock.deepseek_knowledge_parse_enabled = False
    client_cls.return_value.knowledge_enabled = False
    record = SimpleNamespace(
        id=1,
        tenant_id=6,
        original_name="sample.txt",
        file_ext="txt",
        storage_path="6/sample.txt",
        deleted=False,
        parse_status="none",
        parse_error=None,
        parsed_at=None,
        parse_result_json=None,
    )
    db = _FakeSession(record)

    with pytest.raises(ValueError, match="未启用"):
        parse_knowledge_file(db, 1)

    assert record.parse_status == "none"
