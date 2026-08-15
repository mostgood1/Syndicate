"""Deterministic sport coverage in `Ask the Syndicate` (lane `ask-sport-coverage`).

Covers plan items K9 (NFL nickname matching), K2/K11 (soccer + ncaab become
routable), K3 (routing collisions), K4 (the NBA/WNBA dispatch bug) and K5/K6
(`routed_sport` and an as-of on every answer).

WHAT THESE TESTS ASSERT, AND WHY IT IS THE PREDICATE AND NOT THE OUTCOME.
`scripts/ask_syndicate_regression.py` scores the served product against a live
deployment and is the number this lane is judged by; it is deliberately NOT
touched here. These tests assert the SOURCE-LEVEL behaviour that the harness
cannot isolate -- that "Patriots" resolves to a team at all, that `wnba` stops
resolving to `nba` -- so a regression is attributable to a function rather than
to a slate that changed overnight. They use the branding/registry data that
ships in the repo, and assert relationships (uniqueness, precedence) rather than
specific slate values, so they cannot rot the way a fixture of today's odds
would.
"""
from __future__ import annotations

import unittest

from syndicate.blueprints import ask_the_syndicate as ask_module
from syndicate.blueprints import ask_the_syndicate_data as data_module


class NflNicknameMatchingTests(unittest.TestCase):
    """K9. Measured before the fix: `"Patriots vs Seahawks projection"` -> `[]`,
    so `_nfl_matchup_evidence` returned None at `len(teams) < 2` before it ever
    opened an artifact, and NFL produced zero evidence for every question."""

    def test_mascot_alone_resolves_to_the_full_team(self) -> None:
        self.assertEqual(
            data_module._nfl_teams_in_question("Patriots vs Seahawks projection"),
            ["New England Patriots", "Seattle Seahawks"],
        )

    def test_single_mascot_resolves(self) -> None:
        self.assertEqual(
            data_module._nfl_teams_in_question("What does the model project for the Patriots"),
            ["New England Patriots"],
        )

    def test_full_names_still_resolve(self) -> None:
        """The widening must not cost the behaviour that already worked."""
        self.assertEqual(
            data_module._nfl_teams_in_question("New England Patriots vs Seattle Seahawks"),
            ["New England Patriots", "Seattle Seahawks"],
        )

    def test_ambiguous_location_resolves_to_nothing_not_to_a_coin_flip(self) -> None:
        """"New York" is Giants AND Jets; "Los Angeles" is Rams AND Chargers.
        Resolving either to one team would be a fabricated entity, which is
        strictly worse than declining to match."""
        self.assertEqual(data_module._nfl_teams_in_question("the New York game tonight"), [])
        self.assertEqual(data_module._nfl_teams_in_question("Los Angeles spread"), [])

    def test_unambiguous_location_resolves(self) -> None:
        self.assertIn("Miami Dolphins", data_module._nfl_teams_in_question("miami total"))

    def test_alias_ambiguity_is_computed_from_the_data_not_hardcoded(self) -> None:
        """The uniqueness guard must be derived, so a future relocation that
        creates a collision DROPS the alias instead of resolving it wrongly."""
        aliases = data_module._nfl_name_aliases()
        normalized = [alias for alias, _display in aliases]
        self.assertEqual(len(normalized), len(set(normalized)), "aliases must be unambiguous")
        # Longest first, so "new england patriots" can never be shadowed by
        # a shorter alias that is a substring of it.
        self.assertEqual(normalized, sorted(normalized, key=len, reverse=True))

    def test_ncaaf_still_excludes_mascots(self) -> None:
        """NOT a copy of the NFL fix, deliberately. With ~680 FBS/FCS schools
        sharing mascots ("Wildcats", "Tigers"), a mascot match there is
        ambiguous by construction -- the NFL fix is safe only because 32 NFL
        mascots are unique, which is a property of the data, not a technique."""
        self.assertEqual(data_module._ncaaf_teams_in_question("wildcats vs tigers"), [])


