"""UEFA follow-ups (lane soccer-uefa-followups, 2026-10-21): near-kickoff props, branding refresh, odds-only board.

Every gate here has a control arm (a domestic league, or the window/branding being fresh), so the tests prove the
gate is the competition, not a broken path. Hermetic: no network.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"test_uefa_followups_{name}", REPO_ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- (1) props only near kickoff ---------------------------------------------------------------------------


def _steps(leagues: str):
    module = _load_script("refresh_odds_sources")
    args = argparse.Namespace(date="2026-10-21", soccer_leagues=leagues, soccer_date="")
    with patch.object(module, "soccer_active_leagues_for_date", return_value=list(module._SOCCER_LEAGUE_SLUGS)), \
            patch.object(module, "_soccer_live_scope", return_value={}), \
            patch.object(module, "_soccer_uefa_branding_step", return_value=None):
        return {step.name: step for step in module._build_soccer_steps(args)}


def test_uefa_props_step_carries_the_24h_window_and_domestic_does_not():
    steps = _steps("ucl,epl")
    ucl = list(steps["soccer_ucl_props"].command)
    epl = list(steps["soccer_epl_props"].command)
    assert ucl[ucl.index("--max-hours-ahead") + 1] == "24"
    assert "--max-hours-ahead" not in epl  # control: domestic props unchanged


def test_events_within_hours_keeps_only_the_window():
    props = _load_script("fetch_soccer_oddsapi_props_local")
    now = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    events = [
        {"id": "soon", "commence_time": "2026-10-21T19:00:00Z"},
        {"id": "edge", "commence_time": "2026-10-22T12:00:00Z"},
        {"id": "far", "commence_time": "2026-11-04T20:00:00Z"},
        {"id": "past", "commence_time": "2026-10-21T11:00:00Z"},
        {"id": "bad", "commence_time": "not a time"},
        {"id": "none"},
    ]
    kept = [e["id"] for e in props.events_within_hours(events, 24, now=now)]
    assert kept == ["soon", "edge"]


def test_an_empty_window_makes_no_event_call_and_leaves_the_file(tmp_path, monkeypatch):
    props = _load_script("fetch_soccer_oddsapi_props_local")
    out = tmp_path / "2026-10-21.csv"
    out.write_text("league,player\nucl,Kept From Earlier\n", encoding="utf-8")
    far = (datetime.now(timezone.utc) + timedelta(days=13)).isoformat()
    calls = []
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    monkeypatch.setattr(props, "fetch_events", lambda *a, **k: [{"id": "far", "commence_time": far}])
    monkeypatch.setattr(props, "fetch_event_player_props", lambda *a, **k: calls.append(k) or None)
    monkeypatch.setattr(sys, "argv", ["x", "--league", "ucl", "--max-hours-ahead", "24", "--out", str(out)])
    assert props.main() == 0
    assert calls == []                                           # no per-event spend
    assert "Kept From Earlier" in out.read_text(encoding="utf-8")  # earlier capture not erased


# --- (2) UEFA branding refresh -----------------------------------------------------------------------------


def _branding_file(root: Path, league: str) -> Path:
    path = root / league / "source_artifacts" / "data" / "processed" / "team_branding" / f"{league}_team_branding.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def test_uefa_branding_step_fires_when_absent_or_stale_and_names_its_root(tmp_path):
    module = _load_script("refresh_odds_sources")
    step = module._soccer_uefa_branding_step("ucl", tmp_path, "py")              # absent
    assert step is not None
    command = list(step.command)
    assert command[command.index("--sport") + 1] == "ucl"
    assert command[command.index("--out-root") + 1] == str(tmp_path)
    stale = _branding_file(tmp_path, "uel")
    stale.write_text("team_id\n", encoding="utf-8")
    old = time.time() - 8 * 86400
    os.utime(stale, (old, old))
    assert module._soccer_uefa_branding_step("uel", tmp_path, "py") is not None   # 8 days old


def test_uefa_branding_step_is_quiet_when_fresh_and_never_runs_for_domestic(tmp_path):
    module = _load_script("refresh_odds_sources")
    _branding_file(tmp_path, "uecl").write_text("team_id\n", encoding="utf-8")
    assert module._soccer_uefa_branding_step("uecl", tmp_path, "py") is None      # fresh
    assert module._soccer_uefa_branding_step("epl", tmp_path, "py") is None       # control: domestic


def test_branding_snapshot_out_root_targets_the_league_file(tmp_path, monkeypatch):
    snap = _load_script("build_team_branding_snapshot")
    written = {}
    monkeypatch.setattr(snap, "fetch_espn_teams", lambda path, snapshot_date: [{"team_id": "1"}])
    monkeypatch.setattr(snap, "write_team_branding_snapshot", lambda rows, path: written.setdefault("path", path))
    snap.build_snapshot("ucl", out_root=tmp_path)
    assert written["path"] == tmp_path / "ucl" / "source_artifacts" / "data" / "processed" / "team_branding" / "ucl_team_branding.csv"


# --- (3) odds-only market board ----------------------------------------------------------------------------


def _odds(event_id, home, away):
    base = {"league": "ucl", "event_id": event_id, "home_team": home, "away_team": away,
            "commence_time": "2026-10-21T19:00:00Z", "book": "fanduel"}
    return [dict(base, market="h2h", side=home, line="", price="150"),
            dict(base, market="h2h", side="Draw", line="", price="240"),
            dict(base, market="h2h", side=away, line="", price="180")]


def test_no_model_board_builds_games_from_the_schedule_with_odds_only(monkeypatch):
    from syndicate.features.soccer import market_board as mb

    mb.clear_soccer_market_board_cache()
    schedule = {"matches": [
        {"event_id": "401", "date": "2026-10-21T19:00Z", "home_team": "Lille", "away_team": "Galatasaray", "status_state": "pre"},
        {"event_id": "402", "date": "2026-12-30T19:00Z", "home_team": "Far", "away_team": "Away", "status_state": "pre"},
    ]}
    monkeypatch.setattr(mb, "schedule_payload", lambda league, season: schedule)
    monkeypatch.setattr(mb, "game_odds_rows", lambda league: _odds("oa1", "Lille", "Galatasaray"))
    monkeypatch.setattr(mb, "recommendations_payload", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no model: never read")))
    board = mb.build_soccer_market_board("ucl", "2026-10-21")
    assert [g["gamePk"] for g in board["games"]] == ["401"]   # outside the window is excluded
    rows = board["games"][0]["rows"]
    assert {r["market"] for r in rows} == {"Moneyline"} and len(rows) == 3
    assert all(r.get("sim_projection") is None for r in rows)


def test_domestic_board_still_reads_recommendations(monkeypatch):
    from syndicate.features.soccer import market_board as mb

    mb.clear_soccer_market_board_cache()
    seen = []
    monkeypatch.setattr(mb, "recommendations_payload", lambda league, d: seen.append((league, d)) or {"matches": []})
    monkeypatch.setattr(mb, "schedule_payload", lambda *a: (_ for _ in ()).throw(AssertionError("domestic: schedule not used")))
    mb.build_soccer_market_board("epl", "2026-10-21")
    assert seen  # control: the sim path is still the domestic source


def test_canonical_fallback_joins_only_when_both_clubs_are_named(monkeypatch):
    from syndicate.features.soccer import market_board as mb
    import syndicate.features.shared.team_aliases as ta

    names = {"Sporting CP": "sporting cp", "Sporting Lisbon": "sporting cp", "LASK Linz": "lask linz", "LASK": "lask linz"}
    monkeypatch.setattr(ta, "canonical_team", lambda sport, value: names.get(value))
    events = {"e1": ("Sporting Lisbon", "LASK"), "e2": ("Someone", "Else")}
    assert mb._soccer_odds_event_by_canonical(home_team="Sporting CP", away_team="LASK Linz", events=events) == ("e1", "Sporting Lisbon", "LASK")
    assert mb._soccer_odds_event_by_canonical(home_team="Sporting CP", away_team="Nobody", events=events) is None


def test_canonical_fallback_runs_when_home_matches_but_away_does_not(monkeypatch):
    """Fleet 2026-10-21: home 'Trabzonspor' fuzzy-matches exactly, away 'Heart of Midlothian' vs 'Hearts' does not."""
    from syndicate.features.soccer import market_board as mb
    import syndicate.features.shared.team_aliases as ta

    names = {"Trabzonspor": "trabzonspor", "Heart of Midlothian": "heart of midlothian", "Hearts": "heart of midlothian"}
    monkeypatch.setattr(ta, "canonical_team", lambda sport, value: names.get(value))
    rows = [{"event_id": "oa9", "home_team": "Trabzonspor", "away_team": "Hearts"}]
    assert mb._soccer_odds_event_for_match(home_team="Trabzonspor", away_team="Heart of Midlothian",
                                           game_odds_rows_all=rows) == ("oa9", "Trabzonspor", "Hearts")
