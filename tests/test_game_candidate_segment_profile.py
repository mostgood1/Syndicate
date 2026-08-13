"""The per-row profiler blamed a row for work that ran after the loop.

`SLOW_ROW_PROFILE` appended a single closing mark at the END of
`_game_bet_candidates_from_game`, and reported deltas between consecutive marks.
The last delta therefore ran from the final loop iteration's start through the
whole post-loop tail -- the gameLens loop, the MLB props loops, and
`enrich_candidate_rows`.

For a game carrying ONE `game_market_recommendations` row that delta is the
entire function, which is how production read

    rows=1 total_s=399.40 min_s=p50_s=max_s=399.398

and was reported as "one pathological loop iteration". It is one row plus
everything after it, with no boundary between them.

The tests that matter are the two attribution directions. An instrument that
always blamed the tail would pass the first and fail the second, and the old one
passed the second while failing the first.
"""

from __future__ import annotations

import io
import os
import sys
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.blueprints import home


SPORT = {"slug": "mlb", "name": "MLB"}


def _game(rows: list[dict]) -> dict:
    return {
        "gamePk": 823833,
        "matchup": {"away": "AAA", "home": "HHH"},
        "game_market_recommendations": rows,
    }


def _row() -> dict:
    return {
        "market_label": "Moneyline",
        "display_pick": "Away ML",
        "odds": "-110",
        "ev_pct": 3.2,
        "p_win": 0.55,
        "projected": 0.55,
    }


def setUpModule() -> None:
    """Warm the loop-body deferred import.

    `_game_bet_candidates_from_game` imports `_is_game_level_market` from
    intelligence INSIDE the row loop. The first call in a process pays ~0.4s for
    it and that cost is charged -- correctly -- to `row[0]`. Left cold, these
    tests would pass or fail on import order rather than on attribution. In
    production intelligence is already imported: it is this function's caller.
    """
    from syndicate.features.intelligence import _is_game_level_market  # noqa: F401

    home._game_bet_candidates_from_game(SPORT, _game([_row()]), fallback_epoch=0.0)


def _run(game: dict) -> str:
    buf = io.StringIO()
    with patch.dict(os.environ, {"SYNDICATE_SLOW_ROW_TOTAL_SECONDS": "0.10"}):
        with redirect_stdout(buf):
            home._game_bet_candidates_from_game(SPORT, game, fallback_epoch=0.0)
    return "".join(line for line in buf.getvalue().splitlines() if "SLOW_SEGMENT_PROFILE" in line)


def _field(line: str, key: str) -> float:
    for token in line.split():
        if token.startswith(f"{key}="):
            return float(token.split("=", 1)[1])
    raise AssertionError(f"{key} not in {line!r}")


class TailIsNotBlamedOnARow(unittest.TestCase):
    """The production defect, reproduced: one row, slow tail."""

    def test_slow_enrichment_is_named_and_not_charged_to_the_row(self) -> None:
        import syndicate.features.shared.quote_enrichment as qe

        def _slow(*args, **kwargs):
            time.sleep(0.35)

        with patch.object(qe, "enrich_candidate_rows", _slow):
            line = _run(_game([_row()]))

        self.assertTrue(line, "no profile line emitted")
        # The whole point: the cost is attributed BY NAME to the tail segment.
        self.assertIn("enrich_block=", line)
        self.assertGreaterEqual(_field(line, "tail_s"), 0.30)
        # ...and the single row is NOT charged for it. Under the old instrument
        # this row would have absorbed the entire 0.35s.
        self.assertEqual(_field(line, "rows"), 1)
        self.assertLess(_field(line, "rows_s"), 0.10)


class ARealRowIsStillBlamed(unittest.TestCase):
    """The opposite direction. An instrument that always blamed the tail would
    pass the test above and be just as useless."""

    def test_slow_row_body_is_charged_to_a_row(self) -> None:
        calls = {"n": 0}
        real = home._append_game_bet_candidate

        def _slow_append(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                time.sleep(0.35)
            return real(*args, **kwargs)

        with patch.object(home, "_append_game_bet_candidate", _slow_append):
            line = _run(_game([_row(), _row(), _row()]))

        self.assertTrue(line, "no profile line emitted")
        self.assertGreaterEqual(_field(line, "rows_s"), 0.30)
        self.assertLess(_field(line, "tail_s"), 0.20)
        self.assertIn("row[", line)


class SegmentAccounting(unittest.TestCase):
    def test_rows_plus_tail_equals_total(self) -> None:
        """No segment is dropped or double-counted -- the failure that let the
        old line look self-consistent while hiding a whole phase."""
        import syndicate.features.shared.quote_enrichment as qe

        with patch.object(qe, "enrich_candidate_rows", lambda *a, **k: time.sleep(0.2)):
            line = _run(_game([_row(), _row()]))

        self.assertAlmostEqual(
            _field(line, "rows_s") + _field(line, "tail_s"), _field(line, "total_s"), places=2
        )

    def test_a_fast_game_stays_silent(self) -> None:
        self.assertEqual(_run(_game([_row()])), "")


if __name__ == "__main__":
    unittest.main()
