"""The shipped MLB hitter-prop calibration, and the two things about it that
must not be quietly undone — `#624` step 1.

1. **HRR carries no entry, and that is a RESULT, not a gap.** The fitter's
   `prop_keys` omits all four `hits_runs_rbis_*` rungs, which reads exactly like
   an oversight worth "fixing". It was tested on 2026-09-01 and falsified: the
   fit pins the slope at the clamp floor (a=0.05 — it wants to discard the model
   probability outright) and regresses all four rungs on the held-out split.
   Per-prop selection on VAL independently chose "no entry" for all four without
   seeing TEST. Calibration cannot rescue HRR; that is the producer defect
   `#624` step 2 tracks.

2. **The config beat the incumbent on a held-out window**, and the incumbent it
   replaced was worse than NO calibration at all. The `_meta` carries that
   reading so the next person does not have to re-derive it — and these tests
   fail if it is dropped.
"""
from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / "vendor" / "mlb_bettingv2" / "data" / "tuning" / "hitter_props_calibration" / "default.json"
FITTER = REPO_ROOT / "vendor" / "mlb_bettingv2" / "tools" / "tune" / "fit_hitter_prob_calibration.py"
SCRIPT = REPO_ROOT / "scripts" / "fit_mlb_prop_calibration.py"


def _config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


class ShippedConfigShapeTests(unittest.TestCase):
    def test_the_applier_contract_is_intact(self) -> None:
        """`enabled`, `default` and `props` are what the applier reads; a config
        missing any of them silently becomes an identity transform."""
        config = _config()
        self.assertTrue(config.get("enabled"))
        self.assertIn("default", config)
        self.assertIsInstance(config.get("props"), dict)
        self.assertGreater(len(config["props"]), 0)

    def test_every_entry_is_a_usable_affine_logit(self) -> None:
        for prop, spec in _config()["props"].items():
            self.assertEqual(spec.get("mode"), "affine_logit", prop)
            self.assertIsInstance(spec.get("a"), (int, float), prop)
            self.assertIsInstance(spec.get("b"), (int, float), prop)
            self.assertGreaterEqual(float(spec["a"]), 0.05, prop)
            self.assertLessEqual(float(spec["a"]), 5.0, prop)


class HrrMustStayUncalibratedTests(unittest.TestCase):
    def test_no_hits_runs_rbis_entry_is_shipped(self) -> None:
        hrr = [prop for prop in _config()["props"] if "runs_rbis" in prop]
        self.assertEqual(hrr, [], "adding HRR was tested and REGRESSED it held-out; see _meta")

    def test_the_falsification_is_recorded_where_someone_would_look(self) -> None:
        """A negative result nobody can find gets re-run as a fresh idea."""
        meta = _config().get("_meta") or {}
        note = str(meta.get("hits_runs_rbis_deliberately_absent") or "")
        self.assertTrue(note, "_meta must say WHY HRR is absent")
        self.assertIn("clamp floor", note)
        self.assertIn("0.05", note)

    def test_the_fitter_still_omits_hrr_so_a_plain_refit_cannot_add_it(self) -> None:
        """If someone adds HRR to `prop_keys`, this fails — which is the point:
        the change is allowed, but it must come with a fresh held-out reading,
        not ride in silently."""
        source = FITTER.read_text(encoding="utf-8-sig")
        start = source.index("prop_keys = [")
        block = source[start:source.index("]", start)]
        self.assertNotIn("hits_runs_rbis", block)


class HeldOutProvenanceTests(unittest.TestCase):
    def test_meta_records_the_held_out_comparison(self) -> None:
        meta = _config().get("_meta") or {}
        test = meta.get("held_out_test") or {}
        for key in ("raw_no_calibration", "incumbent_2026_07_17", "this_config"):
            self.assertIn(key, test, key)
            self.assertIn("logloss", test[key])

    def test_the_shipped_config_beat_the_incumbent_on_both_metrics(self) -> None:
        test = (_config().get("_meta") or {}).get("held_out_test") or {}
        mine, incumbent = test["this_config"], test["incumbent_2026_07_17"]
        self.assertLess(mine["logloss"], incumbent["logloss"])
        self.assertLessEqual(mine["brier"], incumbent["brier"])

    def test_the_incumbent_was_worse_than_no_calibration(self) -> None:
        """The finding that justified replacing it at all — kept as an assertion
        so it cannot be softened into a footnote."""
        test = (_config().get("_meta") or {}).get("held_out_test") or {}
        raw, incumbent = test["raw_no_calibration"], test["incumbent_2026_07_17"]
        self.assertLess(raw["logloss"], incumbent["logloss"])
        self.assertLess(raw["brier"], incumbent["brier"])

    def test_the_refit_is_reproducible(self) -> None:
        self.assertTrue(SCRIPT.exists(), "a fit nobody can re-run is a fit nobody can check")
        source = SCRIPT.read_text(encoding="utf-8-sig")
        self.assertIn("--write-config", source)
        self.assertIn("REFUSING to write the config", source, "the gate must be able to refuse")


class ApplierMathTests(unittest.TestCase):
    """`a`/`b` must mean what the config claims, or every number above is about
    a transform nobody applies."""

    @staticmethod
    def _apply(p: float, a: float, b: float) -> float:
        logit = math.log(p) - math.log(1.0 - p)
        return 1.0 / (1.0 + math.exp(-(a * logit + b)))

    def test_identity_parameters_change_nothing(self) -> None:
        for p in (0.05, 0.3, 0.5, 0.87):
            self.assertAlmostEqual(self._apply(p, 1.0, 0.0), p, places=9)

    def test_a_below_one_pulls_toward_the_middle(self) -> None:
        """Which is what every shipped slope < 1 is doing: shrinking a model
        whose confident extremes were measured wrong."""
        self.assertGreater(self._apply(0.05, 0.8, 0.0), 0.05)
        self.assertLess(self._apply(0.95, 0.8, 0.0), 0.95)


if __name__ == "__main__":
    unittest.main()
