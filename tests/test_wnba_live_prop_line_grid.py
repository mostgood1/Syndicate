"""WNBA live POINTS props are priced at the lines the LIVE board quotes, not only the pregame one.

`[2026-09-28, lane live-props-model-probability]`. The lens handed
`build_live_prop_rows` one pregame line per (player, market). Live board lines move
off it, so the prop join -- keyed on (player, market, LINE) -- matched 3-5 rows per
build against 147-196 live board props (refresh-worker 2026-09-27 20:50-21:26Z;
sample: jackie young assists board 6.5 vs lens 8.5). `grid_markets` prices every
half-point line near the live projection, for the market whose residual was MEASURED.

Driven through the REAL producer into the REAL index builder, because the join's key
is where the coverage was lost.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import wnba_live_prop_rows as rows_mod
from syndicate.features.shared.live_projection_join import build_live_prop_index
from syndicate.features.shared.wnba_live_prop_probability import live_prop_prob_over

_SIM = {"players": {"home": [{"player_name": "Paige Bueckers", "min_mean": 30.0, "pts_mean": 18.0,
                              "reb_mean": 4.0, "ast_mean": 5.0, "threes_mean": 2.0}]}}
_LIVE = [{"player": "Paige Bueckers", "team_tri": "DAL", "mp": "9",
          "pts": 6.0, "reb": 2.0, "ast": 1.0, "threes_made": 1.0}]
_LINES = {("paige bueckers", "points"): 17.5, ("paige bueckers", "rebounds"): 5.5}


def _snapshot(**kw):
    built = rows_mod.build_live_prop_rows(_LIVE, _SIM, game_minutes_remaining=25.0, lines=_LINES, **kw)
    return built, {"games": [{"state": "live", "liveProps": rows_mod.to_snapshot_live_props(built["rows"])}]}


def _points_keys(index):
    return sorted(line for (player, market, line) in index if market == "player_points")


def test_default_is_todays_behaviour():
    """No `grid_markets` -> exactly the one supplied line per market."""
    _, snap = _snapshot()
    idx = build_live_prop_index(snap)["index"]
    assert _points_keys(idx) == [17.5]


def test_a_live_line_off_the_pregame_line_is_indexed_with_a_probability():
    """THE DEFECT. The live board quotes 14.5 after the pregame 17.5; before, the
    index had no 14.5 key and the row could never be priced."""
    _, snap = _snapshot(grid_markets=("points",))
    idx = build_live_prop_index(snap)["index"]
    keys = _points_keys(idx)
    assert 14.5 in keys and 17.5 in keys
    hit = next(v for (p, m, line), v in idx.items() if m == "player_points" and line == 14.5)
    assert hit["live_prob_over"] is not None


def test_every_grid_line_is_priced_by_the_unchanged_rule():
    built, _ = _snapshot(grid_markets=("points",))
    pts = [r for r in built["rows"] if r["market"] == "points"]
    proj = pts[0]["liveProjectedStat"]
    for r in pts:
        expect = live_prop_prob_over(projected=proj, line=r["line"], minutes_remaining=r["minutes_remaining"])
        assert r["liveModelProbOver"] == expect["prob_over"]


def test_grid_is_half_points_above_what_is_banked_and_within_three_sigma():
    built, _ = _snapshot(grid_markets=("points",))
    pts = [r for r in built["rows"] if r["market"] == "points"]
    proj, sigma = pts[0]["liveProjectedStat"], pts[0]["residual_sigma"]
    grid = [r["line"] for r in pts if r["line"] != 17.5]
    assert grid and all(line % 1 == 0.5 for line in grid)
    assert all(line > 6.0 for line in grid)  # 6 points already banked
    assert all(abs(line - proj) <= 3 * sigma + 1.0 for line in grid)
    assert len(pts) <= rows_mod.GRID_MAX_LINES + 1
    assert built["grid_rows"] == len(pts) - 1


def test_an_unlisted_market_is_NOT_widened():
    """Rebounds' residual was never measured; it keeps its single supplied line."""
    _, snap = _snapshot(grid_markets=("points",))
    idx = build_live_prop_index(snap)["index"]
    assert sorted(line for (_, m, line) in idx if m == "player_rebounds") == [5.5]


def test_no_measured_sigma_falls_back_to_the_supplied_line():
    """No measured interval for this state -> no grid; the supplied line alone."""
    assert rows_mod._grid_lines(17.5, projected=19.0, current=6.0, minutes_remaining=None) == [17.5]
    assert rows_mod._grid_lines(17.5, projected=None, current=6.0, minutes_remaining=20.0) == [17.5]


