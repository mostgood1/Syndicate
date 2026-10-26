"""Syndicate Fair v1 at record time (`syndicate_fair_runtime`), lane `syndicate-decision-engine` (`#736`)."""

from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from scripts import syndicate_fair_fit as fit
from syndicate.features.shared import season_phase
from syndicate.features.shared import syndicate_fair as sf
from syndicate.features.shared import syndicate_fair_runtime as sfr
from syndicate.features.shared.opportunity_signals import devig

NOW = datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc)
BOOKS = ["betmgm", "draftkings", "fanduel", "pinnacle"]
PRICES = {"betmgm": (-125, 105), "draftkings": (-130, 110), "fanduel": (-120, 100), "pinnacle": (-128, 116)}


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _family(sport: str, kind: str, commence: datetime) -> str:
    return f"{sport}|{season_phase.season_phase(sport, sfr._central_date(commence.timestamp()))}|{kind}"


def _grid_row(commence: datetime, *, observed: datetime, books=BOOKS, market="h2h", line=None, updated=None,
              prices=PRICES) -> dict:
    cells = {b: {"home": {"price": prices[b][0], "observed_at": _iso(observed)},
                 "away": {"price": prices[b][1], "observed_at": _iso(observed)}} for b in books}
    return {"event_id": "ev1", "kind": "game", "market": market, "segment": "full", "player_name": None, "line": line,
            "sides": ["away", "home"], "commence_time": _iso(commence), "cells": cells,
            "updated_at": _iso(updated or observed)}


def _params(family: str, theta=None, r2=None) -> dict:
    model = sf.WeightModel(BOOKS)
    th = np.zeros(model.n_params) if theta is None else theta
    return {"version": "v1-test", "families": {family: {"books": BOOKS, "theta": [float(x) for x in th],
                                                         "r2": r2 if r2 is not None else {"h2h|t6h": 0.01}}}}


