"""The scorecard grades the PRICE as well as the model, and its verdicts do not depend on read order.

Lane `inplay-skill-scoreboard` `[2026-09-21]`. Two measured defects, both on production's
own scorecard state that day:

1. THE PRICE-SHOPPING EDGE WAS GRADED NOWHERE. Every scorecard metric needs a model edge
   (`p_model = fair + model_edge_pct/100`; ROI only where `model_edge_pct > 0`), and live rows
   carry none: graded live model rows over 28d were mlb 0, wnba 0, nfl 0, ncaaf 16, soccer 118.
   The money placed live is sized by price shopping, so the question "is that edge real" had
   no instrument at all. `price_cells` grades it: realised ROI of the +EV rows per game.

2. A VERDICT DEPENDED ON THE ORDER GAMES WERE READ. `bootstrap_mean` resamples by INDEX from a
   fixed seed; a run sees games in insertion order and the saved state comes back key-sorted.
   4 of 12 shuffles of the same games changed the validated set, and the published run and a
   re-run of its own saved state already disagreed on one bucket.

Every test here fails on the pre-change code.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

import syndicate.features.shared.measured_bucket_skill as mbs
from syndicate.features.shared import model_scorecard as msc
from syndicate.features.shared.opportunity_population_ledger import population_key, population_record

bs = msc.load_bucket_search()
NOW = datetime(2026, 9, 21, 13, 0, tzinfo=timezone.utc)
FAST = {"resamples": 400, "seed": 11, "q": 0.10}


def _rows(*, seed=5, dates=8, games_per_date=10, phase="live", truth_shift=0.0, model_edge=None, sport="ncaaf",
          segment="q1"):
    """Graded rows in `grade_population`'s output shape, price included, bucketed by the real `bucket_ids`."""
    rng = random.Random(seed)
    rows = []
    for d in range(dates):
        day = f"2026-09-{d + 10:02d}"
        for g in range(games_per_date):
            game = f"{sport}|evt-{d}-{g}"
            for _ in range(3):
                fair = rng.uniform(0.35, 0.65)
                price = 110.0 if rng.random() < 0.5 else -105.0
                view = {"sport": sport, "market": "spreads", "segment": segment, "phase": phase,
                        "model_edge_pct": model_edge, "fair_probability": fair, "book_age_seconds": 30.0,
                        "books_quoting": 6.0, "fair_method": "consensus"}
                truth = min(0.97, max(0.03, fair + truth_shift))
                y = 1.0 if rng.random() < truth else 0.0
                p_model = None if model_edge is None else min(bs.P_CEIL, max(bs.P_FLOOR, fair + model_edge / 100.0))
                rows.append({"date": day, "sport": sport, "game": game, "buckets": mbs.bucket_ids(view), "y": y,
                             "p_market": fair, "p_model": p_model, "model_edge_pct": model_edge,
                             "pnl": (msc._decimal_odds(price) - 1.0) if y else -1.0, "price": price})
    return rows


def _games_from(rows):
    games = {}
    for row in rows:
        entry = games.setdefault(row["game"], {"date": row["date"], "sport": row["sport"], "rows": 0, "ids": {}, "px": {}})
        entry["rows"] += 1
        msc._accumulate(entry["ids"], row)
        msc._accumulate_price(entry["px"], row)
    return games


# --- the order fix ------------------------------------------------------------------


def _model_rows(seed=3):
    return _rows(seed=seed, phase="pregame", model_edge=6.0, truth_shift=0.03, sport="mlb", segment="full")


DECISIVE = ("bucket_id", "games", "dates", "p", "lodo_stable", "fdr_pass", "verdict",
            "roi_p", "roi_fdr_pass", "profit_verdict")


def _decisive(results):
    """The verdicts and what they are counted from, EXACTLY.

    Floats are compared to 1e-12 in `_means_close` instead: a per-game value is a sum over that
    game's rows, and its last bit follows the order the rows were summed in. Before the fix the
    CI endpoints moved in the THIRD decimal under a shuffle; what is left is 1e-17 and decides nothing.
    """
    return [{k: r.get(k) for k in DECISIVE} for r in results]


def _means_close(a, b):
    for x, y in zip(a, b):
        for k in ("market_brier", "model_brier", "brier_diff", "roi_model_side", "ci95", "roi_ci95"):
            if k not in x or k not in y:
                continue  # `evaluate_buckets` has no `model_brier`; the parity test compares shared fields only
            assert (x.get(k) is None) == (y.get(k) is None)
            if isinstance(x.get(k), list):
                assert all(abs(u - v) < 1e-12 for u, v in zip(x[k], y[k])), k
            elif x.get(k) is not None:
                assert abs(x[k] - y[k]) < 1e-12, k


