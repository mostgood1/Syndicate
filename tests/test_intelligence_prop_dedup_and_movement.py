from __future__ import annotations

import unittest

from syndicate.features import intelligence


class MergeDuplicatePropCandidatesTests(unittest.TestCase):
    """2026-07-24 fix: the same prop bet (same player/market/line/side) was
    independently produced by two upstream pipelines with different pick
    text ("Over 4+" vs "OVER Tomoyuki Sugano"), so the existing dedup guard
    (which compares exact pick strings) never caught it. Confirmed live on
    the board: a Tomoyuki Sugano strikeouts prop shown twice, one copy with
    Projected populated and no reasoning, the other with reasoning but
    Projected blank.
    """

    def _artifact_style_candidate(self) -> dict:
        return {
            "candidate_type": "prop",
            "sport_slug": "mlb",
            "player_name": "Tomoyuki Sugano",
            "market": "strikeouts",
            "pick": "Over 4+",
            "name": "Over 4+",
            "line": "3.5",
            "projected": "4.9",
            "detail": "Over 4+ Strikeouts | Pitcher top props",
        }

    def _game_rec_style_candidate(self) -> dict:
        return {
            "candidate_type": "prop",
            "sport_slug": "mlb",
            "player_name": "Tomoyuki Sugano",
            "market": "pitcher strikeouts",
            "pick": "OVER Tomoyuki Sugano",
            "name": "OVER Tomoyuki Sugano",
            "line": "3.5",
            "projected": "-",
            "detail": (
                "The model lands on the over side in 73.5% of sims, while the market "
                "is pricing it closer to 45.7%. The model baseline sits around 4.8 "
                "strikeouts against a line of 3.5."
            ),
        }

    def test_merges_duplicate_across_pipelines_into_one_row(self) -> None:
        candidates = [self._artifact_style_candidate(), self._game_rec_style_candidate()]
        merged = intelligence._merge_duplicate_prop_candidates(candidates)
        self.assertEqual(len(merged), 1)

    def test_merged_row_keeps_projected_and_backfills_detail(self) -> None:
        candidates = [self._artifact_style_candidate(), self._game_rec_style_candidate()]
        merged = intelligence._merge_duplicate_prop_candidates(candidates)
        row = merged[0]
        self.assertEqual(row.get("projected"), "4.9")
        self.assertIn("model baseline sits around 4.8", row.get("detail", ""))

    def test_market_key_normalization_treats_pitcher_prefix_as_same_market(self) -> None:
        bare = self._artifact_style_candidate()
        prefixed = self._game_rec_style_candidate()
        self.assertEqual(
            intelligence._prop_merge_dedup_key(bare)[2],
            intelligence._prop_merge_dedup_key(prefixed)[2],
        )

    def test_different_players_are_not_merged(self) -> None:
        other = self._artifact_style_candidate()
        other["player_name"] = "Shane Drohan"
        other["name"] = "Over 5+"
        candidates = [self._artifact_style_candidate(), other]
        merged = intelligence._merge_duplicate_prop_candidates(candidates)
        self.assertEqual(len(merged), 2)

    def test_different_lines_are_not_merged(self) -> None:
        other = self._game_rec_style_candidate()
        other["line"] = "5.5"
        candidates = [self._artifact_style_candidate(), other]
        merged = intelligence._merge_duplicate_prop_candidates(candidates)
        self.assertEqual(len(merged), 2)

    def test_game_candidates_are_left_untouched(self) -> None:
        game_candidate = {"candidate_type": "game", "sport_slug": "mlb", "market": "moneyline", "pick": "Home ML"}
        candidates = [game_candidate, dict(game_candidate)]
        merged = intelligence._merge_duplicate_prop_candidates(candidates)
        self.assertEqual(len(merged), 2)


