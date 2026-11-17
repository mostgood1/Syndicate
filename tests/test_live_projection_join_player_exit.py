"""The board's live PROPS join never prices a player out of his game (lane live-player-exit-gate, user 11-16).

Every live producer publishes `playersOut` per game; WNBA also stamps an out player's rows
`notPricedReason=player_out`; NBA publishes its exits on `nba_live_resim.json` while its props sit on
`nba_live_lens.json`, so the board passes that file's out players in. An out player's row is shown (his
Live/Actual columns) and never priced. A MODELLED exit (an engine-carried foul-out) stays priced.
"""

from __future__ import annotations

from syndicate.features.shared import board_enrichment as BE
from syndicate.features.shared.live_projection_join import (
    attach_live_projections,
    build_live_prop_index,
    players_out_of_snapshot,
)

OUT, IN = "Tyrese Maxey", "Joel Embiid"


def _prop(player: str, **extra) -> dict:
    return {"playerName": player, "market": "player_points", "line": 24.5, "liveProjection": 21.0,
            "modelProbOver": 0.4, "liveModelProbOver": 0.35, "actualSoFar": 11, "selection": "Over", **extra}


def _snapshot(players_out=None, props=None) -> dict:
    game = {"status": {"abstract": "Live", "detailed": "In Progress"},
            "liveProps": props if props is not None else [_prop(OUT), _prop(IN)]}
    if players_out is not None:
        game["playersOut"] = players_out
    return {"games": [game]}


def _grid() -> list[dict]:
    return [{"kind": "prop", "player_name": name, "market": "player_points", "line": 24.5, "side": "over",
             "price": -110, "game": {"state": "live"}} for name in (OUT, IN)]


def _out(modelled: bool = False) -> list[dict]:
    return [{"team": "PHI", "player": OUT, "reason": "injury", "key": True, "modelled": modelled}]


def test_an_out_player_is_shown_never_priced_and_his_teammate_still_prices():
    grid = _grid()
    coverage = attach_live_projections(grid, build_live_prop_index(_snapshot(_out())))
    out_row, in_row = grid
    assert out_row["projection"]["live_player_out"] is True and out_row["projection"]["live_display_only"] is True
    assert out_row["projection"]["live_display_prob_over"] is None
    assert out_row["projection"].get("edge_vs_market_pct") is None and not out_row["projection"].get("live_aware")
    assert out_row["projection"]["live_projected"] == 21.0  # his Live column stays
    assert in_row["projection"]["live_aware"] is True and "live_player_out" not in in_row["projection"]
    assert coverage["rows_live_display_only_player_out"] == 1


def test_off_ne_on_an_exit_list_without_him_prices_him():
    grid = _grid()
    attach_live_projections(grid, build_live_prop_index(_snapshot([])))
    assert all(row["projection"]["live_aware"] is True for row in grid)


def test_a_modelled_exit_stays_priced():
    grid = _grid()
    attach_live_projections(grid, build_live_prop_index(_snapshot(_out(modelled=True))))
    assert grid[0]["projection"]["live_aware"] is True and "live_player_out" not in grid[0]["projection"]


def test_a_row_the_producer_marked_player_out_is_refused():
    grid = _grid()
    snap = _snapshot(props=[_prop(OUT, notPricedReason="player_out", liveModelProbOver=None), _prop(IN)])
    index = build_live_prop_index(snap)
    attach_live_projections(grid, index)
    assert grid[0]["projection"]["live_player_out"] is True and index["rows_player_out"] == 1


def test_out_players_from_another_snapshot_are_honoured():
    grid = _grid()
    index = build_live_prop_index(_snapshot(), players_out=players_out_of_snapshot(_snapshot(_out())))
    attach_live_projections(grid, index)
    assert grid[0]["projection"]["live_player_out"] is True and grid[1]["projection"]["live_aware"] is True


def test_the_board_reads_nbas_exits_from_its_resim_file(monkeypatch):
    """Reachability: `_exit_players_out` is what the board passes to the join for NBA."""
    import syndicate.features.shared.refresh_state_store as rss

    reads: list[str] = []

    def read(path):
        reads.append(path.name)
        return _snapshot(_out())
    monkeypatch.setattr(rss, "read_json_file", read)
    assert BE._exit_players_out("nba") == {"tyrese maxey"} and reads == ["nba_live_resim.json"]
    reads.clear()
    assert BE._exit_players_out("wnba") == set() and reads == []  # its exits are on the snapshot the join reads
    assert BE._exit_players_out("cricket") == set()


def test_the_board_join_passes_nba_exits_through(monkeypatch):
    import syndicate.features.shared.refresh_state_store as rss

    monkeypatch.setattr(BE, "_live_prop_sports", lambda: frozenset({"nba"}))
    monkeypatch.setattr(rss, "read_json_file",
                        lambda path: _snapshot(_out()) if path.name == "nba_live_resim.json" else _snapshot())
    grid = _grid()
    coverage = BE.attach_live_projections_for_sport(grid, sport="nba", selected_date="2026-11-16")
    assert grid[0]["projection"]["live_player_out"] is True and coverage["rows_live_display_only_player_out"] == 1
    assert grid[1]["projection"]["live_aware"] is True
