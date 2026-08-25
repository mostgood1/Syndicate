"""Kalshi's game lines were offered under a side the board never asks for.

MEASURED 2026-08-25T21:12:14Z, `[layer2_shortlist] VENUE_REPRICE_KEYS`, the
first reading in which `sources_offered` carried kalshi for all four sports:

    kalshi offered   nfl|h2h|yes          nfl|spreads|over|7.5
    board wanted     mlb|spreads|away|1   soccer|h2h|real betis

`classify_market` reports the side the GRAMMAR read -- `_MONEYLINE` sets it to
"yes" and `_TEAM_SPREAD_WINS_BY` to over/under -- and `kalshi_outcome` was
publishing that verbatim. A moneyline quoted `yes` and a spread quoted `over`
can never meet a board row keyed by ROLE, at any line, so this sits UPSTREAM of
every line- and freshness-related reason the fan-in reports.

THE REGRESSION GUARD MATTERS MORE THAN THE FIX. Props and game TOTALS also say
over/under and the board asks for over/under, so those already met and must not
be touched -- a blanket side rewrite would have broken the only families that
were working.
"""

from __future__ import annotations

import unittest


class TeamTokens(unittest.TestCase):
    def test_a_club_the_map_knows_keeps_its_canonical_spelling(self) -> None:
        """`canonical_team` FIRST, so the existing `h2h|<club>` key keeps
        working and this can only add matches."""
        from syndicate.features.shared.venue_quote_adapters import team_quote_token

        self.assertEqual(team_quote_token("mlb", "Chicago Cubs"), "chicago cubs")

    def test_a_name_the_club_map_cannot_resolve_still_yields_a_token(self) -> None:
        """Kalshi writes "Texas", and `canonical_team("mlb", "Texas")` is None --
        `kalshi_board_join._side_for_team` records `team_side_unresolved` on
        all of them for exactly this reason."""
        from syndicate.features.shared.team_aliases import canonical_team
        from syndicate.features.shared.venue_quote_adapters import team_quote_token

        self.assertIsNone(canonical_team("mlb", "Texas"))
        self.assertEqual(team_quote_token("mlb", "Texas"), "texas")


class CandidateKeys(unittest.TestCase):
    def _keys(self, home: str, away: str, side: str = "home") -> list[str]:
        from syndicate.features.shared.venue_quote_fanin import _candidate_keys

        return _candidate_keys(
            {"market": "h2h", "side": side, "home_team": home, "away_team": away},
            "mlb",
        )

    def test_the_role_key_is_still_first_and_unchanged(self) -> None:
        """Additive by construction: every match that worked before still
        works, because the role key is tried first and untouched."""
        self.assertEqual(self._keys("Texas Rangers", "Chicago White Sox")[0], "mlb|h2h|home")

    def test_the_city_alone_is_offered_when_it_names_one_side(self) -> None:
        self.assertIn("mlb|h2h|texas", self._keys("Texas Rangers", "Chicago White Sox"))

    def test_a_city_BOTH_clubs_share_is_offered_to_NEITHER(self) -> None:
        """THE SAFETY PROPERTY. "chicago" sits inside both "chicago cubs" and
        "chicago white sox", so on that game it names neither side. Guessing is
        a bet on the wrong team half the time, at a price that looks confident
        -- the refusal `_side_for_team` already makes, made in the same place
        the two clubs are both known."""
        home = self._keys("Chicago Cubs", "Chicago White Sox", side="home")
        away = self._keys("Chicago Cubs", "Chicago White Sox", side="away")
        self.assertNotIn("mlb|h2h|chicago", home)
        self.assertNotIn("mlb|h2h|chicago", away)
        # The unshared nickname still resolves, so the game is not lost whole.
        self.assertIn("mlb|h2h|cubs", home)

    def test_a_market_that_is_not_a_moneyline_gains_no_team_keys(self) -> None:
        from syndicate.features.shared.venue_quote_fanin import _candidate_keys

        keys = _candidate_keys(
            {"market": "totals", "side": "over", "line": 8.5,
             "home_team": "Texas Rangers", "away_team": "Chicago White Sox"},
            "mlb",
        )
        self.assertEqual(keys, ["mlb|totals|over|8.5"])


class TheTwoHalvesMeet(unittest.TestCase):
    def test_a_real_kalshi_moneyline_title_reaches_a_real_board_row(self) -> None:
        """End to end through both halves, because each half passing alone is
        what let the original mismatch ship."""
        from syndicate.features.shared import kalshi_catalogue as kc
        from syndicate.features.shared.venue_quote_adapters import (
            quote_key,
            team_quote_token,
        )
        from syndicate.features.shared.venue_quote_fanin import _candidate_keys

        kc.register_discovered({"KXMLBGAME": "mlb"})
        verdict = kc.classify_market({
            "series": "KXMLBGAME",
            "title": "Texas wins",
            "ticker": "KXMLBGAME-26AUG251840TEXCWS-TEX",
        })
        self.assertEqual(verdict["market"], "h2h", verdict)
        # What the grammar reports, and what the adapter used to publish.
        self.assertEqual(verdict["side"], "yes", verdict)

        published = quote_key("mlb", "h2h", team_quote_token("mlb", verdict["subject"]), None)
        self.assertEqual(published, "mlb|h2h|texas")
        wanted = _candidate_keys(
            {"market": "h2h", "side": "home",
             "home_team": "Texas Rangers", "away_team": "Chicago White Sox"},
            "mlb",
        )
        self.assertIn(published, wanted)

    def test_an_ambiguous_city_meets_neither_row(self) -> None:
        from syndicate.features.shared.venue_quote_adapters import (
            quote_key,
            team_quote_token,
        )
        from syndicate.features.shared.venue_quote_fanin import _candidate_keys

        published = quote_key("mlb", "h2h", team_quote_token("mlb", "Chicago"), None)
        for side in ("home", "away"):
            with self.subTest(side=side):
                self.assertNotIn(published, _candidate_keys(
                    {"market": "h2h", "side": side,
                     "home_team": "Chicago Cubs", "away_team": "Chicago White Sox"},
                    "mlb",
                ))


class AdapterReasonCounters(unittest.TestCase):
    def test_the_reason_names_what_could_not_be_keyed_and_what_could(self) -> None:
        """`h2h_keyed` rides alongside the refusals deliberately: a counter that
        appears only when it fires cannot distinguish "ran and matched nothing"
        from "never ran"."""
        from syndicate.features.shared.venue_quote_adapters import _kalshi_ok_reason

        self.assertIsNone(_kalshi_ok_reason(0, 0, 0))
        reason = _kalshi_ok_reason(12, 30, 2)
        self.assertIn("spreads_refused:12", reason)
        self.assertIn("h2h_team_unresolved:2", reason)
        self.assertIn("h2h_keyed_by_team:30", reason)


if __name__ == "__main__":
    unittest.main()