class MergeSteamAndPropCandidatesTests(unittest.TestCase):
    """Board audit follow-up, 2026-07-31: the identical real-world bet was
    showing up TWICE on the board -- once as a "prop" (from the analytical
    top-props pipeline) and once as a "steam" candidate (from continuous
    line-movement detection) -- with different, unreconciled prices, and
    only the steam copy had live data. Confirmed live: Miguel Amaya Over 0.5
    Hits showed -123 (prop, no live_projection) alongside +100 (steam,
    live_projection 1.1) at the same time.
    """

    def _prop_style_candidate(self) -> dict:
        return {
            "candidate_type": "prop",
            "sport_slug": "mlb",
            "player_name": "Miguel Amaya",
            "market": "hits",
            "pick": "OVER Miguel Amaya",
            "name": "OVER Miguel Amaya",
            "line": "0.5",
            "odds": "-123",
            "projected": "1.0",
            "live_projection": "-",
            "actual": "-",
            "detail": "Miguel Amaya top prop: over 0.5 hits.",
        }

    def _steam_style_candidate(self) -> dict:
        return {
            "candidate_type": "steam",
            "sport_slug": "mlb",
            "player_name": "Miguel Amaya",
            "market": "Hits · Steam",
            "pick": "Miguel Amaya over 0.5",
            "name": "Miguel Amaya Hits steam move",
            "selection": "Miguel Amaya over 0.5",
            "line": "0.5",
            "odds": "+100",
            "projected": "-",
            "live_projection": "1.1",
            "actual": "-",
            "confidence": "62.0%",
            "edge": "9.4%",
            "is_live": True,
            "line_odds_movement": {"opening_line": 0.5, "latest_line": 0.5},
            "steam": {"capture_phase": "live", "line_delta": 0.0},
        }

    def test_merges_prop_and_steam_for_the_same_bet_into_one_row(self) -> None:
        candidates = [self._prop_style_candidate(), self._steam_style_candidate()]
        merged = intelligence._merge_duplicate_prop_candidates(candidates)
        self.assertEqual(len(merged), 1)

    def test_merged_row_takes_price_and_live_data_from_steam(self) -> None:
        candidates = [self._prop_style_candidate(), self._steam_style_candidate()]
        row = intelligence._merge_duplicate_prop_candidates(candidates)[0]
        self.assertEqual(row.get("odds"), "+100")
        self.assertEqual(row.get("live_projection"), "1.1")
        self.assertEqual(row.get("confidence"), "62.0%")
        self.assertEqual(row.get("edge"), "9.4%")
        self.assertTrue(row.get("is_live"))

    def test_merged_row_keeps_the_props_analytical_detail_and_projection(self) -> None:
        candidates = [self._prop_style_candidate(), self._steam_style_candidate()]
        row = intelligence._merge_duplicate_prop_candidates(candidates)[0]
        self.assertEqual(row.get("projected"), "1.0")
        self.assertIn("top prop", row.get("detail", ""))

    def test_merged_row_is_tagged_steam_confirmed_and_discoverable_via_steam_filter(self) -> None:
        candidates = [self._prop_style_candidate(), self._steam_style_candidate()]
        row = intelligence._merge_duplicate_prop_candidates(candidates)[0]
        self.assertEqual(row.get("candidate_type"), "steam")
        self.assertTrue(row.get("is_steam_confirmed"))
        # player_name survives so the board's player-props filter (which
        # keys off truthy player_name, not candidate_type) still finds it.
        self.assertEqual(row.get("player_name"), "Miguel Amaya")

    def test_merged_from_lists_both_contributing_pipelines(self) -> None:
        candidates = [self._prop_style_candidate(), self._steam_style_candidate()]
        row = intelligence._merge_duplicate_prop_candidates(candidates)[0]
        self.assertEqual(row.get("merged_from"), ["prop", "steam"])

    def test_different_lines_between_prop_and_steam_are_not_merged(self) -> None:
        # A genuinely different line is a different market quote, not a
        # duplicate -- confirmed live for Will Warren's strikeouts prop
        # (3.5 from top-props vs 5.5 from steam).
        steam = self._steam_style_candidate()
        steam["line"] = "5.5"
        candidates = [self._prop_style_candidate(), steam]
        merged = intelligence._merge_duplicate_prop_candidates(candidates)
        self.assertEqual(len(merged), 2)

    def test_over_and_under_steam_for_the_same_line_are_not_merged_together(self) -> None:
        under = self._steam_style_candidate()
        under["pick"] = "Miguel Amaya under 0.5"
        under["selection"] = "Miguel Amaya under 0.5"
        under["name"] = "Miguel Amaya Hits steam move"
        candidates = [self._steam_style_candidate(), under]
        merged = intelligence._merge_duplicate_prop_candidates(candidates)
        self.assertEqual(len(merged), 2)

    def test_steam_only_duplicates_still_merge_using_existing_completeness_logic(self) -> None:
        first = self._steam_style_candidate()
        second = self._steam_style_candidate()
        second["headshot_url"] = "https://example.test/amaya.png"
        merged = intelligence._merge_duplicate_prop_candidates([first, second])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].get("headshot_url"), "https://example.test/amaya.png")


