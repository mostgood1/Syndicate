"""`unmatched_match_rows` was a bare total, and it has read ~99.6% for days.

`state.md` records the soccer join at `rows_with_projection: 4` of 1,142 with
1,138 unmatched, and the user's report is the same fact from the other side:
"none of the soccer data from sims (pregame or live) is joining with the board".

ONE NUMBER, THREE UNRELATED CAUSES. `unmatched_match_rows` cannot distinguish:

  * the league is not in the index at all -- the sim never ran it, or its
    recommendations file falls outside the read window. Fix: the producer.
  * the league IS indexed and its rows still miss -- the two feeds spell the
    club differently. Fix: `_SOCCER_VENDOR_NAME_ALIASES`, and only after seeing
    BOTH spellings.
  * the team key was dropped as ambiguous -- `match_for` refusing on purpose,
    because a wrong projection is worse than a blank one. Not a defect at all.

Those have three different owners and, until this change, one identical
symptom. Same contract `#296` set and `LIVE_PROJECTION_JOIN` already meets for
the live tier: a zero must be attributable, never bare.

WHY THE PAIRED SAMPLES. A board-side name alone answers half a name-join
question. `#374` added five vendor aliases and its note is explicit that each
was "verified against a real 0-projection fixture" -- you cannot write the alias
without knowing what the SIM calls the club, so the coverage carries both sides.
"""

from __future__ import annotations

import json
from pathlib import Path

from syndicate.features.shared.soccer_projections import (
    attach_soccer_projections,
    load_soccer_projections,
)

# CLUBS THAT DO NOT EXIST, on purpose. These tests need a pair the name join
# genuinely cannot resolve, and every REAL pair that fits is a bug waiting to be
# fixed -- this file first used `Inter Milan`/`Internazionale`, which became a
# verified alias two hours later (`#503`) and turned four tests red. A synthetic
# pair cannot be repaired out from under the test.
_BOARD_UNKNOWN = "Rovers Athletic"
_SIM_UNKNOWN = "Wanderers United"

DATE = "2026-08-22"


def _write(root: Path, league: str, date: str, fixtures: list[tuple[str, str]]) -> None:
    path = root / league / "api" / "recommendations" / f"recommendations_{date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "league": league,
                "generated_at": "2026-08-22T10:00:00",
                "matches": [
                    {
                        "match_id": f"{league}-{i}",
                        "event_id": f"espn-{league}-{i}",
                        "league": league,
                        "matchup": {"home_team": home, "away_team": away},
                        "win_probability": {"home": 0.5, "draw": 0.25, "away": 0.25},
                    }
                    for i, (home, away) in enumerate(fixtures)
                ],
            }
        ),
        encoding="utf-8",
    )


def _row(league: str, home: str, away: str, event_id: str) -> dict:
    return {
        "sport": "soccer",
        "kind": "game",
        "market": "h2h",
        "league": league,
        "event_id": event_id,
        "home_team": home,
        "away_team": away,
        "line": None,
    }


def test_per_league_counts_separate_an_unrun_league_from_a_name_miss(tmp_path: Path) -> None:
    """The two causes that need completely different fixes, told apart."""
    _write(tmp_path, "serie_a", DATE, [("Wanderers United", "Monza")])
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    grid = [
        # serie_a IS indexed; this row misses on the club's spelling.
        _row("serie_a", "Rovers Athletic", "Monza", "oddsapi-1"),
        # epl is not in the index at all -- nothing was simulated for it.
        _row("epl", "Arsenal", "Chelsea", "oddsapi-2"),
        _row("epl", "Everton", "Fulham", "oddsapi-3"),
    ]
    coverage = attach_soccer_projections(grid, index)

    assert coverage["unmatched_match_rows"] == 3
    assert coverage["leagues_indexed"] == ["serie_a"]
    # The split is the whole point: one league needs an alias, the other needs
    # the sim to run. The bare total said "3" and named neither.
    assert coverage["unmatched_by_league"] == {"epl": 2, "serie_a": 1}
    assert coverage["rows_by_league"] == {"epl": 2, "serie_a": 1}


def test_the_sample_carries_both_spellings_of_the_same_fixture(tmp_path: Path) -> None:
    """An alias cannot be written from the board's name alone."""
    _write(tmp_path, "serie_a", DATE, [("Wanderers United", "Monza")])
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    coverage = attach_soccer_projections(
        [_row("serie_a", "Rovers Athletic", "Monza", "oddsapi-1")], index
    )
    assert coverage["unmatched_fixture_sample"] == ["serie_a|Rovers Athletic v Monza"]
    assert coverage["indexed_fixture_sample"] == ["serie_a|Wanderers United v Monza"]


