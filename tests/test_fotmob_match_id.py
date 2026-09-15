"""Tests for `syndicate.features.soccer.ingestion.fotmob_match_id`.

The Canada/Brazil trap is the reason this module exists in this shape: matching
FotMob's `Premier League` by name alone resolves to a Canadian league and
`Serie A` alone resolves to a Brazilian one (see the module docstring). Every
positive-match test below includes a same-named-different-country decoy to
prove the ccode gate, not just the name gate, is load-bearing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from syndicate.features.soccer.ingestion import fotmob_shots
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


# --- FotMob's own recorded listing for 2026-09-13 ---------------------------
#
# WHY THESE EXIST. The resolver used to pin FotMob's league `id`, and that id is
# SEASON-SCOPED for four of the ten leagues: Eredivisie 900368 -> 937276,
# Championship 900638 -> 938218, Belgian Pro League 900433 -> 937988 from
# 2025-26 to 2026-27 (MLS 913550 is the 2026 season's). Every fixture in those
# leagues went unresolved in production, and the synthetic rows above could not
# catch it because they carry whatever id the test author typed. These run the
# PRODUCTION fetch path -- `matches_for_date` over a stubbed `_get` -- on the
# listing FotMob actually served, trimmed to the tracked leagues plus that
# day's lookalikes and the Canada/Brazil decoys.

_FIXTURE = Path(__file__).parent / "fixtures" / "fotmob_matches_20260913.json"


def _recorded_listing() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _serve_recorded_listing(monkeypatch, *, drop_primary_id: bool = False) -> None:
    payload = _recorded_listing()
    if drop_primary_id:
        for league in payload["leagues"]:
            league.pop("primaryId", None)
            league.pop("parentLeagueId", None)

    def fake_get(url: str):
        # The resolver probes the day either side too; FotMob lists nothing we
        # recorded there.
        return payload if url.endswith("date=20260913") else {"leagues": []}

    monkeypatch.setattr(fotmob_shots, "_get", fake_get)


@pytest.mark.parametrize("league, home, away, expected", [
    # Season-scoped ids: all three returned None before the fix.
    ("championship", "Sheffield United", "Wolverhampton Wanderers", 5836832),
    ("eredivisie", "PSV Eindhoven", "Sparta Rotterdam", 5781743),
    ("eredivisie", "Excelsior", "FC Utrecht", 5781745),
    ("belgian_pro_league", "Club Brugge", "Royal Antwerp", 5811760),
    ("belgian_pro_league", "Genk", "Gent", 5811761),
    # MLS's id is the 2026 season's, so it still resolves here and breaks in 2027.
    ("mls", "FC Dallas", "Portland Timbers", 5071357),
    # Leagues whose id never changed: controls.
    ("epl", "Coventry City", "Brighton & Hove Albion", 5795448),
    ("la_liga", "Levante", "Barcelona", 5868054),
    ("primeira_liga", "Benfica", "Gil Vicente", 5887635),
])
def test_recorded_listing_resolves_every_tracked_league(monkeypatch, league, home, away, expected):
    _serve_recorded_listing(monkeypatch)
    mid = resolve_fotmob_match_id(league=league, home_team=home, away_team=away, iso_date="2026-09-13")
    assert mid == expected


@pytest.mark.parametrize("drop_primary_id", [False, True])
@pytest.mark.parametrize("league, home, away", [
    ("eredivisie", "FC Twente (W)", "Feyenoord (W)"),          # Eredivisie Vrouwen, NED
    ("eredivisie", "FC Volendam", "FC Den Bosch"),             # Eerste Divisie, NED
    ("championship", "Oakland Roots SC", "Lexington SC"),      # USL Championship, USA
    ("epl", "Middlesbrough U21", "Leeds United U21"),          # Premier League 2, ENG
    ("belgian_pro_league", "Patro Eisden", "Eupen"),           # First Division B, BEL
    ("epl", "Pacific FC", "Cavalry FC"),                       # Premier League, CAN
    ("serie_a", "Flamengo", "Corinthians"),                    # Serie A, BRA
    ("mls", "Chattanooga FC", "Atlanta United 2"),             # MLS Next Pro, USA
])
def test_recorded_listing_does_not_resolve_same_day_lookalikes(monkeypatch, drop_primary_id, league, home, away):
    # The team names are the LOOKALIKE's own, so its row matches on names by
    # construction: only the league gate can refuse it.
    _serve_recorded_listing(monkeypatch, drop_primary_id=drop_primary_id)
    mid = resolve_fotmob_match_id(league=league, home_team=home, away_team=away, iso_date="2026-09-13")
    assert mid is None


@pytest.mark.parametrize("drop_primary_id", [False, True])
def test_league_classifier_over_every_league_in_the_recorded_listing(monkeypatch, drop_primary_id):
    from syndicate.features.soccer.ingestion.fotmob_match_id import FOTMOB_LEAGUES, fotmob_league_slug

    by_primary = {spec.primary_id: slug for slug, spec in FOTMOB_LEAGUES.items()}
    listing = _recorded_listing()
    expected = {league["id"]: by_primary.get(league["primaryId"]) for league in listing["leagues"]}
    # Every tracked league is in the listing, or this test proves nothing for it.
    assert set(expected.values()) - {None} == set(FOTMOB_LEAGUES)

    _serve_recorded_listing(monkeypatch, drop_primary_id=drop_primary_id)
    rows = fotmob_shots.matches_for_date("20260913")
    assert rows
    for row in rows:
        assert fotmob_league_slug(row) == expected[row["league_id"]], (row["league"], row["ccode"])


def test_accented_fotmob_name_matches_unaccented_espn_name(monkeypatch):
    # FotMob lists "RAAL La Louvière"; ESPN writes Belgian names without accents.
    _serve_recorded_listing(monkeypatch)
    mid = resolve_fotmob_match_id(
        league="belgian_pro_league", home_team="RAAL La Louviere", away_team="Kortrijk",
        iso_date="2026-09-13",
    )
    assert mid == 5811763


def test_last_seasons_competition_id_is_not_needed():
    from syndicate.features.soccer.ingestion.fotmob_match_id import fotmob_league_slug

    # 2025-26's Championship, as FotMob listed it on 2025-10-18.
    row = {"league_id": 900638, "league_primary_id": 48, "league": "Championship", "ccode": "ENG"}
    assert fotmob_league_slug(row) == "championship"
    # And 2024-25's Belgian top flight, under the name it had then.
    row = {"league_id": 892857, "league_primary_id": 40, "league": "First Division A", "ccode": "BEL"}
    assert fotmob_league_slug(row) == "belgian_pro_league"


def test_harvest_league_ids_json_matches_the_resolver():
    from syndicate.features.soccer.ingestion.fotmob_match_id import fotmob_leagues_record

    path = Path(__file__).resolve().parents[1] / "reports" / "soccer_backtest" / "fotmob_league_ids.json"
    assert json.loads(path.read_text(encoding="utf-8")) == fotmob_leagues_record()
