"""Multi-season player history (user 2026-10-08: "years of data, not just days"): MLB / NHL producers + readers."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mlb = _load("build_mlb_player_game_logs")
nhl = _load("build_nhl_player_game_logs")


def _csv(path: Path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})


def test_mlb_parsers():
    payload = {"stats": [{"splits": [{"date": "2025-04-01", "gameType": "R", "game": {"gamePk": 9}, "player": {"id": 1, "fullName": "A B"},
                                      "team": {"name": "Cleveland Guardians"}, "opponent": {"name": "Kansas City Royals"}, "isHome": True,
                                      "stat": {"plateAppearances": 4, "hits": 2, "totalBases": 5, "homeRuns": 1, "rbi": 3, "runs": 1}}]}]}
    (row,) = mlb.log_rows("hitting", 2025, payload)
    assert (row["h"], row["tb"], row["rbi"], row["opponent"], row["is_home"]) == (2, 5, 3, "Kansas City Royals", 1)
    pitch = {"stats": [{"splits": [{"date": "2025-04-02", "player": {"id": 2}, "stat": {"inningsPitched": "6.2", "gamesStarted": 1, "strikeOuts": 7}}]}]}
    assert mlb.log_rows("pitching", 2025, pitch)[0]["outs"] == 20
    splits = {"stats": [{"splits": [{"split": {"code": "vl"}, "stat": {"plateAppearances": 10, "hits": 3}}, {"split": {"code": "x"}, "stat": {}}]}]}
    assert [r["code"] for r in mlb.split_rows("hitting", 2025, "1", splits)] == ["vl"]


def test_mlb_sentence_uses_years_of_logs_vs_team_and_hand(tmp_path, monkeypatch):
    from syndicate.features import intelligence_recent_matchup as rm

    root = tmp_path / "data"
    monkeypatch.setenv("SYNDICATE_MLB_DATA_ROOT", str(root))
    fields = mlb.LOG_KEYS + mlb.HITTING
    rows_2024 = [{"date": f"2024-06-{d:02d}", "game_pk": 100 + d, "player_id": "1", "team": "Cleveland Guardians",
                  "opponent": "Kansas City Royals" if d % 2 else "Detroit Tigers", "h": 1 if d % 3 else 0} for d in range(1, 13)]
    _csv(root / "derived" / "mlb_player_game_log_2024_hitting.csv", fields, rows_2024)
    _csv(root / "derived" / "mlb_player_game_log_2025_hitting.csv", fields,
         [{"date": "2025-05-01", "game_pk": 500, "player_id": "1", "team": "Cleveland Guardians", "opponent": "Kansas City Royals", "h": 2}])
    _csv(root / "derived" / "mlb_hand_splits_2024.csv", mlb.SPLIT_FIELDS,
         [{"season": 2024, "group": "hitting", "player_id": "1", "code": "vr", "pa": 100, "ab": 90, "h": 27, "hr": 4}])
    _csv(root / "derived" / "mlb_hand_splits_2025.csv", mlb.SPLIT_FIELDS,
         [{"season": 2025, "group": "hitting", "player_id": "1", "code": "vr", "pa": 50, "ab": 45, "h": 9, "hr": 1}])
    (root / "derived" / "mlb_matchup_splits_2025_asof_20250930.json").write_text(json.dumps(
        {"season": 2025, "batters": {"1": {}}, "pitchers": {"77": {"throws": "R"}}}), encoding="utf-8")
    snap = root / "daily" / "snapshots" / "2025-05-02"
    snap.mkdir(parents=True)
    (snap / "probables.json").write_text(json.dumps({"games": [{"home": {"abbr": "CLE"}, "away": {"abbr": "KC"},
                                                                "away_probable_id": 77, "home_probable_id": 5}]}), encoding="utf-8")
    row = {"market": "batter_hits", "line": 0.5, "side": "over", "player_id": "1",
           "home_team": "Cleveland Guardians", "away_team": "Kansas City Royals"}
    text = rm.mlb_prop_recent_matchup_text(row, selected_date="2025-05-02")
    assert "in 7 of the last 10 logged games" in text and "log since 2024-06-04" in text  # 2025-05-01 + nine 2024 games
    assert "Splits (2024-25): vs RHP .267 AVG, 5 HR in 150 PA" in text  # (27 + 9) / (90 + 45), both seasons
    assert "History vs this team: over 0.5 in 5 of 7 games since 2024-06-01." in text


def test_nhl_rows_keep_the_reader_schema_and_the_reader_merges_seasons(tmp_path, monkeypatch):
    meta = {"name": "B. Gallagher", "role": "skater", "position": "R"}
    rows = nhl.game_rows("8475848", meta, 2, {"gameLog": [{"gameId": 2024021301, "gameDate": "2025-04-16", "teamAbbrev": "MTL",
                                                           "opponentAbbrev": "CAR", "toi": "17:11", "shots": 3, "goals": 1, "assists": 0}]})
    assert rows[0]["date"] == "2025-04-16T16:00:00Z" and rows[0]["player"] == "{'default': 'B. Gallagher'}"

    from syndicate.features.shared.prop_evidence import common as C
    from syndicate.features.shared.prop_evidence import nhl as N

    raw = tmp_path / "raw"
    current = {"gamePk": "2025030126", "date": "2026-05-01T23:00:00Z", "team": "MTL", "player_id": "8475848",
               "player": "{'default': 'B. Gallagher'}", "role": "skater", "shots": "2", "goals": "0", "assists": "0", "timeOnIce": "15:00"}
    _csv(raw / "player_game_stats.csv", nhl.FIELDS[:-2], [current])
    _csv(raw / "player_game_log_20242025.csv", nhl.FIELDS, rows)
    _csv(raw / "player_game_log_20252026.csv", nhl.FIELDS, [dict(current, opponent="TBL", game_type=3)])  # same game twice
    monkeypatch.setattr(N, "game_log_path", lambda: raw / "player_game_stats.csv")
    from syndicate.features.shared.prop_evidence.contract import PropSubject

    subject = PropSubject.from_board_row({"sport": "nhl", "kind": "prop", "player_name": "Brendan Gallagher", "market": "sog",
                                          "line": 1.5, "side": "over", "home_team": "Montreal Canadiens", "away_team": "Toronto Maple Leafs",
                                          "commence_time": "2026-10-10T23:00:00Z"}, selected_date="2026-10-10")
    log = N._game_log(subject, N.Identity(player_id="8475848"), N.MARKETS.get("SOG"))
    assert [g["game_pk"] for g in log.games] == ["2025030126", "2024021301"]  # merged, the duplicate kept once
    assert log.games[1]["opponent"] == "CAR"


def test_nfl_usage_reads_every_season_back_four(tmp_path, monkeypatch):
    from syndicate.features.shared.prop_evidence import common as C
    from syndicate.features.shared.prop_evidence import football as F

    files = {}
    for year, weeks in ((2026, [1, 2]), (2025, [16, 17]), (2023, [3])):
        path = tmp_path / f"nfl_fantasy_usage_{year}.json"
        path.write_text(json.dumps({"player_game_lines": [{"player_id": "g1", "season": year, "week": w} for w in weeks]}), encoding="utf-8")
        files[f"fantasy/nfl_fantasy_usage_{year}.json"] = path
    monkeypatch.setattr(C, "first_existing", lambda local, rel, *a, **k: files.get(rel))
    player = F.NflPlayer(id="g1", name="X", team="CHI", pos="WR", index=0, basis={})
    lines, _path, tried = F._nfl_usage(2026, player)
    assert [(l["season"], l["week"]) for l in lines] == [(2026, 2), (2026, 1), (2025, 17), (2025, 16), (2023, 3)]
    assert len(tried) == 4


def test_recent_values_side_channel_matches_the_sentence(tmp_path, monkeypatch):
    """Layer 2 L5/L10 charts read the values the Recent form sentence was computed from (lane layer2-board-ui-redesign)."""
    from syndicate.features import intelligence_recent_matchup as rm

    root = tmp_path / "data"
    monkeypatch.setenv("SYNDICATE_MLB_DATA_ROOT", str(root))
    rows = [{"date": f"2025-06-{d:02d}", "game_pk": d, "player_id": "1", "team": "Cleveland Guardians",
             "opponent": "Detroit Tigers", "h": d % 3} for d in range(1, 13)]
    _csv(root / "derived" / "mlb_player_game_log_2025_hitting.csv", mlb.LOG_KEYS + mlb.HITTING, rows)
    row = {"sport": "mlb", "kind": "prop", "player_name": "A B", "market": "batter_hits", "line": 0.5, "side": "over", "player_id": "1"}
    rm.RECENT_VALUES.clear()
    text = rm.mlb_prop_recent_matchup_text(row, selected_date="2025-07-01")
    got = rm.recent_values_for(row)
    assert got["dates"][0] == "2025-06-12" and len(got["values"]) == 10  # newest first, last 10
    assert got["values"] == [float(d % 3) for d in range(12, 2, -1)]
    hits = sum(1 for v in got["values"] if v > 0.5)
    assert f"in {hits} of the last 10 logged games" in text
    memo: dict = {}
    rm.prop_recent_matchup_text(row, selected_date="2025-07-01", memo=memo)
    rm.prop_recent_matchup_text(row, selected_date="2025-07-01", memo=memo)  # memo hit: values still there
    assert rm.recent_values_for(row)["values"] == got["values"]


def test_mlb_past_season_never_refetches_a_player_with_no_games(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setenv("SYNDICATE_MLB_DATA_ROOT", str(root))
    (root / "derived").mkdir(parents=True)
    (root / "derived" / "mlb_matchup_splits_2026_asof_20260927.json").write_text(
        json.dumps({"batters": {"1": {}, "2": {}, "3": {}}, "pitchers": {}}), encoding="utf-8")
    calls = []

    def fetch(url):
        calls.append(url)
        if "people/3/" in url:
            raise OSError("boom")  # a failed fetch: must be retried next run
        if "people/1/" in url and "gameLog" in url:
            return {"stats": [{"splits": [{"date": "2024-05-01", "player": {"id": 1}, "stat": {"hits": 1}}]}]}
        return {"stats": [{"splits": []}]}  # player 2: no games in 2024

    mlb.run(2024, current=2026, fetch=fetch, pause=0)
    assert any("people/2/" in c for c in calls)
    calls.clear()
    summary = mlb.run(2024, current=2026, fetch=fetch, pause=0)
    hitting = [c for c in calls if "group=hitting" in c]
    assert not any("people/1/" in c or "people/2/" in c for c in hitting)  # fetched once, never again
    assert any("people/3/" in c for c in hitting)                           # the failure is retried
    assert summary["hitting_rows"] == 1