def test_a_missed_fixture_contributes_one_sample_not_one_per_row(tmp_path: Path) -> None:
    """A soccer fixture carries hundreds of rows and they all miss identically.

    Per-row sampling would fill the list with the same pair and name nothing --
    which is the failure mode the live tier's `unmatched_samples` was capped
    against for the same reason.
    """
    _write(tmp_path, "serie_a", DATE, [("Wanderers United", "Monza")])
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    grid = [_row("serie_a", "Rovers Athletic", "Monza", f"oddsapi-{i}") for i in range(300)]
    coverage = attach_soccer_projections(grid, index)

    assert coverage["unmatched_match_rows"] == 300
    assert coverage["unmatched_fixtures_count"] == 1
    assert coverage["unmatched_fixture_sample"] == ["serie_a|Rovers Athletic v Monza"]


def test_a_row_that_joins_is_absent_from_every_unmatched_counter(tmp_path: Path) -> None:
    """The instrument must not report a defect where there is none."""
    _write(tmp_path, "serie_a", DATE, [("Wanderers United", "Monza")])
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    coverage = attach_soccer_projections(
        [_row("serie_a", "Wanderers United", "Monza", "oddsapi-1")], index
    )
    assert coverage["rows_with_projection"] == 1
    assert coverage["unmatched_match_rows"] == 0
    assert coverage["unmatched_by_league"] == {}
    assert coverage["unmatched_fixture_sample"] == []
    # Still counted as considered -- `rows_by_league` describes the SLATE, so a
    # league at 100% coverage must not vanish from it.
    assert coverage["rows_by_league"] == {"serie_a": 1}


def test_dates_read_is_reported_so_an_unread_date_is_not_read_as_a_name_miss(tmp_path: Path) -> None:
    _write(tmp_path, "serie_a", "2026-08-24", [("Wanderers United", "Monza")])
    window = [DATE, "2026-08-23", "2026-08-24"]
    index = load_soccer_projections([tmp_path], DATE, window_dates=window)

    coverage = attach_soccer_projections(
        [_row("serie_a", "Wanderers United", "Monza", "oddsapi-1")], index
    )
    assert coverage["dates_read"] == window
    assert coverage["rows_with_projection"] == 1


def test_a_row_with_no_league_is_bucketed_rather_than_dropped(tmp_path: Path) -> None:
    """`league` is carried, not keyed (`#330`), so it can genuinely be absent.

    Silently skipping those rows would make the per-league counts stop summing
    to the total, and a counter that does not reconcile is worse than none.
    """
    _write(tmp_path, "serie_a", DATE, [("Wanderers United", "Monza")])
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    grid = [_row("serie_a", "Rovers Athletic", "Monza", "oddsapi-1")]
    grid[0]["league"] = None
    coverage = attach_soccer_projections(grid, index)

    assert coverage["rows_by_league"] == {"?": 1}
    assert sum(coverage["unmatched_by_league"].values()) == coverage["unmatched_match_rows"]


def test_the_sim_side_sample_covers_the_leagues_that_actually_MISS(tmp_path: Path) -> None:
    """SHIPPED WRONG, and this is the regression test for it.

    The first cut sorted every indexed fixture alphabetically and took the first
    12. Measured on production 2026-08-22 17:30:32Z, the board side named 12
    unmatched fixtures across epl (510 rows), la_liga (972), serie_a (606),
    ligue_1 (240) and mls (247) -- and the sim side came back
    belgian_pro_league, bundesliga, championship: three leagues with almost no
    misses, chosen purely because they sort first. The pairing the sample exists
    to enable was impossible for 11 of the 12 fixtures.

    An instrument that reliably samples the leagues with nothing to report is
    worse than no sample, because it looks like an answer.
    """
    # Two leagues sort BEFORE the one with the miss, and each has more fixtures
    # than a global cap would leave room for.
    # Alphabetic for the same reason as above -- `_norm_name` strips digits.
    _write(tmp_path, "belgian_pro_league", DATE, [(f"Belg {c} Home", f"Belg {c} Away") for c in "ABCDEFGHIJKL"])
    _write(tmp_path, "bundesliga", DATE, [(f"Bund {c} Home", f"Bund {c} Away") for c in "ABCDEFGHIJKL"])
    _write(tmp_path, "serie_a", DATE, [("Wanderers United", "Monza")])
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    coverage = attach_soccer_projections(
        [_row("serie_a", "Rovers Athletic", "Monza", "oddsapi-1")], index
    )

    assert coverage["unmatched_by_league"] == {"serie_a": 1}
    sample = coverage["indexed_fixture_sample"]
    # The sim side must answer about serie_a, the league that missed...
    assert "serie_a|Wanderers United v Monza" in sample
    # ...and must not be crowded out by leagues with nothing to report.
    assert not any(entry.startswith("belgian_pro_league|") for entry in sample)
    assert not any(entry.startswith("bundesliga|") for entry in sample)


