"""方案 A：废弃配额/白名单写入须 400；空白名单仅用于清脏。"""

from app.services.credit_service import assert_no_retired_quota_writes, merge_credit_policy


def test_merge_credit_policy_strips_retired_keys():
    merged = merge_credit_policy(
        {
            "credits_per_yuan": 5,
            "keyword_limit": 30,
            "schedule_slots_limit": 3,
            "region_limit": 5,
            "daily_credit_cap": 100,
        }
    )
    assert merged["credits_per_yuan"] == 5
    assert "keyword_limit" not in merged
    assert "schedule_slots_limit" not in merged
    assert "region_limit" not in merged
    assert "daily_credit_cap" not in merged


def test_assert_rejects_retired_policy_keys():
    try:
        assert_no_retired_quota_writes(credit_policy={"keyword_limit": 10})
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "keyword_limit" in str(exc)


def test_assert_rejects_nonempty_whitelist():
    try:
        assert_no_retired_quota_writes(platform_whitelist=["doubao"])
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "白名单" in str(exc)


def test_assert_allows_empty_whitelist_and_rate_only():
    assert_no_retired_quota_writes(credit_policy={"credits_per_yuan": 4.2}, platform_whitelist=[])
