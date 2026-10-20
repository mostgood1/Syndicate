"""Forward-dated football rows reach their fixture even when the slate date has OTHER games.

Measured 2026-10-20: three NCAAF games were played that Tuesday, so the forward
widening (gated on `not candidates`) never ran and all 414 NCAAF game-line rows
refused `no_matching_polymarket_market`. Replayed by game date: 0 -> 35 matched.
User decision 2026-10-20 "Fix both", lane paper-alongside-live.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import polymarket_board_join as mod

CLUBS = {
    "cle": "cleveland", "cleveland browns": "cleveland",
    "jax": "jacksonville", "jacksonville jaguars": "jacksonville",
    "mia": "miami", "miami dolphins": "miami",
    "buf": "buffalo", "buffalo bills": "buffalo",
    "pit": "pittsburgh", "pittsburgh pirates": "pittsburgh",
    "sd": "san diego", "san diego padres": "san diego",
    "nyy": "new york", "new york yankees": "new york",
    "bos": "boston", "boston red sox": "boston",
}


@pytest.fixture(autouse=True)
def _clubs(monkeypatch):
    """Distinct canonical clubs, so a fixture test can actually fail."""
    import syndicate.features.shared.team_aliases as aliases

    def canon(sport, name):
        return CLUBS.get(str(name or "").strip().lower())

    monkeypatch.setattr(aliases, "canonical_team", canon)
    monkeypatch.setattr(
        aliases, "teams_match", lambda sport, a, b: canon(sport, a) is not None and canon(sport, a) == canon(sport, b)
    )
    yield


def _total(slug):
    return {"slug": slug, "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_TOTAL",
            "outcomes": '["Over","Under"]', "outcomePrices": '["0.52","0.48"]'}


def _row(sport="nfl", home="Jacksonville Jaguars", away="Cleveland Browns", line=41.5, date="2026-09-11"):
    return {"market": "totals", "side": "over", "line": line, "sport": sport, "selected_date": date,
            "home_team": home, "away_team": away, "event_id": "e1"}


def _matched_slugs(out):
    return [str((m.get("market") or m.get("row") or {}).get("slug") or m.get("slug") or "") for m in out.get("matches") or []]


def test_a_forward_fixture_is_reached_when_the_slate_date_has_OTHER_games():
    out = mod.join_polymarket_to_board(
        [_total("tsc-nfl-mia-buf-2026-09-11-41pt5"),   # another game, same league, SAME date
         _total("tsc-nfl-cle-jax-2026-09-13-41pt5")],  # our fixture, Sunday
        [_row()],
        selected_date="2026-09-11")
    assert out["matched"] == 1, out["refusals"]
    assert out["forward_date_widened"] == {"nfl|totals|fixture_absent": 1}, out["forward_date_widened"]


def test_ncaaf_under_the_cfb_token_same_rule():
    out = mod.join_polymarket_to_board(
        [_total("tsc-cfb-mia-buf-2026-10-20-41pt5"), _total("tsc-cfb-cle-jax-2026-10-24-41pt5")],
        [_row(sport="ncaaf", date="2026-10-20")],
        selected_date="2026-10-20")
    assert out["matched"] == 1, out["refusals"]
    assert out["forward_date_widened"] == {"ncaaf|totals|fixture_absent": 1}


def test_a_fixture_listed_on_the_slate_date_is_not_widened():
    """Control: the same-date market for OUR fixture wins and nothing widens."""
    out = mod.join_polymarket_to_board(
        [_total("tsc-nfl-cle-jax-2026-09-11-41pt5"), _total("tsc-nfl-mia-buf-2026-09-11-41pt5")],
        [_row()],
        selected_date="2026-09-11")
    assert out["matched"] == 1, out["refusals"]
    assert out["forward_date_widened"] == {}


def test_beyond_the_horizon_is_still_not_reached():
    out = mod.join_polymarket_to_board(
        [_total("tsc-nfl-mia-buf-2026-09-11-41pt5"), _total("tsc-nfl-cle-jax-2026-09-20-41pt5")],
        [_row()],
        selected_date="2026-09-11")
    assert out["matched"] == 0
    assert out["forward_date_widened"] == {}


def test_MLB_never_widens_even_with_other_games_that_day():
    """A series repeats the pair on consecutive days: the safety gate is unchanged."""
    mlb_row = {"market": "totals", "side": "over", "line": 8.5, "sport": "mlb", "selected_date": "2026-08-24",
               "home_team": "San Diego Padres", "away_team": "Pittsburgh Pirates", "event_id": "e1"}
    out = mod.join_polymarket_to_board(
        [_total("tsc-mlb-nyy-bos-2026-08-24-8pt5"), _total("tsc-mlb-pit-sd-2026-08-25-8pt5")],
        [mlb_row],
        selected_date="2026-08-24")
    assert out["matched"] == 0
    assert out["forward_date_widened"] == {}


def test_a_row_with_a_kickoff_widens_to_ITS_game_day_only():
    """The row's own kickoff picks the window: Sunday's market, not Saturday's same-pair market."""
    row = _row()
    row["commence_time"] = "2026-09-13T17:00:00Z"
    out = mod.join_polymarket_to_board(
        [_total("tsc-nfl-mia-buf-2026-09-11-41pt5"),
         _total("tsc-nfl-cle-jax-2026-09-12-41pt5"),   # same pair, wrong day: must not be offered
         _total("tsc-nfl-cle-jax-2026-09-13-41pt5")],
        [row],
        selected_date="2026-09-11")
    assert out["matched"] == 1, out["refusals"]
    assert out["refusals"].get("ambiguous_polymarket_match") is None
    assert "2026-09-13" in str(out["matches"][0])
    assert out["forward_date_widened"] == {"nfl|totals|fixture_absent": 1}


def test_a_row_whose_kickoff_is_on_the_slate_date_is_not_widened():
    row = _row()
    row["commence_time"] = "2026-09-11T23:15:00Z"
    out = mod.join_polymarket_to_board(
        [_total("tsc-nfl-cle-jax-2026-09-11-41pt5"), _total("tsc-nfl-mia-buf-2026-09-11-41pt5")],
        [row],
        selected_date="2026-09-11")
    assert out["matched"] == 1
    assert out["forward_date_widened"] == {}
