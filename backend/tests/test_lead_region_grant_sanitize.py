"""无企业地区编辑权时，诊断地区强制全部区域。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.lead_diagnosis_service import sanitize_lead_region_codes_for_grants


def test_sanitize_lead_regions_keeps_codes_when_can_edit(monkeypatch):
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.can_edit_lead_diagnosis_regions",
        lambda db, current: True,
    )
    current = SimpleNamespace(identity=SimpleNamespace(id=1))
    assert sanitize_lead_region_codes_for_grants(MagicMock(), current, ["110000", "310000"]) == [
        "110000",
        "310000",
    ]


def test_sanitize_lead_regions_clears_when_cannot_edit(monkeypatch):
    monkeypatch.setattr(
        "app.services.lead_diagnosis_service.can_edit_lead_diagnosis_regions",
        lambda db, current: False,
    )
    current = SimpleNamespace(identity=SimpleNamespace(id=1))
    assert sanitize_lead_region_codes_for_grants(MagicMock(), current, ["110000", "310000"]) == []
