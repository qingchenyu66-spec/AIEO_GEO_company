from unittest.mock import MagicMock, patch

from app.services.deepseek_balance_service import fetch_deepseek_balance


def test_fetch_deepseek_balance_without_api_key():
    with patch("app.services.deepseek_balance_service.settings") as settings_mock:
        settings_mock.deepseek_api_key = ""
        data = fetch_deepseek_balance()
    assert data["available"] is False
    assert "DEEPSEEK_API_KEY" in (data["error"] or "")


def test_fetch_deepseek_balance_success():
    with patch("app.services.deepseek_balance_service.settings") as settings_mock:
        settings_mock.deepseek_api_key = "sk-test"
        client = MagicMock()
        client.get_account_balance.return_value = {
            "is_available": True,
            "balance_infos": [
                {"currency": "CNY", "total_balance": "12.50", "granted_balance": "0", "topped_up_balance": "12.50"},
            ],
        }
        with patch("app.services.deepseek_balance_service.DeepseekClient", return_value=client):
            data = fetch_deepseek_balance()
    assert data["available"] is True
    assert data["current_balance"] == 12.5
    assert data["display_value"] == "¥ 12.50"
    assert data["currency"] == "CNY"