def test_every_missing_league_gets_its_own_quota(tmp_path: Path) -> None:
    """One busy league must not crowd out the others -- per-league, not global."""
    # Alphabetic, not "E0/E1/...": `_norm_name` STRIPS DIGITS, so numbered
    # fixture names all normalise to one key and get dropped as ambiguous --
    # which silently empties the league this test is about.
    _write(tmp_path, "epl", DATE, [(f"Club {c} Home", f"Club {c} Away") for c in "ABCDEFGHIJKLMNOPQRST"])
    _write(tmp_path, "mls", DATE, [("Los Angeles Football Club", "Portland Timbers")])
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    grid = [
        _row("epl", "Brighton and Hove Albion", "Aston Villa", "oddsapi-1"),
        _row("mls", "Los Angeles FC", "Portland Timbers", "oddsapi-2"),
    ]
    coverage = attach_soccer_projections(grid, index)

    sample = coverage["indexed_fixture_sample"]
    assert any(entry.startswith("epl|") for entry in sample)
    # The 20-fixture league does not squeeze out the 1-fixture one.
    assert "mls|Los Angeles Football Club v Portland Timbers" in sample


def test_nothing_unmatched_means_no_sim_side_noise(tmp_path: Path) -> None:
    """A clean join must not emit a sample at all -- there is no question to answer."""
    _write(tmp_path, "serie_a", DATE, [("Wanderers United", "Monza")])
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])
    coverage = attach_soccer_projections(
        [_row("serie_a", "Wanderers United", "Monza", "oddsapi-1")], index
    )
    assert coverage["unmatched_by_league"] == {}
    assert coverage["indexed_fixture_sample"] == []


# --- the player bucket, which is now the largest -------------------------
#
# `unmatched_player` reached 6,057 rows at 18:31:07Z and GREW when the
# team-name join was fixed — more rows now reach the player stage instead of
# being rejected at the match stage. It had no attribution at all, and it
# covers the same two states the league split covers one level up:
#
#   the sim published NO players for the match  -> producer gap
#   it published players and this name is absent -> a name join problem, the
#                                                   player-level twin of the 13
#                                                   team aliases
#
# Those have different owners and, until now, one identical counter.

def _player_row(league: str, home: str, away: str, player: str, market: str = "player_shots") -> dict:
    return {
        "sport": "soccer",
        "kind": "prop",
        "market": market,
        "league": league,
        "event_id": "oddsapi-p1",
        "home_team": home,
        "away_team": away,
        "player_name": player,
        "line": 1.5,
    }


def _write_with_players(root: Path, league: str, date: str, home: str, away: str, players: list[str]) -> None:
    path = root / league / "api" / "recommendations" / f"recommendations_{date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "league": league,
                "generated_at": "2026-08-22T10:00:00",
                "matches": [
                    {
                        "match_id": f"{league}-0",
                        "event_id": f"espn-{league}-0",
                        "league": league,
                        "matchup": {"home_team": home, "away_team": away},
                        "win_probability": {"home": 0.5, "draw": 0.25, "away": 0.25},
                    }
                ],
                "player_props": [
                    {
                        "match_id": f"{league}-0",
                        "player_name": name,
                        "expected_shots": 2.1,
                    }
                    for name in players
                ],
            }
        ),
        encoding="utf-8",
    )


def test_a_match_with_no_roster_is_named_as_a_PRODUCER_gap(tmp_path: Path) -> None:
    """No players published for the fixture at all — nothing a name alias fixes."""
    _write_with_players(tmp_path, "epl", DATE, "Arsenal", "Chelsea", [])
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    coverage = attach_soccer_projections(
        [_player_row("epl", "Arsenal", "Chelsea", "Bukayo Saka")], index
    )
    assert coverage["unmatched_player_rows"] == 1
    assert coverage["player_miss_no_roster"] == 1
    assert coverage["player_miss_name"] == 0
    # No sample: there is no sim-side name to pair against, and emitting an
    # empty pairing would imply the roster was read and came back short.
    assert coverage["unmatched_player_sample"] == []


