"""Guards for the NFL/NCAAF player-prop odds capture path.

These exist because the defect they cover was TOTAL and SILENT for months:
every requested market 422'd (wrong endpoint, plus two market keys that do not
exist), the fetcher swallowed each 422 as a WARNING and returned [], and the
run wrote a header-only CSV that is indistinguishable from "the books have not
posted props today".

Measured on production 2026-08-20 before the fix: 13 of 14 weekly NFL prop CSVs
were 5-byte stubs, and 101MB of NFL book_quotes held zero player rows.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(module_name: str, relative: str):
    path = REPO_ROOT / relative
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


nfl = _load("_test_fetch_nfl_props", "scripts/fetch_nfl_oddsapi_props_local.py")
ncaaf = _load("_test_fetch_ncaaf_props", "scripts/fetch_ncaaf_oddsapi_props_local.py")


# The keys OddsAPI actually accepts, verified live 2026-08-20 against both
# americanfootball_nfl and americanfootball_ncaaf. `player_rec_yds` and
# `player_interceptions` are NOT among them -- each 422s INVALID_MARKET.
VALID_ODDSAPI_MARKETS = {
    "player_reception_yds",
    "player_receptions",
    "player_rush_yds",
    "player_rush_attempts",
    "player_pass_yds",
    "player_pass_tds",
    "player_pass_attempts",
    "player_pass_interceptions",
    "player_anytime_td",
}

KNOWN_INVALID_MARKETS = {"player_rec_yds", "player_interceptions"}


@pytest.mark.parametrize("module", [nfl, ncaaf], ids=["nfl", "ncaaf"])
def test_requested_markets_are_keys_the_api_accepts(module):
    requested = set(module.DEFAULT_PLAYER_MARKETS)
    assert requested <= VALID_ODDSAPI_MARKETS, (
        f"unknown OddsAPI market key(s): {sorted(requested - VALID_ODDSAPI_MARKETS)}"
    )
    assert not (requested & KNOWN_INVALID_MARKETS), (
        "these keys 422 INVALID_MARKET and produce a silent zero-row capture"
    )
    assert set(module.MARKET_STD_MAP) == requested


@pytest.mark.parametrize("module", [nfl, ncaaf], ids=["nfl", "ncaaf"])
def test_standard_market_names_are_unchanged(module):
    """The CSV/board contract. Fixing an API key must not rename a market."""
    assert set(module.MARKET_STD_MAP.values()) == {
        "Receiving Yards",
        "Receptions",
        "Rushing Yards",
        "Rushing Attempts",
        "Passing Yards",
        "Passing TDs",
        "Passing Attempts",
        "Interceptions",
        "Anytime TD",
    }


@pytest.mark.parametrize("module", [nfl, ncaaf], ids=["nfl", "ncaaf"])
def test_props_are_fetched_per_event_not_from_the_bulk_odds_endpoint(module, monkeypatch):
    """Bulk /sports/{key}/odds serves featured markets only; player props are
    per-event. Calling the bulk route is the original defect."""
    called: list[str] = []

    class _Response:
        status_code = 200
        headers: dict[str, str] = {}
        text = ""
        url = "https://example.invalid/"

        def json(self):
            return []

        def raise_for_status(self):
            return None

    def _fake_get(url, params=None, timeout=None):
        called.append(url)
        return _Response()

    monkeypatch.setattr(module.requests, "get", _fake_get)
    monkeypatch.setattr(module, "record_oddsapi_quota", lambda *a, **k: None)
    module.fetch_player_props("key")

    assert called, "no request was made"
    assert not any(u.endswith("/odds") and "/events/" not in u for u in called), (
        f"bulk odds endpoint used: {called}"
    )


def test_events_in_scope_keeps_one_slate_not_the_whole_season():
    """/events returns the whole season (272 NFL events, measured). Props are
    billed per event, so an unbounded sweep pays for games weeks away that
    have no props posted."""
    now = datetime.now(tz=timezone.utc)
    events = [
        {"id": "past", "commence_time": (now - timedelta(days=2)).isoformat()},
        {"id": "wk1a", "commence_time": (now + timedelta(days=1)).isoformat()},
        {"id": "wk1b", "commence_time": (now + timedelta(days=4)).isoformat()},
        {"id": "wk2", "commence_time": (now + timedelta(days=12)).isoformat()},
        {"id": "wk9", "commence_time": (now + timedelta(days=60)).isoformat()},
    ]
    kept = {e["id"] for e in nfl.events_in_scope(events, window_days=8)}
    assert kept == {"wk1a", "wk1b"}, kept


def test_events_in_scope_handles_an_empty_schedule():
    assert nfl.events_in_scope([]) == []
    assert nfl.events_in_scope([{"id": "x"}]) == []


@pytest.mark.parametrize("module", [nfl, ncaaf], ids=["nfl", "ncaaf"])
def test_all_markets_invalid_raises_instead_of_returning_empty(module, monkeypatch):
    """THE anti-regression guard. A bad market key must not look like a quiet
    market: returning [] here is what let the caller write a header-only CSV
    and report success."""
    now = datetime.now(tz=timezone.utc)

    class _Resp422:
        status_code = 422
        headers: dict[str, str] = {}
        text = '{"error_code":"INVALID_MARKET"}'
        url = "https://example.invalid/"

        def json(self):
            return {}

        def raise_for_status(self):
            return None

    class _EventsResp:
        status_code = 200
        headers: dict[str, str] = {}
        text = ""
        url = "https://example.invalid/"

        def json(self):
            return [{"id": "e1", "commence_time": (now + timedelta(days=1)).isoformat()}]

        def raise_for_status(self):
            return None

    def _fake_get(url, params=None, timeout=None):
        return _EventsResp() if url.endswith("/events") else _Resp422()

    monkeypatch.setattr(module.requests, "get", _fake_get)
    monkeypatch.setattr(module, "record_oddsapi_quota", lambda *a, **k: None)

    with pytest.raises(module.InvalidMarketError):
        module.fetch_player_props("key")


# ---------------------------------------------------------------------------
# Name resolution. Split out because the failure mode is not "no match" -- it
# is a CONFIDENT WRONG match, which is strictly worse for a betting join.
# ---------------------------------------------------------------------------

def test_ambiguous_short_name_resolves_to_none_not_to_a_guess(monkeypatch):
    """`short_name_from_full` maps "Troy Hill" and "Tyreek Hill" to the same
    "T.Hill". The index must refuse it.

    The old `setdefault` behaviour handed the longshot's price Tyreek Hill's
    game log and produced a +125% anytime_td ROI that was pure join artifact.
    """
    from syndicate.features.nfl import player_stats

    plays = (
        {"receiver_player_id": "TYREEK", "receiver_player_name": "T.Hill",
         "passer_player_id": "", "passer_player_name": "",
         "rusher_player_id": "", "rusher_player_name": "", "week": 1},
        {"receiver_player_id": "TROY", "receiver_player_name": "T.Hill",
         "passer_player_id": "", "passer_player_name": "",
         "rusher_player_id": "", "rusher_player_name": "", "week": 1},
        {"receiver_player_id": "SOLO", "receiver_player_name": "D.Maye",
         "passer_player_id": "", "passer_player_name": "",
         "rusher_player_id": "", "rusher_player_name": "", "week": 1},
    )
    monkeypatch.setattr(player_stats, "load_player_plays", lambda season: plays)
    player_stats.player_name_index.cache_clear()

    assert player_stats.resolve_player_id(2025, "Tyreek Hill") is None
    assert player_stats.resolve_player_id(2025, "Troy Hill") is None
    # An unambiguous name still resolves -- the fix must not blind the join.
    assert player_stats.resolve_player_id(2025, "Drake Maye") == "SOLO"

    collisions = player_stats.player_name_collisions(2025)
    assert set(collisions) == {"t.hill"}
    assert collisions["t.hill"] == frozenset({"TYREEK", "TROY"})
    player_stats.player_name_index.cache_clear()


# ---------------------------------------------------------------------------
# Game context on the BOARD path. Reachability first (standard 4.3), then the
# markets that deliberately ship unchanged.
# ---------------------------------------------------------------------------

def test_schedules_games_is_allowlisted_because_it_is_a_model_input():
    """standard 3b: an unallowlisted model input is an unauditable one."""
    from syndicate.features.shared.artifact_publisher import (
        HOT_ARTIFACT_PATTERNS,
        is_hot_artifact_relative_path,
    )

    assert "nfl_source/tracking/nflverse/schedules_games.csv" in HOT_ARTIFACT_PATTERNS
    assert is_hot_artifact_relative_path("nfl_source/tracking/nflverse/schedules_games.csv")


def _stub_context(monkeypatch, *, ratio, delta):
    from syndicate.features.nfl import props

    monkeypatch.setattr(props, "player_team_by_week", lambda season: {"P1": {1: "KC", 2: "KC", 3: "KC"}})
    monkeypatch.setattr(props, "implied_total_ratio", lambda *a, **k: ratio)
    monkeypatch.setattr(props, "favoured_by_delta", lambda *a, **k: delta)
    return props


def test_game_context_multiplier_off_differs_from_on(monkeypatch):
    props = _stub_context(monkeypatch, ratio=1.25, delta=4.0)

    monkeypatch.setenv("SYNDICATE_NFL_PROPS_GAME_CONTEXT", "off")
    off = props.nfl_game_context_multiplier(2025, 3, "P1", "receiving_yards")
    monkeypatch.setenv("SYNDICATE_NFL_PROPS_GAME_CONTEXT", "on")
    on = props.nfl_game_context_multiplier(2025, 3, "P1", "receiving_yards")

    assert off == 1.0
    assert on != off, "game context is INERT on the board path"


def test_markets_that_ship_unchanged_stay_exactly_one(monkeypatch):
    """rushing_attempts (holdout MAE got worse) and anytime_td (fitted against
    the RAW rate while production uses the shrunk one) must be no-ops."""
    props = _stub_context(monkeypatch, ratio=1.25, delta=4.0)
    monkeypatch.setenv("SYNDICATE_NFL_PROPS_GAME_CONTEXT", "on")

    for stat in ("rushing_attempts", "anytime_td"):
        assert props.nfl_game_context_multiplier(2025, 3, "P1", stat) == 1.0, stat
        assert props._NFL_GAME_CONTEXT_PARAMS[stat] == (0.0, 0.0), stat


def test_unresolvable_context_is_a_no_op_not_a_guess(monkeypatch):
    """`implied_total_ratio` returns None for an unknown lookup. That must
    become exactly 1.0 here and never a fabricated adjustment."""
    props = _stub_context(monkeypatch, ratio=None, delta=None)
    monkeypatch.setenv("SYNDICATE_NFL_PROPS_GAME_CONTEXT", "on")
    assert props.nfl_game_context_multiplier(2025, 3, "P1", "receiving_yards") == 1.0


def test_too_few_prior_weeks_is_a_no_op(monkeypatch):
    from syndicate.features.nfl import props

    monkeypatch.setattr(props, "player_team_by_week", lambda season: {"P1": {5: "KC"}})
    monkeypatch.setenv("SYNDICATE_NFL_PROPS_GAME_CONTEXT", "on")
    assert props.nfl_game_context_multiplier(2025, 6, "P1", "receiving_yards") == 1.0


def test_pass_and_rush_attempt_betas_have_opposite_signs():
    """The falsifiable prediction the fit was judged against: a favoured team
    throws less and runs more. Guards the shipped coefficients against a
    re-fit that silently loses the football."""
    from syndicate.features.nfl.props import _NFL_GAME_CONTEXT_PARAMS

    _, pass_beta = _NFL_GAME_CONTEXT_PARAMS["passing_attempts"]
    _, rush_beta = _NFL_GAME_CONTEXT_PARAMS["rushing_yards"]
    assert pass_beta < 0 < rush_beta


def test_per_season_schedule_is_allowlisted_and_preferred_over_the_gitignored_dump():
    """The mechanism's input must be one production actually has.

    `tracking/nflverse/schedules_games.csv` is gitignored and no script in this
    repo writes it, so a board wired to it is inert everywhere but a dev
    machine -- measured: export count 0 with the pattern confirmed deployed.
    `schedule_{season}.csv` has a real fetcher and must come first.
    """
    from syndicate.features.nfl.game_context import schedule_paths
    from syndicate.features.shared.artifact_publisher import (
        HOT_ARTIFACT_PATTERNS,
        is_hot_artifact_relative_path,
    )

    assert "nfl_source/schedule_*.csv" in HOT_ARTIFACT_PATTERNS
    assert is_hot_artifact_relative_path("nfl_source/schedule_2026.csv")

    order = [p.name for p in schedule_paths(2026)]
    assert order[0] == "schedule_2026.csv", order
    assert "schedules_games.csv" in order[-1], order


def test_schedule_fetcher_publishes_its_output():
    """Allowlisting only PERMITS the transfer (`#208`); this is the call that
    makes one. Without it the game-context input never reaches web."""
    source = (REPO_ROOT / "scripts" / "fetch_nfl_schedule.py").read_text(encoding="utf-8")
    assert "publish_hot_artifact" in source