class MergeLiveLensPropAndStalePropCandidatesTests(unittest.TestCase):
    """Board audit, 2026-07-31: reported live -- game cards correctly showed
    "LIVE" with real scores for many simultaneously-live MLB/WNBA games, but
    almost every prop candidate for those same games stayed stuck at lane
    "pregame" with blank live/actual columns. Root cause confirmed against
    real production data (Andrew Painter, PHI @ BAL, live 4-2): the stale
    top-props candidate (status_display="Warmup", is_live=False, from a
    once/day snapshot) and the fresh live-lens duplicate for the identical
    bet (candidate_type="prop" like every other prop -- NOT "steam" -- from
    _mlb_live_lens_prop_candidates_from_artifact, is_live=True, real
    actual/live_projection) correctly matched and merged via
    _prop_merge_dedup_key, but the merge kept the stale candidate as primary
    (it has detail/headshot text, giving it a higher completeness score --
    a live-lens row never carries those) and then dropped the live-lens
    row's freshness entirely, because the existing "freshest source wins"
    override only ever fired for a "steam"-typed group member.
    """

    def _stale_top_props_candidate(self) -> dict:
        return {
            "candidate_type": "prop",
            "sport_slug": "mlb",
            "player_name": "Andrew Painter",
            "market": "Hits Allowed",
            "pick": "Over 5+",
            "name": "Over 5+",
            "line": "4.5",
            "odds": "-110",
            "projected": "8.2",
            "detail": "Over 5+ Hits Allowed | Pitcher top props",
            "headshot_url": "https://example.test/painter.png",
            "is_live": False,
            "status_display": "Warmup",
            "game_state": "Warmup",
            "live_projection": "-",
            "actual": "-",
        }

    def _fresh_live_lens_candidate(self) -> dict:
        return {
            "candidate_type": "prop",
            "sport_slug": "mlb",
            "player_name": "Andrew Painter",
            "market": "Hits Allowed",
            "pick": "Over 4.5",
            "name": "Andrew Painter Over 4.5 Hits Allowed",
            "line": "4.5",
            "odds": "-130",
            "projected": "-",
            "is_live": True,
            "status_display": "In Progress",
            "game_state": "In Progress",
            "live_projection": "5.0",
            "actual": "3.0",
        }

    def test_merges_live_lens_and_stale_prop_for_the_same_bet_into_one_row(self) -> None:
        merged = intelligence._merge_duplicate_prop_candidates(
            [self._stale_top_props_candidate(), self._fresh_live_lens_candidate()]
        )
        self.assertEqual(len(merged), 1)

    def test_merged_row_takes_live_state_from_the_live_lens_duplicate(self) -> None:
        row = intelligence._merge_duplicate_prop_candidates(
            [self._stale_top_props_candidate(), self._fresh_live_lens_candidate()]
        )[0]
        self.assertTrue(row.get("is_live"))
        self.assertEqual(row.get("status_display"), "In Progress")
        self.assertEqual(row.get("game_state"), "In Progress")
        self.assertEqual(row.get("live_projection"), "5.0")
        self.assertEqual(row.get("actual"), "3.0")

    def test_merged_row_keeps_the_stale_candidates_analytical_detail_and_pick(self) -> None:
        # Unlike the steam merge, a live-lens duplicate doesn't confirm a
        # fresher PRICE the way a steam candidate does -- only fresher
        # live-state -- so pick/odds/detail/projected stay from whichever
        # candidate won on analytical completeness.
        row = intelligence._merge_duplicate_prop_candidates(
            [self._stale_top_props_candidate(), self._fresh_live_lens_candidate()]
        )[0]
        self.assertEqual(row.get("pick"), "Over 5+")
        self.assertEqual(row.get("odds"), "-110")
        self.assertEqual(row.get("projected"), "8.2")
        self.assertIn("top props", row.get("detail", ""))
        # And candidate_type must NOT get reclassified to "steam" -- that
        # relabeling is steam-specific (a confirmed real-time price move),
        # not implied by live-state alone.
        self.assertEqual(row.get("candidate_type"), "prop")

    def test_two_stale_props_with_no_live_duplicate_are_unaffected(self) -> None:
        first = self._stale_top_props_candidate()
        second = self._stale_top_props_candidate()
        second["headshot_url"] = "https://example.test/painter2.png"
        second["detail"] = ""
        merged = intelligence._merge_duplicate_prop_candidates([first, second])
        self.assertEqual(len(merged), 1)
        self.assertFalse(merged[0].get("is_live"))
        self.assertEqual(merged[0].get("status_display"), "Warmup")


