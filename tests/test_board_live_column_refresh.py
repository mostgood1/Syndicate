from __future__ import annotations

import unittest
from unittest.mock import patch

import syndicate.features.intelligence as intelligence_module
from syndicate.blueprints.intelligence import _refresh_live_columns_from_artifact


ROWS = [
    {"playerName": "Dylan Beavers", "marketLabel": "Hits + Runs + RBIs", "line": 0.5, "actual": 1.0, "liveProjection": 1.6}
]

# The refresh reads the report once and indexes it (pk -> game, matchup ->
# game), so tests patch the report rather than a per-game row lookup.
REPORT = {
    "games": [
        {
            "gamePk": 824805,
            "status": {"abstract": "Live", "detailed": "In Progress"},
            "matchup": {"away": {"abbr": "LAA"}, "home": {"abbr": "BAL"}},
            "trackedProps": ROWS,
        }
    ]
}


def _live_candidate(**overrides) -> dict:
    candidate = {
        "sport_slug": "mlb",
        "is_live": True,
        "game_pk": 824805,
        "game_date": "2026-08-04",
        "player_name": "Dylan Beavers",
        "market": "Hits + Runs + RBIs",
        "line": 0.5,
        "actual": "-",
        "live_projection": "-",
    }
    candidate.update(overrides)
    return candidate