def test_the_scorecard_verdict_does_not_depend_on_the_order_games_are_read():
    games = list(_games_from(_model_rows()).values())
    run = lambda gs: msc.evaluate_ids(gs, bs=bs, select=msc.is_bucket, min_games=20, min_dates=5,  # noqa: E731
                                      resamples=FAST["resamples"], seed=FAST["seed"], q=FAST["q"])
    baseline = run(games)
    assert baseline and any(r["ci95"] for r in baseline)
    for order in range(4):
        shuffled = list(games)
        random.Random(order).shuffle(shuffled)
        got = run(shuffled)
        assert _decisive(got) == _decisive(baseline), f"shuffle {order} changed a verdict input"
        _means_close(got, baseline)


def test_bucket_search_is_order_independent_and_still_in_parity_with_the_scorecard():
    rows = _model_rows()
    expected = bs.evaluate_buckets(rows, min_games=20, min_dates=5, **FAST)
    shuffled = list(rows)
    random.Random(7).shuffle(shuffled)
    reordered = bs.evaluate_buckets(shuffled, min_games=20, min_dates=5, **FAST)
    assert _decisive(reordered) == _decisive(expected)
    _means_close(reordered, expected)
    games = list(_games_from(shuffled).values())
    random.Random(8).shuffle(games)
    got = msc.evaluate_ids(games, bs=bs, select=msc.is_bucket, min_games=20, min_dates=5,
                           resamples=FAST["resamples"], seed=FAST["seed"], q=FAST["q"])
    by_id = {r["bucket_id"]: r for r in got}
    for want in expected:
        have = by_id[want["bucket_id"]]
        assert have["verdict"] == want["verdict"], want["bucket_id"]
        _means_close([have], [want])


# --- the price key ------------------------------------------------------------------


def _candidate(**overrides):
    row = {
        "sport": "mlb", "event_id": "evt-1", "kind": "game", "market": "totals", "segment": "full",
        "side": "over", "line": 8.5, "home_team": "Home Team", "away_team": "Away Team",
        "commence_time": "2026-09-01T23:00:00Z", "game_state": "pregame", "model_edge_pct": None,
        "ev_pct": 1.0, "board_lane": "opportunity",
        "quote": {"price": 120, "fair_probability": 0.5, "fair_method": "consensus",
                  "books_quoting": 8, "book_age_seconds": 60.0},
        "score": {"score": 1.0, "value_pct": 1.0},
    }
    row.update(overrides)
    return row


def test_a_graded_row_carries_the_price_it_was_offered_at():
    candidate = _candidate()
    record = population_record(candidate, population_key(candidate), "2026-09-01T18:00:00Z", sport="mlb")
    chips = {"2026-09-01": [{"sport": "mlb", "state": "final", "matchup": "Away Team @ Home Team",
                             "away": {"name": "Away Team", "key": "away team", "score": 4},
                             "home": {"name": "Home Team", "key": "home team", "score": 6}}]}
    graded, ungraded = bs.grade_population([record], chips)
    assert ungraded == {} and len(graded) == 1
    assert graded[0]["price"] == 120, "without the price a +EV row cannot be told from a -EV one"


# --- the accumulator ----------------------------------------------------------------


def test_the_price_accumulator_counts_only_plus_ev_rows_as_the_edge():
    view = {"sport": "ncaaf", "market": "spreads", "segment": "q1", "phase": "live", "fair_probability": 0.5,
            "books_quoting": 6.0, "book_age_seconds": 30.0, "fair_method": "consensus"}
    base = {"buckets": mbs.bucket_ids(view), "p_market": 0.5, "y": 1.0}
    px: dict = {}
    msc._accumulate_price(px, dict(base, price=120.0, pnl=1.2))      # EV 0.5*2.2-1 = +0.10
    msc._accumulate_price(px, dict(base, price=-120.0, pnl=0.8333))  # EV 0.5*1.833-1 < 0
    msc._accumulate_price(px, dict(base, price=None, pnl=1.0))       # unpriced: not counted at all
    cell = "ncaaf|spreads|q1|live"
    assert set(px) == {cell, cell + "|fair_method=consensus"}, "cell and fair_method only -- no other dimension"
    n_pos, pnl, ev, priced = px[cell]
    assert (n_pos, priced) == (1, 2)
    assert abs(pnl - 1.2) < 1e-12 and abs(ev - 0.10) < 1e-12


# --- the evaluation -----------------------------------------------------------------


def _price(rows, select=msc.is_cell):
    return msc.evaluate_price(list(_games_from(rows).values()), bs=bs, select=select, min_games=15, min_dates=3,
                              resamples=FAST["resamples"], seed=FAST["seed"], q=FAST["q"])


