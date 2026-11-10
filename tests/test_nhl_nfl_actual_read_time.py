"""Read-time refresh of the Actual on live NHL / NFL props (lane nhl-nfl-actual-read-time, todo #769 (c)).

The Layer 2 build stamps a live NHL/NFL prop's Actual once per build; the in-play overlay's rows are refreshed far
more often, and both sit in one served payload. Measured 2026-11-10 at NFL halftime (box frozen): overlay rows
matched the ESPN box 40 of 40, board-build rows were behind on 14 of 28, and Josh Allen's passing yards read 70 on
one row and 122 on another in the same response. These tests pin that web now re-reads the box the live tick
published, keyed by the build join's own lookup, and writes the Actual and nothing else.

Fixtures are the RECORDED payloads `test_live_player_actuals` uses: NHL PHI @ NYR 2025020549 and NFL NE @ SEA
401872656 (Drake Maye: 178 passing yards, 3 interceptions)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import syndicate.blueprints.intelligence as bp
from syndicate.features.shared import live_player_actuals as A
from tests.test_live_player_actuals import _nfl_snapshot, _nhl_snapshot

TEAMS = {"nhl": ("Philadelphia Flyers", "New York Rangers"), "nfl": ("New England Patriots", "Seattle Seahawks")}


def _served(player, market, *, sport="nhl", line=0.5, actual=None, segment="full", **overrides) -> dict:
    """A served `top_opportunities` row, shaped as the 2026-11-10 board served it (keys the refresh reads)."""
    away, home = TEAMS[sport]
    row = {"sport": sport, "sport_slug": sport, "is_live": True, "candidate_type": "prop", "kind": "prop",
           "player_name": player, "entity": player, "market": market, "line": line, "away_team": away,
           "home_team": home, "segment": segment, "game_date": "2026-11-09", "actual": actual,
           "live_projection": None, "model_edge_pct": None, "edge": 3.1, "ev_pct": 3.1,
           "source": "layer2_shortlist"}
    row.update(overrides)
    return row


class _Snapshots:
    def __init__(self, by_name):
        self.by_name = by_name
        self.reads: dict[str, int] = {}

    def read(self, path):
        name = Path(path).name
        self.reads[name] = self.reads.get(name, 0) + 1
        return self.by_name.get(name)


@pytest.fixture
def snapshots(monkeypatch):
    """Both sports' live snapshots as web reads them (keyvalue-aware `read_json_file`); index cache cleared both sides."""
    A._NHL_ROSTER_NAMES.clear()
    state = _Snapshots({"nhl_live_lens.json": _nhl_snapshot(), "nfl_live_resim.json": _nfl_snapshot(monkeypatch)})
    monkeypatch.setattr(bp, "read_json_file", state.read)
    bp._LIVE_ACTUAL_INDEX_CACHE.clear()
    yield state
    bp._LIVE_ACTUAL_INDEX_CACHE.clear()
    A._NHL_ROSTER_NAMES.clear()


def test_a_board_build_row_behind_the_box_reads_the_current_count(snapshots, capsys):
    """The 11-10 defect: one player/market at two values in one payload. After the refresh, one value: the box's."""
    lagging = _served("Drake Maye", "player_pass_yds", sport="nfl", line=210.5, actual=70.0)
    overlay = _served("Drake Maye", "player_pass_yds", sport="nfl", line=200.5, actual=178.0,
                      source="layer2_inplay_overlay")
    nhl_blank = _served("Artemi Panarin", "SOG", line=3.5, actual=None)
    counts = bp._refresh_live_player_actual_columns({"top_opportunities": [lagging, overlay, nhl_blank]})
    assert lagging["actual"] == overlay["actual"] == 178.0
    assert nhl_blank["actual"] == 7.0
    assert counts["nfl"]["considered"] == 2 and counts["nfl"]["matched"] == 2 and counts["nfl"]["refreshed"] == 1
    assert counts["nhl"]["refreshed"] == 1
    # The line the verification reads back from the web log.
    assert "LIVE_ACTUALS_REFRESHED_FROM_BOX sport=nfl snapshot=nfl_live_resim.json considered=2 matched=2 refreshed=1" in capsys.readouterr().out


