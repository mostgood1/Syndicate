"""Games history is re-fetched when the schedule has finals after it, not only after 30 days (lane
basketball-games-history-freshness, 2026-10-13).

On the fleet 2026-10-13 the WNBA history stopped at 10-02 while the schedule listed six final playoff games on
10-04/10-07/10-09; the only fetch trigger was `_games_history_is_stale` (newest game > 30 days before the slate).
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import os
from pathlib import Path

import pandas as pd
import pytest

from syndicate.features.shared import basketball_games_history_freshness as fresh

ROOT = Path(__file__).resolve().parents[1]
NOW = dt.datetime(2026, 10, 14, 3, 0, tzinfo=dt.timezone.utc)


def _tree(tmp_path, *, history_dates, schedule):
    raw, processed = tmp_path / "raw", tmp_path / "processed"
    raw.mkdir()
    processed.mkdir()
    pd.DataFrame({"date": history_dates, "game_id": range(len(history_dates))}).to_csv(raw / "games_nba_api.csv", index=False)
    pd.DataFrame(schedule).to_csv(processed / "schedule_2026.csv", index=False)
    return raw / "games_nba_api.csv", processed


def _game(date, status="3", slug="post-season", label="Playoffs"):
    return {"game_id": f"g{date}{slug}{label}", "date_est": date, "game_status": status, "season_type_slug": slug, "game_label": label}


def test_finals_after_the_newest_history_game_are_due_once_then_cooled_down(tmp_path):
    hist, processed = _tree(tmp_path, history_dates=["2026-10-01", "2026-10-02"],
                            schedule=[_game("2026-10-02"), _game("2026-10-04"), _game("2026-10-07"), _game("2026-10-17", status="1")])
    first = fresh.due(hist, processed, league="wnba", now=NOW)
    assert first == {"newest": "2026-10-02", "finals_after": 2, "dates": ["2026-10-04", "2026-10-07"]}
    assert (processed / fresh.MARKER_NAME).is_file()
    assert fresh.due(hist, processed, league="wnba", now=NOW + dt.timedelta(hours=5)) is None  # cooldown (360 min)
    assert fresh.due(hist, processed, league="wnba", now=NOW + dt.timedelta(hours=7)) is not None


def test_a_current_history_is_not_due(tmp_path):
    hist, processed = _tree(tmp_path, history_dates=["2026-10-09"], schedule=[_game("2026-10-09"), _game("2026-10-17", status="1")])
    assert fresh.due(hist, processed, league="wnba", now=NOW) is None
    assert not (processed / fresh.MARKER_NAME).exists()


def test_game_types_the_league_history_never_holds_do_not_trigger(tmp_path):
    hist, processed = _tree(tmp_path, history_dates=["2026-04-12"], schedule=[
        _game("2026-05-01", slug="", label="Playoffs"), _game("2026-10-05", slug="", label="Preseason"),
        _game("2026-02-15", slug="", label="All-Star Game")])
    assert fresh.final_games_after_history(hist, processed, league="nba", today=NOW.date())["finals_after"] == 0
    assert fresh.final_games_after_history(hist, processed, league="wnba", today=NOW.date())["finals_after"] == 1  # WNBA keeps playoffs


def test_without_status_values_a_past_dated_game_counts_as_final(tmp_path):
    hist, processed = _tree(tmp_path, history_dates=["2026-10-20"], schedule=[
        {"game_id": "a", "date_est": "2026-10-21", "game_status": "", "game_label": ""},
        {"game_id": "b", "date_est": "2026-10-23", "game_status": "", "game_label": ""}])
    info = fresh.final_games_after_history(hist, processed, league="nba", today=dt.date(2026, 10, 22))
    assert info["dates"] == ["2026-10-21"]


def test_only_the_newest_schedule_file_is_read(tmp_path):
    hist, processed = _tree(tmp_path, history_dates=["2026-10-02"], schedule=[_game("2026-10-02")])
    stale = processed / "schedule_2026_27.csv"
    pd.DataFrame([_game("2026-10-04")]).to_csv(stale, index=False)
    os.utime(stale, (1, 1))
    assert fresh.final_games_after_history(hist, processed, league="wnba", today=NOW.date())["finals_after"] == 0


@pytest.mark.parametrize("league", ["wnba", "nba"])
def test_the_refresh_fetches_when_the_schedule_has_newer_finals(tmp_path, monkeypatch, league):
    spec = importlib.util.spec_from_file_location(f"refresh_{league}_probe_hist", ROOT / "scripts" / f"refresh_{league}_oddsapi_props.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    data = tmp_path / "data"
    (data / "raw").mkdir(parents=True)
    (data / "processed").mkdir()
    pd.DataFrame({"date": ["2026-10-02"], "game_id": [1], "season": [2026]}).to_csv(data / "raw" / "games_nba_api.csv", index=False)
    slug = "post-season" if league == "wnba" else "regular-season"
    label = "Playoffs" if league == "wnba" else "Regular Season"
    pd.DataFrame([_game("2026-10-04", slug=slug, label=label)]).to_csv(data / "processed" / "schedule_2026.csv", index=False)
    calls = []
    monkeypatch.setattr(mod, "_run_source_subprocess_cli_command", lambda **kw: calls.append(kw["command_parts"]) or 0)
    for name in ("_seed_games_history_from_checkout_if_fresher", "_seed_game_odds_from_props_snapshot", "_seed_game_odds_from_raw_history"):
        monkeypatch.setattr(mod, name, lambda **kw: None)
    monkeypatch.setattr(mod, "_features_are_behind_history", lambda *a, **k: False)
    try:
        mod._ensure_source_game_inputs(source_root=tmp_path, package_name=f"{league}_betting", date_str="2026-10-05",
                                       log_file=tmp_path / "run.log", heartbeat_cb=None)
    except Exception:
        pass  # later bootstrap steps need real inputs; only the fetch decision is under test
    assert calls[0] == ["fetch-schedule"]
    assert any(c[0] == "fetch" for c in calls), calls
    assert "GAMES_HISTORY_BEHIND_SCHEDULE" in (tmp_path / "run.log").read_text(encoding="utf-8")
