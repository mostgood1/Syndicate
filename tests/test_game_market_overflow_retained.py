"""Game markets keep their cap overflow, as prop markets already did — `#626`(b).

Until 2026-09-01 `totals` and `ml` were the ONLY markets on the MLB
locked-policy card that DISCARDED what the cap excluded. `pitcher_props` and
every hitter market retain theirs as `other_playable_candidates`; the game
markets kept nothing, in BOTH card builders, with no comment anywhere giving a
reason. Copy-drift, not a decision.

What it cost: `caps.ml = 1` against **12 raw ML candidates** on a normal slate
(`#610`), so 11 playable picks a day were counted and dropped; `caps.totals = 0`
discarded the totals pool entirely — the market the MLB accuracy assessment
calls "calibration WITHOUT information", which cannot be measured while every
candidate is thrown away before grading.

This is NOT a cap change. `recommendations` is still the capped selection and
the `official` tier is untouched; the overflow lands in `candidate`, which both
consumers already handle by market-agnostic code.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from vendor.mlb_bettingv2.tools.daily_update_multi_profile import (
    _rank_and_cap,
    _subtract_selected_rows,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
WRITER = REPO_ROOT / "vendor" / "mlb_bettingv2" / "tools" / "daily_update_multi_profile.py"
MANIFEST = REPO_ROOT / "vendor" / "mlb_bettingv2" / "tools" / "eval" / "build_season_betting_cards_manifest.py"


def _candidates(n: int) -> list[dict]:
    """n distinct game-market rows, descending edge so ranking is determinate."""
    return [
        {"game_pk": 700000 + i, "market": "ml", "selection": f"TEAM{i}", "edge": 0.20 - i * 0.01}
        for i in range(n)
    ]


class GameMarketOverflowArithmeticTests(unittest.TestCase):
    """The composition the card builders now use for game markets."""

    def test_a_cap_of_one_leaves_eleven_playable_candidates(self) -> None:
        """`#610`'s measured slate: 12 raw ML candidates against `caps.ml = 1`."""
        rows = _candidates(12)
        selected = _rank_and_cap(rows, 1)
        overflow = _subtract_selected_rows(rows, selected)
        self.assertEqual(len(selected), 1)
        self.assertEqual(len(overflow), 11, "the 11 dropped picks are the graded supply at stake")
        self.assertEqual(len(selected) + len(overflow), len(rows), "no candidate is lost or double-counted")

    def test_the_selected_pick_is_never_also_in_the_overflow(self) -> None:
        rows = _candidates(12)
        selected = _rank_and_cap(rows, 1)
        overflow = _subtract_selected_rows(rows, selected)
        chosen = {row["selection"] for row in selected}
        self.assertTrue(chosen.isdisjoint({row["selection"] for row in overflow}))

    def test_a_zero_cap_keeps_every_candidate_as_overflow(self) -> None:
        """`caps.totals = 0` today, so before this change the entire totals pool
        was discarded before grading."""
        rows = _candidates(15)
        selected = _rank_and_cap(rows, 0)
        overflow = _subtract_selected_rows(rows, selected)
        self.assertEqual(selected, [])
        self.assertEqual(len(overflow), 15)

    def test_an_uncapped_market_has_no_overflow(self) -> None:
        """Negative means uncapped (the flag's own help text), so nothing spills."""
        rows = _candidates(12)
        overflow = _subtract_selected_rows(rows, _rank_and_cap(rows, -1))
        self.assertEqual(overflow, [])

    def test_the_added_rank_key_does_not_break_subtraction(self) -> None:
        """`_rank_and_cap` stamps `rank` on what it returns, so subtraction has
        to match on candidate identity rather than on dict equality."""
        rows = _candidates(3)
        selected = _rank_and_cap(rows, 1)
        self.assertIn("rank", selected[0])
        self.assertEqual(len(_subtract_selected_rows(rows, selected)), 2)


class BothCardBuildersEmitOverflowTests(unittest.TestCase):
    """Reachability. The defect was a MISSING KEY in two places, so what needs
    pinning is that both game blocks now write it — and that the prop markets,
    which always did, are untouched."""

    def test_the_production_writer_emits_overflow_for_game_markets(self) -> None:
        source = WRITER.read_text(encoding="utf-8-sig")
        game_block = source.split('raw_rows: Dict[str, List[Dict[str, Any]]] = {', 1)[1].split("baseline_selected_pitcher_rows", 1)[0]
        self.assertIn('"other_playable_candidates": extra,', game_block)
        self.assertIn('"other_playable_candidates_n": int(len(extra)),', game_block)

    def test_the_manifest_builder_emits_overflow_for_game_markets(self) -> None:
        source = MANIFEST.read_text(encoding="utf-8-sig")
        game_block = source.split('for market_name in ("totals", "ml"):', 1)[1].split("selected_pitcher_rows", 1)[0]
        self.assertIn('"other_playable_candidates": extra,', game_block)
        self.assertIn('"other_playable_candidates_n": int(len(extra)),', game_block)

    def test_the_official_tier_is_still_the_capped_selection(self) -> None:
        """The whole point of not raising the cap: `recommendations` unchanged."""
        for path in (WRITER, MANIFEST):
            source = path.read_text(encoding="utf-8-sig")
            self.assertIn('"recommendations": selected,', source, str(path))

    def test_prop_markets_still_retain_theirs(self) -> None:
        source = WRITER.read_text(encoding="utf-8-sig")
        self.assertIn('"other_playable_candidates": extra_pitcher_rows,', source)


class OverflowReachesGradingAsCandidateTests(unittest.TestCase):
    """Why the missing key mattered: both consumers are market-agnostic, so the
    game markets were excluded from grading purely by not writing the field.

    Pinned here because if either consumer stops mapping extras to `candidate`,
    this change silently stops adding graded supply — and the failure would look
    like a supply problem, not a mapping one."""

    def test_the_manifest_grades_extras_as_the_candidate_tier(self) -> None:
        source = MANIFEST.read_text(encoding="utf-8-sig")
        self.assertIn('section.get("other_playable_candidates")', source)
        self.assertIn('tier="candidate"', source)

    def test_the_settler_settles_extras_as_the_candidate_tier(self) -> None:
        settler = REPO_ROOT / "vendor" / "mlb_bettingv2" / "tools" / "eval" / "settle_locked_policy_cards.py"
        source = settler.read_text(encoding="utf-8-sig")
        self.assertIn('("other_playable_candidates", "candidate"', source)


if __name__ == "__main__":
    unittest.main()