def test_a_name_absent_from_a_REAL_roster_is_named_as_a_name_miss(tmp_path: Path) -> None:
    _write_with_players(
        tmp_path, "epl", DATE, "Arsenal", "Chelsea", ["B. Saka", "Martin Ødegaard"]
    )
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    coverage = attach_soccer_projections(
        [_player_row("epl", "Arsenal", "Chelsea", "Bukayo Saka")], index
    )
    assert coverage["player_miss_name"] == 1
    assert coverage["player_miss_no_roster"] == 0
    # BOTH SIDES, so an alias can actually be written from the log line.
    assert coverage["unmatched_player_sample"] == ["epl|Bukayo Saka"]
    assert "B. Saka" in coverage["sim_roster_sample"]


def test_one_player_contributes_one_sample_not_one_per_prop_row(tmp_path: Path) -> None:
    """A player carries a dozen prop rows and they all miss identically."""
    _write_with_players(tmp_path, "epl", DATE, "Arsenal", "Chelsea", ["B. Saka"])
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    grid = [
        _player_row("epl", "Arsenal", "Chelsea", "Bukayo Saka", market=m)
        for m in ("player_shots", "player_shots_on_target", "player_shots", "player_shots_on_target")
    ]
    coverage = attach_soccer_projections(grid, index)
    assert coverage["unmatched_player_rows"] == 4
    assert coverage["unmatched_player_sample"] == ["epl|Bukayo Saka"]


def test_the_player_split_reconciles_with_the_total(tmp_path: Path) -> None:
    """A breakdown that does not sum to its total is worse than none."""
    _write_with_players(tmp_path, "epl", DATE, "Arsenal", "Chelsea", ["B. Saka"])
    _write_with_players(tmp_path, "mls", DATE, "LAFC", "Portland Timbers", [])
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    grid = [
        _player_row("epl", "Arsenal", "Chelsea", "Bukayo Saka"),
        _player_row("mls", "LAFC", "Portland Timbers", "Denis Bouanga"),
    ]
    coverage = attach_soccer_projections(grid, index)
    assert (
        coverage["player_miss_no_roster"] + coverage["player_miss_name"]
        == coverage["unmatched_player_rows"]
    )
    assert coverage["player_miss_no_roster"] == 1
    assert coverage["player_miss_name"] == 1


def test_a_player_that_MATCHES_is_absent_from_every_miss_counter(tmp_path: Path) -> None:
    _write_with_players(tmp_path, "epl", DATE, "Arsenal", "Chelsea", ["Bukayo Saka"])
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    coverage = attach_soccer_projections(
        [_player_row("epl", "Arsenal", "Chelsea", "Bukayo Saka")], index
    )
    assert coverage["unmatched_player_rows"] == 0
    assert coverage["player_miss_name"] == 0
    assert coverage["player_miss_no_roster"] == 0
    assert coverage["unmatched_player_sample"] == []


# ---------------------------------------------------------------------------
# THE SHORT-vs-FULL NAME JOIN, and the three ways it must refuse.
#
# `_norm_name` already folds accents (fixed for MLB 2026-08-16), so the residue
# in soccer is the naming CONVENTION: the sim publishes `Alisson` where the
# board says `Alisson Ramses Becker`. Measured on production 2026-09-03:
# `player_name_miss=7020` with `player_no_roster=0` -- every miss a name, not a
# missing roster.
#
# A WRONG PLAYER IS WORSE THAN AN UNMATCHED ROW: the row still prices, and
# nothing downstream can tell it apart from a correct one. So the refusals below
# are the load-bearing half of this feature, not the happy path.
# ---------------------------------------------------------------------------


def test_a_SHORT_sim_name_joins_a_FULL_board_name(tmp_path: Path) -> None:
    _write_with_players(tmp_path, "epl", DATE, "Liverpool", "Chelsea", ["Alisson"])
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    rows = [_player_row("epl", "Liverpool", "Chelsea", "Alisson Ramses Becker")]
    coverage = attach_soccer_projections(rows, index)

    assert coverage["unmatched_player_rows"] == 0
    assert coverage["player_alias_hits"] == 1
    assert coverage["player_alias_ambiguous"] == 0
    assert rows[0].get("projection") is not None


