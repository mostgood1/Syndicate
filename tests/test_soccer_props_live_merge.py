"""A scoped (live, --event-ids) soccer props capture replaces only its own events.

Lane `soccer-live-lane-priority` (2026-10-09). `refresh_odds_sources`' live step
writes the same `props/<date>.csv` (and `game_markets_<date>.json`) as the pregame
step, scoped to the matches in play, and the script used to REPLACE both files --
wiping the day's not-yet-started fixtures until the next pregame sweep.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def mod():
    path = Path(__file__).resolve().parents[1] / "scripts" / "fetch_soccer_oddsapi_props_local.py"
    spec = importlib.util.spec_from_file_location("test_fetch_soccer_props_merge_mod", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _prop(event_id, player, price):
    return {"league": "epl", "player": player, "market": "player_shots", "market_key": "player_shots",
            "line": 1.5, "over_price": price, "under_price": -price, "book": "fanduel",
            "event": f"E{event_id}", "event_id": event_id, "game_time": "2026-10-10T14:00:00Z",
            "home_team": "H", "away_team": "A"}


def _game(event_id, price):
    return {"event_id": event_id, "market_key": "btts", "side": "Yes", "line": None, "book": "fanduel", "price": price}


def _run(mod, monkeypatch, tmp_path, *, event_ids, fresh_props, fresh_games):
    out = tmp_path / "2026-10-09.csv"
    pd.DataFrame([_prop("live1", "Old Live", 100), _prop("later2", "Later Player", 120)]).to_csv(out, index=False)
    (tmp_path / "game_markets_2026-10-09.json").write_text(
        json.dumps({"rows": [_game("live1", 90), _game("later2", 110)]}), encoding="utf-8")
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    monkeypatch.setattr(mod, "_load_env", lambda: None)
    monkeypatch.setattr(mod, "fetch_events", lambda *a, **k: [{"id": "live1"}, {"id": "later2"}])
    monkeypatch.setattr(mod, "fetch_event_player_props", lambda *a, event_id, **k: {"id": event_id})
    monkeypatch.setattr(mod, "parse_event_to_rows", lambda payload, league: [r for r in fresh_props if r["event_id"] == payload["id"]])
    monkeypatch.setattr(mod, "parse_event_to_game_rows", lambda payload, league: [r for r in fresh_games if r["event_id"] == payload["id"]])
    monkeypatch.setattr(mod, "_append_soccer_prop_book_quotes", lambda **k: None)
    argv = ["x", "--league", "epl", "--out", str(out)]
    if event_ids:
        argv += ["--event-ids", event_ids]
    monkeypatch.setattr(sys, "argv", argv)
    assert mod.main() == 0
    props = pd.read_csv(out, dtype={"event_id": "string"})
    games = json.loads((tmp_path / "game_markets_2026-10-09.json").read_text(encoding="utf-8"))["rows"]
    return props, games


def test_a_live_capture_keeps_the_other_fixtures(mod, monkeypatch, tmp_path):
    props, games = _run(mod, monkeypatch, tmp_path, event_ids="live1",
                        fresh_props=[_prop("live1", "New Live", 150)], fresh_games=[_game("live1", 95)])
    assert sorted(props.player) == ["Later Player", "New Live"]  # later2 kept, live1 replaced
    assert {(g["event_id"], g["price"]) for g in games} == {("later2", 110), ("live1", 95)}


def test_a_scoped_event_that_came_back_empty_loses_its_rows(mod, monkeypatch, tmp_path):
    props, _ = _run(mod, monkeypatch, tmp_path, event_ids="live1", fresh_props=[], fresh_games=[_game("live1", 95)])
    assert list(props.player) == ["Later Player"]


def test_off_is_not_on_an_unscoped_capture_still_replaces_the_file(mod, monkeypatch, tmp_path):
    """Reachability: without --event-ids the file is rewritten whole, as before, so the
    kept rows above are the scoped merge's doing."""
    props, games = _run(mod, monkeypatch, tmp_path, event_ids=None,
                        fresh_props=[_prop("live1", "New Live", 150)], fresh_games=[_game("live1", 95)])
    assert list(props.player) == ["New Live"]
    assert [g["event_id"] for g in games] == ["live1"]


def test_espn_live_ids_resolve_to_the_odds_api_event_with_the_same_clubs(mod, monkeypatch, tmp_path):
    """The live scope passes ESPN ids (`live_state` keys). They never equal Odds API ids,
    so every in-play capture was PROPS_SCOPE_EMPTY (fleet 10-10: 0 of 555 live props fresh)."""
    import syndicate.features.soccer.sources as sources

    out = tmp_path / "2026-10-10.csv"
    pd.DataFrame([_prop("oddsLATER", "Later Player", 120)]).to_csv(out, index=False)
    monkeypatch.setattr(sources, "live_state_payload", lambda league, date: {"games": {
        "401878776": {"home_team": "Arsenal", "away_team": "Chelsea"}}})
    fetched = []
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    monkeypatch.setattr(mod, "_load_env", lambda: None)
    monkeypatch.setattr(mod, "fetch_events", lambda *a, **k: [
        {"id": "oddsLIVE", "home_team": "Arsenal FC", "away_team": "Chelsea FC"},
        {"id": "oddsLATER", "home_team": "Leeds United", "away_team": "Everton"}])
    monkeypatch.setattr(mod, "fetch_event_player_props", lambda *a, event_id, **k: fetched.append(event_id) or {"id": event_id})
    monkeypatch.setattr(mod, "parse_event_to_rows", lambda payload, league: [_prop(payload["id"], "Live Player", 200)])
    monkeypatch.setattr(mod, "parse_event_to_game_rows", lambda payload, league: [])
    monkeypatch.setattr(mod, "_append_soccer_prop_book_quotes", lambda **k: None)
    monkeypatch.setattr(sys, "argv", ["x", "--league", "epl", "--out", str(out), "--event-ids", "401878776"])
    assert mod.main() == 0
    assert fetched == ["oddsLIVE"]
    props = pd.read_csv(out, dtype={"event_id": "string"})
    assert sorted(props.player) == ["Later Player", "Live Player"]