class MergeGameSideAndSteamCandidatesTests(unittest.TestCase):
    """Board audit follow-up, 2026-07-31: a team-level (moneyline/spread)
    steam candidate had no merge counterpart with an equivalent "game"-type
    candidate for the same real bet -- found proactively while auditing
    other duplicate shapes after the prop/steam merge shipped, with zero
    live occurrences at the time (the gap was structural, not yet
    triggered). Fixed via a dedicated pass (_game_side_merge_dedup_key /
    _merge_duplicate_game_side_candidates) rather than folding "game" into
    the prop/steam merge, since a team abbreviation needs the real game id
    to match too (unlike a player's full name, which is strong identity on
    its own).
    """

    def _game_style_candidate(self, **overrides) -> dict:
        base = {
            "candidate_type": "game",
            "sport_slug": "mlb",
            "gamePk": 823271,
            "matchup": "NYY @ CHC",
            "market": "Moneyline",
            "pick": "Away ML",
            "team": "NYY",
            "line": "-",
            "odds": "-143",
            "projected": "58.5%",
            "detail": "Model win probability 58.5%.",
            "is_live": False,
        }
        base.update(overrides)
        return base

    def _steam_style_candidate(self, **overrides) -> dict:
        base = {
            "candidate_type": "steam",
            "sport_slug": "mlb",
            "game_id": "823271",
            "event_id": "823271",
            "game_pk": 823271,
            "matchup": "NYY @ CHC",
            "market": "Moneyline · Steam",
            "pick": "New York Yankees steam move",
            "team": "NYY",
            "line": "-",
            "odds": "-150",
            "is_live": True,
        }
        base.update(overrides)
        return base

    def test_merges_game_and_steam_moneyline_for_the_same_team_into_one_row(self) -> None:
        merged = intelligence._merge_duplicate_game_side_candidates(
            [self._game_style_candidate(), self._steam_style_candidate()]
        )
        self.assertEqual(len(merged), 1)

    def test_merged_row_takes_price_and_live_state_from_steam(self) -> None:
        row = intelligence._merge_duplicate_game_side_candidates(
            [self._game_style_candidate(), self._steam_style_candidate()]
        )[0]
        self.assertEqual(row.get("odds"), "-150")
        self.assertTrue(row.get("is_live"))
        self.assertEqual(row.get("candidate_type"), "steam")
        self.assertEqual(row.get("merged_from"), ["game", "steam"])

    def test_merged_row_keeps_the_games_analytical_detail_and_projection(self) -> None:
        row = intelligence._merge_duplicate_game_side_candidates(
            [self._game_style_candidate(), self._steam_style_candidate()]
        )[0]
        self.assertEqual(row.get("projected"), "58.5%")
        self.assertIn("win probability", row.get("detail", ""))

    def test_different_teams_in_the_same_game_are_not_merged(self) -> None:
        home_side = self._game_style_candidate(pick="Home ML", team="CHC")
        away_steam = self._steam_style_candidate()
        merged = intelligence._merge_duplicate_game_side_candidates([home_side, away_steam])
        self.assertEqual(len(merged), 2)

    def test_same_team_and_market_in_different_games_are_not_merged(self) -> None:
        other_game_steam = self._steam_style_candidate(gamePk=999999, game_id="999999", event_id="999999", game_pk=999999)
        merged = intelligence._merge_duplicate_game_side_candidates([self._game_style_candidate(), other_game_steam])
        self.assertEqual(len(merged), 2)

    def test_total_market_is_never_merged_via_this_path(self) -> None:
        # Total has no team side -- merging it here (team="-" or absent)
        # would be unsafe (a total line recurs across unrelated games).
        total_game = self._game_style_candidate(market="Total", pick="Over 8.5", team=None, line="8.5")
        total_steam = self._steam_style_candidate(market="Total · Steam", pick="NYY/CHC total steam move", team=None, line="8.5")
        merged = intelligence._merge_duplicate_game_side_candidates([total_game, total_steam])
        self.assertEqual(len(merged), 2)

    def test_prop_type_candidates_are_left_untouched_by_this_pass(self) -> None:
        prop = {"candidate_type": "prop", "sport_slug": "mlb", "gamePk": 823271, "market": "Moneyline", "team": "NYY", "player_name": "Someone"}
        merged = intelligence._merge_duplicate_game_side_candidates([prop, dict(prop)])
        self.assertEqual(len(merged), 2)

    def test_merges_live_state_from_a_non_steam_live_duplicate_too(self) -> None:
        # Same gap/fix as MergeLiveLensPropAndStalePropCandidatesTests, for
        # this function's own analogous steam-override block.
        stale = self._game_style_candidate(is_live=False)
        fresh_non_steam = self._game_style_candidate(
            candidate_type="game", odds="-999", is_live=True, status_display="In Progress"
        )
        row = intelligence._merge_duplicate_game_side_candidates([stale, fresh_non_steam])[0]
        self.assertTrue(row.get("is_live"))
        self.assertEqual(row.get("status_display"), "In Progress")
        self.assertEqual(row.get("candidate_type"), "game")  # not reclassified to "steam"


