"""UEFA club competitions (UCL / UEL / UECL), Stage 0: registered, not simulated.

Lane `soccer-uefa-competitions`, 2026-10-15. These competitions get fixtures,
game odds, live scoreboard state and venue joins, and NO model output: every
team rating is fit per domestic league, so a sim here would silently rate a
club from a league we do not carry as league-average. The tests pin both
halves -- the registries carry them, and the sim path cannot reach them.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from syndicate.features.shared import kalshi_catalogue as cat
from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS
from syndicate.features.soccer.sources import (
    LEAGUE_DISPLAY_NAMES,
    UEFA_COMPETITIONS,
    active_leagues_for_date,
    league_has_sim,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"test_uefa_{name}", REPO_ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_uefa_competitions_are_in_every_registry_they_need():
    odds = _load_script("fetch_soccer_oddsapi_odds_local")
    refresh = _load_script("refresh_odds_sources")
    live = _load_script("run_live_odds_refresh_worker")
    assert set(UEFA_COMPETITIONS) == {"ucl", "uel", "uecl"}
    for slug in UEFA_COMPETITIONS:
        assert slug in LEAGUE_DISPLAY_NAMES
        assert slug in LEAGUE_ESPN_SLUGS
        assert odds.LEAGUE_SPORT_KEYS[slug].startswith("soccer_uefa_")
        assert slug in refresh._SOCCER_LEAGUE_SLUGS
        assert slug in live._SOCCER_LIVE_LEAGUES
        assert league_has_sim(slug) is False
    # Same window as the European leagues: league phase Sep-Jan, knockouts to May.
    assert set(UEFA_COMPETITIONS) <= set(active_leagues_for_date("2026-10-21"))
    assert not set(UEFA_COMPETITIONS) & set(active_leagues_for_date("2026-07-01"))


def test_domestic_leagues_keep_their_sim():
    for slug in LEAGUE_DISPLAY_NAMES:
        if slug not in UEFA_COMPETITIONS:
            assert league_has_sim(slug) is True, slug


def _steps(leagues: str):
    module = _load_script("refresh_odds_sources")
    args = argparse.Namespace(date="2026-10-21", soccer_leagues=leagues, soccer_date="")
    with patch.object(module, "soccer_active_leagues_for_date", return_value=list(module._SOCCER_LEAGUE_SLUGS)), \
            patch.object(module, "_soccer_live_scope", return_value={"ucl": ["e1"], "epl": ["e2"]}):
        return {step.name for step in module._build_soccer_steps(args)}


def test_uefa_gets_only_the_model_free_steps():
    names = _steps("ucl,epl")
    # `props` joined this list 2026-10-21 (lane soccer-uefa-followups): pregame UEFA props within 24h of kickoff.
    for suffix in ("schedule", "odds", "live_state", "odds_live", "props"):
        assert f"soccer_ucl_{suffix}" in names, suffix
    for suffix in ("artifacts", "picks", "props_live", "history", "players", "rosters"):
        assert not any(name == f"soccer_ucl_{suffix}" or name.startswith(f"soccer_ucl_{suffix}_") for name in names), suffix
    # Reachability: the same build still gives a domestic league its sim, so the
    # gate is the league, not a broken loop.
    assert "soccer_epl_artifacts" in names
    assert "soccer_epl_picks" in names
    assert "soccer_epl_props_live" in names


_LIVE_STATE = {
    "home_team": "Sabah", "away_team": "Dortmund", "half": 2, "clock_remaining": 1200.0,
    "score_home": 0, "score_away": 2, "home_red_cards": 0, "away_red_cards": 0,
    "home_shots_so_far": 3, "away_shots_so_far": 11, "home_shots_on_target_so_far": 1,
    "away_shots_on_target_so_far": 5, "home_corners_so_far": 2, "away_corners_so_far": 6,
}


def _poll(league: str, tmp: Path):
    from scripts import poll_soccer_live_state as poller

    event = {"event_id": "e1", "home_team": "Sabah", "away_team": "Dortmund", "clock": 4200.0}

    def _fake_fetch_events(_league, *, date_windows, statuses=None, timeout=20):
        return [event] if set(statuses or ()) == {"in"} else []

    with patch.object(poller, "fetch_events", side_effect=_fake_fetch_events), \
            patch.object(poller, "fetch_match_summary", return_value={}), \
            patch.object(poller, "build_live_state", return_value=dict(_LIVE_STATE)), \
            patch.object(poller, "_load_team_ratings", side_effect=SystemExit("no team history")) as ratings:
        try:
            payload = poller.poll_league(league, "2026-10-21", source_root=tmp, out_root=tmp, simulations=5)
        except SystemExit:
            payload = None
    return payload, ratings.call_count


def test_live_poll_of_a_uefa_match_writes_state_without_ratings(tmp_path):
    payload, ratings_calls = _poll("ucl", tmp_path)
    # `_load_team_ratings` raises SystemExit with no history -- a BaseException
    # that would end the shared live-lens thread. The UEFA branch never calls it.
    assert ratings_calls == 0
    game = payload["games"]["e1"]
    assert (game["score_home"], game["score_away"]) == (0, 2)
    assert game["projection"] is None
    assert game["live_player_props"] == []
    assert payload["count"] == 1  # liveness for live_refresh_loop still reads this


def test_live_poll_of_a_domestic_league_still_reaches_the_sim(tmp_path):
    # Control arm: the same harness on a modelled league does go to the ratings.
    _payload, ratings_calls = _poll("epl", tmp_path)
    assert ratings_calls == 1


def test_refresh_worker_launches_no_sim_unit_for_uefa():
    worker = _load_script("run_refresh_worker")
    with patch("syndicate.features.soccer.sources.active_leagues_for_date", return_value=["ucl", "epl"]), \
            patch.object(worker, "_soccer_schedule_dates_in_horizon", return_value=["2026-10-21"]):
        units, _scope = worker._soccer_refresh_units("2026-10-21")
    leagues = {unit.get("league") or str(unit.get("key", "")).split("|")[0] for unit in units}
    assert "ucl" not in leagues
    assert "epl" in leagues


@pytest.mark.parametrize(
    ("series", "expected"),
    [
        ("KXUCLGAME", "soccer"),
        ("KXUELGAME", "soccer"),
        ("KXUECLGAME", "soccer"),
        ("KXUECLSCORE", "soccer"),
        ("KXUCLTOTAL", "soccer"),
        # `UCL` sits inside this ticker; the token must be anchored on `KX`.
        ("KXNUCLEARTEST", None),
    ],
)
def test_kalshi_uefa_series_are_soccer_and_nothing_else_is(series, expected):
    assert cat.sport_for_series(series) == expected


@pytest.mark.parametrize(
    ("title", "league"),
    [
        # Both spellings Kalshi uses, read off the live API 2026-10-15.
        ("UEFA Champions League Game", "ucl"),
        ("Champions League Total Goals", "ucl"),
        ("UEFA Europa League Game", "uel"),
        ("UEFA Conference League Game", "uecl"),
        ("Conference League Total Goals", "uecl"),
        # The prefix still must not let the Championship race the Champions League.
        ("Championship Game", "championship"),
    ],
)
def test_kalshi_titles_resolve_to_the_competition(title, league):
    assert cat.soccer_league_from_title(title) == league


def test_the_artifact_builder_refuses_a_competition_with_no_model(tmp_path):
    from scripts.build_soccer_artifacts import build_artifacts

    with pytest.raises(SystemExit, match="no model"):
        build_artifacts("ucl", "2026-10-21", source_root=tmp_path, out_root=tmp_path, simulations=5)


def test_a_uefa_fixture_card_says_odds_only_and_never_prints_the_build_command():
    from syndicate.features.soccer import cards

    fixture = {"event_id": "401915403", "home_team": "Fenerbahce", "away_team": "Slavia Prague",
               "date": "2026-10-20T16:45Z", "status_state": "pre"}
    game = cards._unsimulated_game(fixture, league="ucl", week=3, season=2026)
    text = repr(game)
    assert "build_soccer_artifacts" not in text
    assert "market odds only" in game["summary"]
    assert game["panels"][0]["eyebrow"] == "No model for this competition"
    # Control: a domestic fixture keeps the operator instruction.
    domestic = cards._unsimulated_game(fixture, league="epl", week=3, season=2026)
    assert "build_soccer_artifacts" in repr(domestic)


# ---------------------------------------------------------------------------
# UEFA club identity in the soccer alias map (Kalshi / OddsAPI joins).
# ---------------------------------------------------------------------------

_BRANDING = {
    # The real collision measured 2026-10-15: ESPN gives Levante AND Levski Sofia `LEV`.
    "la_liga": [{"name": "Levante", "short_name": "Levante", "abbreviation": "LEV"}],
    "uel": [
        {"name": "Levski Sofia", "short_name": "Levski", "abbreviation": "LEV"},
        {"name": "Olympiacos", "short_name": "Olympiacos", "abbreviation": "OLY"},
    ],
    "ucl": [
        {"name": "Slavia Prague", "short_name": "Slavia", "abbreviation": "SLP"},
        {"name": "Sabah FK", "short_name": "Sabah", "abbreviation": "SAB"},
    ],
    "uecl": [
        {"name": "Red Star Belgrade", "short_name": "Red Star", "abbreviation": "CZV"},
        {"name": "F.C. København", "short_name": "København", "abbreviation": "FCK"},
    ],
}


@pytest.fixture
def stub_branding(monkeypatch):
    from syndicate.features.shared import team_aliases as ta
    from syndicate.features.soccer import sources

    monkeypatch.setattr(sources, "all_teams", lambda league: [dict(r) for r in _BRANDING.get(league, [])])
    ta._soccer_alias_to_name.cache_clear()
    ta._soccer_alias_by_league.cache_clear()
    yield ta
    ta._soccer_alias_to_name.cache_clear()
    ta._soccer_alias_by_league.cache_clear()


def test_uefa_branding_adds_club_names_but_never_steals_a_domestic_code(stub_branding):
    ta = stub_branding
    # Before the fix this key became ambiguous and was DROPPED from the global map.
    assert ta.canonical_team("soccer", "LEV") == "levante"
    assert ta.canonical_team("soccer", "Levski Sofia") == "levski sofia"
    # The UEFA abbreviation contributes nothing.
    assert ta.canonical_team("soccer", "OLY") is None
    # Per-league maps (soccer_fixture_clubs' disambiguator) stay domestic-only.
    assert set(ta._soccer_alias_by_league()) == {"la_liga"}


@pytest.mark.parametrize(
    ("vendor_name", "canonical"),
    [
        ("Slavia Praha", "slavia prague"),  # OddsAPI
        ("Sabah Masazir", "sabah fk"),  # Kalshi
        ("Olympiakos Piraeus", "olympiacos"),  # OddsAPI
        # By ELIMINATION, 2026-10-19 (lane uefa-kalshi-elim-aliases): KXUECLGAME-26OCT22CZVFCC.
        ("Crvena Zvezda", "red star belgrade"),  # Kalshi
        ("Copenhagen", "f.c. københavn"),  # Kalshi
    ],
)
def test_vendor_spellings_of_uefa_clubs_resolve(stub_branding, vendor_name, canonical):
    assert stub_branding.canonical_team("soccer", vendor_name) == canonical


def test_refused_names_stay_refused(stub_branding, monkeypatch):
    from syndicate.features.soccer import sources

    ta = stub_branding
    extra = {"eredivisie": [{"name": "FC Twente", "short_name": "Twente", "abbreviation": "TWE"}],
             "belgian_pro_league": [{"name": "Sint-Truidense", "short_name": "Sint-Truiden", "abbreviation": "STV"}]}
    monkeypatch.setattr(sources, "all_teams",
                        lambda league: [dict(r) for r in (_BRANDING.get(league) or extra.get(league) or [])])
    ta._soccer_alias_to_name.cache_clear()
    ta._CANONICAL_MEMO.clear()
    # `#631` refused `Inter` by name: it is Inter Miami AND Inter d'Escaldes, so no fixture settles it.
    assert stub_branding.canonical_team("soccer", "Inter") is None
    # `Enschede` and `St. Truidense` were refused only for want of evidence; exact fixture pairing
    # supplied it on 2026-10-19 (lane uefa-oddsapi-club-aliases, owner-approved).
    assert stub_branding.canonical_team("soccer", "Enschede") == "fc twente"
    assert stub_branding.canonical_team("soccer", "St. Truidense") == "sint truidense"


def test_soccer_prop_call_sends_the_ten_books_only_when_configured(monkeypatch):
    """Reachability: the list must reach the REQUEST, and `None` must leave it out."""
    props = _load_script("fetch_soccer_oddsapi_props_local")
    sent = []

    class _Resp:
        headers: dict = {}
        url = "https://api.the-odds-api.com/v4/x"
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"bookmakers": []}

    monkeypatch.setattr(props.requests, "get", lambda url, params=None, timeout=None: sent.append(dict(params)) or _Resp())
    monkeypatch.setattr(props, "record_oddsapi_quota", lambda *a, **k: None)
    for books in (None, "betrivers,mybookieag"):
        props.fetch_event_player_props("k", sport_key="soccer_epl", event_id="e1", region="us",
                                       markets=["player_goal_scorer_anytime"], bookmakers=books)
    assert "bookmakers" not in sent[0] and sent[0]["regions"] == "us"
    assert sent[1]["bookmakers"] == "betrivers,mybookieag"
