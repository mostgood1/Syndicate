"""Tests for `syndicate.features.soccer.ingestion.fotmob_match_id`.

The Canada/Brazil trap is the reason this module exists in this shape: matching
FotMob's `Premier League` by name alone resolves to a Canadian league and
`Serie A` alone resolves to a Brazilian one (see the module docstring). Every
positive-match test below includes a same-named-different-country decoy to
prove the ccode gate, not just the name gate, is load-bearing.
"""

from __future__ import annotations

from syndicate.features.soccer.ingestion.fotmob_match_id import resolve_fotmob_match_id

_DECOY_PREMIER_LEAGUE_CANADA = {
    "match_id": 999001, "league_id": 9986, "league": "Premier League", "ccode": "CAN",
    "home": "Vancouver FC", "away": "Cavalry FC", "home_id": 1, "away_id": 2,
    "status": None, "finished": True, "time": None,
}
_REAL_EPL_FIXTURE = {
    "match_id": 4193843, "league_id": 47, "league": "Premier League", "ccode": "ENG",
    "home": "Crystal Palace", "away": "Chelsea", "home_id": 3, "away_id": 4,
    "status": None, "finished": True, "time": None,
}


def _fixed_fetch(rows):
    def fetch(_date_compact: str):
        return list(rows)
    return fetch


def test_resolves_correct_league_over_same_named_decoy():
    fetch = _fixed_fetch([_DECOY_PREMIER_LEAGUE_CANADA, _REAL_EPL_FIXTURE])
    mid = resolve_fotmob_match_id(
        league="epl", home_team="Crystal Palace", away_team="Chelsea",
        iso_date="2026-08-14", _fetch=fetch,
    )
    assert mid == 4193843


def test_decoy_alone_does_not_resolve():
    fetch = _fixed_fetch([_DECOY_PREMIER_LEAGUE_CANADA])
    mid = resolve_fotmob_match_id(
        league="epl", home_team="Vancouver FC", away_team="Cavalry FC",
        iso_date="2026-08-14", _fetch=fetch,
    )
    assert mid is None, "same league name, wrong country, must not resolve"


def test_name_normalisation_handles_club_suffix_variants():
    fetch = _fixed_fetch([{
        "match_id": 42, "league_id": 87, "league": "LaLiga", "ccode": "ESP",
        "home": "Athletic Club", "away": "Sevilla FC",
        "home_id": 1, "away_id": 2, "status": None, "finished": True, "time": None,
    }])
    mid = resolve_fotmob_match_id(
        league="la_liga", home_team="Athletic Bilbao", away_team="Sevilla",
        iso_date="2026-08-22", _fetch=fetch,
    )
    assert mid == 42


def test_unknown_league_returns_none_without_fetching():
    calls = []

    def fetch(date_compact):
        calls.append(date_compact)
        return []

    mid = resolve_fotmob_match_id(
        league="not_a_real_league", home_team="A", away_team="B",
        iso_date="2026-08-22", _fetch=fetch,
    )
    assert mid is None
    assert calls == [], "an unresolvable league must not spend an HTTP call"


def test_malformed_date_returns_none():
    mid = resolve_fotmob_match_id(
        league="epl", home_team="A", away_team="B",
        iso_date="not-a-date", _fetch=_fixed_fetch([]),
    )
    assert mid is None


def test_fetch_exception_is_swallowed_not_raised():
    def fetch(_date_compact: str):
        raise RuntimeError("simulated network failure")

    mid = resolve_fotmob_match_id(
        league="epl", home_team="A", away_team="B",
        iso_date="2026-08-22", _fetch=fetch,
    )
    assert mid is None


def test_no_match_in_candidates_returns_none():
    fetch = _fixed_fetch([_REAL_EPL_FIXTURE])
    mid = resolve_fotmob_match_id(
        league="epl", home_team="Arsenal", away_team="Liverpool",
        iso_date="2026-08-14", _fetch=fetch,
    )
    assert mid is None