def test_lens_grids_the_three_measured_markets_the_user_asked_for():
    import inspect
    from syndicate.features.wnba import live_lens
    src = inspect.getsource(live_lens)
    assert 'grid_markets=("points", "rebounds", "assists")' in src


def test_every_grid_row_carries_the_actual_so_far():
    """Raised by lane layer2-triad-alignment: a ladder where only the pregame-line
    row shows the banked actual and 40 grid rows show None reads as data, not as
    absence. Every fanned row must carry it."""
    _, snap = _snapshot(grid_markets=("points",))
    points = [p for p in snap["games"][0]["liveProps"] if p["prop"] == "player_points"]
    assert len(points) > 1
    assert all(p.get("actualSoFar") == 6.0 for p in points)


def test_snapshot_size_per_player_is_bounded():
    """The grid multiplies lens rows; a published artifact's size is a memory
    question on this platform. Bound it per player so a full slate is predictable:
    ~20 live players x 3-5 games stays well under a megabyte."""
    import json
    _, base = _snapshot()
    _, grid = _snapshot(grid_markets=("points",))
    added = len(json.dumps(grid)) - len(json.dumps(base))
    print(f"GRID_SNAPSHOT_BYTES_PER_PLAYER added={added}")
    assert added < 12_000


# ---- per-market residuals `[2026-09-28]`: rebounds/assists/threes stop borrowing points' ----

from syndicate.features.shared.wnba_live_prop_probability import (  # noqa: E402
    MEASURED_MARKETS,
    REASON_NO_MEASURED_MARKET,
    residual_sigma,
)


def test_each_market_prices_on_ITS_OWN_measured_sigma():
    """REACHABILITY (off != on). Before, every market read the points table, so a
    rebounds row at 15 min left carried sigma 5.3; its own measurement is ~2.5."""
    built, _ = _snapshot(grid_markets=("points", "rebounds"))
    by_market = {}
    for r in built["rows"]:
        if r.get("residual_sigma") is not None:
            by_market.setdefault(r["market"], set()).add(r["residual_sigma"])
    assert by_market["rebounds"] and by_market["points"]
    minutes = next(r["minutes_remaining"] for r in built["rows"] if r["market"] == "rebounds")
    assert by_market["rebounds"] == {round(residual_sigma(minutes, "rebounds"), 4)}
    assert residual_sigma(minutes, "rebounds") < residual_sigma(minutes, "points") / 1.8


def test_an_unmeasured_market_refuses_rather_than_borrowing():
    assert "blocks" not in MEASURED_MARKETS
    assert residual_sigma(15.0, "blocks") is None
    out = live_prop_prob_over(projected=2.0, line=1.5, minutes_remaining=15.0, market="blocks")
    assert out["prob_over"] is None and out["unavailable_reason"] == REASON_NO_MEASURED_MARKET


def test_each_grid_reaches_three_of_its_OWN_sigmas():
    built, _ = _snapshot(grid_markets=("points", "rebounds"))
    for market in ("points", "rebounds"):
        rows = [r for r in built["rows"] if r["market"] == market and r["line"] is not None]
        proj, sigma = rows[0]["liveProjectedStat"], rows[0]["residual_sigma"]
        supplied = _LINES[("paige bueckers", market)]
        grid = [r["line"] for r in rows if r["line"] != supplied]
        assert grid, market
        assert all(abs(line - proj) <= 3 * sigma + 1.0 for line in grid), market


def test_a_market_with_no_line_and_no_grid_adds_no_grid_rows():
    """`_grid_lines` falls back to `[supplied]`, which is `[None]` for a market with
    no pregame line -- that is not an added line and must not be counted as one."""
    assert rows_mod._grid_lines(None, projected=None, current=0.0, minutes_remaining=20.0) == [None]
    built = rows_mod.build_live_prop_rows(_LIVE, _SIM, game_minutes_remaining=25.0, lines={},
                                          grid_markets=("threes",))
    added = [r for r in built["rows"] if r["market"] == "threes" and r["line"] is not None]
    assert built["grid_rows"] == len(added)


def test_snapshot_size_per_player_three_markets_is_bounded():
    import json
    _, base = _snapshot()
    _, grid = _snapshot(grid_markets=("points", "rebounds", "assists"))
    added = len(json.dumps(grid)) - len(json.dumps(base))
    print(f"GRID_SNAPSHOT_BYTES_PER_PLAYER_3_MARKETS added={added}")
    assert added < 20_000
