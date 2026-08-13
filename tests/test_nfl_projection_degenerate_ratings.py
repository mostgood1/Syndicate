"""NFL projections: drop league-constant rows, prefer the newest generation.

THE DEFECT, measured on production 2026-08-13. The Layer 1 board served

    margin_mean 0.96   total_mean 44.38   home_win_rate 0.5267

on ALL 16 preseason games across FOUR dates (08-13/14/15/16), while the cards
surface -- reading a file of the SAME NAME -- served 16 distinct totals. It was
never a modelling failure:

  * Running the real generator with empty `prior_season_plays` reproduces
    0.960 / 44.380 / 0.5267 exactly, on all four weeks.
  * `data/nfl_source/tracking/` (where the nflverse pbp lives) is GITIGNORED,
    so a generator run whose root resolved to the repo checkout has no
    play-by-play, rates every team `neutral_no_data`, and writes a file of
    identical rows.
  * `load_nfl_game_projections` deduped candidate files by NAME across source
    roots, so only the first root's copy was ever opened.

The tell that separates "no data" from "a model with no skill": the four
preseason weeks carry different shrinkage factors (0.92/0.80/0.55/0.92), and
0.0 shrunk by any of them is still 0.0 -- so a degenerate input collapses every
WEEK onto one number too, which a merely-unskilled model would not do.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.nfl_game_projections import (
    NflGameProjectionIndex,
    _is_degenerate_rating_source,
    attach_nfl_game_projections,
)


PREFIX = "nflverse_pbp_epa_prior_season_shrunk"


# --------------------------------------------------------------------------
# what counts as degenerate
# --------------------------------------------------------------------------


def test_both_sides_neutral_is_degenerate():
    assert _is_degenerate_rating_source(f"{PREFIX}[neutral_no_data/neutral_no_data]") is True


@pytest.mark.parametrize(
    "source",
    [
        f"{PREFIX}[prior_season_fallback/prior_season_fallback]",
        # Production carries exactly these two: WSH and LAR do not resolve to
        # an nflverse abbreviation. ONE neutral side still leaves the other
        # side's real rating differentiating the matchup, so these must NOT be
        # dropped -- doing so would blank two real games.
        f"{PREFIX}[neutral_no_data/prior_season_fallback]",
        f"{PREFIX}[prior_season_fallback/neutral_no_data]",
        f"{PREFIX}[current_season_rolling/prior_season_fallback]",
    ],
)
def test_one_or_zero_neutral_sides_is_not_degenerate(source):
    assert _is_degenerate_rating_source(source) is False


@pytest.mark.parametrize("source", ["", None, "nflverse_pbp_epa_rolling", "weird[", "]backwards["])
def test_unparseable_rating_source_is_not_treated_as_degenerate(source):
    """Unknown must not default to the destructive branch. A row whose
    provenance cannot be read is kept, not silently deleted -- dropping it
    would remove a real projection on a formatting change."""
    assert _is_degenerate_rating_source(source) is False


# --------------------------------------------------------------------------
# the index
# --------------------------------------------------------------------------


def _row(gid, home, away, *, total, margin, hwr, generated_at, source, profile="nfl_preseason_v1"):
    return {
        "game_id": gid,
        "home_team": home,
        "away_team": away,
        "total_mean": str(total),
        "margin_mean": str(margin),
        "home_win_rate": str(hwr),
        "margin_stdev": "22.0",
        "total_stdev": "16.0",
        "generated_at": generated_at,
        "profile_name": profile,
        "rating_source": source,
    }


DEGENERATE = _row("g1", "CIN", "DET", total=44.38, margin=0.96, hwr=0.5267,
                  generated_at="2026-08-13T21:00:18+00:00",
                  source=f"{PREFIX}[neutral_no_data/neutral_no_data]")
HEALTHY = _row("g1", "CIN", "DET", total=46.275, margin=-0.035, hwr=0.53,
               generated_at="2026-08-13T21:00:18+00:00",
               source=f"{PREFIX}[prior_season_fallback/prior_season_fallback]")


def _index_from(rows):
    """Exercise the same resolution the loader applies, without a filesystem."""
    index = NflGameProjectionIndex()
    for row in rows:
        if _is_degenerate_rating_source(row.get("rating_source")):
            index.rows_dropped_degenerate += 1
            continue
        entry = {
            "margin_mean": float(row["margin_mean"]),
            "total_mean": float(row["total_mean"]),
            "margin_stdev": float(row["margin_stdev"]),
            "total_stdev": float(row["total_stdev"]),
            "home_win_rate": float(row["home_win_rate"]),
            "generated_at": row["generated_at"],
            "profile": row["profile_name"],
            "rating_source": row["rating_source"],
        }
        key = ("2026-08-13", "cin", "det")
        existing = index.by_date_teams.get(key)
        if existing is not None:
            if str(entry["generated_at"]) <= str(existing.get("generated_at") or ""):
                index.rows_superseded_by_newer += 1
                continue
            index.rows_superseded_by_newer += 1
        index.by_date_teams[key] = entry
    index.games = len(index.by_date_teams)
    return index


def test_degenerate_row_is_dropped_and_counted():
    index = _index_from([DEGENERATE])
    assert index.by_date_teams == {}
    assert index.rows_dropped_degenerate == 1


def test_healthy_row_survives_beside_a_degenerate_one_regardless_of_order():
    for rows in ([DEGENERATE, HEALTHY], [HEALTHY, DEGENERATE]):
        index = _index_from(rows)
        entry = index.by_date_teams[("2026-08-13", "cin", "det")]
        assert entry["total_mean"] == 46.275, "the healthy copy must win in either read order"
        assert index.rows_dropped_degenerate == 1


def test_newest_generation_wins_between_two_healthy_copies():
    older = dict(HEALTHY, generated_at="2026-08-12T21:00:00+00:00", total_mean="41.0")
    newer = dict(HEALTHY, generated_at="2026-08-13T21:00:18+00:00", total_mean="46.275")
    for rows in ([older, newer], [newer, older]):
        index = _index_from(rows)
        assert index.by_date_teams[("2026-08-13", "cin", "det")]["total_mean"] == 46.275


def test_a_row_without_a_timestamp_never_displaces_one_that_has_it():
    stamped = dict(HEALTHY, generated_at="2026-08-13T21:00:18+00:00", total_mean="46.275")
    unstamped = dict(HEALTHY, generated_at="", total_mean="99.0")
    index = _index_from([stamped, unstamped])
    assert index.by_date_teams[("2026-08-13", "cin", "det")]["total_mean"] == 46.275


# --------------------------------------------------------------------------
# the observable the user actually reported
# --------------------------------------------------------------------------


def _grid_row(home, away, market="totals", line=37.5):
    return {
        "kind": "game", "segment": "full", "market": market, "line": line,
        "home_team": home, "away_team": away, "commence_time": "2026-08-13T23:00:00Z",
    }


def test_a_fully_degenerate_slate_yields_no_projections_rather_than_one_constant():
    """`#377`'s standing decision, enforced: a number that looks authoritative
    and means nothing is worse on a betting board than a blank cell, because
    it is only detectable by comparing rows."""
    index = NflGameProjectionIndex()
    index.rows_dropped_degenerate = 16
    grid = [_grid_row("Cincinnati Bengals", "Detroit Lions"), _grid_row("Pittsburgh Steelers", "Green Bay Packers")]
    coverage = attach_nfl_game_projections(grid, index)
    assert coverage["rows_with_projection"] == 0
    assert all("projection" not in row for row in grid)
    # ...and it says WHY, so an empty column is attributable.
    assert coverage["rows_dropped_degenerate"] == 16


def test_coverage_distinguishes_no_model_from_dropped_constants():
    empty = attach_nfl_game_projections([_grid_row("Cincinnati Bengals", "Detroit Lions")], NflGameProjectionIndex())
    assert empty["rows_with_projection"] == 0
    assert empty["rows_dropped_degenerate"] == 0, "no model and dropped-constants must not report the same thing"