def _runtime(tmp_path, commence: datetime, *, rows, params=None, day=None) -> sfr.Runtime:
    day = day or sfr._central_date(NOW.timestamp())
    (tmp_path / "reports" / "syndicate_fair").mkdir(parents=True, exist_ok=True)
    fam = _family("nhl", "game", commence)
    (tmp_path / sfr.PARAMS_RELPATH).write_text(json.dumps(params or _params(fam)), encoding="utf-8")
    grid_dir = tmp_path / "nhl_source" / "data" / "book_grid"
    grid_dir.mkdir(parents=True, exist_ok=True)
    (grid_dir / f"book_grid_{day}.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
    return sfr.load_runtime(day, tmp_path)


def _score(rt, commence, side="home", line=None, market="h2h", sport="nhl"):
    return sfr.score(rt, sport=sport, kind="game", event_id="ev1", market=market, segment="full", player=None,
                     side=side, line=line, commence_time=_iso(commence), now=NOW)


# ----------------------------------------------------------------------------- parity with the fit


def test_canonical_sides_match_the_fit():
    for sides in (["away", "home"], ["home", "away", "draw"], ["under", "over"], ["no", "yes"], ["over"], ["x", "y"]):
        assert sfr.canonical_sides(sides) == fit.canonical_sides(sides)


@pytest.mark.parametrize("hours,bucket", [(30, "t24h"), (13, "t24h"), (8, "t6h"), (3.6, "t6h"), (2.5, "t2h"),
                                          (1.1, "t2h"), (0.4, "t30m"), (0, None), (-1, None), (40, None)])
def test_tts_bucket_is_the_nearest_fitted_snapshot_on_a_log_scale(hours, bucket):
    assert sfr.tts_bucket(hours * 3600) == bucket


def test_record_key_negates_a_home_spread_and_leaves_others():
    assert sfr.record_grid_key("nhl", "e", "spreads", "full", None, "home", -1.5)[-1] == 1.5
    assert sfr.record_grid_key("nhl", "e", "spreads", "full", None, "away", 1.5)[-1] == 1.5
    assert sfr.record_grid_key("nhl", "e", "h2h", "full", None, "home", None)[-1] is None
    assert sfr.record_grid_key("nhl", "e", "SOG", "full", "A B", "over", 2.5) == sfr.grid_key("e", "sog", "full", "a b", 2.5)


def test_numpy_log_weights_reproduce_the_fits_predict_and_sigma(tmp_path):
    # Random weights: the runtime's term_index sum must equal the fit's design-matrix product.
    commence = NOW + timedelta(hours=6)
    fam = _family("nhl", "game", commence)
    rng = np.random.default_rng(7)
    theta = rng.normal(0, 0.3, sf.WeightModel(BOOKS).n_params)
    rt = _runtime(tmp_path, commence, rows=[_grid_row(commence, observed=NOW - timedelta(minutes=20))],
                  params=_params(fam, theta, {"h2h|t6h": 0.004}))
    s = _score(rt, commence, side="away")
    books_here = [(b, 1200.0, devig([PRICES[b][0], PRICES[b][1]], method="shin")) for b in BOOKS]
    ds = sf.build_dataset([{"books": books_here, "mfam": "h2h", "tts": "t6h", "t": [0.0, 0.0]}], BOOKS, target_key="t")
    model = sf.WeightModel(BOOKS)
    model.theta = theta
    p, pi = sf.predict(model, ds)
    sigma = sf.sigma_fair(ds, p, pi, {(sf.MARKET_FAMILIES.index("h2h"), sf.TTS_BUCKETS.index("t6h")): 0.004})
    assert s.reason is None and s.tts == "t6h" and s.books_used == 4
    assert s.p_fair_v1 == pytest.approx(float(p[0, 1]), abs=1e-6)       # away = outcome 1 of (home, away)
    assert s.sigma_fair_v1 == pytest.approx(float(sigma[0, 1]), abs=1e-6)


def test_equal_weights_give_the_geometric_pool_and_the_shin_median_beside_it(tmp_path):
    commence = NOW + timedelta(hours=6)
    rt = _runtime(tmp_path, commence, rows=[_grid_row(commence, observed=NOW - timedelta(minutes=5))])
    s = _score(rt, commence, side="home")
    shin = [devig([PRICES[b][0], PRICES[b][1]], method="shin") for b in BOOKS]
    geo = [math.exp(sum(math.log(p[i]) for p in shin) / len(shin)) for i in range(2)]
    assert s.p_fair_v1 == pytest.approx(geo[0] / sum(geo), abs=1e-6)
    med = [statistics.median(p[i] for p in shin) for i in range(2)]
    assert s.p_shin_median == pytest.approx(med[0] / sum(med), abs=1e-6)
    assert s.sigma_fair_v1 > math.sqrt(0.01) - 1e-9          # the cell's residual is the floor of sigma


# ----------------------------------------------------------------------------- every absence has a reason


def test_reasons(tmp_path):
    commence = NOW + timedelta(hours=6)
    rt = _runtime(tmp_path, commence, rows=[_grid_row(commence, observed=NOW - timedelta(minutes=5))])
    assert _score(rt, commence, sport="soccer").reason == "not_a_v1_family"
    assert _score(rt, NOW - timedelta(minutes=1)).reason in ("in_play", "not_a_v1_family")
    assert _score(rt, NOW + timedelta(hours=40)).reason in ("outside_fitted_window", "not_a_v1_family")
    assert _score(rt, commence, market="totals", line=5.5).reason == "no_grid_line"
    assert _score(rt, commence, side="draw").reason == "side_not_on_grid_line"
    assert sfr.score(sfr.Runtime(load_error="no_params"), sport="nhl", kind="game", event_id="ev1", market="h2h",
                     segment="full", player=None, side="home", line=None, commence_time=_iso(commence),
                     now=NOW).reason == "no_params"


def test_stale_and_unfitted_books_are_dropped_and_counted(tmp_path):
    commence = NOW + timedelta(hours=6)
    row = _grid_row(commence, observed=NOW - timedelta(minutes=5))
    # Age is from the book's LATEST change on either side (as the fit), so both sides must be > 12h old.
    for sd in ("home", "away"):
        row["cells"]["pinnacle"][sd]["observed_at"] = _iso(NOW - timedelta(hours=13))
    row["cells"]["newbook"] = {"home": {"price": -110, "observed_at": _iso(NOW)}, "away": {"price": -110, "observed_at": _iso(NOW)}}
    rt = _runtime(tmp_path, commence, rows=[row])
    s = _score(rt, commence)
    assert s.books_used == 3 and s.books_dropped == 2 and s.reason is None


def test_a_one_sided_grid_line_says_so(tmp_path):
    commence = NOW + timedelta(hours=6)
    one = _grid_row(commence, observed=NOW, market="totals", line=5.5)
    one["sides"] = ["over"]
    rt = _runtime(tmp_path, commence, rows=[_grid_row(commence, observed=NOW), one])
    assert _score(rt, commence, market="totals", line=5.5, side="over").reason == "one_sided_line"
    assert _score(rt, commence).reason is None


def test_under_min_books(tmp_path):
    commence = NOW + timedelta(hours=6)
    rt = _runtime(tmp_path, commence, rows=[_grid_row(commence, observed=NOW, books=["fanduel"])])
    assert _score(rt, commence).reason == "under_min_books"


def test_missing_params_and_the_freshest_grid_row_wins(tmp_path):
    assert sfr.load_runtime("2026-10-26", tmp_path).load_error == "no_params"
    commence = NOW + timedelta(hours=6)
    day = sfr._central_date(NOW.timestamp())
    stale = _grid_row(commence, observed=NOW - timedelta(hours=1), updated=NOW - timedelta(hours=1),
                      prices={b: (-200, 170) for b in BOOKS})
    fresh = _grid_row(commence, observed=NOW - timedelta(minutes=1), updated=NOW - timedelta(minutes=1))
    _runtime(tmp_path, commence, rows=[stale], day=day)
    nxt = (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()
    (tmp_path / "nhl_source" / "data" / "book_grid" / f"book_grid_{nxt}.json").write_text(
        json.dumps({"rows": [fresh]}), encoding="utf-8")
    rt = sfr.load_runtime(day, tmp_path)
    assert len(rt.grid_files) == 2
    s = _score(rt, commence)
    assert s.p_shin_median < 0.6                     # the fresh -125ish prices, not the -200 stale ones
