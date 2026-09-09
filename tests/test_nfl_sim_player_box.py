"""Tests for the NFL card's PER-PLAYER sim projections.

The defect this closes was not a wrong number either. NFL's only "Sim" panel on
the box tab was two rows of team-level projected scoring -- measured on
production 2026-09-09 as chip `Sim`, 0 columns, 2 rows -- while MLB's box tab
carries a projected line per player and soccer's squad panels carry 8 columns
over 22-43 rows per side. Every NFL test passed throughout, because nothing
asserted what the Sim panel CONTAINED.

The assertions that matter here are the ones about CONFUSABILITY, not the ones
about a value:

  * `test_projections_are_never_merged_into_the_actuals_table` -- this platform
    shipped and backed out a surface that put a projected number where a real
    one belonged. A single combined table is that surface.
  * `test_anytime_td_renders_as_a_probability_not_a_count` -- the artifact's
    `anytime_td` is P(scores) in [0, 1]. The actuals column beside it is an
    integer count of touchdowns actually scored. 0.35 printed there, or rounded
    to 0, is a probability in a column a reader reads as a score.
  * `test_a_different_week_inside_the_artifact_is_refused` -- the filename
    encodes the week and the payload also stamps it. A file that disagrees with
    its own name renders last week's numbers under tonight's teams, which looks
    entirely plausible and is wrong in every cell.
  * `test_a_republished_artifact_is_picked_up_without_a_restart` -- the direct
    regression for `ncaaf/player_stats.py:68`, a bare `@lru_cache` that served a
    stale empty result until a deploy cleared it. This artifact is rebuilt a few
    hours before kickoff, so a non-invalidating cache would pin the pregame copy
    for the life of the dyno.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl import cards as nfl_cards  # noqa: E402


# Real rows, copied in shape and magnitude from
# `nfl_source/nfl_prop_projections_2026_wk1.json` (1,126 rows, 16 games,
# generated 2026-09-09T21:41:48Z).
_GAME_ID = "New England Patriots|Seattle Seahawks"


def _row(market: str, entity: str, team: str, value: float) -> dict:
    return {
        "game_id": _GAME_ID,
        "market": f"{market}::{entity.lower()}",
        "period": "full_game",
        "entity": entity,
        "sim_projection": value,
        "projected_value": value,
        "sim_source": "nfl_prior_season_fallback",
        "player_team": team,
    }


_ROWS = [
    _row("passing_yards", "Drake Maye", "NE", 257.6),
    _row("passing_tds", "Drake Maye", "NE", 1.75),
    _row("rushing_yards", "Drake Maye", "NE", 25.9),
    _row("anytime_td", "Drake Maye", "NE", 0.2423),
    _row("rushing_yards", "Rhamondre Stevenson", "NE", 40.4),
    _row("receptions", "Rhamondre Stevenson", "NE", 2.1),
    _row("receiving_yards", "Rhamondre Stevenson", "NE", 23.0),
    _row("anytime_td", "Rhamondre Stevenson", "NE", 0.4617),
    _row("passing_yards", "Sam Darnold", "SEA", 238.4),
    _row("anytime_td", "Sam Darnold", "SEA", 0.1042),
    _row("receptions", "Jaxon Smith-Njigba", "SEA", 6.6),
    _row("receiving_yards", "Jaxon Smith-Njigba", "SEA", 99.6),
    _row("anytime_td", "Jaxon Smith-Njigba", "SEA", 0.4488),
]


def _write(tmp_path: Path, *, season: int = 2026, week: int = 1, rows=None,
           payload_season=None, payload_week=None) -> Path:
    rows = _ROWS if rows is None else rows
    path = tmp_path / f"nfl_prop_projections_{season}_wk{week}.json"
    path.write_text(
        json.dumps(
            {
                "season": season if payload_season is None else payload_season,
                "week": week if payload_week is None else payload_week,
                "generated_at": "2026-09-09T21:41:48.863298+00:00",
                "sim_rows": rows,
                "row_count": len(rows),
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture(autouse=True)
def _clear_cache():
    nfl_cards._nfl_sim_player_projection_index_cached.cache_clear()
    yield
    nfl_cards._nfl_sim_player_projection_index_cached.cache_clear()


@pytest.fixture
def artifact(tmp_path, monkeypatch):
    """Point the module's path resolver at a controlled artifact.

    BOTH halves of the read are redirected, because the cache key and the read
    are deliberately taken from different places. `nfl_prop_projection_
    artifact_path` picks the winning root by parsing every candidate (470KB a
    go), so the warm path never calls it -- the cache key is a `stat()` of the
    artifact under each root in `nfl_source_roots()`. A fixture that patched
    only the resolver would leave the key reading the developer's real
    `data/nfl_source`, which is the class of test that passes on a laptop with
    a mirror and fails on a clean checkout.

    The roots lambda reads `state["path"]` lazily, so a test that reassigns it
    mid-test (a republish, a different payload) moves the key with it.
    """
    state = {"path": _write(tmp_path)}
    monkeypatch.setattr(nfl_cards, "nfl_prop_projection_artifact_path",
                        lambda season, week: state["path"])
    monkeypatch.setattr(nfl_cards, "nfl_source_roots",
                        lambda: [state["path"].parent])
    return state


def _card(**live_state) -> dict:
    game = {
        "gamePk": "2026_01_NE_SEA",
        "card_variant": "nfl_main",
        "away": {"abbr": "NE", "name": "New England Patriots"},
        "home": {"abbr": "SEA", "name": "Seattle Seahawks"},
        "nfl_card": {
            "scoreboard": {"away_points": 21.8, "home_points": 22.1,
                           "source_label": "SmartSim 2.0"}
        },
    }
    if live_state:
        game["live_state"] = dict(live_state)
    return game


def _sections(game: dict, *, season: int = 2026, week: int = 1) -> list[dict]:
    return nfl_cards._nfl_sim_player_box_sections(game, season=season, week=week)


# --------------------------------------------------------------------------
# The panels themselves
# --------------------------------------------------------------------------


def test_one_table_per_side_with_the_players_that_side_actually_has(artifact):
    away, home = _sections(_card())
    assert away["title"] == "NE sim player projections"
    assert home["title"] == "SEA sim player projections"
    assert [r[0] for r in away["table_rows"]] == ["Drake Maye", "Rhamondre Stevenson"]
    assert [r[0] for r in home["table_rows"]] == ["Sam Darnold", "Jaxon Smith-Njigba"]


def test_the_team_level_sim_box_is_kept_beside_the_player_panels(artifact):
    """Adding player detail must not delete the team projection."""
    titles = [s["title"] for s in nfl_cards._nfl_box_sections(_card(), season=2026, week=1)]
    assert titles == [
        "Live / final box",
        "Sim box",
        "Player box",
        "NE sim player projections",
        "SEA sim player projections",
    ]


def test_columns_are_only_the_stats_this_side_actually_carries(artifact):
    """A column of dashes claims a stat was projected at nothing. It was not."""
    away, home = _sections(_card())
    # NE has a passer, so Pass yds/Pass TD are real columns for that side.
    assert away["columns"] == [
        "Player", "Pass yds", "Pass TD", "Rush yds", "Rec", "Rec yds", "Anytime TD%"
    ]
    # SEA's fixture has passing yards but NO passing TDs and no rushing, so
    # neither column is padded in.
    assert home["columns"] == ["Player", "Pass yds", "Rec", "Rec yds", "Anytime TD%"]


def test_a_market_a_player_has_no_line_in_is_a_dash_not_a_zero(artifact):
    away, _ = _sections(_card())
    maye = away["table_rows"][0]
    # Drake Maye has no receptions/receiving line at all.
    assert maye[4] == "—" and maye[5] == "—"
    assert "0" not in {maye[4], maye[5]}


def test_players_rank_by_projected_total_yards(artifact):
    """Same ordering rule as the actuals panel, so the two read together.

    Passing yardage counts, exactly as it does in `_nfl_player_box_section`'s
    `total_yards` sort -- so the quarterback leads both panels and a reader can
    scan them against each other line for line.
    """
    _, home = _sections(_card())
    assert [r[0] for r in home["table_rows"]] == ["Sam Darnold", "Jaxon Smith-Njigba"]


def test_a_side_with_no_projected_players_says_so_rather_than_vanishing(artifact, tmp_path):
    artifact["path"] = _write(tmp_path, rows=[r for r in _ROWS if r["player_team"] == "SEA"])
    away, home = _sections(_card())
    assert "columns" not in away and away["rows"] == []
    assert "No player projections were published for New England Patriots" in away["body"]
    assert home["table_rows"]


def test_sides_resolve_through_the_alias_map_not_by_tri_code(artifact, tmp_path):
    """nflverse writes the Rams `LA`; the card's branding writes `LAR`.

    That exact gap has already cost this module twice. A tri-code comparison
    would drop every Rams player into the unassigned bucket.
    """
    rows = [
        _row("receiving_yards", "Puka Nacua", "LA", 88.0),
        _row("receiving_yards", "Ricky Pearsall", "SF", 51.0),
    ]
    for row in rows:
        row["game_id"] = "San Francisco 49ers|Los Angeles Rams"
    artifact["path"] = _write(tmp_path, rows=rows)
    game = {
        "away": {"abbr": "SF", "name": "San Francisco 49ers"},
        "home": {"abbr": "LAR", "name": "Los Angeles Rams"},
    }
    away, home = _sections(game)
    assert [r[0] for r in away["table_rows"]] == ["Ricky Pearsall"]
    assert [r[0] for r in home["table_rows"]] == ["Puka Nacua"]
    assert "matches neither side" not in away["body"]


def test_a_player_on_neither_side_is_counted_not_guessed_onto_one(artifact, tmp_path):
    rows = list(_ROWS) + [_row("receiving_yards", "Nobody Atall", "ZZZ", 10.0)]
    artifact["path"] = _write(tmp_path, rows=rows)
    away, home = _sections(_card())
    assert "1 projected player(s)" in away["body"]
    assert "Nobody Atall" not in json.dumps(away) + json.dumps(home)


# --------------------------------------------------------------------------
# Projections must never be mistakable for actuals
# --------------------------------------------------------------------------


def test_projections_are_never_merged_into_the_actuals_table(artifact):
    game = _card(final=True, in_progress=False)
    game["live_player_box"] = [
        {"player_name": "Drake Maye", "team_abbr": "NE", "pass_yards": 103,
         "pass_td": 1, "rush_yards": 8, "rec_yards": 0, "td_scored": 0,
         "total_yards": 111},
    ]
    sections = nfl_cards._nfl_box_sections(game, season=2026, week=1)
    player_box = [s for s in sections if s["title"] == "Player box"][0]
    projections = [s for s in sections if "sim player projections" in s["title"]]
    assert player_box["kind"] == "actual"
    assert projections and all(s["kind"] == "projection" for s in projections)
    assert all(s["title"] != "Player box" for s in projections)
    # The real 103 lives in the actuals table and NOWHERE in a projection one.
    assert ["Drake Maye", "NE", "103", "1", "8", "0", "0"] in player_box["table_rows"]
    assert player_box["chip"] == "Final"
    # And the projected 258 lives only in the projection table.
    assert any("258" in cell for row in projections[0]["table_rows"] for cell in row)
    assert not any("258" in cell for row in player_box["table_rows"] for cell in row)


def test_the_chip_stays_sim_in_every_game_state(artifact):
    """Soccer's squad panel derived its chip from live-state and put a `Live`
    label on a simulated number. A projection is a projection all game."""
    for game in (
        _card(),
        _card(in_progress=False, final=False),
        _card(in_progress=True, final=False, period=2),
        _card(final=True, in_progress=False),
    ):
        for section in _sections(game):
            assert section["chip"] == "Sim", section["title"]
            assert section["kind"] == "projection"


def test_anytime_td_renders_as_a_probability_not_a_count(artifact):
    away, _ = _sections(_card())
    stevenson = away["table_rows"][1]
    assert stevenson[-1] == "46.2%"
    assert away["columns"][-1] == "Anytime TD%"
    assert "PROBABILITY, not a count" in away["body"]


def test_each_of_the_four_states_says_which_one_it_is(artifact):
    bodies = {
        "no_reading": _sections(_card())[0]["body"],
        "pregame": _sections(_card(in_progress=False, final=False))[0]["body"],
        "live": _sections(_card(in_progress=True, final=False, period=2))[0]["body"],
        "final": _sections(_card(final=True, in_progress=False))[0]["body"],
    }
    assert "has not been read" in bodies["no_reading"]
    assert "has not kicked off" in bodies["pregame"]
    assert "NOT what has happened" in bodies["live"]
    assert "from before kickoff" in bodies["final"]
    assert len(set(bodies.values())) == 4


# --------------------------------------------------------------------------
# The join, and the refusals
# --------------------------------------------------------------------------


def test_a_different_week_inside_the_artifact_is_refused(artifact, tmp_path):
    artifact["path"] = _write(tmp_path, payload_week=18)
    sections = _sections(_card())
    assert len(sections) == 1
    assert sections[0]["chip"] == "Sim"
    assert "week 18, not season 2026 week 1" in sections[0]["body"]
    assert "table_rows" not in sections[0]


def test_a_different_season_inside_the_artifact_is_refused(artifact, tmp_path):
    artifact["path"] = _write(tmp_path, payload_season=2025)
    sections = _sections(_card())
    assert "season 2025" in sections[0]["body"]
    assert "REFUSED" in sections[0]["body"]


def test_an_absent_artifact_names_what_is_missing(artifact, tmp_path):
    artifact["path"] = tmp_path / "gone" / "nfl_prop_projections_2026_wk1.json"
    sections = _sections(_card())
    assert len(sections) == 1
    assert "No prop-projection artifact has been published" in sections[0]["body"]
    assert "nfl_prop_projections_2026_wk1.json" in sections[0]["body"]
    assert "Nothing is being substituted" in sections[0]["body"]


def test_an_unstamped_artifact_is_refused_rather_than_assumed_current(artifact, tmp_path):
    path = tmp_path / "nfl_prop_projections_2026_wk1.json"
    path.write_text(json.dumps({"sim_rows": _ROWS}), encoding="utf-8")
    artifact["path"] = path
    assert "does not carry the `season`/`week` fields" in _sections(_card())[0]["body"]


def test_a_game_the_artifact_has_no_rows_for_is_said_not_blank(artifact):
    game = {
        "away": {"abbr": "DAL", "name": "Dallas Cowboys"},
        "home": {"abbr": "NYG", "name": "New York Giants"},
    }
    sections = _sections(game)
    assert len(sections) == 1
    assert "carries no player rows for Dallas Cowboys @ New York Giants" in sections[0]["body"]


def test_a_republished_artifact_is_picked_up_without_a_restart(artifact, tmp_path):
    """`ncaaf/player_stats.py:68` is a bare lru_cache and served a stale empty
    result until a deploy cleared it. The cache key here carries the artifact's
    mtime, so a republish -- which happens ~3h before kickoff -- is visible on
    the next request."""
    empty = tmp_path / "nfl_prop_projections_2026_wk1.json"
    empty.write_text(
        json.dumps({"season": 2026, "week": 1, "sim_rows": [], "row_count": 0}),
        encoding="utf-8",
    )
    artifact["path"] = empty
    assert "carries no player rows" in _sections(_card())[0]["body"]

    # Same PATH, new content and a new mtime -- exactly what the refresh job does.
    import os
    import time

    empty.write_text(
        json.dumps({"season": 2026, "week": 1, "sim_rows": _ROWS, "row_count": len(_ROWS)}),
        encoding="utf-8",
    )
    stamp = time.time() + 5
    os.utime(empty, (stamp, stamp))

    away, home = _sections(_card())
    assert away["table_rows"] and home["table_rows"]


def test_an_unreadable_artifact_never_costs_the_board(artifact, tmp_path):
    path = tmp_path / "nfl_prop_projections_2026_wk1.json"
    path.write_text("{not json", encoding="utf-8")
    artifact["path"] = path
    sections = _sections(_card())
    assert "could not be read" in sections[0]["body"]
    # And the whole board still stamps.
    games = [_card()]
    assert nfl_cards.attach_nfl_box_sections(games, 2026, 1) == 1


# --------------------------------------------------------------------------
# The cache key is cheap AND strictly stronger than a single-file mtime
# --------------------------------------------------------------------------


def test_a_whole_board_parses_the_artifact_once_not_once_per_card(artifact, monkeypatch):
    """`attach_nfl_box_sections` runs over every card on the board.

    The resolver it used to call on the warm path (`nfl_prop_projection_
    artifact_path`) decides which root wins by parsing the WHOLE 470KB
    artifact per candidate root. Measured on the real 2026 week-1 file over
    four roots: 60.7ms for a 16-game slate against 1.88ms for the `stat()`
    key that replaced it. Web is the display-only service; that parse belongs
    behind the cache, not on every card.

    Asserted as a CALL COUNT rather than a duration -- a timing assertion on a
    shared CI box measures the box, and would go green on a machine that is
    merely fast while the per-card parse is still there.
    """
    calls = {"n": 0}
    real = artifact["path"]

    def _counting(season, week):
        calls["n"] += 1
        return real

    monkeypatch.setattr(nfl_cards, "nfl_prop_projection_artifact_path", _counting)
    games = [_card() for _ in range(16)]
    assert nfl_cards.attach_nfl_box_sections(games, 2026, 1) == 16
    assert calls["n"] == 1, f"the resolver ran {calls['n']}x for 16 cards, not once"
    # And the panels actually rendered off that single read.
    assert games[0]["shared_box_sections"][-1]["table_rows"]


def test_an_artifact_appearing_on_another_root_invalidates(tmp_path, monkeypatch):
    """The case a single-path mtime key CANNOT see, and the one that matters.

    The mounted disk is searched ahead of the ephemeral checkout. When the
    checkout's copy is being served and the real one lands on the disk, the
    winning path CHANGES -- so a key that stats only the path it resolved last
    time is keyed on a file whose relevance has just ended. Keying on every
    candidate root makes the appearance itself the invalidation.
    """
    disk = tmp_path / "disk"
    checkout = tmp_path / "checkout"
    disk.mkdir()
    checkout.mkdir()
    _write(checkout, rows=[])
    state = {"path": checkout / "nfl_prop_projections_2026_wk1.json"}

    monkeypatch.setattr(nfl_cards, "nfl_prop_projection_artifact_path",
                        lambda season, week: state["path"])
    monkeypatch.setattr(nfl_cards, "nfl_source_roots", lambda: [disk, checkout])

    assert "carries no player rows" in _sections(_card())[0]["body"]

    # The real capture lands on the disk root and wins. Nothing restarts.
    _write(disk)
    state["path"] = disk / "nfl_prop_projections_2026_wk1.json"
    away, home = _sections(_card())
    assert away["table_rows"] and home["table_rows"]
