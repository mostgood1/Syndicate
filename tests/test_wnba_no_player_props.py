"""WNBA odds run with game lines but no player props (lane wnba-no-player-props).

Same rule as the NBA runner (ca860dd5): measured on NBA preseason MIA@TOR
2026-10-02, a snapshot of 28 game-line rows and 0 props failed every hourly run
at props-edges. The WNBA runner already warned in-run on zero edges, but main()
still exited 1 on `snapshot_rows > 0 and edges_rows <= 0`, and props
recommendations ran with no edges behind them.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_HEADER = "snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,outcome_name,player_name,point,price,last_update,home_team,away_team\n"
GAME_LINE = "t,e1,2026-10-03T00:00:00Z,draftkings,DraftKings,spreads,Las Vegas Aces,,-4.5,-110,t,Las Vegas Aces,Phoenix Mercury\n"
PROP_LINE = "t,e1,2026-10-03T00:00:00Z,draftkings,DraftKings,player_points,Over,A'ja Wilson,24.5,-110,t,Las Vegas Aces,Phoenix Mercury\n"


def _load():
    path = REPO_ROOT / "scripts" / "refresh_wnba_oddsapi_props.py"
    spec = importlib.util.spec_from_file_location("refresh_wnba_oddsapi_props_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_count_player_prop_rows(tmp_path):
    mod = _load()
    games = tmp_path / "g.csv"
    games.write_text(SNAPSHOT_HEADER + GAME_LINE * 2, encoding="utf-8")
    both = tmp_path / "b.csv"
    both.write_text(SNAPSHOT_HEADER + GAME_LINE + PROP_LINE, encoding="utf-8")
    assert mod._count_player_prop_rows(games) == 0
    assert mod._count_player_prop_rows(both) == 1
    assert mod._count_player_prop_rows(tmp_path / "missing.csv") is None


def _run(tmp_path, monkeypatch, body: str):
    mod = _load()
    source_root = tmp_path / "data" / "wnba_source"
    processed = source_root / "data" / "processed"
    processed.mkdir(parents=True)
    (source_root / "data" / "raw").mkdir(parents=True)
    calls = []

    def fake_run_to_file(cmd, log_file, *, cwd=None, env=None, timeout_s=None, heartbeat_cb=None, heartbeat_every_s=None):
        cmd = list(map(str, cmd))
        if "--out" in cmd:
            Path(cmd[cmd.index("--out") + 1]).write_text(body, encoding="utf-8")
        return 0

    def fake_preds(**kwargs):
        Path(kwargs["out_path"]).write_text("player_name,team\nA'ja Wilson,LVA\n", encoding="utf-8")
        return 1, kwargs["out_path"]

    def fake_edges(**kwargs):
        calls.append("edges")
        Path(kwargs["out_path"]).write_text("player_name,edge\nA'ja Wilson,0.1\n", encoding="utf-8")
        return 1, kwargs["out_path"]

    def fake_recs(**kwargs):
        calls.append("recs")
        (processed / "props_recommendations_2026-10-02.csv").write_text("player_name\nA'ja Wilson\n", encoding="utf-8")
        return 1, None

    def fake_cards(**kwargs):
        calls.append("game_cards")
        p = processed / "game_cards_2026-10-02.csv"
        p.write_text("home_team,visitor_team\nLVA,PHX\n", encoding="utf-8")
        return 1, p

    monkeypatch.setattr(mod, "_run_to_file", fake_run_to_file)
    monkeypatch.setattr(mod, "_existing_refresh_state", lambda **k: None, raising=False)
    for name in ("_seed_game_odds_from_props_snapshot", "_refresh_derived_basketball_artifacts", "_ensure_wnba_totals_calibration"):
        monkeypatch.setattr(mod, name, lambda *a, **k: None, raising=False)
    monkeypatch.setattr(mod, "_ensure_source_game_inputs", lambda **k: {}, raising=False)
    monkeypatch.setattr(mod, "_ensure_player_logs_for_props_refresh", lambda **k: (True, None))
    monkeypatch.setattr(mod, "_ensure_game_predictions_for_props_refresh", lambda **k: (True, None))
    monkeypatch.setattr(mod, "export_props_predictions_local", fake_preds)
    monkeypatch.setattr(mod, "export_props_edges_local", fake_edges)
    monkeypatch.setattr(mod, "export_props_recommendations_local", fake_recs)
    monkeypatch.setattr(mod, "_build_local_game_cards_artifact", fake_cards)
    monkeypatch.setattr(mod, "_build_local_game_recommendations_artifact", lambda **k: (1, processed / "recs.json"))
    state = mod._run_refresh_via_cli(
        source_root=source_root, date_str="2026-10-02", regions="us", bookmakers="", markets="",
        do_edges=True, do_export=True, do_push=False, log_file=tmp_path / "run.log",
    )
    return mod, state, calls


def test_game_lines_only_skips_props_edges_and_recs(tmp_path, monkeypatch):
    _mod, state, calls = _run(tmp_path, monkeypatch, SNAPSHOT_HEADER + GAME_LINE * 3)
    assert state["player_prop_rows"] == 0
    assert "edges" not in calls and "recs" not in calls
    assert "game_cards" in calls
    assert state.get("rc_edges") == 0
    assert "no player-prop lines" in str(state.get("warning") or "")
    assert not str(state.get("error") or "")


def test_player_props_present_still_run_edges(tmp_path, monkeypatch):
    """off != on: the skip is keyed on a zero, not on the snapshot shape."""
    _mod, state, calls = _run(tmp_path, monkeypatch, SNAPSHOT_HEADER + GAME_LINE + PROP_LINE)
    assert state["player_prop_rows"] == 1
    assert "edges" in calls and "recs" in calls  # WNBA builds game cards before edges too


@pytest.mark.parametrize("prop_rows, expected", [(0, 0), (None, 1), (5, 1)])
def test_main_exit_tolerates_only_a_known_zero(tmp_path, monkeypatch, prop_rows, expected):
    mod = _load()
    state = {"date": "2026-10-02", "snapshot_rows": 3, "snapshot_alias_rows": 3, "edges_rows": 0, "recs_rows": 0,
             "player_prop_rows": prop_rows, "error": None}
    monkeypatch.setattr(mod, "_run_refresh_via_cli", lambda **k: dict(state))
    monkeypatch.setattr(sys, "argv", ["refresh_wnba_oddsapi_props.py", "--date", "2026-10-02",
                                      "--source-root", str(tmp_path), "--log-file", str(tmp_path / "r.log"),
                                      "--do-edges", "--do-export"])
    assert mod.main() == expected