NHL_CASES = [
    ("Artemi Panarin", "GOALS", None), ("Artemi Panarin", "SOG", None), ("Mika Zibanejad", "POINTS", None),
    ("Igor Shesterkin", "SAVES", None), ("Vincent Trocheck", "player_goal_scorer_anytime", None),
    ("Connor McDavid", "GOALS", None),     # not dressed: refused, never a 0
    ("Artemi Panarin", "SAVES", None),     # a skater has no saves
    ("Artemi Panarin", "GOALS", "p1"),     # a period prop: the box is whole-game
    ("Artemi Panarin", "player_hits", None),  # a market the grader cannot settle
]
NFL_CASES = [
    ("Drake Maye", "Interceptions", None), ("Drake Maye", "Passing Attempts", None),
    ("Drake Maye", "player_pass_yds", None), ("Rhamondre Stevenson", "Receptions", None),
    ("Rhamondre Stevenson", "Anytime TD", None), ("Nobody Here", "Receptions", None),
    ("Drake Maye", "player_pass_yds", "1h"),
]


@pytest.mark.parametrize("sport,cases", [("nhl", NHL_CASES), ("nfl", NFL_CASES)])
def test_it_attaches_exactly_what_the_build_join_attaches(snapshots, sport, cases):
    """Same index, same lookup: whatever the build's join writes (or refuses), the read-time refresh writes (or refuses)."""
    away, home = TEAMS[sport]
    snapshot = snapshots.by_name["nhl_live_lens.json" if sport == "nhl" else "nfl_live_resim.json"]
    grid = []
    for player, market, segment in cases:
        row = {"kind": "prop", "game": {"state": "live"}, "player_name": player, "market": market, "line": 0.5,
               "away_team": away, "home_team": home, "projection": {}}
        if segment:
            row["segment"] = segment
        grid.append(row)
    A.attach_live_player_actuals(grid, snapshot, sport=sport)
    served = [_served(player, market, sport=sport, segment=segment or "full") for player, market, segment in cases]
    bp._refresh_live_player_actual_columns({"ranked_all": served})
    built = [row["projection"].get("actual_so_far") for row in grid]
    assert built == [row["actual"] for row in served]
    assert any(value is not None for value in built) and any(value is None for value in built)


def test_only_the_actual_changes(snapshots):
    row = _served("Artemi Panarin", "SOG", line=3.5, actual=4.0)
    before = dict(row)
    bp._refresh_live_player_actual_columns({"ranked_all": [row]})
    changed = {key for key in set(before) | set(row) if before.get(key) != row.get(key)}
    assert changed == {"actual"} and row["actual"] == 7.0
    assert row["live_projection"] is None and row["model_edge_pct"] is None and "live_total" not in row


def test_a_real_zero_is_written_and_a_refused_row_keeps_what_the_build_gave_it(snapshots):
    zero = _served("Sam Carrick", "GOALS", actual=1.0)             # the box says 0: a fact, written
    absent = _served("Connor McDavid", "GOALS", actual=1.0)        # not in the box: the build's value stays
    counts = bp._refresh_live_player_actual_columns({"ranked_all": [zero, absent]})
    assert zero["actual"] == 0.0 and absent["actual"] == 1.0
    assert counts["nhl"]["refused"] == {"miss_player_absent": 1}


