"""NBA in the hourly odds runs (lane nba-hourly-odds-failures).

Every hourly all-sport run since at least 2026-10-01 05:00Z exited rc=1 on NBA,
for two stacked reasons read from the fleet's nba_source props log:
- the game-cards export ran `python -m nba_source.cli` from vendor/nba_source_repo,
  because the package name was taken from the DATA-root folder name;
- once an NBA game was on the slate (preseason MIA@TOR, 2026-10-02 16:03Z), SmartSim
  failed first: the NBA vendored smart_sim has no `LEAGUE`, 0 player rows.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from syndicate.features.shared import basketball_props_smart_sim as sim

REPO_ROOT = Path(__file__).resolve().parents[1]


# --- SmartSim: LEAGUE --------------------------------------------------------

def test_module_league_wins_when_present():
    own = SimpleNamespace(regulation_team_minutes=200.0)
    assert sim._smart_sim_league_local(SimpleNamespace(LEAGUE=own), "nba") is own


def test_missing_league_falls_back_to_the_callers_league():
    assert sim._smart_sim_league_local(SimpleNamespace(), "nba").regulation_team_minutes == 240.0
    assert sim._smart_sim_league_local(SimpleNamespace(), "wnba").regulation_team_minutes == 200.0


def test_missing_league_and_no_code_raises_instead_of_guessing():
    with pytest.raises(AttributeError):
        sim._smart_sim_league_local(SimpleNamespace(), None)


def test_the_nba_orchestrator_view_really_has_no_league(tmp_path):
    """Precondition: the fallback is the path production takes for NBA. Plan P6: the ports read the native
    orchestrator's VIEW, which carries `LEAGUE` for WNBA only, exactly as only the WNBA fork exported one."""
    from syndicate.features.basketball_engine.orchestrator import OrchestratorEnv, module_view

    assert not hasattr(module_view(OrchestratorEnv.for_processed_root(tmp_path, "nba")), "LEAGUE")
    assert module_view(OrchestratorEnv.for_processed_root(tmp_path, "wnba")).LEAGUE.regulation_team_minutes == 200.0


def _module_without_league(base):
    return SimpleNamespace(
        _roll_minutes_unscaled=lambda df, date_str=None, team_tri=None: pd.Series(base, index=df.index, dtype=float),
        _first_minutes_signal=lambda df: pd.Series(base, index=df.index, dtype=float),
        _minutes_priors_from_player_logs=lambda **k: {},
        _frame_series=lambda df, col, default: df.get(col, pd.Series([default] * len(df))),
        _norm_player_key=lambda v: str(v).upper(),
        _minutes_caps_from_team_df=lambda df, base_minutes: pd.Series([48.0] * len(df), index=df.index),
        _scale_minutes_to_target=lambda mins, total_target: mins * (total_target / mins.sum()),
        _cap_and_redistribute_minutes=lambda mins, total_target, cap, iters: mins,
    )


NBA_ROTATION = np.array([36.0, 34.0, 33.0, 31.0, 29.0, 24.0, 21.0, 18.0, 15.0, 12.0, 10.0])  # 263 > 240


def test_derive_sim_minutes_off_vs_on():
    """off != on: without league_code the NBA module still fails; with it, 240 minutes."""
    df = pd.DataFrame({"player_name": [f"p{i}" for i in range(len(NBA_ROTATION))]})
    m = _module_without_league(NBA_ROTATION)
    with pytest.raises(AttributeError):
        sim._derive_sim_minutes_local(smart_sim_module=m, team_df=df, date_str="2026-10-03", team_tri="TOR")
    out = sim._derive_sim_minutes_local(smart_sim_module=m, team_df=df, date_str="2026-10-03", team_tri="TOR", league_code="nba")
    assert out.sum() == pytest.approx(240.0)


