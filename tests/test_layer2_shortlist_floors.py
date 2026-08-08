"""The two quality floors on the L2-A shortlist.

Measured on the SERVED board, 2026-08-08 (`/api/board/layer2-shortlist`, 200
rows): **105 rows carried negative value%**, median -0.702, range -8.72..+4.24.
More than half the board was priced worse than the market's own no-vig fair.
That is floor-then-merit with no quality bar: `per_sport` and `kind_floor`
guarantee slots are filled whether or not anything deserves them, so the floors
must be applied BEFORE the per-sport buckets or the guarantee re-seats the rows
they just rejected.

The value floor is NOT a positive-EV gate and must never be relabelled as one --
it is "best price beats consensus fair", which is L2-C's question. `65b15a03`
withdrew an earlier `ev_pct >= 0` proposal, correctly, because it was headed for
`opportunity_gate`, whose job `#245` fixed as "is this market live". This is a
selection rule on the DISPLAY artifact; the ledger still carries every gated row
for S6.

The age ceiling is deliberately loose. Same 200 rows: mlb's 100 quotes all sat
within a 1.2-minute window 11.46h old, wnba's 36 within 13h, while soccer showed
a real 1.85-22.2h spread. 100 markets do not independently freeze inside 1.2
minutes -- that is one stale capture, and a ceiling tight enough to act on it
(<=6h) leaves 3 of 200 rows and deletes two sports. So the ceiling is a backstop
against dead quotes, not the instrument for that lag.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from syndicate.features.shared.layer2_board import (
    SHORTLIST_MAX_QUOTE_AGE_SECONDS,
    SHORTLIST_MIN_VALUE_PCT,
    select_shortlist,
)

_NOW = datetime(2026, 8, 8, 18, 0, tzinfo=timezone.utc)


def _row(*, sport="mlb", kind="game", ev=1.0, age=3600.0, score=None):
    return {
        "sport": sport,
        "kind": kind,
        "ev_pct": ev,
        "commence_time": (_NOW + timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
        "quote": {"book_age_seconds": age},
        "score": {"score": score if score is not None else ev},
    }


class ValueFloorTests(unittest.TestCase):
    def test_junk_is_dropped_and_normal_pricing_is_kept(self) -> None:
        """The floor is a junk filter, not a value gate.

        -0.7 is what a NORMALLY PRICED market looks like -- `ev_pct` is measured
        against consensus no-vig fair, so it is `1/overround - 1` and negative
        on every side of any market with hold (a realistic 3-book market scores
        -1.0953 on both sides). Dropping it would empty the board of ordinary
        markets, which is what the briefly-shipped 0.0 default did.
        """
        out = select_shortlist([_row(ev=2.0), _row(ev=-0.7), _row(ev=-8.72)], now=_NOW)
        kept = sorted(r["ev_pct"] for r in out["rows"])
        self.assertEqual(kept, [-0.7, 2.0])
        self.assertEqual(out["rows_below_value_floor"], 1)

    def test_the_floor_is_inclusive_at_its_boundary(self) -> None:
        out = select_shortlist([_row(ev=-2.0)], now=_NOW, min_value_pct=-2.0)
        self.assertEqual(len(out["rows"]), 1)

    def test_the_kind_floor_cannot_re_seat_a_rejected_row(self) -> None:
        """The whole point. kind_floor guarantees 30 prop slots; if the floors
        ran after bucketing, the guarantee would drag negative rows back in --
        which is how 105 of them reached the served board."""
        rows = [_row(kind="prop", ev=-5.0) for _ in range(40)] + [_row(kind="game", ev=3.0)]
        out = select_shortlist(rows, now=_NOW, kind_floor=30)
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["rows"][0]["kind"], "game")

    def test_a_row_with_no_value_at_all_is_not_dropped(self) -> None:
        """Absence of a measurement is not a negative measurement."""
        row = _row()
        row.pop("ev_pct")
        row["score"] = {"score": 1.0}
        out = select_shortlist([row], now=_NOW)
        self.assertEqual(len(out["rows"]), 1)

    def test_floor_is_env_tunable(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_SHORTLIST_MIN_VALUE_PCT": "2.0"}, clear=False):
            out = select_shortlist([_row(ev=1.0), _row(ev=2.5)], now=_NOW)
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["min_value_pct"], 2.0)


class QuoteAgeCeilingTests(unittest.TestCase):
    def test_quotes_beyond_the_ceiling_are_dropped(self) -> None:
        out = select_shortlist(
            [_row(age=3600.0), _row(age=48 * 3600.0)], now=_NOW, max_quote_age_seconds=24 * 3600
        )
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["rows_beyond_quote_age"], 1)

    def test_unknown_age_is_kept(self) -> None:
        """No book clock is not evidence of staleness -- the score already
        discounts it (0.6). Excluding it would delete whole sources."""
        row = _row()
        row["quote"] = {}
        out = select_shortlist([row], now=_NOW)
        self.assertEqual(len(out["rows"]), 1)

    def test_default_ceiling_does_not_delete_todays_board(self) -> None:
        """The measured clusters -- mlb 11.46h, wnba 13.0h, soccer up to 22.2h --
        must all survive the DEFAULT. A ceiling that silently emptied the board
        would look identical to an outage."""
        rows = [
            _row(sport="mlb", age=11.46 * 3600),
            _row(sport="wnba", age=13.0 * 3600),
            _row(sport="soccer", age=22.2 * 3600),
        ]
        out = select_shortlist(rows, now=_NOW)
        self.assertEqual(len(out["rows"]), 3, "default ceiling must not gut the live board")
        self.assertEqual(out["rows_beyond_quote_age"], 0)

    def test_ceiling_is_env_tunable(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_SHORTLIST_MAX_QUOTE_AGE_SECONDS": "21600"}, clear=False):
            out = select_shortlist([_row(age=11.46 * 3600), _row(age=1800.0)], now=_NOW)
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["max_quote_age_seconds"], 21600.0)

    def test_zero_ceiling_disables_the_rule(self) -> None:
        out = select_shortlist([_row(age=100 * 3600)], now=_NOW, max_quote_age_seconds=0)
        self.assertEqual(len(out["rows"]), 1)


class ReportingTests(unittest.TestCase):
    def test_both_rejections_are_reported_not_silent(self) -> None:
        """A board that shrinks must say which rule shrank it."""
        out = select_shortlist(
            [_row(ev=-8.0), _row(age=100 * 3600), _row(ev=2.0)],
            now=_NOW,
            max_quote_age_seconds=24 * 3600,
        )
        self.assertEqual(out["rows_below_value_floor"], 1)
        self.assertEqual(out["rows_beyond_quote_age"], 1)
        self.assertEqual(len(out["rows"]), 1)

    def test_defaults_are_the_documented_ones(self) -> None:
        out = select_shortlist([_row(ev=1.0)], now=_NOW)
        self.assertEqual(out["min_value_pct"], SHORTLIST_MIN_VALUE_PCT)
        self.assertEqual(out["max_quote_age_seconds"], SHORTLIST_MAX_QUOTE_AGE_SECONDS)


class StaleKickoffGuardTests(unittest.TestCase):
    """A market cannot be "pregame" after its own start time.

    `opportunity_gate`'s dead-market rule is the real defence, but it reads
    `game.state`, and for nine of the ten soccer leagues that state is
    PERMANENTLY `pregame` -- `_unsimulated_game` defaults `status_state` to
    "pre" and fixtures carry no live status, so only the SIMULATED path (MLS
    alone) ever stamps a real one. The gate therefore cannot fire for them at
    any hour.

    Measured on the served board 2026-08-08 19:53Z: the **#1 and #2 ranked
    rows** were a match that kicked off **5.47 hours earlier**, still labelled
    pregame with `game.state: None`. Replaying that payload through this guard
    takes it 115 -> 112 rows and puts MLB back on top.
    """

    def _row_at(self, hours_ago: float, *, state=None, ev: float = 3.0) -> dict:
        started = (_NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
        row = _row(ev=ev)
        row["commence_time"] = started
        row["market_state"] = "pregame"
        if state is not None:
            row["game"] = {"state": state}
        return row

    def test_a_finished_game_with_no_state_is_dropped(self) -> None:
        out = select_shortlist([self._row_at(5.47)], now=_NOW)
        self.assertEqual(len(out["rows"]), 0)
        self.assertEqual(out["rows_stale_kickoff"], 1)

    def test_a_row_with_a_real_state_is_left_to_the_gate(self) -> None:
        """Never second-guess a working `game.state` -- MLB carries one, so its
        rain delays keep being handled by the gate rather than by a clock."""
        out = select_shortlist([self._row_at(5.47, state="live")], now=_NOW)
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["rows_stale_kickoff"], 0)

    def test_a_delayed_start_inside_the_grace_survives(self) -> None:
        out = select_shortlist([self._row_at(1.5)], now=_NOW)
        self.assertEqual(len(out["rows"]), 1)

    def test_a_pregame_row_is_untouched(self) -> None:
        out = select_shortlist([self._row_at(-3.0)], now=_NOW)
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["rows_stale_kickoff"], 0)

    def test_missing_commence_time_is_not_treated_as_stale(self) -> None:
        """Absence of a start time is not evidence the game finished."""
        row = _row(ev=3.0)
        row.pop("commence_time", None)
        out = select_shortlist([row], now=_NOW)
        self.assertEqual(len(out["rows"]), 1)

    def test_guard_is_disabled_at_zero(self) -> None:
        out = select_shortlist([self._row_at(99.0)], now=_NOW, stale_kickoff_seconds=0)
        self.assertEqual(len(out["rows"]), 1)

    def test_rejections_are_reported(self) -> None:
        out = select_shortlist([self._row_at(9.0), _row(ev=2.0)], now=_NOW)
        self.assertEqual(out["rows_stale_kickoff"], 1)
        self.assertEqual(len(out["rows"]), 1)

if __name__ == "__main__":
    unittest.main()
