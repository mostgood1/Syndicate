"""`syndicate/features/shared/syndicate_fair.py` -- the pool, the weight model's gradient, the fit, and sigma_fair.

Hermetic: synthetic books only. The fit/eval driver and its data plumbing are tested in
`tests/test_syndicate_fair_fit.py`.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from syndicate.features.shared import syndicate_fair as sf


def _row(books, target, mfam="h2h", tts="t2h"):
    return {"books": books, "target": target, "mfam": mfam, "tts": tts}


def _random_rows(rng, n, books, three_way_share=0.3):
    rows = []
    for _ in range(n):
        k = 3 if rng.random() < three_way_share else 2
        chosen = rng.choice(len(books), size=rng.integers(2, len(books) + 1), replace=False)
        entries = []
        for b in chosen:
            p = rng.dirichlet(np.ones(k) * 4)
            entries.append((books[b], float(rng.uniform(0, 40000)), list(p)))
        rows.append(_row(entries, list(rng.dirichlet(np.ones(k) * 4)),
                         mfam=sf.MARKET_FAMILIES[rng.integers(0, 5)], tts=sf.TTS_BUCKETS[rng.integers(0, 4)]))
    return rows


def test_two_way_log_pool_is_the_plans_logit_formula() -> None:
    probs = [0.55, 0.60, 0.48]
    w = np.array([1.0, 3.0, 0.5])
    lp = np.log([[p, 1 - p] for p in probs])
    pooled = sf.log_pool(lp, w)
    expected = 1 / (1 + math.exp(-sum(wi * math.log(p / (1 - p)) for wi, p in zip(w, probs)) / w.sum()))
    assert pooled[0] == pytest.approx(expected, abs=1e-12)
    assert pooled.sum() == pytest.approx(1.0)


def test_zero_theta_is_the_equal_weight_pool() -> None:
    rows = [_row([("a", 0, [0.6, 0.4]), ("b", 0, [0.5, 0.5]), ("c", 0, [0.2, 0.3, 0.5])[:0] or ("c", 0, [0.55, 0.45])],
                 [0.5, 0.5])]
    ds = sf.build_dataset(rows, ["a", "b", "c"])
    model = sf.WeightModel(ds.books)
    p, pi = sf.predict(model, ds)
    assert np.allclose(pi, 1 / 3)
    lp = np.log([[0.6, 0.4], [0.5, 0.5], [0.55, 0.45]])
    assert np.allclose(p[0, :2], sf.log_pool(lp, np.ones(3)))
    assert p[0, 2] == 0.0  # the padded third outcome is masked out


def test_gradient_matches_finite_differences_including_three_way_rows() -> None:
    rng = np.random.default_rng(7)
    books = ["a", "b", "c", "d"]
    ds = sf.build_dataset(_random_rows(rng, 40, books), books)
    model = sf.WeightModel(books)
    theta = rng.normal(0, 0.5, model.n_params)
    _, grad = sf.objective(theta, model, ds, lam=0.01)
    eps = 1e-6
    for j in rng.choice(model.n_params, size=25, replace=False):
        up, down = theta.copy(), theta.copy()
        up[j] += eps
        down[j] -= eps
        numeric = (sf.objective(up, model, ds, 0.01)[0] - sf.objective(down, model, ds, 0.01)[0]) / (2 * eps)
        assert grad[j] == pytest.approx(numeric, rel=1e-4, abs=1e-8)


def test_fit_learns_to_follow_the_book_that_is_the_close() -> None:
    rng = np.random.default_rng(11)
    rows = []
    for _ in range(600):
        truth = rng.uniform(0.25, 0.75)
        sharp = truth
        soft = [min(max(truth + rng.normal(0, 0.06), 0.05), 0.95) for _ in range(3)]
        entries = [("sharp", 300.0, [sharp, 1 - sharp])] + [(f"soft{i}", 300.0, [s, 1 - s]) for i, s in enumerate(soft)]
        rows.append(_row(entries, [truth, 1 - truth]))
    books = ["sharp", "soft0", "soft1", "soft2"]
    ds = sf.build_dataset(rows, books)
    model = sf.WeightModel(books)
    before = sf.cross_entropy(sf.predict(model, ds)[0], ds.target, ds.mask).mean()
    sf.fit(model, ds, lam=1e-6)
    after = sf.cross_entropy(sf.predict(model, ds)[0], ds.target, ds.mask).mean()
    table = model.weights_table("h2h", "t2h", sf.AGE_BUCKETS[0])
    assert after < before
    assert table["sharp"] > 5 * max(table["soft0"], table["soft1"], table["soft2"])


def test_a_heavy_ridge_holds_the_weights_at_equal() -> None:
    rng = np.random.default_rng(3)
    books = ["a", "b", "c"]
    ds = sf.build_dataset(_random_rows(rng, 80, books, three_way_share=0.0), books)
    model = sf.WeightModel(books)
    sf.fit(model, ds, lam=100.0)
    assert np.abs(model.theta).max() < 1e-3


def test_subset_keeps_each_rows_own_entries() -> None:
    rng = np.random.default_rng(5)
    books = ["a", "b", "c", "d"]
    rows = _random_rows(rng, 30, books)
    ds = sf.build_dataset(rows, books)
    pick = np.array([3, 7, 8, 21])
    sub = ds.subset(pick)
    alone = sf.build_dataset([rows[i] for i in pick], books)
    assert np.array_equal(sub.row_of, alone.row_of)
    assert np.allclose(sub.log_p, alone.log_p)
    assert np.allclose(sub.target, alone.target)
    model = sf.WeightModel(books)
    model.theta = rng.normal(0, 1, model.n_params)
    assert np.allclose(sf.predict(model, sub)[0], sf.predict(model, alone)[0])


def test_sigma_has_no_dispersion_when_books_agree_and_takes_the_cell_residual() -> None:
    rows = [_row([("a", 0, [0.6, 0.4]), ("b", 0, [0.6, 0.4])], [0.62, 0.38])]
    ds = sf.build_dataset(rows, ["a", "b"])
    model = sf.WeightModel(ds.books)
    p, pi = sf.predict(model, ds)
    assert np.allclose(sf.dispersion_var(ds, pi, p), 0.0)
    r2 = {(sf.MARKET_FAMILIES.index("h2h"), sf.TTS_BUCKETS.index("t2h")): 0.04}
    sigma = sf.sigma_fair(ds, p, pi, r2)
    assert sigma[0, 0] == pytest.approx(0.2)
    assert sigma[0, 2] == 0.0


def test_fitted_residual_variance_calibrates_one_sigma_coverage() -> None:
    rng = np.random.default_rng(19)
    rows = []
    for _ in range(4000):
        centre = rng.normal(0, 0.8)
        books = [(f"b{i}", 0.0, [1 / (1 + math.exp(-(centre + rng.normal(0, 0.05))))]) for i in range(4)]
        books = [(b, a, [p[0], 1 - p[0]]) for b, a, p in books]
        close = 1 / (1 + math.exp(-(centre + rng.normal(0, 0.15))))
        rows.append(_row(books, [close, 1 - close]))
    ds = sf.build_dataset(rows, [f"b{i}" for i in range(4)])
    model = sf.WeightModel(ds.books)
    p, pi = sf.predict(model, ds)
    r2 = sf.fit_residual_var(ds, p, pi)
    inside, scored = sf.sigma_coverage(ds, p, sf.sigma_fair(ds, p, pi, r2))
    assert scored == 4000
    assert 0.64 < inside / scored < 0.73  # Gaussian residuals: ~68.3% inside one sigma


@pytest.mark.parametrize("market,segment,kind,family", [
    ("h2h", "full", "game", "h2h"), ("spreads", "full", "game", "spreads"), ("totals", "full_game", "game", "totals"),
    ("totals", "h1", "game", "game_other"), ("alternate_spreads", "full", "game", "game_other"),
    ("h2h_3_way", "full", "game", "game_other"),
    ("player_points", "full", "prop", "prop"),
])
def test_market_family(market, segment, kind, family) -> None:
    assert sf.market_family(market, segment, kind) == family


def test_age_buckets() -> None:
    assert [sf.age_bucket(a) for a in (0, 899, 900, 3599, 3600, 10799, 10800, 43199)] == [0, 0, 1, 1, 2, 2, 3, 3]
