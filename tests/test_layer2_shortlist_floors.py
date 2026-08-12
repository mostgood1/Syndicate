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

    def test_default_ceiling_does_not_delete_a_whole_sport(self) -> None:
        """No sport may go to ZERO rows under the default ceiling (`#380`).

        This is the invariant, not "nothing is excluded" -- the 22.2h soccer tail
        SHOULD be cut, and this test asserted otherwise until 2026-08-12, which is
        why it failed silently through the 1h change rather than blocking it.

        Each sport is given its measured span, so a ceiling landing anywhere
        inside a sport's range still leaves that sport represented. The 1h value
        took wnba and soccer to zero; 12h took wnba to zero, because wnba's range
        is 12.47h..13.00h and only its FRESHEST end is below 12h.
        """
        rows = [
            _row(sport="mlb", age=11.46 * 3600),
            _row(sport="wnba", age=12.47 * 3600),
            _row(sport="wnba", age=13.00 * 3600),
            _row(sport="soccer", age=1.85 * 3600),
            _row(sport="soccer", age=22.2 * 3600),
        ]
        out = select_shortlist(rows, now=_NOW)
        seated = {r.get("sport") for r in out["rows"]}
        self.assertEqual(
            seated, {"mlb", "wnba", "soccer"}, "default ceiling took a sport to zero rows"
        )
        # The dead 22.2h soccer quote is excluded -- the gate must still bite.
        self.assertEqual(out["rows_beyond_quote_age"], 1)

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


    def test_a_pregame_state_after_kickoff_does_not_protect_the_row(self) -> None:
        """The regression that shipped. `bool(state)` treated PRESENCE as
        evidence, so when a concurrent fix (60689dee) took soccer rows from
        `game.state: None` to `"pregame"`, this guard switched OFF for exactly
        the rows it was written for. Measured 2026-08-08 20:30Z: the same match
        still ranked #1 and #2, state='pregame', 6.02h after kickoff.

        `pregame` after commence_time is a contradiction, not information.
        """
        out = select_shortlist([self._row_at(6.02, state="pregame")], now=_NOW)
        self.assertEqual(len(out["rows"]), 0)
        self.assertEqual(out["rows_stale_kickoff"], 1)

    def test_an_unrecognised_state_fails_toward_the_clock(self) -> None:
        out = select_shortlist([self._row_at(6.0, state="banana")], now=_NOW)
        self.assertEqual(len(out["rows"]), 0)

    def test_final_and_live_are_still_left_to_the_gate(self) -> None:
        for state in ("live", "final", "in_progress", "post"):
            out = select_shortlist([self._row_at(6.0, state=state)], now=_NOW)
            self.assertEqual(len(out["rows"]), 1, f"{state} must be left to opportunity_gate")

    def test_pregame_BEFORE_kickoff_is_untouched(self) -> None:
        out = select_shortlist([self._row_at(-2.0, state="pregame")], now=_NOW)
        self.assertEqual(len(out["rows"]), 1)

    def test_rejections_are_reported(self) -> None:
        out = select_shortlist([self._row_at(9.0), _row(ev=2.0)], now=_NOW)
        self.assertEqual(out["rows_stale_kickoff"], 1)
        self.assertEqual(len(out["rows"]), 1)