class OddsHistoryMatchScoreCrossMarketGuardTests(unittest.TestCase):
    """2026-07-24 fix: a player-prop candidate must never adopt a GAME-level
    market's odds history (h2h/spreads/totals) just because it shares the
    same matchup text. Confirmed live: a Sugano strikeouts-prop candidate
    was showing the Milwaukee Brewers moneyline's price delta as its own
    "Move" value.
    """

    def _prop_candidate(self) -> dict:
        return {
            "candidate_type": "prop",
            "matchup": "COL @ MIL",
            "market": "pitcher strikeouts",
            "name": "OVER Tomoyuki Sugano",
            "pick": "OVER Tomoyuki Sugano",
            "line": "3.5",
        }

    def test_rejects_game_level_market_key_with_no_player_identity_match(self) -> None:
        market_key = "event_id=abc|home_team=Milwaukee Brewers|away_team=Colorado Rockies|market=h2h|bookmaker=draftkings"
        state = {"last_line": -258.0}
        score = intelligence._candidate_odds_history_match_score(self._prop_candidate(), market_key, state)
        self.assertEqual(score, 0.0)

    def test_accepts_genuine_player_prop_market_key(self) -> None:
        market_key = "event_id=abc|player_name=Tomoyuki Sugano|market=pitcher_strikeouts|bookmaker=draftkings"
        state = {"last_line": 3.5}
        score = intelligence._candidate_odds_history_match_score(self._prop_candidate(), market_key, state)
        self.assertGreater(score, 0.0)

    def test_game_level_candidate_still_matches_game_level_market(self) -> None:
        game_candidate = {
            "candidate_type": "game",
            "matchup": "COL @ MIL",
            "market": "Moneyline",
            "pick": "Home ML",
            "name": "Home ML",
            "line": "-258",
        }
        market_key = "event_id=abc|home_team=Milwaukee Brewers|away_team=Colorado Rockies|market=h2h|bookmaker=draftkings"
        state = {"last_line": -258.0}
        score = intelligence._candidate_odds_history_match_score(game_candidate, market_key, state)
        self.assertGreater(score, 0.0)

    def _steam_candidate(self) -> dict:
        # Real shape from _steam_candidates_for_sport: a player-level steam
        # candidate carries subject_key/player_name/entity, not the
        # prop-only "OVER Name" pick text _candidate_subject_key() parses.
        return {
            "candidate_type": "steam",
            "matchup": "SSF @ PT",
            "market": "Shots · Steam",
            "name": "Gage Guerra Shots steam move",
            "pick": "Gage Guerra steam move",
            "selection": "Gage Guerra steam move",
            "subject_key": "gage guerra",
            "player_name": "Gage Guerra",
            "entity": "Gage Guerra",
            "line": "2.5",
        }

    def test_steam_candidate_rejects_unrelated_games_game_level_market(self) -> None:
        # Confirmed live 2026-07-31: 120 soccer steam candidates all
        # converged onto ONE unrelated game's (NYCFC/Toronto FC) odds
        # history because "steam" wasn't covered by this gate at all.
        market_key = "event_id=52ee1a58|home_team=New York City FC|away_team=Toronto FC|market=spreads|bookmaker=draftkings"
        state = {"last_line": -0.25}
        score = intelligence._candidate_odds_history_match_score(self._steam_candidate(), market_key, state)
        self.assertEqual(score, 0.0)

    def test_steam_candidate_accepts_its_own_players_prop_market(self) -> None:
        market_key = "event_id=abc|player_name=Gage Guerra|market=player_shots_on_target|bookmaker=draftkings"
        state = {"last_line": 2.5}
        score = intelligence._candidate_odds_history_match_score(self._steam_candidate(), market_key, state)
        self.assertGreater(score, 0.0)

    def test_game_level_steam_candidate_still_matches_its_own_game(self) -> None:
        game_steam_candidate = {
            "candidate_type": "steam",
            "matchup": "SSF @ PT",
            "market": "Moneyline · Steam",
            "name": "San Francisco FC steam move",
            "pick": "San Francisco FC steam move",
            "subject_key": "san francisco fc",
            "player_name": "San Francisco FC",
            "entity": "San Francisco FC",
            "line": "-120",
        }
        market_key = "event_id=xyz|home_team=San Francisco FC|away_team=Portland Timbers|market=h2h|bookmaker=draftkings"
        state = {"last_line": -120.0}
        score = intelligence._candidate_odds_history_match_score(game_steam_candidate, market_key, state)
        self.assertGreater(score, 0.0)


