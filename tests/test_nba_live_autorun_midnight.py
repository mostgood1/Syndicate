"""An NBA game still in play at midnight Central keeps its quote pulls (todo #782, lane `nba-quote-capture-midnight`).

11-11 on the fleet: the lens and the re-sim carried OKC @ POR past the roll (`#776`/`#777`), and the carryover board's
props join read `considered=293 projected=230` -- then the served board had 0 NBA rows. The live-odds-worker's NBA
in-play lane asks "is a game live TODAY?", so its last pull was 05:59:52Z (`NBA_LIVE_AUTORUN_LAUNCHED date=2026-11-10`
every ~240 s until then, none after), the 11-10 shard's last write 05:59:54Z, and by the 06:05Z rebuild the opportunity
gate put 6,983 of 6,991 NBA candidates in `dead`. These tests run the lane's real launch decision through the real
re-sim window (`SYNDICATE_NBA_LIVE_RESIM_PRIOR_DATE_HOURS`, absent = 4 h, "0" = off) and the real fetcher's date and
in-play filters, and check the gate's dead reasons now reach the ingest.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from syndicate.features.nba import live_lens
from syndicate.features.nba import live_resim as lr
from syndicate.features.shared import live_refresh_loop

ROOT = Path(__file__).resolve().parents[1]
PRIOR, TODAY = "2026-11-10", "2026-11-11"
ROLL_PLUS_5 = datetime(2026, 11, 11, 6, 5, tzinfo=timezone.utc)        # 00:05 CST 11-11
PAST_WINDOW = datetime(2026, 11, 11, 10, 30, tzinfo=timezone.utc)      # 04:30 CST: 4 h window closed
OKC_POR = "401909965"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _resim(*, date: str = TODAY, generated: datetime = ROLL_PLUS_5 - timedelta(seconds=60), rows=None) -> dict:
    if rows is None:
        rows = [{"event_id": OKC_POR, lr.SLATE_DATE_KEY: PRIOR, "status": {"detailedState": "In Progress"}}]
    return {"date": date, "generatedAt": generated.isoformat(), "games": rows}


@pytest.fixture()
def resim_file(monkeypatch):
    """The re-sim snapshot `prior_slate_in_play` reads, through the reader the lens module calls."""
    box = {"doc": _resim()}
    path = str(lr.live_lens_snapshot_path())
    monkeypatch.setattr(live_lens, "read_json_file", lambda p: box["doc"] if str(p) == path else None)
    monkeypatch.delenv(lr.PRIOR_DATE_HOURS_ENV, raising=False)
    return box


# ------------------------------------------------------------------------------------------- the signal (lens)

def test_the_previous_dates_game_in_play_is_named_inside_the_window(resim_file):
    assert live_lens.prior_slate_in_play(ROLL_PLUS_5) == (PRIOR, [OKC_POR])


def test_off_is_not_on_through_the_env(resim_file, monkeypatch):
    monkeypatch.setenv(lr.PRIOR_DATE_HOURS_ENV, "0")
    assert live_lens.prior_slate_in_play(ROLL_PLUS_5) == (None, [])
    monkeypatch.delenv(lr.PRIOR_DATE_HOURS_ENV)
    assert live_lens.prior_slate_in_play(ROLL_PLUS_5) == (PRIOR, [OKC_POR])


def test_outside_the_window_there_is_no_previous_date(resim_file):
    assert live_lens.prior_slate_in_play(PAST_WINDOW) == (None, [])


def test_a_stale_missing_or_naive_resim_file_names_no_game(resim_file):
    resim_file["doc"] = _resim(generated=ROLL_PLUS_5 - timedelta(seconds=live_lens.PRIOR_SLATE_IN_PLAY_MAX_AGE_SECONDS + 1))
    assert live_lens.prior_slate_in_play(ROLL_PLUS_5) == (PRIOR, [])         # a stopped re-sim must not keep paying
    resim_file["doc"] = None
    assert live_lens.prior_slate_in_play(ROLL_PLUS_5) == (PRIOR, [])
    resim_file["doc"] = {**_resim(), "generatedAt": "2026-11-11T06:04:00"}   # no offset: unknown is not fresh
    assert live_lens.prior_slate_in_play(ROLL_PLUS_5) == (PRIOR, [])


def test_only_the_previous_dates_rows_in_progress_count(resim_file):
    resim_file["doc"] = _resim(rows=[
        {"event_id": "refused", lr.SLATE_DATE_KEY: PRIOR, "status": {"detailedState": "Unknown"}},
        {"event_id": "today", "status": {"detailedState": "In Progress"}},              # the snapshot's own date
        {"event_id": OKC_POR, lr.SLATE_DATE_KEY: PRIOR, "status": {"detailedState": "In Progress"}},
        {"event_id": OKC_POR, lr.SLATE_DATE_KEY: PRIOR, "status": {"detailedState": "In Progress"}},
    ])
    assert live_lens.prior_slate_in_play(ROLL_PLUS_5) == (PRIOR, [OKC_POR])


def test_the_pre_midnight_resim_file_counts_for_the_previous_date(resim_file):
    # Its first post-roll tick has not run yet: the whole file is the previous date's, no `slateDate` on its rows.
    resim_file["doc"] = _resim(date=PRIOR, rows=[{"event_id": OKC_POR, "status": {"detailedState": "In Progress"}}])
    assert live_lens.prior_slate_in_play(ROLL_PLUS_5) == (PRIOR, [OKC_POR])


# --------------------------------------------------------------------------------------- the lane (worker)

@pytest.fixture()
def worker(tmp_path, monkeypatch, resim_file):
    mod = _load("nba_live_worker_midnight_test", "scripts/run_live_odds_refresh_worker.py")
    store: dict = {}
    monkeypatch.setattr(mod, "reports_root", lambda: tmp_path)
    monkeypatch.setattr(mod, "read_json_file", lambda path: store.get(str(path)))
    monkeypatch.setattr(mod, "write_json_file", lambda path, doc: store.__setitem__(str(path), dict(doc)))
    monkeypatch.setattr(mod, "central_today_iso", lambda: TODAY)
    live = {"days": set()}
    monkeypatch.setattr(live_refresh_loop, "_nba_has_live_game", lambda day: day in live["days"])
    calls: list = []
    monkeypatch.setattr(mod, "launch_refresh_run", lambda **kw: calls.append(kw) or {"runStamp": "r1"})
    monkeypatch.delenv("SYNDICATE_ENABLE_NBA_LIVE_REFRESH_AUTORUN", raising=False)
    # The lane calls `prior_slate_in_play()` on the wall clock; pin the re-sim window's clock and the file's age
    # to 00:05 CST 11-11. Everything else is the real code path.
    original = live_lens.prior_slate_in_play
    monkeypatch.setattr(live_lens, "prior_slate_in_play", lambda now=None: original(now or ROLL_PLUS_5))
    mod._calls, mod._store, mod._live = calls, store, live
    return mod


def test_after_the_roll_the_lane_pulls_the_previous_date_while_its_game_is_in_play(worker, capsys):
    worker._launch_autorun_nba_live_refresh()
    assert len(worker._calls) == 1
    kw = worker._calls[0]
    assert kw["date"] == PRIOR                                     # the shard and snapshot the carryover reads
    assert (kw["sports"], kw["phase"], kw["mode"], kw["force_refresh"]) == ("nba", "live", "fast", True)
    assert kw["lane"] == "live-odds-worker-nba-live"
    assert "NBA_LIVE_AUTORUN_LAUNCHED date=2026-11-10" in capsys.readouterr().out
    worker._launch_autorun_nba_live_refresh()                      # the same 240 s interval applies
    assert len(worker._calls) == 1


def test_off_is_not_on_at_the_lane(worker, monkeypatch):
    monkeypatch.setenv(lr.PRIOR_DATE_HOURS_ENV, "0")
    worker._launch_autorun_nba_live_refresh()
    assert worker._calls == []                                     # exactly the behaviour before #782
    monkeypatch.delenv(lr.PRIOR_DATE_HOURS_ENV)
    worker._launch_autorun_nba_live_refresh()
    assert [kw["date"] for kw in worker._calls] == [PRIOR]


def test_a_live_game_today_wins(worker):
    worker._live["days"].add(TODAY)
    worker._launch_autorun_nba_live_refresh()
    assert [kw["date"] for kw in worker._calls] == [TODAY]


def test_no_previous_date_game_in_play_launches_nothing(worker, resim_file):
    resim_file["doc"] = _resim(rows=[{"event_id": OKC_POR, lr.SLATE_DATE_KEY: PRIOR,
                                      "status": {"detailedState": "Unknown"}}])
    worker._launch_autorun_nba_live_refresh()
    assert worker._calls == []


def test_a_broken_signal_never_breaks_the_lane(worker, monkeypatch, capsys):
    def boom(now=None):
        raise RuntimeError("redis down")

    monkeypatch.setattr(live_lens, "prior_slate_in_play", boom)
    worker._launch_autorun_nba_live_refresh()
    assert worker._calls == []
    assert "NBA_LIVE_AUTORUN_PRIOR_SLATE_ERROR RuntimeError: redis down" in capsys.readouterr().out


# ------------------------------------------------------------------------------------ the fetch it launches

def test_the_fetch_for_the_previous_date_takes_the_game_still_in_play(monkeypatch):
    """`--date 2026-11-10 --in-play-only` at 00:05 CST: OKC @ POR (tip 04:14Z, 10:14 PM CST) is that date's game and
    within 3 h of tip, so it is fetched; the next date's games are not."""
    fetch = _load("fetch_bball_props_midnight_test", "scripts/fetch_basketball_oddsapi_props_local.py")
    events = [{"id": OKC_POR, "commence_time": "2026-11-11T04:14:00Z", "home_team": "Portland Trail Blazers",
               "away_team": "Oklahoma City Thunder"},
              {"id": "tomorrow", "commence_time": "2026-11-12T00:30:00Z", "home_team": "H", "away_team": "A"}]
    asked: list[str] = []

    class Resp:
        def __init__(self, payload):
            self._p = payload

        def json(self):
            return self._p

    def fake_get(url, params):
        asked.append(url)
        if url.endswith("/events"):
            return Resp(events)
        if url.endswith("/markets"):
            return Resp({"bookmakers": [{"markets": [{"key": "player_points"}]}]})
        eid = url.split("/events/")[1].split("/")[0]
        return Resp({"id": eid, "commence_time": "2026-11-11T04:14:00Z", "home_team": "Portland Trail Blazers",
                     "away_team": "Oklahoma City Thunder", "bookmakers": [{"key": "draftkings", "title": "DK",
                     "markets": [{"key": "player_points", "outcomes": [
                         {"name": "Over", "description": "Shai Gilgeous-Alexander", "point": 30.5, "price": -110}]}]}]})

    monkeypatch.setattr(fetch, "_get", fake_get)
    monkeypatch.setattr(fetch, "league_sport_keys", lambda league: ("basketball_nba",))
    df = fetch.fetch_player_props_current(api_key="k", league="nba", date_str=PRIOR, regions="us", bookmakers=None,
                                          markets=["player_points"], in_play_only=True,
                                          now=pd.Timestamp(ROLL_PLUS_5))
    assert set(df["event_id"]) == {OKC_POR}
    assert not any("/events/tomorrow/" in u for u in asked)


