"""Stage A settings: the bankroll, and what happens when its store loses it."""

from __future__ import annotations

import importlib

import pytest

from syndicate.features.shared import portfolio_settings as ps


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Point the store at a temp dir so tests never touch a real setting."""
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_REFRESH_STATE_BACKEND", raising=False)
    for key in ps._ENV_KEYS.values():
        monkeypatch.delenv(key, raising=False)
    importlib.reload(ps)
    yield
    importlib.reload(ps)


def test_default_bankroll_is_the_users_opening_figure():
    assert ps.resolve_settings().bankroll_units == 1000.0


def test_a_saved_bankroll_wins_over_the_default():
    settings, rejected = ps.update_settings({"bankroll_units": 2500})
    assert rejected == {}
    assert settings.bankroll_units == 2500.0
    assert settings.sources["bankroll_units"] == "stored"
    # And it survives a fresh resolve, not just the one that wrote it.
    assert ps.resolve_settings().bankroll_units == 2500.0


def test_env_sits_between_stored_and_default(monkeypatch):
    monkeypatch.setenv("SYNDICATE_BANKROLL_UNITS", "750")
    assert ps.resolve_settings().bankroll_units == 750.0
    ps.update_settings({"bankroll_units": 1800})
    assert ps.resolve_settings().bankroll_units == 1800.0


@pytest.mark.parametrize("bad", ["", "abc", 0, -50, None, True, float("inf"), 99_000_000])
def test_an_unusable_bankroll_is_rejected_by_name_and_changes_nothing(bad):
    ps.update_settings({"bankroll_units": 1500})
    settings, rejected = ps.update_settings({"bankroll_units": bad})
    assert "bankroll_units" in rejected
    # The previous good value must survive a rejected edit.
    assert settings.bankroll_units == 1500.0


def test_an_unknown_field_is_rejected_rather_than_silently_ignored():
    _, rejected = ps.update_settings({"bankrol_units": 500})
    assert rejected == {"bankrol_units": "unknown_field"}


def test_a_partial_edit_leaves_untouched_fields_alone():
    ps.update_settings({"bankroll_units": 2000, "max_positions": 5})
    settings, rejected = ps.update_settings({"min_ev_pct": 3.5})
    assert rejected == {}
    assert settings.bankroll_units == 2000.0
    assert settings.max_positions == 5
    assert settings.min_ev_pct == 3.5


def test_a_lost_store_resolves_to_the_default_and_says_so(monkeypatch):
    """The eviction case, and the direction of the failure is the whole point.

    The keyvalue store is a 256MB `allkeys-lru` instance measured at 96%
    occupancy with 38,865 keys already evicted, so a read returning nothing is a
    routine event on a healthy system. A bankroll that resolved to 0 there would
    size every bet at $0 and produce an empty portfolio indistinguishable from
    "the model found nothing today".
    """
    ps.update_settings({"bankroll_units": 4000})

    def _boom(_path):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(ps, "read_json_file", _boom)
    settings = ps.resolve_settings()
    assert settings.bankroll_units == ps.DEFAULT_BANKROLL_UNITS
    assert settings.bankroll_units > 0
    assert settings.sources["bankroll_units"] == "default"
    # And the fault is visible rather than inferred from the value.
    assert "connection reset" in (settings.store_error or "")


def test_the_settings_path_carries_no_date_token():
    """A dated path is handed a 10-day TTL by the store. A bankroll must not
    expire, so the absence of a date in this path is load-bearing."""
    import re

    from syndicate.features.shared.refresh_state_store import _default_keyvalue_ttl_seconds

    path = ps._settings_path()
    assert not re.search(r"20\d{2}[-_]?\d{2}[-_]?\d{2}", str(path))
    assert _default_keyvalue_ttl_seconds(path) is None


def test_slate_ceiling_is_reported_in_dollars():
    settings, _ = ps.update_settings({"bankroll_units": 1000, "max_slate_exposure_fraction": 0.2})
    assert settings.max_slate_exposure_units() == pytest.approx(200.0)


def test_a_write_that_does_not_land_is_reported_rather_than_read_as_saved(monkeypatch):
    """A write that RAISES is easy. A write that returns cleanly and does not
    land is the one that costs you -- and on a keyvalue backend with a payload
    guard and an eviction policy, that is a real shape."""
    swallowed = {}

    def _swallow(path, payload):
        swallowed["called"] = True  # accepted, then dropped on the floor

    monkeypatch.setattr(ps, "write_json_file", _swallow)
    settings, rejected = ps.update_settings({"bankroll_units": 3000})
    assert swallowed.get("called") is True
    assert "_store" in rejected
    assert "write_not_durable" in rejected["_store"]
    # And the caller is not handed a value that was never stored.
    assert settings.bankroll_units != 3000.0
