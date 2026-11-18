"""Bounded NBA games-history fetch (lane nba-midnight-bootstrap-hold, 2026-11-18).

The midnight NBA props run's bootstrap ran `cli fetch --years 1`, which walked BoxScoreSummaryV2 for EVERY game of the
season (the history's ids round-trip through CSV as `22600001`, LeagueGameLog's are `0022600001`, so no game ever
matched its stored quarters) under a 2,700 s timeout -- longer than the live odds lane's 1,800 s step. The same
mismatch kept every completed fetch from replacing the season, so the history carried up to 16 copies of a game.

`SYNDICATE_NBA_HISTORY_FETCH_BOUNDED` (absent = OFF) keys by the 10-digit id, walks only quarter-less games, newest
first, under a deadline, writes one row per game, and caps the bootstrap's fetch at 900 s. The reachability tests drive
the REAL callers (`fetch_games_nba_api`, `_ensure_source_game_inputs`) and assert off != on.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from syndicate.features.nba.source_cli import scrape_nba_api as scrape

ROOT = Path(__file__).resolve().parents[1]
SWITCH = scrape.HISTORY_FETCH_BOUNDED_ENV

# Three games of the "current" season, oldest first. LeagueGameLog serves ids zero-padded.
GAMES = [
    ("0022600001", "2026-10-20", "DET", "BOS", 121, 113),
    ("0022600002", "2026-10-20", "NYK", "PHI", 100, 106),
    ("0022600003", "2026-11-17", "SAS", "OKC", 104, 116),
]
FULL = {"DET": "Detroit Pistons", "BOS": "Boston Celtics", "NYK": "New York Knicks", "PHI": "Philadelphia 76ers",
        "SAS": "San Antonio Spurs", "OKC": "Oklahoma City Thunder"}


class _GameLog:
    def __init__(self, *args, **kwargs):
        pass

    def get_data_frames(self):
        rows = []
        for gid, date, home, away, hp, ap in GAMES:
            rows.append({"GAME_ID": gid, "GAME_DATE": date, "MATCHUP": f"{home} vs. {away}", "TEAM_ABBREVIATION": home, "PTS": hp})
            rows.append({"GAME_ID": gid, "GAME_DATE": date, "MATCHUP": f"{away} @ {home}", "TEAM_ABBREVIATION": away, "PTS": ap})
        return [pd.DataFrame(rows)]


def _box_factory(calls: list[str], clock: list[float] | None = None, step_s: float = 0.0):
    by_id = {gid: (home, away) for gid, _d, home, away, _hp, _ap in GAMES}

    class _Box:
        def __init__(self, game_id, timeout=30):
            calls.append(str(game_id))
            if clock is not None:
                clock[0] += step_s
            self.game_id = str(game_id)

        def get_normalized_dict(self):
            home, away = by_id[self.game_id]
            return {"LineScore": [
                {"TEAM_ABBREVIATION": home, "PTS_QTR1": 30, "PTS_QTR2": 30, "PTS_QTR3": 30, "PTS_QTR4": 31, "PTS": 121},
                {"TEAM_ABBREVIATION": away, "PTS_QTR1": 28, "PTS_QTR2": 28, "PTS_QTR3": 28, "PTS_QTR4": 29, "PTS": 113},
            ]}

    return _Box


def _seed_history(raw: Path) -> None:
    """The fleet's shape on 11-18: 8-digit ids (the CSV round-trip), game 1 stored three times (one copy with quarters),
    game 2 once without quarters, game 3 absent (last night's final), plus an older season that must survive."""
    rows = [
        {"season": 2026, "date": "2026-04-12", "home_team": "Boston Celtics", "visitor_team": "Detroit Pistons",
         "home_pts": 110, "visitor_pts": 100, "game_id": 22501230, "home_q1": None},
        {"season": 2027, "date": "2026-10-20", "home_team": "Detroit Pistons", "visitor_team": "Boston Celtics",
         "home_pts": 121, "visitor_pts": 113, "game_id": 22600001, "home_q1": None},
        {"season": 2027, "date": "2026-10-20", "home_team": "Detroit Pistons", "visitor_team": "Boston Celtics",
         "home_pts": 121, "visitor_pts": 113, "game_id": 22600001, "home_q1": 27.0},
        {"season": 2027, "date": "2026-10-20", "home_team": "Detroit Pistons", "visitor_team": "Boston Celtics",
         "home_pts": 121, "visitor_pts": 113, "game_id": 22600001, "home_q1": None},
        {"season": 2027, "date": "2026-10-20", "home_team": "New York Knicks", "visitor_team": "Philadelphia 76ers",
         "home_pts": 100, "visitor_pts": 106, "game_id": 22600002, "home_q1": None},
    ]
    pd.DataFrame(rows).to_csv(raw / "games_nba_api.csv", index=False)


@pytest.fixture
def fetch_env(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    _seed_history(raw)
    monkeypatch.setattr(scrape, "paths", SimpleNamespace(data_raw=raw))
    monkeypatch.setattr(scrape.leaguegamelog, "LeagueGameLog", _GameLog)
    monkeypatch.setattr(scrape.static_teams, "get_teams", lambda: [{"abbreviation": a, "full_name": n} for a, n in FULL.items()])
    monkeypatch.delenv(SWITCH, raising=False)
    monkeypatch.delenv(scrape.LINESCORE_DEADLINE_ENV, raising=False)
    return raw


def _run(monkeypatch, calls, **box_kwargs):
    monkeypatch.setattr(scrape.boxscoresummaryv2, "BoxScoreSummaryV2", _box_factory(calls, **box_kwargs))
    return scrape.fetch_games_nba_api(last_n=1, rate_delay=0.0, with_periods=True)


def test_normalize_game_ids_pads_ints_floats_and_leaves_non_digits():
    got = scrape.normalize_game_ids(pd.Series([22600001, "22600001.0", "0022600001", "nan", "g1"]))
    assert got.tolist() == ["0022600001", "0022600001", "0022600001", "nan", "g1"]


def test_switch_is_off_when_absent_and_on_only_for_on_values(monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)
    assert scrape.history_fetch_bounded() is False
    for value in ("0", "off", "false", "", "maybe"):
        monkeypatch.setenv(SWITCH, value)
        assert scrape.history_fetch_bounded() is False, value
    for value in ("1", "on", "true", "YES"):
        monkeypatch.setenv(SWITCH, value)
        assert scrape.history_fetch_bounded() is True, value


def test_off_walks_every_game_and_keeps_appending_copies(fetch_env, monkeypatch):
    """Today's behaviour, pinned: the id mismatch asks for all 3 games and the save drops none of the old copies."""
    calls: list[str] = []
    _run(monkeypatch, calls)
    assert sorted(calls) == ["0022600001", "0022600002", "0022600003"]
    saved = pd.read_csv(fetch_env / "games_nba_api.csv")
    assert len(saved[saved["season"] == 2027]) == 4 + 3  # the 4 stored rows were never replaced, 3 appended


def test_on_walks_only_quarterless_games_newest_first_and_saves_one_row_per_game(fetch_env, monkeypatch):
    monkeypatch.setenv(SWITCH, "on")
    calls: list[str] = []
    _run(monkeypatch, calls)
    # game 1 already has quarters in one of its copies; game 3 (newest) is asked before game 2.
    assert calls == ["0022600003", "0022600002"]
    saved = pd.read_csv(fetch_env / "games_nba_api.csv", dtype={"game_id": str})
    season = saved[saved["season"] == 2027]
    assert len(season) == 3 and season["game_id"].nunique() == 3
    assert set(season["game_id"]) == {"0022600001", "0022600002", "0022600003"}
    assert season.set_index("game_id").loc["0022600001", "home_q1"] == 27.0  # the stored quarters were kept
    assert season["home_q1"].notna().all()
    assert len(saved[saved["season"] == 2026]) == 1  # the older season survives


def test_off_and_on_differ_through_the_real_fetch(fetch_env, monkeypatch, tmp_path):
    """Reachability: the switch must change what the real fetch does (calls and rows), not just a helper."""
    off_calls: list[str] = []
    _run(monkeypatch, off_calls)
    off_rows = len(pd.read_csv(fetch_env / "games_nba_api.csv"))
    _seed_history(fetch_env)
    monkeypatch.setenv(SWITCH, "1")
    on_calls: list[str] = []
    _run(monkeypatch, on_calls)
    on_rows = len(pd.read_csv(fetch_env / "games_nba_api.csv"))
    assert (len(off_calls), off_rows) != (len(on_calls), on_rows)
    assert len(on_calls) < len(off_calls) and on_rows < off_rows


def test_deadline_cuts_the_walk_and_the_history_is_still_written(fetch_env, monkeypatch, capsys):
    monkeypatch.setenv(SWITCH, "on")
    monkeypatch.setenv(scrape.LINESCORE_DEADLINE_ENV, "100")
    clock = [1000.0]
    monkeypatch.setattr(scrape.time, "monotonic", lambda: clock[0])
    calls: list[str] = []
    _run(monkeypatch, calls, clock=clock, step_s=150.0)  # each call "takes" 150 s, past the 100 s deadline
    assert calls == ["0022600003"]  # newest first, then the deadline stops the walk
    out = capsys.readouterr().out
    assert "LINESCORE_WALK bounded=1 to_fetch=2 attempted=1" in out and "skipped_deadline=1 deadline_hit=1" in out
    saved = pd.read_csv(fetch_env / "games_nba_api.csv", dtype={"game_id": str})
    season = saved[saved["season"] == 2027]
    assert set(season["game_id"]) == {"0022600001", "0022600002", "0022600003"}  # last night's final is in
    assert pd.isna(season.set_index("game_id").loc["0022600002", "home_q1"])  # left for the next fetch


def test_deadline_parse_falls_back_to_the_default(monkeypatch):
    for value in ("", "abc", "0", "-5"):
        monkeypatch.setenv(scrape.LINESCORE_DEADLINE_ENV, value)
        assert scrape.linescore_deadline_seconds() == scrape.DEFAULT_LINESCORE_DEADLINE_SECONDS
    monkeypatch.setenv(scrape.LINESCORE_DEADLINE_ENV, "240")
    assert scrape.linescore_deadline_seconds() == 240.0


def _props_module():
    spec = importlib.util.spec_from_file_location("refresh_nba_probe_fetch_bound", ROOT / "scripts" / "refresh_nba_oddsapi_props.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fetch_timeout_is_legacy_off_and_capped_on(monkeypatch):
    mod = _props_module()
    monkeypatch.delenv(SWITCH, raising=False)
    monkeypatch.delenv(mod.GAMES_HISTORY_FETCH_TIMEOUT_ENV, raising=False)
    assert mod._games_history_fetch_timeout_seconds() == 2700
    monkeypatch.setenv(SWITCH, "on")
    assert mod._games_history_fetch_timeout_seconds() == 900
    monkeypatch.setenv(mod.GAMES_HISTORY_FETCH_TIMEOUT_ENV, "600")
    assert mod._games_history_fetch_timeout_seconds() == 600
    for bad in ("abc", "0", "99999"):
        monkeypatch.setenv(mod.GAMES_HISTORY_FETCH_TIMEOUT_ENV, bad)
        assert mod._games_history_fetch_timeout_seconds() == 900, bad


@pytest.mark.parametrize("switch, expected", [(None, 2700), ("on", 900)])
def test_the_bootstrap_hands_the_fetch_its_timeout(tmp_path, monkeypatch, switch, expected):
    """Reachability through `_ensure_source_game_inputs`: the fetch call itself carries the bounded timeout."""
    mod = _props_module()
    if switch is None:
        monkeypatch.delenv(SWITCH, raising=False)
    else:
        monkeypatch.setenv(SWITCH, switch)
    monkeypatch.delenv(mod.GAMES_HISTORY_FETCH_TIMEOUT_ENV, raising=False)
    data = tmp_path / "data"
    (data / "raw").mkdir(parents=True)
    (data / "processed").mkdir()
    calls = []
    monkeypatch.setattr(mod, "_run_source_subprocess_cli_command",
                        lambda **kw: calls.append((kw["command_parts"], kw["timeout_s"])) or 0)
    for name in ("_seed_games_history_from_checkout_if_fresher", "_seed_game_odds_from_props_snapshot", "_seed_game_odds_from_raw_history"):
        monkeypatch.setattr(mod, name, lambda **kw: None)
    monkeypatch.setattr(mod, "_features_are_behind_history", lambda *a, **k: False)
    try:  # no history at all -> the 30-day rule fetches
        mod._ensure_source_game_inputs(source_root=tmp_path, package_name="nba_betting", date_str="2026-11-19",
                                       log_file=tmp_path / "run.log", heartbeat_cb=None)
    except Exception:
        pass  # later bootstrap steps need real inputs; only the fetch call is under test
    fetches = [timeout for parts, timeout in calls if parts and parts[0] == "fetch"]
    assert fetches == [expected], calls
    logged = (tmp_path / "run.log").read_text(encoding="utf-8") if (tmp_path / "run.log").exists() else ""
    assert ("GAMES_HISTORY_FETCH_BOUNDED timeout_s=900" in logged) is (switch == "on")
