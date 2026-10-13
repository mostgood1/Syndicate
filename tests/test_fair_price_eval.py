"""`scripts/fair_price_eval.py` -- the de-vig methods, shared-feed detection and calibration it scores with."""
from __future__ import annotations

import importlib.util
import math
import random
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "fair_price_eval", Path(__file__).resolve().parents[1] / "scripts" / "fair_price_eval.py"
)
fpe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fpe)


def _imps(fav: int, dog: int) -> dict[str, float]:
    return {"home": fpe.implied(fav), "away": fpe.implied(dog)}


def test_every_devig_sums_to_one_and_keeps_order() -> None:
    imps = _imps(-400, 300)
    for method in ("mult", "power", "shin"):
        fair = fpe._DEVIG[method](imps)
        assert math.isclose(sum(fair.values()), 1.0, abs_tol=1e-9)
        assert fair["home"] > fair["away"]


def test_power_and_shin_take_more_from_the_longshot_than_multiplicative() -> None:
    imps = _imps(-400, 300)
    mult, power, shin = (fpe._DEVIG[m](imps)["away"] for m in ("mult", "power", "shin"))
    assert power < mult and shin < mult


def test_balanced_market_is_identical_across_methods() -> None:
    imps = _imps(-110, -110)
    assert all(math.isclose(fpe._DEVIG[m](imps)["home"], 0.5, abs_tol=1e-9) for m in ("mult", "power", "shin"))


def test_spread_sides_share_one_group_on_the_home_line() -> None:
    home = fpe.group_key("e1", "spreads", "full", None, "home", -3.5)
    away = fpe.group_key("e1", "spreads", "full", None, "away", 3.5)
    other = fpe.group_key("e1", "spreads", "full", None, "away", -3.5)
    assert home == away != other
    assert fpe.group_key("e1", "totals", "full", None, "over", 44.5) == fpe.group_key("e1", "totals", "full", None, "under", 44.5)


def test_shared_feed_books_are_detected_and_vote_once() -> None:
    last = {}
    for i in range(300):
        p = -110 - (i % 7)
        last[(("e", "m", "full", "", float(i)), "over")] = {"dk": p, "mgm": p, "fd": p + 5}
    clusters = fpe.feed_clusters(last, threshold=0.9)
    assert clusters["dk"] == clusters["mgm"] != clusters["fd"]
    per_book = {
        "dk": {"over": -150, "under": 125},
        "mgm": {"over": -150, "under": 125},
        "fd": {"over": -110, "under": -110},
    }
    plain, n_plain = fpe.fair_for(per_book, "over", "power")
    dedup, n_dedup = fpe.fair_for(per_book, "over", "power_dedup", clusters)
    assert n_plain == 3 and n_dedup == 2
    assert dedup < plain  # the duplicated -150 no longer wins the median by itself


def test_incomplete_or_impossible_books_are_refused() -> None:
    assert fpe.fair_for({"a": {"over": -110}}, "over", "mult") == (None, 0)
    assert fpe.fair_for({"a": {"over": 200, "under": 200}}, "over", "mult") == (None, 0)  # 67% total: underround


def test_calibration_recovers_a_known_slope() -> None:
    rng = random.Random(1)
    ps, ys = [], []
    for _ in range(6000):
        p = rng.uniform(0.05, 0.95)
        x = math.log(p / (1 - p))
        true = 1 / (1 + math.exp(-(0.0 + 0.7 * x)))  # an over-spread forecast: true slope 0.7
        ps.append(p)
        ys.append(1.0 if rng.random() < true else 0.0)
    a, b = fpe.calibration(ps, ys)
    assert abs(a) < 0.1 and 0.6 < b < 0.8
