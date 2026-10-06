"""OUT players are refused per line at export_props_edges_local (lane wnba-props-out-player-leak).

Runs the REAL edges compute and the REAL recommendations export over a tiny slate, with the switch on and
off, so the test proves the refusal is reachable (off != on) and not only that a helper filters a frame.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from syndicate.features.shared import basketball_props_availability as availability
from syndicate.features.shared.basketball_props_edges import export_props_edges_local
from syndicate.features.shared.basketball_props_recommendations import export_props_recommendations_local

DATE = "2026-10-07"

# name on the odds feed, team the slate puts her on, model mean points
_PLAYERS = [
    ("Allisha Gray", "ATL", 20.0),  # OUT on the latest snapshot -> refused
    ("Ny'Ceara Pryor", "DAL", 20.0),  # OUT, feed spells it with U+2019 and lists a stale team -> refused
    ("Jewell Loyd", "LVA", 20.0),  # OUT on 10-05, OFF the 10-06 snapshot (returned) -> priced
    ("Rhyne Howard", "ATL", 20.0),  # DAY-TO-DAY -> priced
]

_FEED = [
    ("ATL", "Allisha Gray", "OUT", "2026-10-05"),
    ("LVA", "Jewell Loyd", "OUT", "2026-10-05"),
    ("ATL", "Allisha Gray", "OUT", "2026-10-06"),
    ("CON", "Ny’Ceara Pryor", "OUT", "2026-10-06"),
    ("ATL", "Rhyne Howard", "DAY-TO-DAY", "2026-10-06"),
]


def _write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _slate(root: Path, *, feed: bool = True) -> tuple[Path, Path, Path, Path]:
    source_root = root / "wnba_source"
    (source_root / "src").mkdir(parents=True, exist_ok=True)
    processed = source_root / "data" / "processed"
    stats = ["pts", "reb", "ast", "threes", "pra", "stl", "blk", "tov"]
    _write_csv(
        processed / f"props_predictions_{DATE}.csv",
        ["player_id", "player_name", "team", *[f"pred_{stat}" for stat in stats]],
        [[100 + i, name, team, mean, 5.0, 4.0, 1.5, mean + 9.0, 1.0, 0.5, 2.0] for i, (name, team, mean) in enumerate(_PLAYERS)],
    )
    odds_path = source_root / "data" / "raw" / f"odds_wnba_player_props_{DATE}.csv"
    header = ["snapshot_ts", "event_id", "commence_time", "bookmaker", "bookmaker_title", "market", "outcome_name",
              "player_name", "point", "price", "home_team", "away_team"]
    rows = []
    for name, _team, _mean in _PLAYERS:
        for side in ("Over", "Under"):
            rows.append(["2026-10-06T18:00:00Z", "e1", f"{DATE}T23:30:00Z", "fanduel", "FanDuel", "player_points", side,
                         name, 10.5, -110, "Atlanta Dream", "New York Liberty"])
    _write_csv(odds_path, header, rows)
    if feed:
        _write_csv(source_root / "data" / "raw" / "injuries.csv", ["team", "player", "status", "injury", "date"],
                   [[team, player, status, "Out", date] for team, player, status, date in _FEED])
    return source_root, processed, odds_path, processed / f"props_edges_{DATE}.csv"


def _run(source_root: Path, processed: Path, odds_path: Path, edges_path: Path) -> tuple[set[str], set[str]]:
    export_props_edges_local(
        source_root=source_root,
        date_str=DATE,
        raw_path=odds_path,
        predictions_path=processed / f"props_predictions_{DATE}.csv",
        out_path=edges_path,
        league="wnba",
    )
    export_props_recommendations_local(processed_root=processed, date_str=DATE)
    edge_players = {row["player_name"] for row in _read_csv(edges_path)}
    recs = _read_csv(processed / f"props_recommendations_{DATE}.csv")
    recommended = {row["player"] for row in recs if (row.get("top_play") or "").strip() not in ("", "None")}
    return edge_players, recommended


def test_out_player_refused_through_edges_and_recommendations(tmp_path, monkeypatch):
    monkeypatch.delenv("SYNDICATE_PROPS_OUT_PLAYER_REFUSAL", raising=False)
    edge_players, recommended = _run(*_slate(tmp_path))

    assert "Allisha Gray" not in edge_players and "Allisha Gray" not in recommended
    assert "Ny'Ceara Pryor" not in edge_players and "Ny'Ceara Pryor" not in recommended
    # returned (off the latest snapshot) and day-to-day players stay priced and recommended
    assert {"Jewell Loyd", "Rhyne Howard"} <= edge_players
    assert {"Jewell Loyd", "Rhyne Howard"} <= recommended

    sidecar = json.loads((tmp_path / "wnba_source" / "data" / "processed" / f"props_out_player_refusals_{DATE}.json").read_text())
    assert sidecar["reason"] == "player OUT on the injury feed"
    assert sidecar["snapshot_date"] == "2026-10-06"
    assert sidecar["lines_refused"] == 4  # 2 players x over/under
    refused = {item["player"]: item for item in sidecar["players_refused"]}
    assert set(refused) == {"Allisha Gray", "Ny'Ceara Pryor"}
    assert refused["Ny'Ceara Pryor"]["feed_team"] == "CON" and refused["Ny'Ceara Pryor"]["team"] == "DAL"


def test_switch_off_restores_old_behaviour(tmp_path, monkeypatch):
    # reachability: the same slate with the switch off recommends the OUT player -> the refusal is what removes her
    monkeypatch.setenv("SYNDICATE_PROPS_OUT_PLAYER_REFUSAL", "0")
    edge_players, recommended = _run(*_slate(tmp_path))
    assert "Allisha Gray" in edge_players and "Allisha Gray" in recommended
    assert "Ny'Ceara Pryor" in recommended


def test_missing_feed_refuses_nothing_and_says_so(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("SYNDICATE_PROPS_OUT_PLAYER_REFUSAL", raising=False)
    edge_players, _ = _run(*_slate(tmp_path, feed=False))
    assert {name for name, _, _ in _PLAYERS} <= edge_players
    assert "feed_status=absent" in capsys.readouterr().out


def test_namesake_on_another_team_is_not_refused():
    pd = pytest.importorskip("pandas")
    edges = pd.DataFrame(
        [
            {"player_name": "Sam Smith", "team": "ATL", "stat": "pts"},
            {"player_name": "Sam Smith", "team": "NYL", "stat": "pts"},
        ]
    )
    out = {"SAM SMITH": {"player": "Sam Smith", "team": "ATL", "status": "OUT", "feed_date": "2026-10-06"}}
    original = availability.out_players_for_date
    try:
        availability.out_players_for_date = lambda **_: {"feed_path": "x", "feed_status": "read", "feed_rows": 1, "out": out}
        kept = availability.refuse_out_player_lines(edges, source_root=Path("."), date_str=DATE, league="wnba", out_dir=None)
    finally:
        availability.out_players_for_date = original
    assert kept["team"].tolist() == ["NYL"]


@pytest.mark.parametrize(
    "status, expected",
    [("OUT", True), ("Suspended", True), ("OUT FOR SEASON", True), ("DAY-TO-DAY", False), ("QUESTIONABLE", False),
     ("PROBABLE", False), ("DOUBTFUL", False)],
)
def test_status_classes(status, expected):
    assert availability._is_out_status(status) is expected