class OddsHistoryPlayerIndexTests(unittest.TestCase):
    """2026-07-24 fix: _candidate_odds_history_state used to linear-scan
    every market for every candidate. Fine when MLB only had ~33 game-level
    entries, but once MLB prop odds-history started being written
    (same-day fix), that payload grew past 3,000 entries and the resulting
    O(candidates * markets) scan made one production compute cycle take
    147s instead of ~1.3s, directly contributing to a worker timeout and
    an empty board. _build_odds_history_player_index buckets by player so
    a prop candidate only ever scans its own player's handful of entries.
    """

    def _big_odds_history(self, *, real_player: str, other_player_count: int) -> dict:
        markets = {
            "event_id=abc|home_team=Milwaukee Brewers|away_team=Colorado Rockies|market=h2h|bookmaker=draftkings": {"last_line": -258.0},
        }
        for i in range(other_player_count):
            markets[f"player_name=filler player {i}|market=strikeouts|selection=over"] = {"last_line": 3.5}
        markets[f"player_name={real_player}|market=strikeouts|selection=over"] = {"last_line": 3.5, "last_odds": 106.0}
        return {"markets": markets}

    def test_prop_candidate_only_scans_its_own_player_bucket(self) -> None:
        odds_history = self._big_odds_history(real_player="tomoyuki sugano", other_player_count=2000)
        index = intelligence._build_odds_history_player_index(odds_history)
        by_player, unattributed = index
        # 2000 filler players + the real one = 2001 buckets; the game-level
        # entry is the only thing in the unattributed pool.
        self.assertEqual(len(by_player), 2001)
        self.assertEqual(len(unattributed), 1)

        candidate = {
            "candidate_type": "prop",
            "player_name": "Tomoyuki Sugano",
            "matchup": "COL @ MIL",
            "market": "strikeouts",
            "pick": "Over 3.5",
            "name": "Over 3.5",
            "line": "3.5",
        }
        market_key, state = intelligence._candidate_odds_history_state(candidate, index)
        self.assertIsNotNone(state)
        self.assertIn("tomoyuki sugano", market_key.lower())

    def test_game_candidate_still_matches_via_unattributed_pool(self) -> None:
        odds_history = self._big_odds_history(real_player="tomoyuki sugano", other_player_count=50)
        index = intelligence._build_odds_history_player_index(odds_history)
        game_candidate = {
            "candidate_type": "game",
            "matchup": "COL @ MIL",
            "market": "Moneyline",
            "pick": "Home ML",
            "name": "Home ML",
            "line": "-258",
        }
        market_key, state = intelligence._candidate_odds_history_state(game_candidate, index)
        self.assertIsNotNone(state)
        self.assertIn("h2h", market_key)

    def test_empty_odds_history_returns_empty_index(self) -> None:
        by_player, unattributed = intelligence._build_odds_history_player_index(None)
        self.assertEqual(by_player, {})
        self.assertEqual(unattributed, [])


