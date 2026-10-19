"""The game-day NBA props pull's gate (user 2026-10-19: "Pull now + fix game days"). It spends credits, so every
reason it might NOT pull is tested without spending any."""
from __future__ import annotations

import importlib.util
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("nba_gameday_props_pull", ROOT / "scripts" / "nba_gameday_props_pull.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

NOW = datetime(2026, 10, 20, 12, 40, tzinfo=timezone.utc)          # 7:40 AM CT


def _odds(processed: Path, day: str, starts: list[str]) -> None:
    processed.mkdir(parents=True, exist_ok=True)
    lines = ["date,commence_time,home_team,visitor_team"] + [f"{day},{s},H{i},V{i}" for i, s in enumerate(starts)]
    (processed / f"game_odds_{day}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_the_slate_comes_from_game_odds_then_the_sims_then_nothing(tmp_path):
    p = tmp_path / "processed"
    assert g.slate_starts(p, "2026-10-20") is None
    p.mkdir()
    (p / "smart_sim_2026-10-20_DET_BOS.json").write_text("{}", encoding="utf-8")
    assert g.slate_starts(p, "2026-10-20") == []
    _odds(p, "2026-10-20", ["2026-10-20T23:00:00Z", "2026-10-21T01:30:00Z"])
    assert len(g.slate_starts(p, "2026-10-20")) == 2


def test_a_game_day_with_games_ahead_and_an_old_snapshot_pulls():
    starts = [NOW + timedelta(hours=6), NOW + timedelta(hours=9)]
    assert g.decide(starts, NOW, snapshot_age_min=900, running=False) == (True, "2 of 2 games still to start")
    assert g.decide([], NOW, snapshot_age_min=None, running=False)[0] is True          # sims only, no snapshot yet


def test_every_reason_not_to_spend():
    ahead = [NOW + timedelta(hours=6)]
    assert g.decide(None, NOW, 900, False) == (False, "no NBA games today")
    assert g.decide([NOW + timedelta(minutes=5), NOW - timedelta(hours=1)], NOW, 900, False)[0] is False
    assert g.decide(ahead, NOW, 900, True) == (False, "an NBA props job is already running")
    assert g.decide(ahead, NOW, 30, False)[0] is False                                  # someone just pulled
    assert g.decide(ahead, NOW, 61, False)[0] is True


def test_the_snapshot_age_is_the_files_age(tmp_path):
    p = tmp_path
    f = p / "oddsapi_player_props_2026-10-20.csv"
    assert g.snapshot_age_minutes(p, "2026-10-20", time.time()) is None
    f.write_text("x\n", encoding="utf-8")
    os.utime(f, (time.time() - 3600, time.time() - 3600))
    assert 59 < g.snapshot_age_minutes(p, "2026-10-20", time.time()) < 61


def test_the_pull_is_the_orchestrators_forced_nba_pregame_run():
    cmd = g.pull_command("2026-10-20", python="py")
    assert cmd[:2] == ["py", "scripts/refresh_odds_sources.py"]
    assert cmd[cmd.index("--date") + 1] == "2026-10-20" and cmd[cmd.index("--sports") + 1] == "nba"
    assert cmd[cmd.index("--phase") + 1] == "pregame" and "--force-refresh" in cmd


def test_a_dry_run_decides_and_never_pulls(tmp_path, monkeypatch, capsys):
    p = tmp_path / "nba_source" / "data" / "processed"
    _odds(p, "2026-10-20", ["2030-01-01T00:00:00Z"])
    monkeypatch.setattr(g, "props_job_running", lambda: False)
    monkeypatch.setattr(g.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("pulled")))
    assert g.main(["--data-root", str(tmp_path), "--date", "2026-10-20", "--dry-run"]) == 0
    assert "PULL: 1 of 1 games still to start" in capsys.readouterr().out
