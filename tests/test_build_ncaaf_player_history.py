"""NCAAF prior-season player history: producer helpers + the vs-opponent split it feeds (lane intelligence-evidence-coverage)."""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

from syndicate.features.shared.prop_evidence import common as C
from syndicate.features.shared.prop_evidence import football

_SPEC = importlib.util.spec_from_file_location(
    "build_ncaaf_player_history", Path(__file__).resolve().parents[1] / "scripts" / "build_ncaaf_player_history.py"
)
hist = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hist)

COLUMNS = ("season", "week", "game_id", "player_id", "player_name", "team", "receptions", "receiving_yards", "source_snapshot_date")


def test_current_players_and_opponent():
    newest, keep = hist.current_players([{"season": "2025", "player_id": "1"}, {"season": "2026", "player_id": "2"}])
    assert newest == 2026 and keep == {"2"}
    rows = hist.with_opponent([{"game_id": "g", "team": "Colorado"}, {"game_id": "g", "team": "Utah"}, {"game_id": "h", "team": "Solo"}])
    assert [r["opponent"] for r in rows] == ["Utah", "Colorado", ""]


def test_vs_opponent_reads_snapshot_and_prior_seasons_with_a_hit_rate(tmp_path, monkeypatch):
    snapshot = tmp_path / "snapshot.csv"
    with snapshot.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, restval="0")
        writer.writeheader()
        writer.writerow({"season": 2025, "week": 4, "game_id": "S1", "player_id": "777", "player_name": "Joseph Williams", "team": "Colorado", "receptions": 6})
        writer.writerow({"season": 2025, "week": 4, "game_id": "S1", "player_id": "5", "player_name": "Rival Guy", "team": "Northwestern", "receptions": 1})
        writer.writerow({"season": 2026, "week": 1, "game_id": "C1", "player_id": "777", "player_name": "Joseph Williams", "team": "Colorado", "receptions": 3})
    history = tmp_path / "history.csv"
    with history.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS + ("opponent",), restval="0")
        writer.writeheader()
        writer.writerow({"season": 2024, "week": 9, "game_id": "H1", "player_id": "777", "team": "Colorado", "receptions": 2, "opponent": "Northwestern"})
        writer.writerow({"season": 2023, "week": 9, "game_id": "H0", "player_id": "777", "team": "Colorado", "receptions": 7, "opponent": "Northwestern"})
        writer.writerow({"season": 2024, "week": 3, "game_id": "H2", "player_id": "777", "team": "Colorado", "receptions": 9, "opponent": "Utah"})
    monkeypatch.setattr(C, "first_existing", lambda local, *rel, **k: history if rel and rel[0] == football.NCAAF_HISTORY_FILE else snapshot)
    from syndicate.features.shared.prop_evidence.contract import PropSubject

    subject = PropSubject.from_board_row({"sport": "ncaaf", "kind": "prop", "player_name": "Joseph Williams", "market": "receptions",
                                          "line": 4.5, "side": "over", "home_team": "Colorado", "away_team": "Northwestern"},
                                         selected_date="2026-09-19")
    box = football._ncaaf_box(subject, "Colorado", "Northwestern")
    layer = football._ncaaf_matchup(subject, "receptions", "Receptions", box, "Colorado", "Northwestern")
    assert layer.facts["vs_opponent_games"] == 3  # 2025 snapshot game + two prior-season meetings; Utah excluded
    assert layer.facts["vs_opponent"]["hit_rate"]["hits"] == 2  # 6 and 7 over 4.5, 2 not