class BoardLiveColumnRefreshTests(unittest.TestCase):
    """LIVE PROJ. / LIVE ACTUAL aged at the worker's build cadence.

    Both columns were only ever written during refresh-worker's board build,
    so they were as old as the last build -- minutes -- while the values they
    display change every pitch. Confirmed live 2026-08-05: the board showed
    live_projection on 1 of 9 live MLB props for over 15 minutes while web's
    OWN live-lens artifact was 3 minutes old and carried 329 tracked props
    with real actual/liveProjection for every live game. The numbers were
    already on the box serving the page; nothing read them.

    Refreshing two display fields from an artifact web already holds is the
    "light transformation for display" the runtime split allows. It must
    never become a recompute.
    """

    def test_live_columns_are_refreshed_from_the_artifact(self) -> None:
        payload = {"top_opportunities": [_live_candidate()]}
        with patch.object(intelligence_module, "_mlb_live_lens_report_cached", return_value=REPORT):
            _refresh_live_columns_from_artifact(payload)
        self.assertEqual(payload["top_opportunities"][0]["live_projection"], "1.6")
        self.assertEqual(payload["top_opportunities"][0]["actual"], "1.0")

    def test_a_candidate_whose_game_is_not_in_the_artifact_is_left_alone(self) -> None:
        # This assertion used to be "a candidate the BUILD did not flag live
        # is left alone", which was correct only while is_live gated the
        # refresh. It no longer does, deliberately: the build's flag was
        # measured disagreeing with reality both across and within games (8
        # live games, 4 matchups flagged; PIT @ MIL had live numbers on 4
        # candidates and zero flagged), so liveness now comes from the
        # artifact's own per-game status. A candidate in a live game SHOULD
        # now be promoted and hydrated -- see BoardLiveFlagFromArtifactTests.
        # What must still be left untouched is a game the artifact says
        # nothing about.
        payload = {"top_opportunities": [_live_candidate(is_live=False, game_pk=999999, matchup="XXX @ YYY")]}
        with patch.object(intelligence_module, "_mlb_live_lens_report_cached", return_value=REPORT):
            _refresh_live_columns_from_artifact(payload)
        self.assertEqual(payload["top_opportunities"][0]["actual"], "-")
        self.assertFalse(payload["top_opportunities"][0].get("is_live"))

    def test_an_unreadable_artifact_leaves_the_board_intact(self) -> None:
        payload = {"top_opportunities": [_live_candidate()]}
        with patch.object(
            intelligence_module, "_mlb_live_lens_report_cached", side_effect=OSError("gone")
        ):
            _refresh_live_columns_from_artifact(payload)
        self.assertEqual(payload["top_opportunities"][0]["actual"], "-")

    def test_every_board_collection_is_covered(self) -> None:
        payload = {
            "top_opportunities": [_live_candidate()],
            "top_live_opportunities": [_live_candidate()],
            "recommendations": [_live_candidate()],
            "by_sport": {"mlb": [_live_candidate()]},
        }
        with patch.object(intelligence_module, "_mlb_live_lens_report_cached", return_value=REPORT):
            _refresh_live_columns_from_artifact(payload)
        for key in ("top_opportunities", "top_live_opportunities", "recommendations"):
            self.assertEqual(payload[key][0]["actual"], "1.0", key)
        self.assertEqual(payload["by_sport"]["mlb"][0]["actual"], "1.0")

    def test_the_artifact_is_read_once_per_game_not_once_per_candidate(self) -> None:
        payload = {"top_opportunities": [_live_candidate() for _ in range(25)]}
        with patch.object(
            intelligence_module, "_mlb_live_lens_report_cached", return_value=REPORT
        ) as mocked_report:
            _refresh_live_columns_from_artifact(payload)
        self.assertEqual(mocked_report.call_count, 1)

    def test_other_sports_are_not_touched(self) -> None:
        payload = {"top_opportunities": [_live_candidate(sport_slug="wnba")]}
        with patch.object(intelligence_module, "_mlb_live_lens_report_cached") as mocked_report:
            _refresh_live_columns_from_artifact(payload)
        mocked_report.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class BoardLiveFlagFromArtifactTests(unittest.TestCase):
    """is_live disagreed with reality, across AND within games.

    Measured on the served board 2026-08-05: 8 MLB games were live, but
    candidates were flagged live in only 4 matchups -- WSH @ PHI 20 of 40,
    LAA @ BAL 4 of 8, NYM @ CLE 3 of 6, CWS @ BOS 1 of 12 -- and PIT @ MIL,
    MIA @ ATL, STL @ NYY and MIN @ KC had ZERO flagged despite being live.
    PIT @ MIL even carried live_projection on 4 candidates with none flagged,
    proving the numbers and the flag came from different mechanisms and the
    flag was the weaker one. The artifact's own per-game status is
    authoritative and minutes-fresh.
    """

    LIVE_REPORT = {
        "games": [
            {
                "gamePk": 111,
                "status": {"abstract": "Live", "detailed": "In Progress"},
                "matchup": {"away": {"abbr": "PIT"}, "home": {"abbr": "MIL"}},
                "trackedProps": [
                    {"playerName": "Jake Mangum", "marketLabel": "Hits", "line": 0.5, "actualSoFar": 2.0, "liveProjection": 2.3}
                ],
            },
            {
                "gamePk": 222,
                "status": {"abstract": "Final", "detailed": "Final"},
                "matchup": {"away": {"abbr": "SD"}, "home": {"abbr": "AZ"}},
                "trackedProps": [],
            },
        ]
    }

    def _candidate(self, **overrides) -> dict:
        candidate = {
            "sport_slug": "mlb",
            "matchup": "PIT @ MIL",
            "game_date": "2026-08-04",
            "player_name": "Jake Mangum",
            "market": "Hitter Hits",
            "line": 0.5,
            "actual": "-",
            "live_projection": "-",
        }
        candidate.update(overrides)
        return candidate

    def test_a_candidate_in_a_live_game_is_promoted_even_without_a_game_pk(self) -> None:
        # game_pk was blank on a fifth of MLB candidates, so matchup fallback
        # is what reaches them at all.
        payload = {"top_opportunities": [self._candidate()]}
        with patch.object(intelligence_module, "_mlb_live_lens_report_cached", return_value=self.LIVE_REPORT):
            _refresh_live_columns_from_artifact(payload)
        candidate = payload["top_opportunities"][0]
        self.assertTrue(candidate["is_live"])
        self.assertEqual(candidate["live_projection"], "2.3")
        self.assertEqual(candidate["actual"], "2.0")

    def test_a_final_game_is_not_promoted_to_live(self) -> None:
        payload = {"top_opportunities": [self._candidate(matchup="SD @ AZ", player_name="Nobody")]}
        with patch.object(intelligence_module, "_mlb_live_lens_report_cached", return_value=self.LIVE_REPORT):
            _refresh_live_columns_from_artifact(payload)
        self.assertFalse(payload["top_opportunities"][0].get("is_live"))

    def test_a_card_the_build_called_live_is_never_demoted(self) -> None:
        # Demoting is a bigger behaviour change than a read-path refresh
        # should make on its own.
        payload = {"top_opportunities": [self._candidate(matchup="SD @ AZ", is_live=True)]}
        with patch.object(intelligence_module, "_mlb_live_lens_report_cached", return_value=self.LIVE_REPORT):
            _refresh_live_columns_from_artifact(payload)
        self.assertTrue(payload["top_opportunities"][0]["is_live"])
