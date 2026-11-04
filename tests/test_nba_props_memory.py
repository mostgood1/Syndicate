"""The props-edges short-key fallback must not multiply odds rows (lane nba-props-oom).

Fleet 2026-11-04: the fallback merged an odds-sized lookup back onto the odds by
short_key, so every player's lines multiplied by themselves -- 60,790 odds rows
became 5,040,004 merged rows (7,740 MB) and refresh_nba_oddsapi_props.py ran at
6.5-7.7 GB. The lookup is now built from the predictions. These tests pin:
the merged frame stays odds-sized, the fallback still fires, and the output is
the one the old code produced after its drop_duplicates.
"""
from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import basketball_props_edges as edges

_MARKETS = ("player_points", "player_rebounds", "player_assists", "player_threes")
_BOOKS = ("draftkings", "fanduel", "betmgm")
_POINTS = (4.5, 9.5, 14.5, 19.5, 24.5)


def _write_slate(tmp_path: Path) -> tuple[Path, Path, int]:
    # 12 players match by full name; "Nicolas Claxton" matches "Nic Claxton" only by
    # short key (CLAXTONN); "Jalen Williams" and "Jaylin Williams" share WILLIAMSJ in
    # the predictions -- the ambiguous case the old fallback kept both of.
    pred_names = [f"Player Number{i}" for i in range(12)] + ["Nic Claxton", "Jalen Williams", "Jaylin Williams"]
    odds_names = [f"Player Number{i}" for i in range(12)] + ["Nicolas Claxton", "Jason Williams"]
    preds_path = tmp_path / "props_predictions.csv"
    with preds_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["player_id", "player_name", "team", "pred_pts", "pred_reb", "pred_ast", "pred_threes",
                         "pred_pra", "pred_stl", "pred_blk", "pred_tov"])
        for index, name in enumerate(pred_names):
            writer.writerow([1000 + index, name, "BOS", 18.0 + index, 6.0, 4.0, 2.0, 28.0, 1.0, 0.5, 2.0])
    odds_path = tmp_path / "odds.csv"
    rows = 0
    with odds_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["snapshot_ts", "event_id", "commence_time", "bookmaker", "bookmaker_title", "market",
                         "outcome_name", "player_name", "point", "price", "home_team", "away_team"])
        for name in odds_names:
            for market in _MARKETS:
                for book in _BOOKS:
                    for point in _POINTS:
                        for side, price in (("Over", -110), ("Under", -110)):
                            writer.writerow(["2026-11-04T18:00:00Z", "evt1", "2026-11-05T00:00:00Z", book, book,
                                             market, side, name, point, price, "Boston Celtics", "Milwaukee Bucks"])
                            rows += 1
    return odds_path, preds_path, rows


def _run(tmp_path: Path, capsys):
    odds_path, preds_path, odds_rows = _write_slate(tmp_path)
    seen: dict[str, int] = {}

    def _capture(name, frame, **_kwargs):
        seen[name] = len(frame)

    with patch.object(edges, "log_dataframe_memory", side_effect=_capture):
        out = edges._compute_props_edges_file_only_local(
            source_root=tmp_path, date_str="2026-11-04", raw_path=odds_path, predictions_path=preds_path,
            calibrate_prob=False, league="nba",
        )
    return out, seen, odds_rows, capsys.readouterr().out


def test_merged_frame_stays_odds_sized(tmp_path, capsys):
    _out, seen, odds_rows, _stdout = _run(tmp_path, capsys)
    merged_rows = seen["basketball_props_edges.merged_odds_predictions"]
    # Only the ambiguous WILLIAMSJ lines may fan out, once per candidate prediction (x2).
    williams_rows = len(_MARKETS) * len(_BOOKS) * len(_POINTS) * 2
    assert merged_rows == odds_rows + williams_rows
    # The old code made 14 players x 120 lines each into 120 x 120 = 14,400 per player.
    assert merged_rows < 2 * odds_rows


def test_fallback_still_fires_and_output_is_the_deduplicated_one(tmp_path, capsys):
    out, _seen, odds_rows, stdout = _run(tmp_path, capsys)
    assert "short_key_recovered=240" in stdout  # Nicolas Claxton (120) + Jason Williams (120)
    claxton = out[out["player_name"] == "Nicolas Claxton"]
    assert len(claxton) == 120 and set(claxton["player_id"].astype(int)) == {1012}
    williams = out[out["player_name"] == "Jason Williams"]
    assert set(williams["player_id"].astype(int)) == {1013, 1014}
    assert len(williams) == 240
    # Every exact-name line appears once: no duplicates leak past the merge.
    assert len(out) == odds_rows + 120
    dedup_keys = ["player_id", "player_name", "stat", "side", "line", "price", "bookmaker"]
    assert not out.duplicated(subset=dedup_keys).any()
