"""职位可配平台多选：空列表表示不可勾任何端。"""

from app.services.brand_service import merge_platform_selections_for_grants


def test_merge_platforms_preserves_outside_allowlist():
    existing = [{"code": "doubao", "mode": "search", "screenshot": 1}, {"code": "qianwen", "mode": "search", "screenshot": 1}]
    incoming = [{"code": "deepseek", "mode": "search", "screenshot": 1}]
    merged = merge_platform_selections_for_grants(existing, incoming, allowed_codes={"doubao"})
    codes = {item["code"] for item in merged}
    assert "qianwen" in codes  # 无权端保留
    assert "deepseek" not in codes  # 不在授权内不能加
    assert "doubao" not in codes  # 授权端按 incoming 去掉


def test_merge_platforms_empty_allowlist_keeps_all_existing():
    existing = [{"code": "doubao", "mode": "search", "screenshot": 1}]
    incoming = [{"code": "qianwen", "mode": "search", "screenshot": 1}]
    merged = merge_platform_selections_for_grants(existing, incoming, allowed_codes=set())
    assert [item["code"] for item in merged] == ["doubao"]
