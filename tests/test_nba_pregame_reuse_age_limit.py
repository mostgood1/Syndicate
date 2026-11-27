"""`#863`: the NBA pregame reuse age limit (`SYNDICATE_NBA_PREGAME_REUSE_MAX_AGE_SECONDS`, absent = off).

Measured 11-27: the sweep re-served the 6:40 AM CST NBA capture all morning (34 launches, 0 fetches), so 2 h after each
scheduled pull every sportsbook quote went stale and the board picked 0 of 627 NBA rows. Each test pairs the case
that must reuse with the case that must fetch, and the first test is reachability through `main()`: off != on.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import time
from pathlib import Path

import pytest

from scripts import refresh_nba_oddsapi_props as nba

DAY = "2026-11-27"
KEY = "SYNDICATE_NBA_PREGAME_REUSE_MAX_AGE_SECONDS"
WINDOW = "SYNDICATE_NBA_PREGAME_REUSE_WINDOW_HOURS"


def _iso(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _bundle(root: Path, *, starts_in_s: list[float], age_s: float) -> Path:
    """A day's snapshot + alias under `root`, games starting `starts_in_s` from now, the snapshot `age_s` old."""
    raw = root / "data" / "raw"
    processed = root / "data" / "processed"
    raw.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    now = time.time()
    lines = ["event_id,commence_time,bookmaker,market,outcome,price"]
    for i, lead in enumerate(starts_in_s):
        lines.append(f"e{i},{_iso(now + lead)},draftkings,player_points,Over,-110")
        lines.append(f"e{i},{_iso(now + lead)},fanduel,player_points,Under,-110")
    snapshot = raw / f"odds_nba_player_props_{DAY}.csv"
    snapshot.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (processed / f"oddsapi_player_props_{DAY}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    old = now - age_s
    os.utime(snapshot, (old, old))
    return snapshot


def _source_state(root: Path):
    return nba._existing_refresh_state(source_root=root, date_str=DAY, do_edges=False, do_export=False)


def _bundle_state(root: Path):
    return nba._existing_artifact_bundle_state(artifact_root=root, date_str=DAY, do_edges=False, do_export=False)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(KEY, raising=False)
    monkeypatch.delenv(WINDOW, raising=False)


def _run_main(monkeypatch, root: Path) -> list[str]:
    fetched: list[str] = []

    def fake_fetch(**kwargs):
        fetched.append(str(kwargs.get("date_str")))
        return {"date": kwargs.get("date_str"), "snapshot_rows": 4, "snapshot_alias_rows": 4, "error": None}

    monkeypatch.setattr(nba, "_run_refresh_via_cli", fake_fetch)
    monkeypatch.setattr(nba, "record_refresh_state", lambda *a, **k: None)
    monkeypatch.setattr(nba, "_materialize_artifact_bundle", lambda **k: [])
    monkeypatch.setattr(nba, "_refresh_step_input_hash", lambda **k: "h")
    monkeypatch.setattr(sys, "argv", ["refresh_nba_oddsapi_props.py", "--date", DAY, "--source-root", str(root),
                                      "--artifact-root", str(root), "--log-file", str(root / "job.log")])
    nba.main()
    return fetched


def test_main_reaches_the_fetch_only_when_switched_on(monkeypatch, tmp_path, capsys):
    """Reachability: the sweep's real command (both roots one directory, as on the fleet) fetches only when on."""
    _bundle(tmp_path, starts_in_s=[3 * 3600], age_s=3 * 3600)
    assert _run_main(monkeypatch, tmp_path) == []            # off: today's reuse
    monkeypatch.setenv(KEY, "4500")
    assert _run_main(monkeypatch, tmp_path) == [DAY]          # on: the 3 h old capture is refetched
    out = capsys.readouterr().out
    assert "PREGAME_REUSE_DECLINED" in out and "branch=source_root" in out and "branch=artifact_bundle" in out


@pytest.mark.parametrize("state", [_source_state, _bundle_state])
def test_both_branches_decline_an_old_snapshot_and_keep_a_fresh_one(monkeypatch, tmp_path, state):
    monkeypatch.setenv(KEY, "4500")
    _bundle(tmp_path, starts_in_s=[2 * 3600], age_s=80 * 60)
    assert state(tmp_path) is None                           # 80 min > 75 min: fetch
    _bundle(tmp_path, starts_in_s=[2 * 3600], age_s=70 * 60)
    assert state(tmp_path) is not None                       # 70 min: reuse


@pytest.mark.parametrize("value", ["", "0", "-5", "abc"])
def test_absent_zero_or_junk_is_off(monkeypatch, tmp_path, value):
    _bundle(tmp_path, starts_in_s=[2 * 3600], age_s=6 * 3600)
    if value:
        monkeypatch.setenv(KEY, value)
    assert _source_state(tmp_path) is not None
    assert _bundle_state(tmp_path) is not None
    monkeypatch.setenv(KEY, "4500")
    assert _source_state(tmp_path) is None


def test_no_fetch_once_every_game_has_started(monkeypatch, tmp_path):
    """In play, the in-play lane owns the snapshot; an old file whose games all started is reused."""
    monkeypatch.setenv(KEY, "4500")
    _bundle(tmp_path, starts_in_s=[-3600, -600], age_s=3 * 3600)
    assert _source_state(tmp_path) is not None
    _bundle(tmp_path, starts_in_s=[-3600, 1800], age_s=3 * 3600)
    assert _source_state(tmp_path) is None                   # one game still to start: fetch


def test_window_keeps_an_overnight_sweep_from_refetching(monkeypatch, tmp_path):
    monkeypatch.setenv(KEY, "4500")
    _bundle(tmp_path, starts_in_s=[17 * 3600], age_s=12 * 3600)
    assert _source_state(tmp_path) is not None               # first tip 17 h away, outside the 12 h default
    _bundle(tmp_path, starts_in_s=[11 * 3600], age_s=12 * 3600)
    assert _source_state(tmp_path) is None                   # inside it
    monkeypatch.setenv(WINDOW, "6")
    assert _source_state(tmp_path) is not None               # a 6 h window


def test_no_start_times_is_reused(monkeypatch, tmp_path):
    monkeypatch.setenv(KEY, "4500")
    snapshot = _bundle(tmp_path, starts_in_s=[2 * 3600], age_s=3 * 3600)
    snapshot.write_text("event_id,bookmaker\ne0,draftkings\n", encoding="utf-8")
    old = time.time() - 3 * 3600
    os.utime(snapshot, (old, old))
    assert _source_state(tmp_path) is not None