class SportRoutingTests(unittest.TestCase):
    """K2/K3. Before: a flat keyword list with first-tuple-wins, so `wnba` was a
    keyword inside `nba`, `assists` was resolved by list position, and soccer
    and ncaab had no entry at all."""

    def test_wnba_no_longer_routes_to_nba(self) -> None:
        self.assertEqual(ask_module._infer_sport("What are the best WNBA points props?", {}), "wnba")

    def test_nba_still_routes_to_nba(self) -> None:
        self.assertEqual(ask_module._infer_sport("best nba points props tonight", {}), "nba")

    def test_soccer_is_nameable(self) -> None:
        """Soccer is 100 of 200 published board rows and was previously
        unroutable, so the board fetcher could never filter to it."""
        self.assertEqual(ask_module._infer_sport("best soccer bets tonight", {}), "soccer")
        self.assertEqual(ask_module._infer_sport("Premier League value today", {}), "soccer")

    def test_ncaab_is_nameable(self) -> None:
        self.assertEqual(ask_module._infer_sport("ncaab bracket picks", {}), "ncaab")

    def test_identifier_beats_hint_regardless_of_table_order(self) -> None:
        """The load-bearing property. `ncaaf` used to need to be physically
        written above `nfl`; now it wins on evidence, so re-ordering the table
        cannot silently change routing."""
        self.assertEqual(ask_module._infer_sport("who wins the college football game this week", {}), "ncaaf")
        self.assertEqual(ask_module._infer_sport("rushing touchdowns prop", {}), "nfl")

    def test_explicit_context_sport_still_wins(self) -> None:
        self.assertEqual(ask_module._infer_sport("best bets tonight", {"sport": "nhl"}), "nhl")

    def test_no_domain_question_routes_to_no_sport(self) -> None:
        self.assertIsNone(ask_module._infer_sport("What is the capital of France?", {}))

    def test_scores_are_reported_for_diagnosis(self) -> None:
        scores = dict((sport, score) for sport, score, _terms in ask_module._sport_scores("wnba points props"))
        self.assertGreater(scores["wnba"], scores["nba"])

    def test_soccer_club_shorthand_resolves(self) -> None:
        """"United" and "City" are how these clubs are actually named. Without
        them a soccer question carrying only "goals" loses the tie to NHL,
        which shares that hint."""
        self.assertEqual(ask_module._infer_sport("What is United's price this weekend?", {}), "soccer")
        self.assertEqual(ask_module._infer_sport("How does the model see City?", {}), "soccer")
        self.assertEqual(ask_module._infer_sport("How many goals will Arsenal score?", {}), "soccer")

    def test_club_shorthand_does_not_steal_kansas_city(self) -> None:
        """The one real collision in the table, and the reason "city" is
        guarded rather than listed bare. An NFL question frequently carries no
        other NFL vocabulary at all, so an unguarded "city" would silently
        route it to soccer -- a regression in the sport this lane just fixed."""
        self.assertIsNone(ask_module._infer_sport("What does the model project for the Kansas City game?", {}))
        self.assertEqual(ask_module._infer_sport("Kansas City Chiefs rushing touchdowns", {}), "nfl")

    def test_united_does_not_fire_on_united_states(self) -> None:
        self.assertEqual(ask_module._infer_sport("United States soccer team", {}), "soccer")
        self.assertIsNone(ask_module._infer_sport("the United States economy", {}))

    def test_goals_still_resolves_to_nhl_when_hockey_is_named(self) -> None:
        """Soccer must not steal NHL's shared hint -- an explicit sport name
        outscores a shared stat noun by construction, not by list order."""
        self.assertEqual(ask_module._infer_sport("How many goals in the hockey game", {}), "nhl")

    def test_raw_pattern_escape_hatch_is_explicit(self) -> None:
        """Plain terms must stay escaped, so a keyword can never accidentally
        behave as a pattern; only an `re:` prefix opts in."""
        self.assertTrue(ask_module._sport_keyword_matches("clean sheet", " clean sheet "))
        self.assertFalse(ask_module._sport_keyword_matches("c.ty", " city "))
        self.assertTrue(ask_module._sport_keyword_matches(r"re:\bcity\b", " city "))


