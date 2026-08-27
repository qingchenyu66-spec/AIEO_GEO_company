from app.core.redis_client import bare_redis_url


def test_bare_redis_url_strips_empty_password():
    assert bare_redis_url("redis://:@127.0.0.1:6379/0") == "redis://127.0.0.1:6379/0"


def test_bare_redis_url_keeps_real_password():
    assert (
        bare_redis_url("redis://:secret@127.0.0.1:6379/0")
        == "redis://:secret@127.0.0.1:6379/0"
    )
