"""#17 / #18 -- OddsAPI credit reduction.

OddsAPI bills per (market x region) PER REQUEST, so cost is driven by how
work is split across requests, not by how much data comes back. Measured
burn on 2026-07-25 was already over the 5M target the account is being
brought back down to, so these are correctness-preserving cost fixes, not
optimisations.

#17: the core three game markets (h2h/spreads/totals) are served by the
slate endpoint, which returns every game in ONE request -- 3 credits for the
whole slate instead of 3 per game (45 at a 15-game slate). Inning-segment
markets are "additional markets" the slate endpoint does not serve, so they
stay on the per-event endpoint.

#18: NCAAF defaulted to four regions (us,us2,eu,uk), a flat 4x multiplier,
and was the only sport not on US-only.
"""

from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(rel_path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mlb_fetch = _load("scripts/fetch_mlb_oddsapi_local.py", "mlb_oddsapi_fetch_under_test")
ncaaf_refresh = _load("scripts/refresh_ncaaf_oddsapi.py", "ncaaf_oddsapi_under_test")


_EVENTS = [
    {"id": "e1", "home_team": "Detroit Tigers", "away_team": "Kansas City Royals", "commence_time": "2026-07-25T17:10:00Z"},
    {"id": "e2", "home_team": "New York Mets", "away_team": "Los Angeles Dodgers", "commence_time": "2026-07-25T23:10:00Z"},
]


def _book(key: str, market_keys: list[str], home: str = "Detroit Tigers", away: str = "Kansas City Royals") -> dict:
    # Outcomes must name the event's OWN teams: _extract_game_lines matches
    # outcomes by team name, so a book quoting another game's teams scores
    # zero and the game is legitimately dropped.
    return {
        "key": key,
        "title": key.title(),
        "markets": [
            {"key": m, "outcomes": [{"name": home, "price": -120}, {"name": away, "price": 100}]}
            for m in market_keys
        ],
    }


def _event_by_id(event_id: str) -> dict:
    for event in _EVENTS:
        if event["id"] == event_id:
            return event
    return _EVENTS[0]


def _event_id_from_url(url: str) -> str:
    parts = str(url).split("/events/")
    return parts[1].split("/")[0] if len(parts) > 1 else ""


def _books_for(event: dict, market_keys: list[str], key: str = "fanduel") -> list[dict]:
    return [_book(key, market_keys, event["home_team"], event["away_team"])]


class SlateEndpointForCoreMarketsTests(unittest.TestCase):
    def _run(self, http_get):
        with patch.object(mlb_fetch, "_http_get", side_effect=http_get):
            return mlb_fetch.fetch_live_game_lines_for_date("KEY", "2026-07-25", events=list(_EVENTS))

    def test_core_markets_are_fetched_once_for_the_whole_slate(self) -> None:
        calls: list[tuple[str, str]] = []

        def _http_get(url, params, timeout=30):
            calls.append((url, str(params.get("markets") or "")))
            if url.endswith("/odds") and "/events/" not in url:
                return [dict(e, bookmakers=_books_for(e, ["h2h", "spreads", "totals"])) for e in _EVENTS], {}
            ev = _event_by_id(_event_id_from_url(url))
            return {"bookmakers": _books_for(ev, ["totals_1st_5_innings"])}, {}

        self._run(_http_get)

        slate_calls = [c for c in calls if c[0].endswith("/odds") and "/events/" not in c[0]]
        self.assertEqual(len(slate_calls), 1, "core markets must cost one request for the whole slate")
        self.assertEqual(sorted(slate_calls[0][1].split(",")), ["h2h", "spreads", "totals"])

    def test_per_event_requests_drop_the_core_markets(self) -> None:
        # The saving only materialises if core stops being requested per event.
        per_event_markets: list[str] = []

        def _http_get(url, params, timeout=30):
            if url.endswith("/odds") and "/events/" not in url:
                return [dict(e, bookmakers=_books_for(e, ["h2h"])) for e in _EVENTS], {}
            per_event_markets.append(str(params.get("markets") or ""))
            ev = _event_by_id(_event_id_from_url(url))
            return {"bookmakers": _books_for(ev, ["totals_1st_5_innings"])}, {}

        self._run(_http_get)

        self.assertEqual(len(per_event_markets), 2)
        for markets in per_event_markets:
            keys = markets.split(",")
            self.assertNotIn("h2h", keys)
            self.assertNotIn("spreads", keys)
            self.assertNotIn("totals", keys)

    def test_core_and_segment_prices_are_merged_before_choosing_a_bookmaker(self) -> None:
        # Scoring the two payloads separately would pick one book for core and
        # possibly another for segments, mixing two books into one game.
        def _http_get(url, params, timeout=30):
            if url.endswith("/odds") and "/events/" not in url:
                return [dict(e, bookmakers=_books_for(e, ["h2h", "totals", "spreads"])) for e in _EVENTS], {}
            ev = _event_by_id(_event_id_from_url(url))
            return {"bookmakers": _books_for(ev, ["totals_1st_5_innings"])}, {}

        payload = self._run(_http_get)

        self.assertEqual(len(payload["games"]), 2)
        first = payload["games"][0]
        self.assertEqual(first["bookmaker"], "fanduel")
        self.assertIsInstance(first["markets"].get("h2h"), dict)

    def test_falls_back_to_per_event_core_when_the_slate_call_fails(self) -> None:
        # A cheaper path that can break the working one is not worth having:
        # a game with no h2h is worse than a more expensive request.
        import requests as _requests

        per_event_markets: list[str] = []

        def _http_get(url, params, timeout=30):
            if url.endswith("/odds") and "/events/" not in url:
                response = _requests.Response()
                response.status_code = 500
                raise _requests.HTTPError(response=response)
            per_event_markets.append(str(params.get("markets") or ""))
            ev = _event_by_id(_event_id_from_url(url))
            return {"bookmakers": _books_for(ev, ["h2h", "totals"])}, {}

        payload = self._run(_http_get)

        self.assertTrue(per_event_markets)
        self.assertIn("h2h", per_event_markets[0].split(","))
        self.assertEqual(len(payload["games"]), 2)

    def test_out_of_credits_on_the_slate_call_is_not_silently_downgraded(self) -> None:
        # Reacting to OUT_OF_USAGE_CREDITS by falling back to the 15x more
        # expensive path is the worst possible response to running out.
        import requests as _requests

        def _http_get(url, params, timeout=30):
            response = _requests.Response()
            response.status_code = 401
            response._content = b'{"message": "OUT_OF_USAGE_CREDITS"}'
            raise _requests.HTTPError(response=response)

        with self.assertRaises(mlb_fetch.OddsApiLiveFetchError):
            self._run(_http_get)


class MergeEventOddsPayloadTests(unittest.TestCase):
    def test_unions_markets_for_the_same_bookmaker(self) -> None:
        merged = mlb_fetch._merge_event_odds_payloads(
            {"id": "e1", "bookmakers": [_book("fanduel", ["h2h", "totals"])]},
            {"id": "e1", "bookmakers": [_book("fanduel", ["totals_1st_5_innings"])]},
        )
        keys = [m["key"] for m in merged["bookmakers"][0]["markets"]]
        self.assertEqual(keys, ["h2h", "totals", "totals_1st_5_innings"])

    def test_keeps_bookmakers_present_in_only_one_payload(self) -> None:
        merged = mlb_fetch._merge_event_odds_payloads(
            {"id": "e1", "bookmakers": [_book("fanduel", ["h2h"])]},
            {"id": "e1", "bookmakers": [_book("draftkings", ["h2h_1st_1_innings"])]},
        )
        self.assertEqual(sorted(b["key"] for b in merged["bookmakers"]), ["draftkings", "fanduel"])

    def test_does_not_duplicate_a_market_present_in_both(self) -> None:
        merged = mlb_fetch._merge_event_odds_payloads(
            {"id": "e1", "bookmakers": [_book("fanduel", ["h2h"])]},
            {"id": "e1", "bookmakers": [_book("fanduel", ["h2h"])]},
        )
        self.assertEqual([m["key"] for m in merged["bookmakers"][0]["markets"]], ["h2h"])

    def test_handles_missing_payloads(self) -> None:
        only = {"id": "e1", "bookmakers": [_book("fanduel", ["h2h"])]}
        self.assertIs(mlb_fetch._merge_event_odds_payloads(None, only), only)
        self.assertIs(mlb_fetch._merge_event_odds_payloads(only, None), only)
        self.assertIsNone(mlb_fetch._merge_event_odds_payloads(None, None))

    def test_ignores_bookmakers_without_a_key(self) -> None:
        merged = mlb_fetch._merge_event_odds_payloads(
            {"id": "e1", "bookmakers": [{"markets": [{"key": "h2h"}]}]},
            {"id": "e1", "bookmakers": [_book("fanduel", ["totals"])]},
        )
        self.assertEqual([b["key"] for b in merged["bookmakers"]], ["fanduel"])


class NcaafRegionDefaultTests(unittest.TestCase):
    def test_defaults_to_a_single_region(self) -> None:
        # Four regions is a flat 4x on every NCAAF request.
        source = (REPO_ROOT / "scripts" / "refresh_ncaaf_oddsapi.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("ODDS_API_REGIONS", "us")', source)
        # Scoped to the DEFAULT expression, not the bare string -- the old
        # value is still named in the explanatory comment above the line.
        self.assertNotIn('os.environ.get("ODDS_API_REGIONS", "us,us2,eu,uk")', source)

    def test_env_override_still_wins(self) -> None:
        # Restoring the old behaviour must be an env change, not a deploy.
        with patch.dict(os.environ, {"ODDS_API_REGIONS": "us,uk"}, clear=False):
            self.assertEqual(os.environ.get("ODDS_API_REGIONS", "us"), "us,uk")
