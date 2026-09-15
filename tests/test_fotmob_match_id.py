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


# --- Team-name aliases: the loose pass -------------------------------------
#
# After the league fix, the join still missed fixtures whose ESPN and FotMob
# names differ in SHAPE, not club: "Waasland-Beveren" / "SK Beveren",
# "Sint-Truidense" / "St.Truiden", "LAFC" / "Los Angeles FC", "Bayern Munich" /
# "Bayern München". Measured 2026-09-15 on production's inputs (ESPN
# `team.displayName`). These run the production fetch path on FotMob's recorded
# listings for 2026-09-12 and 2026-09-13.

_FIXTURE_0912 = Path(__file__).parent / "fixtures" / "fotmob_matches_20260912.json"


def _serve_listing(monkeypatch, fixture: Path, compact: str) -> None:
    payload = json.loads(fixture.read_text(encoding="utf-8"))

    def fake_get(url: str):
        return payload if url.endswith(f"date={compact}") else {"leagues": []}

    monkeypatch.setattr(fotmob_shots, "_get", fake_get)


@pytest.mark.parametrize("fixture, compact, iso_date, league, home, away, expected", [
    (_FIXTURE_0912, "20260912", "2026-09-12", "belgian_pro_league", "Waasland-Beveren", "Sint-Truidense", 5811756),
    (_FIXTURE, "20260913", "2026-09-13", "mls", "Sporting Kansas City", "LAFC", 5071358),
    (_FIXTURE, "20260913", "2026-09-13", "bundesliga", "Elversberg", "Bayern Munich", 5881163),
])
def test_loose_pass_resolves_name_shape_aliases(monkeypatch, fixture, compact, iso_date, league, home, away, expected):
    _serve_listing(monkeypatch, fixture, compact)
    mid = resolve_fotmob_match_id(league=league, home_team=home, away_team=away, iso_date=iso_date)
    assert mid == expected


def test_loose_pass_does_not_let_first_division_b_answer_for_the_pro_league(monkeypatch):
    # "Genk U23" plays in First Division B on 09-12. The league gate refuses it
    # before any name pass runs, loose included.
    _serve_listing(monkeypatch, _FIXTURE_0912, "20260912")
    mid = resolve_fotmob_match_id(
        league="belgian_pro_league", home_team="Virton", away_team="Genk", iso_date="2026-09-12",
    )
    assert mid is None


_BEL = {"league_id": 937988, "league_primary_id": 40, "league": "Belgian Pro League", "ccode": "BEL",
        "home_id": 1, "away_id": 2, "status": None, "finished": False, "time": None}


def test_loose_pass_refuses_an_ambiguous_fixture():
    rows = [
        {**_BEL, "match_id": 11, "home": "SK Beveren", "away": "St.Truiden"},
        {**_BEL, "match_id": 12, "home": "KV Beveren", "away": "St.Truiden"},
    ]
    mid = resolve_fotmob_match_id(
        league="belgian_pro_league", home_team="Waasland-Beveren", away_team="Sint-Truidense",
        iso_date="2026-09-12", _fetch=_fixed_fetch(rows),
    )
    assert mid is None, "two fixtures fit loosely: refuse, never guess"


def test_strict_match_wins_over_an_earlier_loose_only_row():
    rows = [
        {**_BEL, "match_id": 11, "home": "SK Beveren", "away": "St.Truiden"},          # loose only
        {**_BEL, "match_id": 10, "home": "Waasland-Beveren", "away": "Sint-Truidense"},  # strict
    ]
    mid = resolve_fotmob_match_id(
        league="belgian_pro_league", home_team="Waasland-Beveren", away_team="Sint-Truidense",
        iso_date="2026-09-12", _fetch=_fixed_fetch(rows),
    )
    assert mid == 10


def test_loose_pass_takes_a_strict_side_beside_a_loose_one():
    # "D.C. United" has no 3+ letter word, so it can only match strictly; the
    # fixture resolves because its other side matches by acronym.
    mls = {"league_id": 913550, "league_primary_id": 130, "league": "Major League Soccer", "ccode": "USA",
           "home_id": 1, "away_id": 2, "status": None, "finished": False, "time": None}
    rows = [{**mls, "match_id": 21, "home": "DC United", "away": "Los Angeles FC"}]
    mid = resolve_fotmob_match_id(
        league="mls", home_team="D.C. United", away_team="LAFC", iso_date="2026-08-29", _fetch=_fixed_fetch(rows),
    )
    assert mid == 21


@pytest.mark.parametrize("league, league_id, ccode, league_name, fotmob_home, espn_home", [
    ("ligue_1", 53, "FRA", "Ligue 1", "Rennes", "Stade Rennais"),
    ("bundesliga", 54, "GER", "Bundesliga", "1. FC Köln", "FC Cologne"),
])
def test_measured_espn_aliases_resolve(league, league_id, ccode, league_name, fotmob_home, espn_home):
    rows = [{"match_id": 31, "league_id": league_id, "league_primary_id": league_id, "league": league_name,
             "ccode": ccode, "home": fotmob_home, "away": "Visitors Athletic", "home_id": 1, "away_id": 2,
             "status": None, "finished": False, "time": None}]
    mid = resolve_fotmob_match_id(
        league=league, home_team=espn_home, away_team="Visitors Athletic", iso_date="2026-08-30",
        _fetch=_fixed_fetch(rows),
    )
    assert mid == 31


@pytest.mark.parametrize("espn, fotmob, expected", [
    ("Waasland-Beveren", "SK Beveren", True),
    ("Paris Saint-Germain", "PSG", True),
    ("Sint-Truidense", "St.Truiden", True),
    ("LAFC", "Los Angeles FC", True),
    ("Bayern Munich", "Bayern München", True),
    ("Borussia Monchengladbach", "Gladbach", True),
    # Sharing only a word that names a KIND of club is not evidence.
    ("Royal Antwerp", "Royal Charleroi", False),
    ("Real Madrid", "Real Sociedad", False),
    ("FC Twente", "FC Utrecht", False),
    ("Sporting Kansas City", "Sporting CP", False),
])
def test_loose_side_match(espn, fotmob, expected):
    from syndicate.features.soccer.ingestion.fotmob_match_id import _loose_side_match

    assert _loose_side_match(espn, fotmob) is expected
