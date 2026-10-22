"""A pytest process must not be able to open the keyvalue state store at a loopback Redis."""

from __future__ import annotations

import pytest

from syndicate.features.shared import refresh_state_store as rss


@pytest.fixture(autouse=True)
def _fresh_client(monkeypatch):
    monkeypatch.delenv(rss._ALLOW_TEST_LOOPBACK_ENV, raising=False)
    rss._get_keyvalue_client.cache_clear()
    yield
    rss._get_keyvalue_client.cache_clear()


@pytest.mark.parametrize("url", [
    "redis://127.0.0.1:6379/0",
    "redis://localhost:6379/0",
    "redis://[::1]:6379/0",
    "redis://127.0.0.2:6379/0",
    "redis://:hunter2@127.0.0.1:6379/0",
])
def test_loopback_is_refused_under_pytest(url):
    with pytest.raises(RuntimeError) as err:
        rss._refuse_loopback_redis_under_pytest(url)
    assert "hunter2" not in str(err.value)
    assert "127.0.0.1:6379" not in str(err.value)


def test_non_loopback_passes():
    rss._refuse_loopback_redis_under_pytest("redis://example:6379/0")
    rss._refuse_loopback_redis_under_pytest("redis://10.1.2.3:6379/0")


def test_allow_flag_passes(monkeypatch):
    monkeypatch.setenv(rss._ALLOW_TEST_LOOPBACK_ENV, "1")
    rss._refuse_loopback_redis_under_pytest("redis://127.0.0.1:6379/0")


def test_not_under_pytest_is_never_refused(monkeypatch):
    # The fleet has no PYTEST_CURRENT_TEST, so its own loopback Redis must stay reachable.
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    rss._refuse_loopback_redis_under_pytest("redis://127.0.0.1:6379/0")


def test_unparseable_url_does_not_raise():
    rss._refuse_loopback_redis_under_pytest("redis://[::1")


def test_client_builder_applies_the_guard(monkeypatch):
    """Reachability: the guard is on the path _execute_keyvalue_operation takes, not just defined."""
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.delenv("REDIS_URL", raising=False)
    with pytest.raises(RuntimeError, match="loopback"):
        rss._get_keyvalue_client()
    with pytest.raises(RuntimeError, match="loopback"):
        rss._execute_keyvalue_operation(lambda c: c.ping())