def test_a_real_price_edge_holds_and_a_false_one_fails():
    holds = _price(_rows(truth_shift=0.15))
    assert [r["verdict"] for r in holds] == [msc.PRICE_EDGE_HOLDS]
    assert holds[0]["ci95"][0] > 0 and holds[0]["predicted_ev"] > 0
    fails = _price(_rows(truth_shift=-0.25))
    assert [r["verdict"] for r in fails] == [msc.PRICE_EDGE_FAILS]


def test_too_few_games_is_insufficient_and_says_how_many_are_missing():
    [row] = _price(_rows(dates=2, games_per_date=4, truth_shift=0.15))
    assert row["verdict"] == msc.PRICE_INSUFFICIENT
    assert row["games_short"] == 15 - row["games"] > 0 and row["dates_short"] == 1


def test_live_rows_with_no_model_edge_get_a_price_verdict_where_the_model_side_cannot_speak():
    """The production shape: live rows, `model_edge_pct` None. The model side is blind by
    construction; the price side answers."""
    rows = _rows(truth_shift=0.15, model_edge=None)
    games = list(_games_from(rows).values())
    model = msc.evaluate_ids(games, bs=bs, select=msc.is_cell, min_games=15, min_dates=3,
                             resamples=FAST["resamples"], seed=FAST["seed"], q=FAST["q"])
    assert [r["games"] for r in model] == [0] and model[0]["verdict"] == mbs.VERDICT_INSUFFICIENT
    assert _price(rows)[0]["verdict"] == msc.PRICE_EDGE_HOLDS


# --- the payload --------------------------------------------------------------------


def _state(rows):
    state = msc.empty_state("sig")
    state["games"] = _games_from(rows)
    return state


def test_the_scorecard_serves_the_price_side_and_the_overlay_is_untouched_by_it():
    rows = _model_rows() + _rows(truth_shift=0.15)
    scorecard, overlay = msc.build_scorecard(_state(rows), bs=bs, today="2026-09-19", now=NOW, grader={}, run={},
                                             resamples=300)
    for label in ("7d", "28d"):
        assert scorecard["windows"][label]["price_cells"], label
    by_method = scorecard["windows"]["28d"]["price_by_fair_method"]
    live = [r for r in by_method if r["phase"] == "live" and r["segment"] == "q1"]
    assert live and live[0]["fair_method"] == "consensus" and live[0]["verdict"] == msc.PRICE_EDGE_HOLDS
    assert "price_by_fair_method" not in scorecard["windows"]["7d"]
    # The model-only pregame rows here were priced at +EV too, so to exercise the drop, add a cell whose
    # every side is -EV: it must be graded (priced) and still not SERVED, since it has no +EV game.
    minus_ev = [dict(r, price=-400.0, pnl=0.25 if r["y"] else -1.0) for r in _rows(sport="nfl", segment="h2")]
    served, _ = msc.build_scorecard(_state(rows + minus_ev), bs=bs, today="2026-09-19", now=NOW, grader={}, run={},
                                    resamples=300)
    for label in ("7d", "28d"):
        assert all(c["games"] > 0 for c in served["windows"][label]["price_cells"]), label
        assert not [c for c in served["windows"][label]["price_cells"] if c["sport"] == "nfl"], label
    assert "price-shopping edge" in msc.markdown(scorecard)

    stripped = _state(rows)
    for game in stripped["games"].values():
        game["px"] = {}
    _, overlay_without_price = msc.build_scorecard(stripped, bs=bs, today="2026-09-19", now=NOW, grader={}, run={},
                                                   resamples=300)
    assert overlay == overlay_without_price, "the price side is reporting only; it must never move the overlay"


def test_grade_pending_stores_the_price_accumulator_on_the_committed_game():
    """Reachability: the cron's path, not a hand-built game."""
    state = msc.empty_state("sig")
    record = {"k": "evt-9|spreads||q1|home|-3.5", "sport": "ncaaf", "ct": "2026-09-18T23:00:00Z",
              "t": "2026-09-18T23:30:00Z", "px": 120.0, "fp": 0.5, "gs": "live"}
    state["pending"]["ncaaf|evt-9"] = [record]
    graded_row = _rows(dates=1, games_per_date=1)[0]

    def grade(records, chips_by_date, today=None, ungraded_by_sport=None):
        return [dict(graded_row, game="ncaaf|evt-9", date="2026-09-18")], {}

    counts = msc.grade_pending(state, today="2026-09-21", grade=grade, chips_for=lambda day: [{"x": 1}],
                               central_date=lambda value: str(value)[:10] if value else None)
    assert counts.get("committed") == 1
    assert state["games"]["ncaaf|evt-9"]["px"], "committed without the price side: nothing would ever grade it"
