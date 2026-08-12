"""`#391` -- one game could take the whole visible board.

There was a cap per sport (100) and a floor per kind (30), and nothing per
EVENT. Measured on the served board 2026-08-12, 200 rows across 36 games:

    26  wnba Chicago Sky @ Golden State Valkyries
    19  mlb  Philadelphia Phillies @ St. Louis Cardinals
    14  mlb  Baltimore Orioles @ Minnesota Twins

**The aggregate looked healthy and the experience did not.** "200 rows, 36
games" passes any endpoint check. The board is sorted by score, so the
concentration lands entirely at the TOP -- the first ~14 rows a person sees were
one matchup, listed as over/under/spread/alt/prop until that game ran out of
markets. This was caught by a user's screenshot, not by any check I ran.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from syndicate.features.shared.layer2_board import select_shortlist

# `#391` is unimplemented, so the real constant does not exist yet. Declared here
# so this spec module IMPORTS (a skip decorator does not stop a module-level
# ImportError from breaking collection for the whole suite). On implementation,
# delete this and import `SHORTLIST_ROWS_PER_GAME` from layer2_board instead --
# if these two ever disagree the spec is testing itself, not the code.
SHORTLIST_ROWS_PER_GAME = 6

_NOW = datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc)


def _row(*, event_id, ev, kind="game", sport="mlb"):
    return {
        "sport": sport,
        "kind": kind,
        "event_id": event_id,
        "market": "totals",
        "ev_pct": ev,
        "commence_time": (_NOW + timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
        "quote": {"book_age_seconds": 60.0},
        "score": {"score": ev},
    }


@unittest.skip(
    "`#391` SPEC, NOT YET IMPLEMENTED. These tests describe the per-game cap and "
    "are committed unimplemented on purpose -- an attempt on 2026-08-12 capped to "
    "6 but kept each game's WORST rows and never incremented its counter, and was "
    "reverted rather than shipped half-working. Un-skip when implementing."
)
class PerGameCapTests(unittest.TestCase):
    def test_one_game_cannot_take_the_whole_board(self) -> None:
        # The measured shape: one game with 26 strong rows, three others with a
        # few. Without the cap the big game's 26 outrank everything.
        rows = [_row(event_id="hot", ev=9.0 - i * 0.1) for i in range(26)]
        rows += [_row(event_id=f"other-{n}", ev=5.0) for n in range(3)]
        out = select_shortlist(rows, now=_NOW)
        seated = {}
        for r in out["rows"]:
            seated[r["event_id"]] = seated.get(r["event_id"], 0) + 1
        self.assertLessEqual(seated.get("hot", 0), SHORTLIST_ROWS_PER_GAME)
        self.assertEqual(out["rows_beyond_game_cap"], 26 - SHORTLIST_ROWS_PER_GAME)
        # And the other games are still on the board rather than crowded out.
        self.assertEqual(len([k for k in seated if k.startswith("other-")]), 3)

    def test_the_cap_keeps_a_games_BEST_rows(self) -> None:
        # Trimming must drop the worst rows of a game, never the best.
        rows = [_row(event_id="g", ev=float(i)) for i in range(20)]
        out = select_shortlist(rows, now=_NOW)
        kept = sorted((r["ev_pct"] for r in out["rows"]), reverse=True)
        self.assertEqual(kept, [19.0, 18.0, 17.0, 16.0, 15.0, 14.0][: len(kept)])

    def test_rows_without_event_id_do_not_collapse_into_one_bucket(self) -> None:
        """An absent key must not make unrelated games share a single cap."""
        rows = []
        for n in range(10):
            r = _row(event_id=None, ev=5.0)
            r["home_team"], r["away_team"] = f"home-{n}", f"away-{n}"
            rows.append(r)
        out = select_shortlist(rows, now=_NOW)
        self.assertEqual(len(out["rows"]), 10, "distinct matchups were capped as one game")

    def test_the_kind_floor_cannot_re_seat_a_row_the_cap_dropped(self) -> None:
        """Same ordering rule the value floor follows: guarantees seat FROM the
        capped list, or the guarantee undoes the cap."""
        rows = [_row(event_id="g", ev=9.0 - i * 0.1, kind="prop") for i in range(40)]
        out = select_shortlist(rows, now=_NOW, kind_floor=30)
        self.assertLessEqual(len(out["rows"]), SHORTLIST_ROWS_PER_GAME)

    def test_zero_disables_the_cap(self) -> None:
        rows = [_row(event_id="g", ev=5.0) for _ in range(20)]
        out = select_shortlist(rows, now=_NOW, rows_per_game=0)
        self.assertEqual(len(out["rows"]), 20)
        self.assertEqual(out["rows_beyond_game_cap"], 0)
