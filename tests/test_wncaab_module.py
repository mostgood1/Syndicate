"""Women's college basketball (WNCAAB), built on the shared college-basketball code (lane wncaab-module).

Women play four 10-minute quarters; every piece that NCAAB hard-coded as two halves is checked here,
and NCAAB's own values are checked unchanged alongside.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from syndicate.features.college_basketball.league import NCAAB, WNCAAB, league_for
from syndicate.features.ncaab import slate
from syndicate.features.shared.game_chip_scoreboard import GAME_CHIP_DEFAULT_SPORTS, build_game_chip

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_league_config_keeps_ncaab_and_adds_wncaab():
    assert league_for("ncaab") is NCAAB and league_for("WNCAAB") is WNCAAB
    assert NCAAB.oddsapi_key == "basketball_ncaab" and WNCAAB.oddsapi_key == "basketball_wncaab"
    assert "mens-college-basketball" in NCAAB.scoreboard_url and "womens-college-basketball" in WNCAAB.scoreboard_url
    assert "groups=50" in WNCAAB.scoreboard_url
    assert slate.SCOREBOARD_URL == NCAAB.scoreboard_url  # the men's URL is byte-identical to what shipped
    assert [NCAAB.period_label(p) for p in (1, 2, 3, 4)] == ["H1", "H2", "OT", "2OT"]
    assert [WNCAAB.period_label(p) for p in (1, 4, 5, 6)] == ["Q1", "Q4", "OT", "2OT"]
    with pytest.raises(ValueError):
        league_for("nba")


def test_womens_registry_and_aliases():
    from syndicate.features.shared.ncaab_team_registry import registry_rows
    from syndicate.features.shared.team_aliases import chip_join_key

    rows = registry_rows("wncaab")
    assert len(rows) >= 350
    ids = {r["espn_id"] for r in rows}
    assert {"2511", "88", "2815"} <= ids  # Queens, Southern Indiana, Lindenwood are in ESPN's women's list
    assert chip_join_key("wncaab", "Tennessee Lady Volunteers") == "tennessee"
    assert chip_join_key("wncaab", "Georgia St Panthers") == chip_join_key("wncaab", "Georgia State Panthers")
    assert len(registry_rows("ncaab")) == len(registry_rows())  # the men's default is unchanged


def _event(event_id, away_id, home_id, *, state="in", period=3, clock="4:12", lines=((15, 14, 12), (17, 10, 13))):
    def comp(tid, side, pts):
        return {"homeAway": side, "score": str(sum(pts)), "linescores": [{"value": v} for v in pts],
                "team": {"id": tid, "displayName": f"Team {tid}", "abbreviation": f"T{tid}", "logo": f"https://logo/{tid}.png"}}

    return {"id": event_id, "date": "2026-11-03T23:00Z", "competitions": [{
        "neutralSite": False, "competitors": [comp(away_id, "away", lines[0]), comp(home_id, "home", lines[1])],
        "status": {"period": period, "displayClock": clock, "type": {"state": state, "completed": False, "shortDetail": f"{clock} - 3rd"}}}]}


def test_womens_slate_chip_reads_quarters():
    games, dropped = slate.parse_scoreboard({"events": [_event("1", "10", "20"), _event("2", "10", "999")]}, d1_ids=frozenset({"10", "20"}))
    assert dropped == 1 and len(games) == 1
    chip = build_game_chip("wncaab", games[0])
    assert chip["state"] == "live" and chip["status_token"] == "Q3 4:12"
    assert chip["away"]["logo"] == "https://logo/10.png"  # no branding index: the slate's own ESPN logo
    from syndicate.features.shared.game_chip_linescore import linescore

    box = linescore("wncaab", games[0], "2026-11-03")
    assert box["labels"] == ["1", "2", "3"] and box["away"] == [15, 14, 12]
    ot = build_game_chip("wncaab", {"live_state": {"in_progress": True, "period": 5, "clock": "2:00"}, "away": {"abbr": "A", "score": 70}, "home": {"abbr": "B", "score": 70}})
    assert ot["status_token"] == "OT 2:00"
    assert "wncaab" in GAME_CHIP_DEFAULT_SPORTS


def test_womens_slate_artifact_lives_in_its_own_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(slate, "_d1_ids", lambda league="ncaab": frozenset({"10", "20"}))
    seen = []
    art = slate.refresh_slate("2026-11-03", league="wncaab", fetch_json=lambda url: seen.append(url) or {"events": [_event("1", "10", "20")]})
    assert art["league"] == "wncaab" and len(art["games"]) == 1
    assert "womens-college-basketball" in seen[0] and "groups=50" in seen[0]
    assert (tmp_path / "wncaab_source" / "data" / "scoreboard" / "scoreboard_2026-11-03.json").exists()
    assert not (tmp_path / "ncaab_source").exists()
    assert slate.slate_games("2026-11-03", refresh=False, league="wncaab")[0]["event_id"] == "1"


def test_fetcher_asks_only_open_quarters_and_labels_them():
    module = _load("ncaab_odds_wncaab", "scripts/refresh_ncaab_odds_history.py")
    assert module.TheOddsApiClient._infer_period_from_key("totals_q3") == "q3"
    now = dt.datetime(2026, 11, 3, 1, 0, tzinfo=dt.timezone.utc)
    segments = ["spreads_q1", "totals_q1", "spreads_q2", "spreads_q3", "spreads_q4", "spreads_h1", "spreads_h2"]

    def wanted(minutes, league):
        return [m for m in segments if module._segment_open(m, minutes, league)]

    assert wanted(-10, "wncaab") == ["spreads_q1", "totals_q1", "spreads_h1"]
    assert wanted(20, "wncaab") == ["spreads_q1", "totals_q1", "spreads_q2", "spreads_h1"]
    assert wanted(45, "wncaab") == ["spreads_q2", "spreads_q3", "spreads_h1", "spreads_h2"]
    assert wanted(100, "wncaab") == ["spreads_q4", "spreads_h2"]
    # NCAAB's rule is untouched: both halves pre-tip, first half dropped after 75 min.
    assert [m for m in ("spreads_h1", "spreads_h2") if module._segment_open(m, 74, "ncaab")] == ["spreads_h1", "spreads_h2"]
    assert [m for m in ("spreads_h1", "spreads_h2") if module._segment_open(m, 76, "ncaab")] == ["spreads_h2"]
    assert module._QUOTE_SEGMENT["q3"] == "q3"


def test_orchestrator_knows_wncaab(monkeypatch):
    ros = _load("ros_wncaab", "scripts/refresh_odds_sources.py")
    assert "wncaab" in ros.REGISTRY
    assert "spreads_q1" in ros._effective_markets("wncaab", "") and "spreads_h2" in ros._effective_markets("wncaab", "")
    args = argparse.Namespace(date="2026-11-03", regions="us", markets="", phase="live", force_refresh=True, force_refresh_sports="wncaab")
    step = ros._build_wncaab_steps(args)[0]
    assert "--league" in step.command and "wncaab" in step.command
    assert ros._in_play_only_scope(args, "wncaab") is True
    assert "--in-play-only" in ros._step_command_with_mode(step, "fast", force_refresh=True, in_play_only=True)
    monkeypatch.setenv("SYNDICATE_WNCAAB_IN_PLAY_ONLY", "0")
    assert ros._in_play_only_scope(args, "wncaab") is False


def test_wncaab_inplay_lane_launches_its_own_lane(monkeypatch):
    from syndicate.features.ncaab import inplay_lane

    monkeypatch.setattr(inplay_lane, "central_today_iso", lambda: "2026-11-03")
    monkeypatch.setattr(inplay_lane, "ncaab_live_game_count", lambda d, league="ncaab": 2 if league == "wncaab" else 0)
    store: dict = {}
    monkeypatch.setattr(inplay_lane, "read_json_file", lambda path: store.get(str(path)))
    monkeypatch.setattr(inplay_lane, "write_json_file", lambda path, payload: store.__setitem__(str(path), payload))
    launches: list = []
    monkeypatch.setattr(inplay_lane, "launch_refresh_run", lambda **kw: launches.append(kw) or {"runStamp": "r"})
    assert inplay_lane.launch_autorun_wncaab_live_refresh()["live_games"] == 2
    assert launches[0]["sports"] == "wncaab" and launches[0]["lane"] == "live-odds-worker-wncaab-live"
    assert any(k.endswith("wncaab_live_autorun_status.json") for k in store)
    assert inplay_lane.launch_autorun_ncaab_live_refresh() is None  # the men's lane sees no live game here


def test_provider_routes_and_nav(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    path = slate.slate_artifact_path("2026-11-03", "wncaab")
    path.parent.mkdir(parents=True)
    games, _ = slate.parse_scoreboard({"events": [_event("7", "10", "20", state="pre", period=0, clock="0:00")]}, d1_ids=frozenset({"10", "20"}))
    path.write_text(json.dumps({"games": games}), encoding="utf-8")
    from syndicate.app import app
    from syndicate.features.shared.sport_data_provider import get_sport_data_provider

    provider = get_sport_data_provider("wncaab")
    assert provider is not None
    assert [g["event_id"] for g in provider.games(provider.resolve_context(requested_date="2026-11-03"), is_active_today=False)] == ["7"]
    client = app.test_client()
    page = client.get("/wncaab/cards?date=2026-11-03")
    assert page.status_code == 200 and 'data-cards-payload-path="/wncaab/api/source/cards"' in page.get_data(as_text=True)
    api = client.get("/wncaab/api/source/cards?date=2026-11-03").get_json()
    assert api["board_contract"]["sport"] == "wncaab" and api["games"][0]["gameType"] == "WNCAAB"
    assert client.get("/wncaab/market-board?date=2026-11-03").status_code == 200
    assert any(s.get("slug") == "wncaab" for s in app.config.get("SYNDICATE_SPORTS", []))