class NormalizedMarketTextDiacriticTests(unittest.TestCase):
    """2026-08-04 fix: confirmed live that real, actively-moving MLB prop
    odds-history existed for "Endy Rodriguez"/"Nasim Nunez" and never
    surfaced on their board cards. Root cause: _normalized_market_text's
    char-class filter (`[^a-z0-9]` -> space) replaced an accented letter
    with a SPACE rather than folding it, splitting "Rodriguez" into
    "rodr guez" and breaking the exact-string player-bucket lookup against
    odds-history's plain-ASCII "endy rodriguez" key.
    """

    def test_accented_name_normalizes_to_same_text_as_plain_ascii(self) -> None:
        self.assertEqual(intelligence._normalized_market_text("Endy Rodríguez"), intelligence._normalized_market_text("Endy Rodriguez"))
        self.assertEqual(intelligence._normalized_market_text("Nasim Nuñez"), intelligence._normalized_market_text("Nasim Nunez"))
        self.assertEqual(intelligence._normalized_market_text("Endy Rodríguez"), "endy rodriguez")

    def test_accented_prop_candidate_now_matches_its_plain_ascii_odds_history_entry(self) -> None:
        candidate = {
            "candidate_type": "prop",
            "player_name": "Endy Rodríguez",
            "matchup": "PIT @ CHC",
            "market": "Hitter Hits",
            "pick": "OVER Endy Rodríguez",
            "name": "OVER Endy Rodríguez",
            "line": "1.5",
        }
        odds_history = {
            "markets": {
                "player_name=endy rodriguez|market=batter_hits|selection=over": {"last_line": 1.5, "last_odds": -120.0},
            }
        }
        index = intelligence._build_odds_history_player_index(odds_history)
        market_key, state = intelligence._candidate_odds_history_state(candidate, index)
        self.assertIsNotNone(state)
        self.assertIn("endy rodriguez", market_key)


