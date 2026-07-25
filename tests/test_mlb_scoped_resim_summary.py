"""Regression tests for #41 -- scoped resims truncating the MLB daily summary.

The bug (fixed in dcda6243, previously untested): on a `--only-game-pks` run,
a non-targeted game with adequate existing artifacts hit `continue` in
daily_update.py's preserve branch BEFORE `outputs.append(record)`. So
`summary["outputs"]` came out holding only the targeted games. The skipped
games were recorded under a separate `preserved_non_targeted_games` key
carrying only metadata -- paths and abbreviations, no sim segments -- and
nothing downstream ever merged it back.

That matters because `_games_from_daily_summary` builds the ENTIRE MLB board
from `summary["outputs"]`. So every scoped resim -- every lineup/injury
fingerprint_change, every tip_off_window, every join_mismatch -- rewrote the
summary with only the resimmed game(s) and silently dropped the rest of the
slate off the board until the next full-slate run. Very likely the mechanism
behind the long-standing "board count swings 184 -> 10" flakiness.

Two layers of guard here, because the producer and consumer live in
different repos:

1. Consumer contract (behavioural) -- pins what cards.py actually does with
   the summary, so the blast radius of a truncated summary stays visible.
2. Producer guard (structural) -- daily_update.py is vendored, and the fix
   lives inside a ~2000-line `main()` whose helpers are nested locals that
   cannot be imported. A source-level assertion is the only thing that can
   catch a re-vendor or refactor reverting the merge; it is deliberately
   pinned to the few tokens that encode the invariant, not to formatting.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from syndicate.features.mlb.cards import _games_from_daily_summary


REPO_ROOT = Path(__file__).resolve().parent.parent
DAILY_UPDATE = REPO_ROOT / "vendor" / "mlb_bettingv2" / "tools" / "daily_update.py"


def _summary_row(game_pk: int, away: str, home: str) -> dict:
    return {
        "game_pk": game_pk,
        "away": away,
        "home": home,
        "starter_names": {"away": f"{away} SP", "home": f"{home} SP"},
        "full": {"home_win_prob": 0.55, "away_win_prob": 0.45},
    }


class ScopedResimBoardContractTests(unittest.TestCase):
    """The board is built from summary["outputs"] and nothing else -- so a
    summary missing preserved games IS a board missing those games."""

    def test_board_includes_every_game_in_outputs(self) -> None:
        summary = {
            "date": "2026-07-25",
            "games": 6,
            "games_simulated": 2,
            "outputs": [_summary_row(100 + index, f"A{index}", f"H{index}") for index in range(6)],
        }

        games = _games_from_daily_summary(summary)

        self.assertEqual(len(games), 6)
        self.assertEqual([game["gamePk"] for game in games], [100, 101, 102, 103, 104, 105])

    def test_board_shrinks_to_exactly_what_a_truncated_summary_carries(self) -> None:
        # This is the failure the fix prevents, asserted directly: a summary
        # holding only the 2 resimmed games yields a 2-game board, even though
        # 6 games are on the slate and the other 4 are named under
        # preserved_non_targeted_games. That key is metadata only -- the board
        # never reads it -- which is why merging into "outputs" was required.
        truncated = {
            "date": "2026-07-25",
            "games": 2,
            "outputs": [_summary_row(100, "A0", "H0"), _summary_row(101, "A1", "H1")],
            "preserved_non_targeted_games": [
                {"game_pk": 102, "away": "A2", "home": "H2"},
                {"game_pk": 103, "away": "A3", "home": "H3"},
                {"game_pk": 104, "away": "A4", "home": "H4"},
                {"game_pk": 105, "away": "A5", "home": "H5"},
            ],
        }

        games = _games_from_daily_summary(truncated)

        self.assertEqual(len(games), 2)
        self.assertNotIn(102, [game["gamePk"] for game in games])

    def test_preserved_rows_carry_real_predictions_not_just_metadata(self) -> None:
        # The preserve branch loads the game's existing sim artifact off disk
        # to build a full row. A metadata-only row would put the game on the
        # board but with empty predictions, which is its own silent failure.
        summary = {"date": "2026-07-25", "outputs": [_summary_row(100, "A0", "H0")]}

        game = _games_from_daily_summary(summary)[0]

        self.assertIsNotNone(game.get("predictions"))
        self.assertEqual(game["away"]["abbr"], "A0")
        self.assertEqual(game["home"]["abbr"], "H0")

    def test_board_preserves_outputs_ordering(self) -> None:
        # dcda6243 emits rows sorted by slate index. The board does no sorting
        # of its own, so summary order IS display order.
        summary = {
            "date": "2026-07-25",
            "outputs": [_summary_row(300, "C", "D"), _summary_row(100, "A", "B"), _summary_row(200, "E", "F")],
        }

        games = _games_from_daily_summary(summary)

        self.assertEqual([game["gamePk"] for game in games], [300, 100, 200])


class ScopedResimProducerGuardTests(unittest.TestCase):
    """Structural guard on the vendored producer. See module docstring for
    why this cannot be a behavioural test."""

    @classmethod
    def setUpClass(cls) -> None:
        if not DAILY_UPDATE.is_file():
            raise unittest.SkipTest(f"vendored daily_update.py not present at {DAILY_UPDATE}")
        cls.source = DAILY_UPDATE.read_text(encoding="utf-8", errors="ignore")

    def test_outputs_are_emitted_from_merged_summary_rows(self) -> None:
        # The regression to catch: reverting to a comprehension over `outputs`,
        # which by construction holds only the resimmed games.
        self.assertRegex(
            self.source,
            r'"outputs":\s*\[\s*row\s+for\s+_,\s*row\s+in\s+sorted\(\s*summary_rows',
            "summary['outputs'] must be built from the merged summary_rows (sorted by slate "
            "index), not from `outputs` -- `outputs` contains only resimmed games, so building "
            "from it drops every preserved game off the MLB board. See dcda6243.",
        )

    def test_preserve_branch_contributes_a_row_before_continuing(self) -> None:
        # The original bug in one line: `continue` before anything was recorded.
        preserve_block = re.search(
            r"summary_rows\.append\(\(int\(idx\), _daily_summary_row\(preserved_record\)\)\).*?\bcontinue\b",
            self.source,
            re.DOTALL,
        )
        self.assertIsNotNone(
            preserve_block,
            "the --only-game-pks preserve branch must append a summary row for the skipped "
            "game BEFORE `continue`; without it the game vanishes from summary['outputs'] "
            "and therefore from the board.",
        )

    def test_games_counts_full_slate_and_simulated_is_separate(self) -> None:
        self.assertIn('"games": len(summary_rows)', self.source)
        self.assertIn('"games_simulated": len(outputs)', self.source)

    def test_missing_preserved_artifact_is_reported_not_swallowed(self) -> None:
        # A preserved game whose sim artifact is unreadable still drops off the
        # board. That is a real gap and must be loud, per "no silent caps".
        self.assertIn("it will be missing from the summary", self.source)
