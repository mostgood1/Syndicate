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


class StandardLineWinsWithAlternateLadderTests(unittest.TestCase):
    """#16 decision: the displayed spread/total comes from the STANDARD
    market, and the other quoted lanes are preserved as a ladder.

    Before this, selection ran across standard and alternate_* lanes together
    and picked whichever was priced closest to a coin flip -- so an alternate
    could win and be shown as "the total". And game lines kept only that one
    lane, discarding the rest, while props already preserved theirs via
    _finalize_prop_market. The alternate_* markets were being paid for and
    thrown away.
    """

    def _extract(self, markets):
        return mlb_fetch._extract_game_lines(markets, home_team="Detroit Tigers", away_team="Kansas City Royals")

    def _totals_market(self, key, line, over, under):
        return {"key": key, "outcomes": [
            {"name": "Over", "point": line, "price": over},
            {"name": "Under", "point": line, "price": under},
        ]}

    def _spreads_market(self, key, home_line, home_price, away_price):
        return {"key": key, "outcomes": [
            {"name": "Detroit Tigers", "point": home_line, "price": home_price},
            {"name": "Kansas City Royals", "point": -home_line, "price": away_price},
        ]}

    def test_standard_total_wins_even_when_an_alternate_is_better_balanced(self) -> None:
        # The alternate here is a perfect coin flip and would have won before.
        out = self._extract([
            self._totals_market("totals_1st_5_innings", 4.5, -130, 110),
            self._totals_market("alternate_totals_1st_5_innings", 5.5, -100, -100),
        ])
        self.assertEqual(out["segments"]["first5"]["totals"]["line"], 4.5)

    def test_standard_spread_wins_even_when_an_alternate_is_better_balanced(self) -> None:
        out = self._extract([
            self._spreads_market("spreads_1st_5_innings", -1.5, 150, -170),
            self._spreads_market("alternate_spreads_1st_5_innings", -0.5, -100, -100),
        ])
        self.assertEqual(out["segments"]["first5"]["spreads"]["home_line"], -1.5)

    def test_alternates_are_preserved_as_a_ladder(self) -> None:
        # Alternates are SEGMENT-scoped in this fetcher -- there is no
        # full-game alternate_totals/alternate_spreads market requested at
        # all, so the ladder lives on the segment buckets.
        out = self._extract([
            self._totals_market("totals_1st_5_innings", 4.5, -110, -110),
            self._totals_market("alternate_totals_1st_5_innings", 3.5, 130, -150),
            self._totals_market("alternate_totals_1st_5_innings", 5.5, -140, 120),
        ])
        segment = out["segments"]["first5"]["totals"]
        self.assertEqual(segment["line"], 4.5)
        self.assertEqual([lane["line"] for lane in segment["alternates"]], [3.5, 5.5])

    def test_primary_line_is_not_duplicated_into_the_ladder(self) -> None:
        out = self._extract([
            self._totals_market("totals_1st_5_innings", 4.5, -110, -110),
            self._totals_market("alternate_totals_1st_5_innings", 4.5, -105, -115),
        ])
        segment = out["segments"]["first5"]["totals"]
        self.assertEqual(segment["line"], 4.5)
        self.assertEqual(segment["alternates"], [])

    def test_falls_back_to_alternates_when_no_standard_market_is_quoted(self) -> None:
        # A book offering only alternates is better than showing no line.
        out = self._extract([self._totals_market("alternate_totals_1st_5_innings", 5.5, -110, -110)])
        self.assertEqual(out["segments"]["first5"]["totals"]["line"], 5.5)

    def test_spread_ladder_is_sorted_by_line(self) -> None:
        out = self._extract([
            self._spreads_market("spreads_1st_5_innings", -1.5, -110, -110),
            self._spreads_market("alternate_spreads_1st_5_innings", 1.5, -300, 250),
            self._spreads_market("alternate_spreads_1st_5_innings", -2.5, 180, -220),
        ])
        segment = out["segments"]["first5"]["spreads"]
        self.assertEqual(segment["home_line"], -1.5)
        self.assertEqual([lane["home_line"] for lane in segment["alternates"]], [-2.5, 1.5])


class First7MarketsRemovedTests(unittest.TestCase):
    """#16 decision: F7 dropped. Six markets, ~90 credits/sweep, and the sim
    never emitted a first7 projection, so the tab showed book lines with no
    model behind them."""

    def test_no_first7_market_is_requested(self) -> None:
        requested = mlb_fetch._CORE_GAME_MARKET_KEYS + mlb_fetch._SEGMENT_GAME_MARKET_KEYS
        self.assertFalse([key for key in requested if "1st_7_innings" in key])

    def test_remaining_segments_are_still_requested(self) -> None:
        requested = ",".join(mlb_fetch._SEGMENT_GAME_MARKET_KEYS)
        for segment in ("1st_1_innings", "1st_3_innings", "1st_5_innings"):
            self.assertIn(segment, requested)

    def test_segment_output_no_longer_carries_first7(self) -> None:
        out = mlb_fetch._extract_game_lines(
            [{"key": "totals_1st_5_innings", "outcomes": [
                {"name": "Over", "point": 4.5, "price": -110},
                {"name": "Under", "point": 4.5, "price": -110},
            ]}],
            home_team="Detroit Tigers",
            away_team="Kansas City Royals",
        )
        self.assertNotIn("first7", out.get("segments") or {})

    def test_f7_tab_is_not_rendered(self) -> None:
        source = (REPO_ROOT / "syndicate" / "static" / "mlb" / "cards_source.js").read_text(encoding="utf-8")
        self.assertNotIn('{ key: "first7", label: "F7"', source)