class PerSportMeasuredFloorTests(unittest.TestCase):
    """The floor is expressed in units of each sport's OWN hold.

    `ev_pct` against the consensus no-vig fair is exactly `1/overround - 1`, so
    `ev_pct == -hold_pct` -- verified to four decimals against `hold_pct()`
    (best -115/+110 -> hold 1.0953%, measured ev -1.0953). A row's value% is its
    market's hold, negated.

    Natural hold is a property of MARKET STRUCTURE, not quality: soccer's 3-way
    markets hold more than MLB's 2-way ones. A single global number is therefore
    an MLB-shaped default that silently penalises every sport whose markets are
    not shaped like MLB's -- measured, soccer contributed 3 rows at -2.0 and 24
    at -5.0.

    Replayed on the real pre-floor payload: mlb measured median hold -1.1417 ->
    floor -2.2834; wnba +1.2048 -> -2.4096; soccer had only ONE two-sided market
    in that sample and correctly declined to measure.
    """

    def _priced(self, sport, event, side, price, ev):
        row = _row(sport=sport, ev=ev)
        row["event_id"] = event
        row["market"] = "h2h"
        row["segment"] = "full"
        row["side"] = side
        row["quote"] = {"book_age_seconds": 3600.0, "price": price}
        return row

    def _two_sided_pool(self, sport, n, home=-110, away=-110, ev=-1.0):
        rows = []
        for i in range(n):
            rows.append(self._priced(sport, f"e{i}", "home", home, ev))
            rows.append(self._priced(sport, f"e{i}", "away", away, ev))
        return rows

    def test_a_measured_floor_is_derived_and_reported_with_its_evidence(self) -> None:
        """A threshold that cannot show its own measurement is the class of
        constant this repo has paid for most often."""
        out = select_shortlist(self._two_sided_pool("mlb", 12), now=_NOW, stale_kickoff_seconds=0)
        ev = out["value_floor_by_sport"]["mlb"]
        self.assertEqual(ev["method"], "measured_hold")
        self.assertEqual(ev["markets_measured"], 12)
        self.assertAlmostEqual(ev["median_hold_pct"], 4.5455, places=3)
        self.assertAlmostEqual(ev["floor"], -9.0909, places=3)

    def test_too_few_markets_falls_back_to_the_flat_default(self) -> None:
        """A median over three markets is not a market-structure measurement,
        it is noise with a decimal point."""
        out = select_shortlist(self._two_sided_pool("soccer", 3), now=_NOW, stale_kickoff_seconds=0)
        ev = out["value_floor_by_sport"]["soccer"]
        self.assertEqual(ev["method"], "flat_default")
        self.assertEqual(ev["floor"], SHORTLIST_MIN_VALUE_PCT)

    def test_a_wider_holding_sport_gets_a_looser_floor(self) -> None:
        """The whole point: structure, not quality."""
        tight = select_shortlist(self._two_sided_pool("mlb", 12, home=-102, away=-102), now=_NOW, stale_kickoff_seconds=0)
        wide = select_shortlist(self._two_sided_pool("soccer", 12, home=-140, away=110), now=_NOW, stale_kickoff_seconds=0)
        self.assertLess(
            wide["value_floor_by_sport"]["soccer"]["floor"],
            tight["value_floor_by_sport"]["mlb"]["floor"],
            "the sport whose markets hold more must get the looser bar",
        )

    def test_the_floor_never_tightens_below_the_flat_default(self) -> None:
        """DELIBERATE SAFETY PROPERTY, stated so it is not read as a bug.

        A measured floor may only LOOSEN. Tonight a floor at 0.0 took the board
        200 -> 103 and deleted two sports, so a mis-measured hold must not be
        able to gut one. The cost is that a genuinely tight-holding sport keeps
        the default bar rather than a stricter one -- the safer of the two
        failure directions.
        """
        out = select_shortlist(self._two_sided_pool("mlb", 12, home=-101, away=-101), now=_NOW, stale_kickoff_seconds=0)
        self.assertEqual(out["value_floor_by_sport"]["mlb"]["floor"], SHORTLIST_MIN_VALUE_PCT)

    def test_a_crossed_market_does_not_invert_the_floor(self) -> None:
        """Best prices that cross give a NEGATIVE hold. Without abs() that would
        produce a floor ABOVE zero and reject the sport's own normal rows."""
        out = select_shortlist(self._two_sided_pool("mlb", 12, home=105, away=105), now=_NOW, stale_kickoff_seconds=0)
        self.assertLessEqual(out["value_floor_by_sport"]["mlb"]["floor"], 0.0)

    def test_calibration_can_be_disabled(self) -> None:
        out = select_shortlist(self._two_sided_pool("mlb", 12), now=_NOW, stale_kickoff_seconds=0, hold_multiple_override=0)
        self.assertEqual(out["value_floor_by_sport"]["mlb"]["method"], "flat_default")

    def test_one_sided_markets_are_not_measurable(self) -> None:
        """A 3-way market whose third leg was gated out leaves one side; so does
        most of the SHORTLIST for soccer. Measuring on the full pool rather than
        downstream is why this is done inside select_shortlist."""
        rows = [self._priced("soccer", f"e{i}", "home", -110, -1.0) for i in range(20)]
        out = select_shortlist(rows, now=_NOW, stale_kickoff_seconds=0)
        self.assertEqual(out["value_floor_by_sport"]["soccer"]["method"], "flat_default")
        self.assertEqual(out["value_floor_by_sport"]["soccer"]["markets_measured"], 0)


if __name__ == "__main__":
    unittest.main()