def test_a_FULL_sim_name_joins_a_SHORT_board_name(tmp_path: Path) -> None:
    """The convention runs both directions, so the subset test must too."""
    _write_with_players(
        tmp_path, "epl", DATE, "Liverpool", "Chelsea", ["Emersonn Correia da Silva"]
    )
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    rows = [_player_row("epl", "Liverpool", "Chelsea", "Emersonn")]
    coverage = attach_soccer_projections(rows, index)

    assert coverage["unmatched_player_rows"] == 0
    assert coverage["player_alias_hits"] == 1


def test_an_AMBIGUOUS_surname_is_REFUSED_and_counted_not_guessed(tmp_path: Path) -> None:
    """Two players, one surname, same match. Picking either is a silently wrong
    projection on a row that still prices -- so it must refuse."""
    _write_with_players(
        tmp_path, "epl", DATE, "Liverpool", "Chelsea", ["Rodrigo Silva", "Bruno Silva"]
    )
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    rows = [_player_row("epl", "Liverpool", "Chelsea", "Silva")]
    coverage = attach_soccer_projections(rows, index)

    assert coverage["unmatched_player_rows"] == 1
    assert coverage["player_alias_hits"] == 0
    assert coverage["player_alias_ambiguous"] == 1
    assert rows[0].get("projection") is None


def test_a_SHORT_token_cannot_swallow_a_roster(tmp_path: Path) -> None:
    """A one-token subset under four characters is not distinctive enough to
    join on -- `da`, `de` and initials would otherwise match half a squad."""
    _write_with_players(tmp_path, "epl", DATE, "Liverpool", "Chelsea", ["Ali Hassan"])
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    rows = [_player_row("epl", "Liverpool", "Chelsea", "Ali")]
    coverage = attach_soccer_projections(rows, index)

    assert coverage["unmatched_player_rows"] == 1
    assert coverage["player_alias_hits"] == 0
    assert coverage["player_alias_ambiguous"] == 0


def test_an_EXACT_match_is_not_counted_as_an_alias(tmp_path: Path) -> None:
    """The fallback's yield has to be its OWN number, or it will be credited
    with joins the exact match was always making."""
    _write_with_players(tmp_path, "epl", DATE, "Liverpool", "Chelsea", ["Mohamed Salah"])
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    rows = [_player_row("epl", "Liverpool", "Chelsea", "Mohamed Salah")]
    coverage = attach_soccer_projections(rows, index)

    assert coverage["unmatched_player_rows"] == 0
    assert coverage["player_alias_hits"] == 0


# ---------------------------------------------------------------------------
# THE SILENT DROP. Measured 2026-09-03: `considered=140924 projected=25145`
# while the three named miss buckets summed to 9,329 -- so 106,450 rows (75.5%)
# fell through `if projection is None: continue` with NO counter at all. That is
# 92% of everything unprojected, against 6.1% for the name join above.
# ---------------------------------------------------------------------------


def test_a_matched_player_with_NO_VALUE_for_the_market_is_ATTRIBUTED(tmp_path: Path) -> None:
    """The fixture matched, the market is supported, the player was found -- the
    sim just published no value for this field. Previously invisible."""
    _write_with_players(tmp_path, "epl", DATE, "Liverpool", "Chelsea", ["Mohamed Salah"])
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    # The fixture writes `expected_shots` only, so shots-on-target has no value.
    rows = [
        _player_row(
            "epl", "Liverpool", "Chelsea", "Mohamed Salah", market="player_shots_on_target"
        )
    ]
    coverage = attach_soccer_projections(rows, index)

    assert rows[0].get("projection") is None
    assert coverage["unmatched_player_rows"] == 0, "the player MATCHED; this is not a name miss"
    assert coverage["unprojected_no_field"] == 1
    assert coverage["unprojected_by_market"].get("player_shots_on_target") == 1


def test_the_unprojected_bucket_stays_ZERO_when_everything_projects(tmp_path: Path) -> None:
    """A counter that is never zero is not a measurement."""
    _write_with_players(tmp_path, "epl", DATE, "Liverpool", "Chelsea", ["Mohamed Salah"])
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])

    rows = [_player_row("epl", "Liverpool", "Chelsea", "Mohamed Salah")]
    coverage = attach_soccer_projections(rows, index)

    assert rows[0].get("projection") is not None
    assert coverage["unprojected_no_field"] == 0
    assert coverage["unprojected_by_market"] == {}