class MlbGameMarketTeamAbbreviationTests(unittest.TestCase):
    """2026-08-04 fix: MLB board candidates carry team abbreviations
    (matchup="LAD @ CHC", team="CHC") while odds-history's own OddsAPI-
    sourced market keys carry full team names ("Chicago Cubs") -- neither
    ever textually overlapped the other, so every MLB game-market
    (moneyline/spread/total) candidate showed zero movement even when real
    odds-history existed for the exact same game. Confirmed live: Red Sox/
    Yankees moneylines moved 6-10 cents same-day, captured correctly in
    odds-history, never surfaced on any board card. Deliberately uses
    DIFFERENT candidate/state prices so the pre-existing line-proximity
    scoring bonus can't accidentally paper over a real text-matching gap.
    """

    def _home_ml_candidate(self, **overrides) -> dict:
        candidate = {
            "sport_slug": "mlb",
            "sport": "MLB",
            "candidate_type": "game",
            "matchup": "LAD @ CHC",
            "team": "CHC",
            "market": "Moneyline",
            "pick": "Home ML",
            "selection": "Home ML",
            "name": "CHC",
            "line": None,
        }
        candidate.update(overrides)
        return candidate

    def test_expand_mlb_team_abbreviations_returns_each_full_name_separately(self) -> None:
        names = intelligence._expand_mlb_team_abbreviations("LAD @ CHC")
        self.assertEqual(sorted(names), ["Chicago Cubs", "Los Angeles Dodgers"])

    def test_home_side_candidate_matches_its_real_game(self) -> None:
        market_key = "event_id=00828e81b6bef980ada2777528d99f93|home_team=Chicago Cubs|away_team=Los Angeles Dodgers|market=h2h|bookmaker=fanduel"
        state = {"last_line": -126.0}
        score = intelligence._candidate_odds_history_match_score(self._home_ml_candidate(), market_key, state)
        self.assertGreater(score, 0.0)

    def test_away_side_candidate_matches_the_same_game(self) -> None:
        market_key = "event_id=00828e81b6bef980ada2777528d99f93|home_team=Chicago Cubs|away_team=Los Angeles Dodgers|market=h2h|bookmaker=fanduel"
        state = {"last_line": -126.0}
        away_candidate = self._home_ml_candidate(team="LAD", pick="Away ML", selection="Away ML", name="LAD")
        score = intelligence._candidate_odds_history_match_score(away_candidate, market_key, state)
        self.assertGreater(score, 0.0)

    def test_does_not_match_an_unrelated_games_market(self) -> None:
        unrelated_key = "event_id=abc|home_team=Boston Red Sox|away_team=Chicago White Sox|market=h2h|bookmaker=fanduel"
        state = {"last_line": -126.0}
        score = intelligence._candidate_odds_history_match_score(self._home_ml_candidate(), unrelated_key, state)
        self.assertEqual(score, 0.0)

    def test_non_mlb_sport_does_not_get_abbreviation_expansion(self) -> None:
        # Guards against the expansion accidentally firing for a different
        # sport whose short team codes might collide with an MLB abbreviation.
        candidate = self._home_ml_candidate(sport_slug="nhl", sport="NHL")
        market_key = "event_id=xyz|home_team=Chicago Cubs|away_team=Los Angeles Dodgers|market=h2h|bookmaker=fanduel"
        state = {"last_line": -126.0}
        score = intelligence._candidate_odds_history_match_score(candidate, market_key, state)
        self.assertEqual(score, 0.0)


if __name__ == "__main__":
    unittest.main()