# ---------------------------------------------------------------------------------- why rows go dead (ingest)

def test_dead_rows_are_counted_by_state_and_reason():
    from syndicate.features.shared.layer2_board import build_layer2_rows

    def row(event_id: str, state: str, age: float) -> dict:
        return {"sport": "nba", "event_id": event_id, "kind": "game", "market": "totals", "segment": "full",
                "line": 220.5, "player_name": None, "home_team": "Portland Trail Blazers",
                "away_team": "Oklahoma City Thunder", "commence_time": "2026-11-11T04:14:00Z",
                "sides": ["over", "under"], "books_quoting": 9, "game": {"state": state, "status_token": "Q4"},
                "best": {"over": {"price": -110, "bookmaker": "draftkings", "age_seconds": age, "books_quoting": 9},
                         "under": {"price": -110, "bookmaker": "draftkings", "age_seconds": age, "books_quoting": 9}}}

    result = build_layer2_rows([row("e1", "final", 30.0), row("e2", "live", 5000.0)])
    assert result["by_lane"].get("dead") == 4
    assert result["dead_by_reason"] == {"final:game_final": 2, "live:live_market_stale": 2}
    assert build_layer2_rows([])["dead_by_reason"] == {}


def test_the_ingest_names_the_dead_reasons(monkeypatch):
    """Through the real `build_layer2_shortlist`: `per_sport_ingest` is an explicit key list (#444), so a producer key
    reaches nobody until it is named there. A pregame market last priced 2 days ago is `pregame_market_stale`."""
    from pipeline.layer2_shortlist import build_layer2_shortlist

    stale = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    quotes = []
    for book, home, away in (("draftkings", -120, 105), ("fanduel", -115, 100)):
        for selection, price in (("home", home), ("away", away)):
            quotes.append({"sport": "mlb", "kind": "game", "event_id": "evt-1", "segment": "full_game",
                           "market": "h2h", "player_name": "", "selection": selection, "line": None, "price": price,
                           "bookmaker": book, "home_team": "Baltimore Orioles", "away_team": "Los Angeles Angels",
                           "commence_time": "2026-08-08T23:05:00Z", "snapshot_ts": stale})
    monkeypatch.setattr("syndicate.features.shared.odds_book_quotes.read_book_quotes_latest",
                        lambda sport, date_str: quotes if str(sport).lower() == "mlb" else [])
    for key, value in (("SYNDICATE_SHORTLIST_MIN_VALUE_PCT", "-99999"), ("SYNDICATE_SHORTLIST_MAX_QUOTE_AGE_SECONDS", "0"),
                       ("SYNDICATE_SHORTLIST_STALE_KICKOFF_SECONDS", "0"),
                       ("SYNDICATE_GATE_DEMOTE_UNKNOWN_GAME_STATE", "0")):
        monkeypatch.setenv(key, value)
    ingest = build_layer2_shortlist("2026-08-08", ["mlb"])["per_sport_ingest"]["mlb"]
    assert ingest["by_lane"].get("dead") == 2
    assert ingest["dead_by_reason"] == {"pregame:pregame_market_stale": 2}