def test_a_stale_block_refreshes_nothing(snapshots):
    old = (datetime.now(timezone.utc) - timedelta(seconds=A.MAX_BLOCK_AGE_SECONDS + 60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    snapshots.by_name["nhl_live_lens.json"]["games"][0][A.BLOCK_KEY]["asOf"] = old
    row = _served("Artemi Panarin", "SOG", line=3.5, actual=4.0)
    counts = bp._refresh_live_player_actual_columns({"ranked_all": [row]})
    assert row["actual"] == 4.0 and counts["nhl"]["refused"] == {"miss_stale_block": 1}


def test_no_published_snapshot_is_counted_and_touches_nothing(snapshots):
    snapshots.by_name.clear()
    row = _served("Artemi Panarin", "SOG", actual=4.0)
    counts = bp._refresh_live_player_actual_columns({"ranked_all": [row]})
    assert row["actual"] == 4.0 and counts["nhl"]["no_snapshot"] == 1 and counts["nhl"]["matched"] == 0


@pytest.mark.parametrize("row", [
    _served("Artemi Panarin", "SOG", is_live=False),                          # pregame rows keep the pregame tier
    _served("Artemi Panarin", "SOG", sport="nhl", sport_slug="nba"),         # NBA's own refresh owns its rows
    _served(None, "totals", candidate_type="game", kind="game", line=6.5),  # game lines are priced, not refreshed
])
def test_rows_outside_scope_are_untouched(snapshots, row):
    before = dict(row)
    bp._refresh_live_player_actual_columns({"ranked_all": [row]})
    assert row == before


def test_a_sport_admitted_to_the_priced_join_leaves_this_refresh(snapshots, monkeypatch):
    """The build stops routing a priced sport to the display-only join; web's refresh follows the same switch."""
    from syndicate.features.shared import board_enrichment

    assert set(bp._live_actual_refresh_snapshots()) == {"nhl", "nfl"}
    monkeypatch.setattr(board_enrichment, "_live_prop_sports", lambda: frozenset({"mlb", "nhl"}))
    assert bp._live_actual_refresh_snapshots() == {"nfl": "nfl_live_resim.json"}
    row = _served("Artemi Panarin", "SOG", actual=4.0)
    bp._refresh_live_player_actual_columns({"ranked_all": [row]})
    assert row["actual"] == 4.0


def test_one_snapshot_read_per_sport_per_request_and_none_without_a_live_row(snapshots):
    row = _served("Artemi Panarin", "SOG", line=3.5)
    payload = {"ranked_all": [row, _served("Mika Zibanejad", "POINTS")], "top_opportunities": [row],
               "by_sport": {"nhl": [row], "nfl": [_served("Drake Maye", "Interceptions", sport="nfl")]}}
    counts = bp._refresh_live_player_actual_columns(payload)
    assert snapshots.reads == {"nhl_live_lens.json": 1, "nfl_live_resim.json": 1}
    assert counts["nhl"]["considered"] == 2 and counts["nfl"]["considered"] == 1
    bp._LIVE_ACTUAL_INDEX_CACHE.clear()
    snapshots.reads.clear()
    nba = _served("Alex Sarr", "player_rebounds")
    nba.update(sport="nba", sport_slug="nba")
    assert bp._refresh_live_player_actual_columns({"ranked_all": [nba]}) == {}
    assert snapshots.reads == {}


def test_the_index_is_reused_for_a_few_seconds_then_reread(snapshots):
    bp._live_actual_index("nhl", "nhl_live_lens.json", now=1000.0)
    bp._live_actual_index("nhl", "nhl_live_lens.json", now=1000.0 + bp._LENS_PROP_INDEX_TTL_SECONDS - 1)
    assert snapshots.reads == {"nhl_live_lens.json": 1}
    bp._live_actual_index("nhl", "nhl_live_lens.json", now=1000.0 + bp._LENS_PROP_INDEX_TTL_SECONDS + 1)
    assert snapshots.reads == {"nhl_live_lens.json": 2}


def test_the_serve_path_runs_it_and_a_failure_never_breaks_the_board(snapshots, monkeypatch):
    """off != on through the route's own hook, then a broken read must leave the build's value and not raise."""
    row = _served("Artemi Panarin", "SOG", line=3.5, actual=4.0)
    bp._refresh_live_columns_from_artifact({"ranked_all": [row]})
    assert row["actual"] == 7.0

    def boom(*_a, **_k):
        raise RuntimeError("keyvalue down")
    monkeypatch.setattr(bp, "_live_actual_index", boom)
    row = _served("Artemi Panarin", "SOG", line=3.5, actual=4.0)
    bp._refresh_live_columns_from_artifact({"ranked_all": [row]})  # must not raise
    assert row["actual"] == 4.0