def test_the_sim_wiring_hands_league_code_to_both_ports(tmp_path, monkeypatch):
    """Drive the REAL hooks (plan P6: the orchestrator's direct calls into the ports): the module the ports
    see has no LEAGUE, so league_code must arrive through the hook."""
    from syndicate.features.basketball_engine import orchestrator as orch_pkg
    from syndicate.features.basketball_engine.orchestrator import hooks

    seen = {}
    m = _module_without_league(NBA_ROTATION)
    df = pd.DataFrame({"player_name": [f"p{i}" for i in range(len(NBA_ROTATION))]})
    for name in ("_frame_numeric_series", "_weighted_positive_mean", "_bounded_split_multiplier",
                 "_normalize_position", "_boolish_series", "_safe_float"):
        if not hasattr(m, name):
            setattr(m, name, lambda *a, **k: None)
    m._derive_sim_minutes = lambda team_df, date_str=None, team_tri=None: sim._derive_sim_minutes_local(
        smart_sim_module=m, team_df=team_df, date_str=date_str, team_tri=team_tri, league_code="nba")
    monkeypatch.setattr(hooks, "_view", lambda orch: m)

    def simulate_smart_game(*, orch, **_kwargs):
        seen["minutes"] = float(hooks._derive_sim_minutes(df, date_str="2026-10-03", team_tri="TOR", orch=orch).sum())
        try:
            hooks._apply_player_priors(pd.DataFrame(), None, "TOR", orch=orch)
            seen["priors"] = "ok"
        except AttributeError as exc:  # pragma: no cover - the failure this guards
            seen["priors"] = f"AttributeError: {exc}"
        return {}

    monkeypatch.setattr(orch_pkg, "simulate_smart_game", simulate_smart_game)
    sim._call_source_simulate_smart_game_local(processed_root=tmp_path, league_code="nba", kwargs={})
    assert seen == {"minutes": pytest.approx(240.0), "priors": "ok"}


# --- game-cards export: package name ----------------------------------------

