"""NBA preseason odds come from OddsAPI's own `basketball_nba_preseason` key.

OddsAPI splits the preseason out the way it does `icehockey_nhl_preseason`, and
nothing asked for it, so every NBA preseason day read as "no games" and the
vendored NBA repo fell back to Bovada's `nba-pre-season` scrape. The Bovada
game-odds uses are removed (user decision 2026-10-02).

The vendored NBA package runs in a SUBPROCESS with its `src` on PYTHONPATH, so
this process's sys.path/sys.modules stay untouched.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import unittest
from unittest import mock

import pandas as pd

from scripts import fetch_basketball_oddsapi_props_local as fetcher

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NBA_SRC = os.path.join(REPO_ROOT, "vendor", "nba_betting_repo", "src")

PRESEASON_EVENT = {"id": "evt-pre-1", "commence_time": "2026-10-03T23:00:00Z",
                   "home_team": "Toronto Raptors", "away_team": "Miami Heat"}
EVENT_ODDS = {**PRESEASON_EVENT, "bookmakers": [{
    "key": "draftkings", "title": "DraftKings", "last_update": "2026-10-02T16:00:00Z",
    "markets": [{"key": "player_points", "last_update": "2026-10-02T16:00:00Z", "outcomes": [
        {"name": "Over", "description": "Bam Adebayo", "price": -110, "point": 17.5},
        {"name": "Under", "description": "Bam Adebayo", "price": -110, "point": 17.5}]}]}]}


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status
        self.headers = {}
        self.url = "https://example.invalid"

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def _router(regular, preseason, *, fail=()):
    calls = []

    def fake_get(url, params):
        calls.append(url)
        for key in fail:
            if url.endswith(f"/sports/{key}/events"):
                raise RuntimeError(f"listing failed for {key}")
        if url.endswith("/sports/basketball_nba/events"):
            return _Resp(regular)
        if url.endswith("/sports/basketball_nba_preseason/events"):
            return _Resp(preseason)
        if url.endswith("/markets"):
            return _Resp({"bookmakers": [{"markets": [{"key": "player_points"}]}]})
        if url.endswith("/odds"):
            return _Resp(EVENT_ODDS)
        raise AssertionError(f"unexpected url {url}")

    return fake_get, calls


def _fetch(regular, preseason, fail=()):
    fake_get, calls = _router(regular, preseason, fail=fail)
    with mock.patch.object(fetcher, "_get", side_effect=fake_get):
        out = fetcher.fetch_player_props_current(api_key="k", league="nba", date_str="2026-10-03",
                                                 regions="us", bookmakers=None, markets=["player_points"])
    return out, calls


class SyndicatePropsFetcherTests(unittest.TestCase):
    def test_nba_lists_regular_and_preseason(self) -> None:
        self.assertEqual(fetcher.league_sport_keys("nba"), ("basketball_nba", "basketball_nba_preseason"))
        self.assertEqual(fetcher.league_sport_keys("wnba"), ("basketball_wnba",))

    def test_preseason_event_is_priced_under_its_own_key(self) -> None:
        out, calls = _fetch(regular=[], preseason=[PRESEASON_EVENT])
        self.assertIsInstance(out, pd.DataFrame)
        self.assertFalse(out.empty)
        priced = [u for u in calls if u.endswith("/odds") or u.endswith("/markets")]
        self.assertTrue(priced and all("/sports/basketball_nba_preseason/events/evt-pre-1/" in u for u in priced), priced)

    def test_none_only_when_every_listing_succeeded_with_no_game(self) -> None:
        out, _ = _fetch(regular=[], preseason=[])
        self.assertIsNone(out)

    def test_a_failed_listing_makes_an_empty_day_inconclusive(self) -> None:
        out, _ = _fetch(regular=[], preseason=[], fail=("basketball_nba_preseason",))
        self.assertIsInstance(out, pd.DataFrame)
        self.assertTrue(out.empty)


def _run_vendor(code: str) -> dict:
    env = dict(os.environ, PYTHONPATH=NBA_SRC)
    done = subprocess.run([sys.executable, "-c", textwrap.dedent(code)], capture_output=True, text=True,
                          env=env, cwd=REPO_ROOT, timeout=180)
    if done.returncode != 0:
        raise AssertionError(f"subprocess rc={done.returncode}\n{done.stderr[-3000:]}")
    return json.loads(done.stdout.strip().splitlines()[-1])


class VendoredNbaTests(unittest.TestCase):
    def test_game_odds_list_both_keys_and_price_each_under_its_own(self) -> None:
        out = _run_vendor(f"""
            import json
            from unittest import mock
            import nba_betting.odds_api as oa
            pre = {json.dumps(PRESEASON_EVENT)}
            calls = []
            class R:
                def __init__(self, p): self.p = p
                def json(self): return self.p
            def fake(url, params):
                calls.append(url)
                if url.endswith("/sports/basketball_nba/events"): return R([])
                if url.endswith("/sports/basketball_nba_preseason/events"): return R([pre])
                if url.endswith("/odds"): return R(dict(pre, bookmakers=[]))
                raise AssertionError(url)
            cfg = oa.OddsApiConfig(api_key="k")
            with mock.patch.object(oa, "_get", side_effect=fake):
                oa.fetch_game_odds_current(cfg, __import__("datetime").datetime(2026, 10, 3))
            print(json.dumps({{"keys": list(oa.NBA_GAME_SPORT_KEYS), "calls": calls}}))
        """)
        self.assertEqual(out["keys"], ["basketball_nba", "basketball_nba_preseason"])
        odds_calls = [u for u in out["calls"] if u.endswith("/odds")]
        self.assertEqual(len(odds_calls), 1)
        self.assertIn("/sports/basketball_nba_preseason/events/evt-pre-1/odds", odds_calls[0])

    def test_no_bovada_game_odds_in_cli(self) -> None:
        out = _run_vendor("""
            import inspect, json
            import nba_betting.cli as cli
            def src(cmd):
                return inspect.getsource(getattr(cmd, "callback", None) or cmd)
            print(json.dumps({
                "predict_date": "fetch_bovada_odds_current(" in src(cli.predict_date_cmd),
                "odds_snapshots": "fetch_bovada_odds_current(" in src(cli.odds_snapshots_cmd),
                "module_name": hasattr(cli, "fetch_bovada_odds_current"),
            }))
        """)
        self.assertEqual(out, {"predict_date": False, "odds_snapshots": False, "module_name": False})


if __name__ == "__main__":
    unittest.main()
