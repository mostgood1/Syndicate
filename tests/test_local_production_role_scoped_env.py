"""Role-scoped `ROLE__KEY` overrides in local_production.env `[2026-10-05, lane local-env-role-scoped-pin]`.

The local file applies every key to every role. live-odds-worker's
SYNDICATE_ACTIVE_SPORTS legitimately differs from web's and refresh-worker's, so
before this it could only live in the imported Render snapshot (render_env/<role>.json),
which a re-import overwrites.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import local_production as lp


@pytest.fixture()
def settings(tmp_path: Path) -> lp.Settings:
    return lp.Settings(home=tmp_path / "home", port=12345)


@pytest.fixture(scope="module")
def blueprint():
    return lp.load_blueprint()


def _env(role, blueprint, settings, local=None, live=None):
    return lp.derive_role_env(role, blueprint, local or {}, settings, live=live, base_env={})


# The fleet's real per-role lists on 2026-10-04 (render_env import + the NBA edit).
_LIVE = {
    "web": {"SYNDICATE_ACTIVE_SPORTS": "mlb,wnba,soccer,nfl"},
    "refresh-worker": {"SYNDICATE_ACTIVE_SPORTS": "mlb,wnba,soccer,ncaaf,nfl"},
    "live-odds-worker": {"SYNDICATE_ACTIVE_SPORTS": "mlb,wnba,soccer,ncaaf,nfl,nhl"},
}
_PIN = {
    "LIVE_ODDS_WORKER__SYNDICATE_ACTIVE_SPORTS": "mlb,wnba,soccer,ncaaf,nfl,nhl,nba",
    "LIVE_ODDS_WORKER__SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS_NBA": "1800",
}


def test_prefix_is_the_role_upper_snake():
    assert lp.role_scope_prefix("live-odds-worker") == "LIVE_ODDS_WORKER__"
    assert lp.role_scope_prefix("web") == "WEB__"


def test_the_fleet_pin_reaches_live_odds_worker_only(blueprint, settings):
    envs = {r: _env(r, blueprint, settings, local=_PIN, live=_LIVE[r])[0] for r in lp.ROLE_ORDER}
    assert envs["live-odds-worker"]["SYNDICATE_ACTIVE_SPORTS"] == "mlb,wnba,soccer,ncaaf,nfl,nhl,nba"
    assert envs["live-odds-worker"]["SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS_NBA"] == "1800"
    # The other two keep their own lists exactly.
    assert envs["web"]["SYNDICATE_ACTIVE_SPORTS"] == "mlb,wnba,soccer,nfl"
    assert envs["refresh-worker"]["SYNDICATE_ACTIVE_SPORTS"] == "mlb,wnba,soccer,ncaaf,nfl"
    assert "SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS_NBA" not in envs["web"]
    assert "SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS_NBA" not in envs["refresh-worker"]


def test_scoped_keys_never_appear_literally(blueprint, settings):
    for role in lp.ROLE_ORDER:
        env, _ = _env(role, blueprint, settings, local=_PIN, live=_LIVE[role])
        assert not any(k.startswith(lp.role_scope_prefix(r)) for k in env for r in lp.ROLE_ORDER), role


def test_scoped_beats_the_global_line_and_the_live_import(blueprint, settings):
    local = {"SYNDICATE_ACTIVE_SPORTS": "mlb", "LIVE_ODDS_WORKER__SYNDICATE_ACTIVE_SPORTS": "mlb,nba"}
    lo, audit = _env("live-odds-worker", blueprint, settings, local=local, live=_LIVE["live-odds-worker"])
    web, _ = _env("web", blueprint, settings, local=local, live=_LIVE["web"])
    assert lo["SYNDICATE_ACTIVE_SPORTS"] == "mlb,nba"
    assert web["SYNDICATE_ACTIVE_SPORTS"] == "mlb"  # the global line still applies to everyone else
    assert audit["role_scoped"] == ["SYNDICATE_ACTIVE_SPORTS"]


def test_without_a_pin_nothing_changes(blueprint, settings):
    for role in lp.ROLE_ORDER:
        env, audit = _env(role, blueprint, settings, live=_LIVE[role])
        assert env["SYNDICATE_ACTIVE_SPORTS"] == _LIVE[role]["SYNDICATE_ACTIVE_SPORTS"]
        assert audit["role_scoped"] == []


def test_never_carry_holds_for_a_scoped_key(blueprint, settings):
    env, _ = _env("web", blueprint, settings, local={"WEB__RENDER_API_KEY": "x"})
    assert "RENDER_API_KEY" not in env


def test_an_unknown_prefix_is_an_ordinary_key(blueprint, settings):
    env, audit = _env("web", blueprint, settings, local={"SOMETHING__ELSE": "1", "WEB__": "bare"})
    assert env["SOMETHING__ELSE"] == "1"
    assert env["WEB__"] == "bare"  # a bare prefix names no key
    assert audit["role_scoped"] == []


def test_env_file_round_trip(tmp_path, blueprint, settings):
    path = tmp_path / "local_production.env"
    path.write_text(
        "# pinned for live-odds-worker only\n"
        "LIVE_ODDS_WORKER__SYNDICATE_ACTIVE_SPORTS=mlb,wnba,soccer,ncaaf,nfl,nhl,nba\n",
        encoding="utf-8",
    )
    local = lp.parse_env_file(path)
    env, _ = _env("live-odds-worker", blueprint, settings, local=local)
    assert env["SYNDICATE_ACTIVE_SPORTS"].endswith(",nba")
