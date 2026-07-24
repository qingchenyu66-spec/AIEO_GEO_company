"""redis_lock fail-closed when Redis commands error."""

from unittest.mock import MagicMock, patch

from redis.exceptions import RedisError

from app.core.redis_client import redis_lock


def test_redis_lock_fail_closed_on_redis_error() -> None:
    client = MagicMock()
    client.set.side_effect = RedisError("boom")
    with patch("app.core.redis_client.get_redis_client", return_value=client):
        with redis_lock("demo-key", ttl_seconds=10) as acquired:
            assert acquired is False


def test_redis_lock_fail_open_when_redis_disabled() -> None:
    with patch("app.core.redis_client.get_redis_client", return_value=None):
        with redis_lock("demo-key", ttl_seconds=10) as acquired:
            assert acquired is True
