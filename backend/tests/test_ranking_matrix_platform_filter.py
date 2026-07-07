from app.services.monitor_service import matrix_platform_visible


def test_matrix_platform_visible_allows_configured_platforms() -> None:
    purchased = ["doubao_mobile", "deepseek", "kimi"]
    assert matrix_platform_visible("doubao_mobile", purchased) is True
    assert matrix_platform_visible("wenxinyiyan", purchased) is False


def test_matrix_platform_visible_allows_all_when_unconfigured() -> None:
    assert matrix_platform_visible("kimi", []) is True
    assert matrix_platform_visible(None, []) is True