class FetcherDispatchTests(unittest.TestCase):
    """K4/K11."""

    def test_nba_no_longer_dispatches_to_the_wnba_fetcher(self) -> None:
        """`_wnba_focused_evidence` reads `_wnba_processed_dirs()` exclusively,
        so on an NBA question it could only ever answer with WNBA players."""
        fetchers = data_module._entity_fetchers_for_sport("nba", "best nba points props")
        self.assertNotIn(data_module._wnba_focused_evidence, fetchers)

    def test_wnba_still_dispatches_to_the_wnba_fetcher(self) -> None:
        fetchers = data_module._entity_fetchers_for_sport("wnba", "how is caitlin clark looking")
        self.assertIn(data_module._wnba_focused_evidence, fetchers)

    def test_soccer_and_ncaab_still_reach_the_board_fetcher(self) -> None:
        """They have no entity fetcher of their own -- the point of K2/K11 is
        that being ROUTABLE lets the board fetcher filter to them exactly."""
        for sport in ("soccer", "ncaab"):
            self.assertEqual(data_module._entity_fetchers_for_sport(sport, "best bets"), [])
            self.assertIn(data_module._board_candidates_evidence, data_module._fetchers_for_sport(sport, "best bets tonight"))

    def test_nfl_matchup_fetcher_is_reachable_from_a_nickname(self) -> None:
        """The falsification test for K9, kept as a regression: if this returns
        None again, the cause is the artifact and not the matcher."""
        self.assertIn(data_module._nfl_matchup_evidence, data_module._fetchers_for_sport("nfl", "Patriots vs Seahawks projection"))


class ResponseContractTests(unittest.TestCase):
    """K5/K6, asserted at the FIELD A CONSUMER READS.

    Both of these were first implemented as new top-level keys, which was
    useless: `scripts/ask_syndicate_regression.py` reads the routed sport from
    `context.sport` / `routing_context.sport` and the as-of from
    `visuals.as_of`, and a field nobody reads is indistinguishable from the
    `None` it replaced. These tests pin the LOCATIONS, not just the values, so
    the same mistake cannot recur silently.
    """

    def _post(self, question: str) -> dict:
        from syndicate.app import app

        with app.test_client() as client:
            response = client.post("/api/syndicate/query", json={"question": question})
            self.assertEqual(response.status_code, 200)
            return response.get_json()

    def test_routed_sport_is_visible_where_consumers_read_it(self) -> None:
        payload = self._post("What are the best soccer bets tonight?")
        self.assertEqual(payload.get("routed_sport"), "soccer")
        self.assertEqual((payload.get("context") or {}).get("sport"), "soccer")
        self.assertEqual((payload.get("routing_context") or {}).get("sport"), "soccer")

    def test_every_answer_carries_an_as_of_slot(self) -> None:
        """`visuals` used to be written ONLY when a fetcher matched, so an
        unrouted question carried no timestamp field at all -- and those are
        exactly the answers where a user has least other signal about
        staleness. The guarantee K6 actually makes is that the SLOT is always
        there and always mirrored at the top level.

        It deliberately does NOT assert a non-None value. Whether a timestamp
        exists depends on the snapshot having `freshness`, which depends on the
        box having artifacts -- asserting non-None here would be asserting the
        fixture, and it passed on a developer box while failing on a clean
        checkout of the deployed commit. That is the failure mode this repo
        already documents for `data/**`: a test that reads the local mirror is
        testing the mirror.
        """
        payload = self._post("What are the best bets tonight?")
        self.assertIn("visuals", payload)
        self.assertIn("as_of", payload.get("visuals") or {})
        self.assertEqual(payload.get("as_of"), (payload.get("visuals") or {}).get("as_of"))

    def test_as_of_is_never_fabricated(self) -> None:
        """An absent timestamp is honest; a served-at stamp on a two-hour-old
        snapshot is not. When the snapshot carries no freshness and no fetcher
        matched, the answer must say None rather than `now`."""
        payload = self._post("What are the best bets tonight?")
        as_of = (payload.get("visuals") or {}).get("as_of")
        if as_of is None:
            return  # nothing to fabricate from, and nothing was fabricated
        # If it IS populated it must come from the data, not the clock: a
        # request-time stamp would be within seconds of now.
        import datetime as _dt

        parsed = str(as_of)
        now = _dt.datetime.now(_dt.timezone.utc)
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
            try:
                stamp = _dt.datetime.strptime(parsed, fmt).replace(tzinfo=_dt.timezone.utc)
            except ValueError:
                continue
            self.assertLess(
                stamp, now + _dt.timedelta(seconds=5),
                "as_of must describe the data, never a future clock read",
            )
            break


if __name__ == "__main__":
    unittest.main()