class ModelledHoldFloorTests(unittest.TestCase):
    """`#382` -- a sport whose pool is one-sided by construction got MLB's floor.

    `_measured_floor_for_pool` regroups the pool into two-sided markets to
    measure a sport's own hold. Soccer's markets are 3-way and the draw leg is
    gated, so the pool keeps ~1.1 sides per row. Measured on production
    2026-08-12 via `value_floor_by_sport`:

        mlb    markets_measured 1986  median_hold 5.99%  floor -11.98
        wnba   markets_measured  722  median_hold 5.26%  floor -10.53
        nfl    markets_measured  107  median_hold 3.89%  floor  -7.78
        soccer markets_measured    0                     floor  -2.00  <- flat

    Zero, not "too few". Soccer was judged at a constant calibrated on 2-way
    markets and seated 0 of 2,359 opportunities.
    """

    @staticmethod
    def _one_sided(*, ev, hold=5.53, sport="soccer"):
        row = _row(sport=sport, ev=ev)
        # Mirrors what the fan-out produces (see the survives_the_fan_out test
        # below, which asserts this shape against the real builder).
        row["quote"]["assumed_hold_pct"] = hold
        return row

    def test_a_one_sided_sport_is_floored_on_its_own_modelled_hold(self) -> None:
        # -6.0 is normal pricing for a market holding 5.53%, and the flat -2.0
        # would reject it. 5.53 * 2.0 = -11.06, which keeps it.
        rows = [self._one_sided(ev=-6.0) for _ in range(12)]
        out = select_shortlist(rows, now=_NOW)
        evidence = (out["value_floor_by_sport"] or {}).get("soccer") or {}
        self.assertEqual(evidence.get("method"), "modelled_hold")
        self.assertAlmostEqual(evidence.get("floor"), -11.06, places=2)
        self.assertEqual(len(out["rows"]), 12, "soccer was deleted by an MLB-shaped floor")
        self.assertEqual(out["rows_below_value_floor"], 0)

    def test_the_modelled_floor_still_cuts_genuine_junk(self) -> None:
        # Looser is not absent. A row far below what the measured hold explains
        # must still go, or this becomes "no floor" wearing a measurement's name.
        rows = [self._one_sided(ev=-6.0) for _ in range(12)] + [self._one_sided(ev=-40.0)]
        out = select_shortlist(rows, now=_NOW)
        self.assertEqual(out["rows_below_value_floor"], 1)

    def test_it_never_tightens_past_the_flat_default(self) -> None:
        # A tiny modelled hold must not produce a floor STRICTER than -2.0 and
        # start rejecting ordinary rows -- same clamp as the two-sided path.
        rows = [self._one_sided(ev=-1.5, hold=0.1) for _ in range(12)]
        out = select_shortlist(rows, now=_NOW)
        evidence = (out["value_floor_by_sport"] or {}).get("soccer") or {}
        self.assertLessEqual(evidence.get("floor"), SHORTLIST_MIN_VALUE_PCT)
        self.assertEqual(len(out["rows"]), 12)

    def test_too_few_modelled_rows_still_falls_back_to_flat(self) -> None:
        # The second estimator needs evidence too. Below the threshold it must
        # not invent a floor from a handful of rows.
        rows = [self._one_sided(ev=-6.0) for _ in range(3)]
        out = select_shortlist(rows, now=_NOW)
        evidence = (out["value_floor_by_sport"] or {}).get("soccer") or {}
        self.assertEqual(evidence.get("method"), "flat_default")


class ModelledHoldReachesTheFloorTests(unittest.TestCase):
    """`#382` -- the floor logic was right and read a field that never arrived.

    `assumed_hold_pct` is stamped at `modelled_fair[side]` on the GRID row.
    `build_layer2_rows` fans a grid row into one candidate per side by copying a
    fixed field list, and did not carry it. `_measured_floor_for_pool` runs on
    candidates, so the modelled-hold branch read 0 rows on production for two
    hours while four unit tests passed -- they hand-built candidates ALREADY
    carrying the field, proving the branch works given its input and never that
    the input arrives.

    So this test drives the REAL builder. A test that constructs the row it is
    testing cannot fail for this reason, which is the whole lesson.
    """

    def test_the_modelled_hold_survives_the_real_fan_out(self) -> None:
        from syndicate.features.shared.layer2_board import build_layer2_rows

        grid = [
            {
                "sport": "soccer",
                "event_id": "evt-1",
                "kind": "game",
                "market": "h2h",
                "sides": ["home"],
                "commence_time": (_NOW + timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
                "best": {
                    "home": {
                        "price": -140,
                        "bookmaker": "pinnacle",
                        "books_quoting": 3,
                        "book_age_seconds": 120.0,
                    }
                },
                "game": {"state": "pre", "start_time": (_NOW + timedelta(hours=3)).isoformat().replace("+00:00", "Z")},
                # One-sided market filled by the margin model -- the exact shape
                # `apply_margin_model` writes, and the only source of a soccer hold.
                "modelled_fair": {
                    "home": {
                        "fair_probability": 0.55,
                        "assumed_hold_pct": 5.53,
                        "fair_method": "book_margin_model",
                    }
                },
            }
        ]
        # `build_layer2_rows` returns STATS plus the candidate list under
        # `opportunities` -- it does not return a bare list of rows.
        result = build_layer2_rows(grid)
        rows = result.get("opportunities") or []
        self.assertTrue(rows, "the fan-out produced no gated candidate at all")
        quote = rows[0].get("quote") or {}
        self.assertEqual(
            quote.get("assumed_hold_pct"),
            5.53,
            "the margin model's hold did not survive grid -> candidate; the "
            "modelled-hold floor is inert again",
        )
