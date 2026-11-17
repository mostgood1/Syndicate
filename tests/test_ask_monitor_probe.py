"""Read-only Ask monitor probe (lane ask-engine-monitor): the log parser, the row -> ask mapping, the answer summary."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location("ask_monitor_probe",
                                               Path(__file__).resolve().parents[1] / "scripts" / "ask_monitor_probe.py")
amp = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = amp
_spec.loader.exec_module(amp)

SINCE = dt.datetime(2026, 11, 17, 16, 0, tzinfo=dt.timezone.utc)
LOG = [
    # before the window: never counted
    '2026-11-17T15:23:37.696Z [2026-11-17 09:23:37 -0600] [438] [CRITICAL] WORKER TIMEOUT (pid:4012882)',
    '2026-11-17T16:49:49.857Z [2026-11-17 10:49:49 -0600] [438] [CRITICAL] WORKER TIMEOUT (pid:4035235)',
    '2026-11-17T16:49:51.998Z [2026-11-17 10:49:51 -0600] [438] [ERROR] Worker (pid:4035235) was sent SIGKILL!',
    '2026-11-17T16:53:41.776Z WEB_WORKER_MEMORY_RECYCLE {"age_s": 228.5, "anon_mb": 820.2, "hard": true, '
    '"last_recycle_age_s": 76.9, "limit_mb": 648.5, "pid": 4041177, "requests": 25}',
    '2026-11-17T16:54:48.925Z [intelligence_state] COMBINED_BOARD_OVERLAY_WARMED dates=3 sport=all '
    'overlay_age_s=0.4 build_s=45.11 rebuilt=True',
    '2026-11-17T16:51:52.722Z [intelligence_state] COMBINED_BOARD_OVERLAY_WARMED dates=3 sport=all '
    'overlay_age_s=1.0 build_s=64.45 rebuilt=True',
    '2026-11-17T16:50:24.927Z 127.0.0.1 - - [17/Nov/2026:10:50:24 -0600] "POST /api/syndicate/query HTTP/1.1" '
    '200 123196 "-" "curl/8.14.1" 26629ms',
    '2026-11-17T16:52:56.643Z 127.0.0.1 - - [17/Nov/2026:10:52:56 -0600] "POST /api/intelligence/query HTTP/1.1" '
    '200 6100000 "http://127.0.0.1:10000/intelligence" "Mozilla/5.0" 38246ms',
    '2026-11-17T16:53:04.602Z 127.0.0.1 - - [17/Nov/2026:10:53:04 -0600] "POST /api/intelligence/query?x=1 HTTP/1.1" '
    '200 6100000 "-" "Mozilla/5.0" 51000ms',
    '2026-11-17T16:54:00.491Z 127.0.0.1 - - [17/Nov/2026:10:54:00 -0600] "POST /api/syndicate/query HTTP/1.1" '
    '500 90 "-" "curl/8.14.1" 529ms',
    'a continuation line with no stamp',
]


def test_parse_log_counts_only_the_window_with_denominators():
    w = amp.parse_log(LOG, SINCE)
    assert w["worker_timeouts"] == ["2026-11-17T16:49:49.857Z"]          # the 15:23 kill is before the window
    assert w["requests"] == 4
    assert w["recycles"] == {"n": 1, "hard": 1, "max_anon_mb": 820.2, "limit_mb": 648.5}
    ow = w["overlay_warms"]
    assert (ow["n"], ow["over_20s"], ow["over_45s"], ow["over_60s"], ow["max_s"]) == (2, 2, 2, 1, 64.45)
    assert w["slow_over_20s"] == {"POST /api/intelligence/query": 2, "POST /api/syndicate/query": 1}
    assert w["over_45s"] == {"POST /api/intelligence/query": 1}           # the query string is dropped
    asks = w["asks_any_client"]
    assert (asks["n"], asks["over_45s"], asks["non_200"]) == (2, 0, 1)


def test_row_context_matches_the_ask_bar_keys():
    game = {"sport": "NCAAB", "market": "h2h", "side": "home", "line": None, "segment": "full",
            "event_id": "f427", "home_team": "Wisconsin Badgers", "away_team": "Marquette Golden Eagles",
            "quote": {"price": -270}}
    ctx = amp.row_context(game)
    assert ctx == {"sport": "ncaab", "market": "h2h", "selection": "Wisconsin Badgers",
                   "matchup": "Marquette Golden Eagles @ Wisconsin Badgers", "name": "Wisconsin Badgers",
                   "event_id": "f427", "side": "home", "segment": "full", "odds": "-270"}
    assert amp.row_question(ctx) == "What's the case for and against Wisconsin Badgers?"
    total = dict(game, market="totals", side="under", line=141.5)
    assert amp.row_question(amp.row_context(total)) == \
        "What's the case for and against Under 141.5 in Marquette Golden Eagles @ Wisconsin Badgers?"
    prop = dict(game, market="player_points", side="over", line=18.5, player_name="John Blackwell")
    pctx = amp.row_context(prop)
    assert pctx["player_name"] == "John Blackwell" and pctx["name"] == "John Blackwell"
    assert amp.row_question(pctx) == "What's the case for and against John Blackwell Over 18.5?"


def test_pick_rows_takes_one_of_each_kind_in_order():
    rows = [{"event_id": "a", "market": "player_points", "player_name": "x"},
            {"event_id": "b", "market": "spreads"},
            {"event_id": "", "market": "h2h"},                                  # no identity: never asked
            {"event_id": "c", "market": "totals", "is_live": True},
            {"event_id": "d", "market": "h2h"}]
    assert [(k, r["event_id"]) for k, r in amp.pick_rows(rows)] == \
        [("pregame_game_line", "b"), ("pregame_prop", "a"), ("live_row", "c")]


def test_summarise_answer_and_the_cutoff(monkeypatch):
    now = dt.datetime(2026, 11, 17, 17, 0, tzinfo=dt.timezone.utc)
    raw = json.dumps({"ok": True, "schema_type": "bet_analysis", "answer_source": "snapshot", "routed_sport": None,
                      "visuals": {"as_of": "2026-11-17T16:58:10Z", "tables": [{}, {}], "charts": [{}]}}).encode()
    s = amp.summarise_answer(raw, now)
    assert (s["ok"], s["as_of_age_s"], s["tables"], s["charts"], s["named_bet"]) == (True, 110, 2, 1, False)
    assert amp.summarise_answer(b"<html>", now) == {"json": False}
    naive = json.dumps({"ok": True, "visuals": {"as_of": "2026-11-17T16:59:00"}}).encode()   # no zone: read as UTC
    assert amp.summarise_answer(naive, now)["as_of_age_s"] == 60
    day = amp.summarise_answer(json.dumps({"ok": True, "visuals": {"as_of": "2026-11-17"}}).encode(), now)
    assert (day["as_of_kind"], day["as_of_age_s"], day["as_of_in_future"]) == ("date", None, False)
    ahead = amp.summarise_answer(json.dumps({"ok": True, "visuals": {"as_of": "2026-11-20"}}).encode(), now)
    assert ahead["as_of_in_future"] is True                                  # a fixture date is not a data time

    def slow(method, url, body=None, timeout=0):
        return 200, 46.0, raw, None

    monkeypatch.setattr(amp, "_http", slow)
    a = amp.ask("http://x", "q", {})
    assert a["user_saw_timeout"] is True and a["answered"] is False         # 200 and ok, but past the 45 s cut-off