def _load_refresh_nba():
    path = REPO_ROOT / "scripts" / "refresh_nba_oddsapi_props.py"
    spec = importlib.util.spec_from_file_location("refresh_nba_oddsapi_props_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


SNAPSHOT_HEADER = "snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,outcome_name,player_name,point,price,last_update,home_team,away_team\n"
GAME_LINE = "t,e1,2026-10-03T23:00:00Z,draftkings,DraftKings,spreads,Miami Heat,,-1.5,-105,t,Toronto Raptors,Miami Heat\n"
PROP_LINE = "t,e1,2026-10-03T23:00:00Z,draftkings,DraftKings,player_points,Over,Bam Adebayo,15.5,-110,t,Toronto Raptors,Miami Heat\n"


def test_count_player_prop_rows(tmp_path):
    mod = _load_refresh_nba()
    games = tmp_path / "games.csv"
    games.write_text(SNAPSHOT_HEADER + GAME_LINE * 3, encoding="utf-8")
    both = tmp_path / "both.csv"
    both.write_text(SNAPSHOT_HEADER + GAME_LINE + PROP_LINE, encoding="utf-8")
    no_col = tmp_path / "nocol.csv"
    no_col.write_text("a,b\n1,2\n", encoding="utf-8")
    assert mod._count_player_prop_rows(games) == 0
    assert mod._count_player_prop_rows(both) == 1
    assert mod._count_player_prop_rows(tmp_path / "missing.csv") is None  # unknown is not zero
    assert mod._count_player_prop_rows(no_col) is None


def _run_with_snapshot(tmp_path, monkeypatch, body: str):
    mod = _load_refresh_nba()
    source_root = tmp_path / "data" / "nba_source"
    processed = source_root / "data" / "processed"
    processed.mkdir(parents=True)
    (source_root / "data" / "raw").mkdir(parents=True)
    calls = []

    def fake_run_to_file(cmd, log_file, *, cwd=None, env=None, timeout_s=None, heartbeat_cb=None, heartbeat_every_s=None):
        cmd = list(map(str, cmd))
        if "--out" in cmd:  # the owned snapshot fetch
            Path(cmd[cmd.index("--out") + 1]).write_text(body, encoding="utf-8")
        return 0

    def fake_preds(**kwargs):
        Path(kwargs["out_path"]).write_text("player_name,team\nBam Adebayo,MIA\n", encoding="utf-8")
        return 1, kwargs["out_path"]

    def fake_edges(**kwargs):
        calls.append("edges")
        Path(kwargs["out_path"]).write_text("player_name,edge\nBam Adebayo,0.1\n", encoding="utf-8")
        return 1, kwargs["out_path"]

    def fake_recs(**kwargs):
        calls.append("recs")
        (processed / "props_recommendations_2026-10-03.csv").write_text("player_name\nBam Adebayo\n", encoding="utf-8")
        return 1, None

    def fake_cards(**kwargs):
        calls.append("game_cards")
        p = processed / "game_cards_2026-10-03.csv"
        p.write_text("home_team,visitor_team\nTOR,MIA\n", encoding="utf-8")
        return 1, p

    monkeypatch.setattr(mod, "_run_to_file", fake_run_to_file)
    monkeypatch.setattr(mod, "_ensure_player_logs_for_props_refresh", lambda **k: (True, None))
    monkeypatch.setattr(mod, "_ensure_game_predictions_for_props_refresh", lambda **k: (True, None))
    monkeypatch.setattr(mod, "export_props_predictions_local", fake_preds)
    monkeypatch.setattr(mod, "export_props_edges_local", fake_edges)
    monkeypatch.setattr(mod, "export_props_recommendations_local", fake_recs)
    monkeypatch.setattr(mod, "_ensure_source_game_cards_export", fake_cards)
    monkeypatch.setattr(mod, "_build_local_game_recommendations_artifact", lambda **k: (1, processed / "recs.json"))
    monkeypatch.setattr(mod, "_export_cards_sim_detail_snapshot", lambda **k: None)
    state = mod._run_refresh_via_cli(
        source_root=source_root, date_str="2026-10-03", regions="us", bookmakers="", markets="",
        do_edges=True, do_export=True, do_push=False, log_file=tmp_path / "run.log",
    )
    return state, calls


def test_game_lines_only_skips_props_edges_instead_of_failing(tmp_path, monkeypatch):
    state, calls = _run_with_snapshot(tmp_path, monkeypatch, SNAPSHOT_HEADER + GAME_LINE * 3)
    assert state["player_prop_rows"] == 0
    assert "edges" not in calls and "recs" not in calls
    assert "game_cards" in calls  # the game side still exports
    assert state.get("rc_edges") == 0
    assert not str(state.get("error") or "").startswith(("props-edges", "export-props"))
    assert "no player-prop lines" in str(state.get("warning") or "")


def test_player_props_present_still_run_edges(tmp_path, monkeypatch):
    """off != on: the skip is keyed on a zero, not on the snapshot shape."""
    state, calls = _run_with_snapshot(tmp_path, monkeypatch, SNAPSHOT_HEADER + GAME_LINE + PROP_LINE)
    assert state["player_prop_rows"] == 1
    assert calls[:2] == ["edges", "recs"]


class _StopAtGameCards(BaseException):
    """BaseException so the run function's `except Exception` cannot swallow it."""


def test_game_cards_export_runs_the_vendored_package_from_a_data_root(tmp_path, monkeypatch):
    mod = _load_refresh_nba()
    source_root = tmp_path / "data" / "nba_source"  # the fleet's shape: a DATA bundle, not a code checkout
    (source_root / "data" / "processed").mkdir(parents=True)
    (source_root / "data" / "raw").mkdir(parents=True)
    calls = []

    def fake_run_to_file(cmd, log_file, *, cwd=None, env=None, timeout_s=None, heartbeat_cb=None, heartbeat_every_s=None):
        calls.append((list(map(str, cmd)), str(cwd)))
        if "export-game-cards" in map(str, cmd):
            raise _StopAtGameCards()
        return 0

    monkeypatch.setattr(mod, "_run_to_file", fake_run_to_file)
    with pytest.raises(_StopAtGameCards):
        mod._run_refresh_via_cli(
            source_root=source_root, date_str="2026-10-03", regions="us", bookmakers="", markets="",
            do_edges=False, do_export=True, do_push=False, log_file=tmp_path / "run.log",
        )
    cmd, cwd = calls[-1]
    assert cmd[1:3] == ["-m", "nba_betting.cli"], cmd
    assert Path(cwd) == mod._vendor_code_root("nba_betting")
    assert Path(cwd).name == "nba_betting_repo"
