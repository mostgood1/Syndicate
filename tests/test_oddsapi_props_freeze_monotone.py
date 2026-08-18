"""The pregame props seal must be MONOTONE (`#440` Phase 7 follow-up).

Measured 2026-08-17 over 29 production dates: the props fetch usually runs
AFTER the slate, and a post-slate fetch returns an empty market because books
pull player props once games end. 12 of 29 dates archived ZERO pitchers, and
2026-08-08/08-09 sealed 1 and 2 pitchers permanently because the freeze was
first-write-wins whenever the slate clock was unknown.

Two directions, both of which were wrong before:
  - a poorer doc must NEVER replace a richer seal (the clock-known branch used
    to re-copy unconditionally, so it could downgrade);
  - a strictly richer doc MUST be able to replace a poorer seal (the
    clock-unknown branch was first-write-wins, so it could never improve).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.refresh_mlb_oddsapi import _oddsapi_props_richness


def doc(n_pitchers: int, *, priced: bool = True, markets=("outs",)) -> dict:
    props = {}
    for i in range(n_pitchers):
        entry = {"line": 17.5}
        if priced:
            entry["over_odds"] = "-110"
            entry["under_odds"] = "-110"
        props[f"pitcher {i}"] = {m: dict(entry) for m in markets}
    return {"date": "2026-08-17", "mode": "live", "pitcher_props": props}


def write(directory: Path, name: str, payload) -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class RichnessTests(unittest.TestCase):
    def test_absent_scores_minus_one_and_is_distinct_from_empty(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(_oddsapi_props_richness(root / "nope.json"), -1)
            self.assertEqual(_oddsapi_props_richness(write(root, "empty.json", doc(0))), 0)

    def test_counts_priced_sides_not_players(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 3 pitchers x 1 market x 2 priced sides
            self.assertEqual(_oddsapi_props_richness(write(root, "a.json", doc(3))), 6)
            # same players, two markets each
            self.assertEqual(
                _oddsapi_props_richness(write(root, "b.json", doc(3, markets=("outs", "so")))), 12
            )

    def test_an_unpriced_line_is_not_a_gradeable_quote(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(_oddsapi_props_richness(write(root, "c.json", doc(5, priced=False))), 0)

    def test_a_post_slate_empty_doc_scores_below_any_real_capture(self) -> None:
        # The production case: 12 of 29 dates archived zero pitchers.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            empty = _oddsapi_props_richness(write(root, "post.json", doc(0)))
            thin = _oddsapi_props_richness(write(root, "thin.json", doc(1)))
            rich = _oddsapi_props_richness(write(root, "rich.json", doc(30)))
            self.assertLess(empty, thin)
            self.assertLess(thin, rich)

    def test_bytes_do_not_decide_it(self) -> None:
        # A doc can grow in bytes while carrying fewer gradeable markets.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            padded = doc(2)
            padded["junk"] = "x" * 100_000
            big_but_poor = write(root, "big.json", padded)
            small_but_rich = write(root, "small.json", doc(10))
            self.assertGreater(big_but_poor.stat().st_size, small_but_rich.stat().st_size)
            self.assertLess(
                _oddsapi_props_richness(big_but_poor), _oddsapi_props_richness(small_but_rich)
            )

    def test_malformed_scores_zero_rather_than_raising(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            self.assertEqual(_oddsapi_props_richness(bad), 0)
            self.assertEqual(_oddsapi_props_richness(write(root, "list.json", [1, 2])), 0)
            self.assertEqual(_oddsapi_props_richness(write(root, "null.json", {"pitcher_props": None})), 0)


class SealDecisionTests(unittest.TestCase):
    """The guard's own arithmetic, stated as the rule the caller implements:
        skip when   slate_started
        skip when   best_frozen >= 0 and candidate <= best_frozen
        else        (re-)seal
    """

    @staticmethod
    def should_seal(candidate: int, best_frozen: int, slate_started: bool) -> bool:
        if slate_started:
            return False
        if best_frozen >= 0 and candidate <= best_frozen:
            return False
        return True

    def test_first_seal_happens_when_nothing_is_frozen(self) -> None:
        self.assertTrue(self.should_seal(candidate=60, best_frozen=-1, slate_started=False))

    def test_a_richer_capture_replaces_a_thin_seal(self) -> None:
        # 2026-08-08 sealed 1 pitcher and never improved. It must now improve.
        self.assertTrue(self.should_seal(candidate=60, best_frozen=2, slate_started=False))

    def test_a_poorer_capture_never_replaces_a_richer_seal(self) -> None:
        # The clock-known branch used to re-copy unconditionally.
        self.assertFalse(self.should_seal(candidate=2, best_frozen=60, slate_started=False))

    def test_an_equal_capture_does_not_churn_the_seal(self) -> None:
        self.assertFalse(self.should_seal(candidate=60, best_frozen=60, slate_started=False))

    def test_an_empty_post_slate_doc_cannot_overwrite_a_good_seal(self) -> None:
        # Even with NO clock (slate_started False), monotonicity protects it.
        self.assertFalse(self.should_seal(candidate=0, best_frozen=60, slate_started=False))

    def test_nothing_is_sealed_once_the_slate_has_started(self) -> None:
        for candidate, frozen in ((60, -1), (60, 2), (0, 60)):
            self.assertFalse(self.should_seal(candidate, frozen, slate_started=True))


class ReachabilityTests(unittest.TestCase):
    """Drives the REAL `_freeze_oddsapi_pregame_markets` over a temp tree.

    SealDecisionTests above re-states the rule; this proves the shipped function
    obeys it. A knob the freeze never reads would pass every test above --
    `calibration_profile_store` sat callable-by-nothing for months and looked
    fine from outside, and my own first pass at this lane's other test file had
    three assertions passing on `0.0 == 0.0`.
    """

    DATE = "2026-08-17"
    SLUG = "2026_08_17"

    def _tree(self, root: Path):
        from scripts.refresh_mlb_oddsapi import _daily_snapshot_dir, _freeze_market_dirs

        market_dirs = _freeze_market_dirs(root)
        for directory in market_dirs:
            directory.mkdir(parents=True, exist_ok=True)
        _daily_snapshot_dir(source_root=root, date_str=self.DATE).mkdir(parents=True, exist_ok=True)
        return market_dirs

    def _freeze(self, root: Path):
        from scripts.refresh_mlb_oddsapi import _freeze_oddsapi_pregame_markets

        return _freeze_oddsapi_pregame_markets(source_root=root, date_str=self.DATE)

    def _sealed(self, market_dirs) -> int:
        name = f"oddsapi_pitcher_props_{self.SLUG}_pregame.json"
        return max(_oddsapi_props_richness(d / name) for d in market_dirs)

    def test_a_thin_seal_is_replaced_by_a_later_richer_capture(self) -> None:
        """The 2026-08-08 case: sealed 1 pitcher, then never improved."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            market_dirs = self._tree(root)
            live = market_dirs[0] / f"oddsapi_pitcher_props_{self.SLUG}.json"

            live.write_text(json.dumps(doc(1)), encoding="utf-8")
            self._freeze(root)
            thin = self._sealed(market_dirs)
            self.assertEqual(thin, 2, "first seal did not happen at all")

            live.write_text(json.dumps(doc(30)), encoding="utf-8")
            self._freeze(root)
            self.assertEqual(self._sealed(market_dirs), 60,
                             "richer capture did NOT replace the thin seal -- "
                             "the freeze is still first-write-wins")

    def test_a_later_empty_capture_cannot_destroy_a_good_seal(self) -> None:
        """The post-slate case: books pull the market, the doc goes empty."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            market_dirs = self._tree(root)
            live = market_dirs[0] / f"oddsapi_pitcher_props_{self.SLUG}.json"

            live.write_text(json.dumps(doc(30)), encoding="utf-8")
            self._freeze(root)
            self.assertEqual(self._sealed(market_dirs), 60)

            live.write_text(json.dumps(doc(0)), encoding="utf-8")
            self._freeze(root)
            self.assertEqual(self._sealed(market_dirs), 60,
                             "an empty post-slate doc overwrote a real pregame seal")


if __name__ == "__main__":
    unittest.main()
