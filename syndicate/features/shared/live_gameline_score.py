"""Score the live game-line model against realised outcomes — worker-side.

WHY THIS EXISTS. `live-game-line-projection` closed with the ledger proven able
to produce a sample (`written=13` across two builds, 2 of them non-priceable)
and its edges **unscored**. Nobody had measured whether those probabilities were
RIGHT. This is that measurement.

WHY IT RUNS HERE AND NOT IN A SCRIPT. Measured 2026-08-17 01:0xZ, three ways in:

  * the ledger lives at `<sport>_source/data/live_gameline_ledger/*.jsonl` on the
    WORKER's disk and matches **zero** `HOT_ARTIFACT_PATTERNS`, so
    `/api/ops/artifacts/export` returns `count 0` and `/stream` refuses it;
  * both endpoints read the SERVING service's disk, which never holds the
    worker's file whatever the allowlist says;
  * and there is no retrospective shortcut: at 01:02:26Z the board read
    `by_state {final: 14, live: 1}` while rows carrying a
    `live_gameline.model_prob` were `{live: 12}` — **a finished game retains no
    model probability on any served surface.**

So the sample is only reachable where it is written. This scores it there and
emits a small summary onto the `book_grid` artifact, which is ALREADY published
— no new publish pattern, and no edit to `artifact_publisher.py`, which an OPEN
lane holds.

THE ONLY SCORE THAT MEANS ANYTHING IS AGAINST THE MARKET. A Brier score alone
says nothing: predicting the market's own number scores well and is worth zero.
Every ledger record carries `market_fair_prob` beside `model_home_win_prob`, so
both are scored **on exactly the same rows** and the difference is reported.
Negative `model_minus_market_brier` = the model beat the market.

WHAT IS DELIBERATELY NOT IMPORTED. `intelligence_evaluation._calibration`
already computes Brier and MAE, and reusing it would normally be right. It is
not imported here because this runs inside the per-build artifact path on
refresh-worker, which has a live OOM lane and a standing rule that periodic
worker work is never free (`#241`). Pulling a large evaluation module into every
build to reuse three lines of arithmetic trades a real memory cost for a
cosmetic one. The arithmetic is inlined and this paragraph is why.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# A record with no outcome is not scored, and the count is reported rather than
# dropped: "we had no outcome" and "the model was wrong" must never look alike.
_UNSCORED_NO_OUTCOME = "no_final_outcome_for_game"
_UNSCORED_NO_MODEL_PROB = "record_carries_no_model_probability"


def _finite_prob(value: Any) -> float | None:
    """A probability in (0, 1), or None. Bounds are EXCLUSIVE on purpose.

    A stored 0.0 or 1.0 is a certainty no 120-sim estimator can express, so it
    is far more likely a sentinel or a unit error than a real forecast. Scoring
    it would hand the model a perfect or maximally-wrong Brier on a value it
    never actually claimed.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    p = float(value)
    if p != p or p <= 0.0 or p >= 1.0:  # NaN-safe
        return None
    return p


def build_finals_index(grid: Any) -> dict[str, bool]:
    """`game_pk` -> did HOME win, for games that are FINAL on this grid.

    Keyed on `game_pk` because that is what the ledger stores as its join key.
    A tie is EXCLUDED rather than coerced: baseball does not tie, so a final
    with equal scores is a bad row, and guessing a winner from it would inject a
    fabricated outcome into the score.
    """
    out: dict[str, bool] = {}
    if not isinstance(grid, (list, tuple)):
        return out
    for row in grid:
        if not isinstance(row, Mapping):
            continue
        game = row.get("game") if isinstance(row.get("game"), Mapping) else {}
        if str(game.get("state") or "").strip().lower() != "final":
            continue
        home, away = game.get("home_score"), game.get("away_score")
        try:
            h, a = float(home), float(away)
        except (TypeError, ValueError):
            continue
        if h == a:
            continue
        key = str(row.get("game_pk") or game.get("game_pk") or row.get("event_id") or "").strip()
        if key:
            out[key] = h > a
    return out


def _score(pairs: list[tuple[float, bool]]) -> dict[str, Any]:
    """Brier and MAE over (probability, outcome). Empty is None, never 0.0."""
    if not pairs:
        return {"brier": None, "mae": None, "n": 0}
    briers = [(p - (1.0 if won else 0.0)) ** 2 for p, won in pairs]
    maes = [abs(p - (1.0 if won else 0.0)) for p, won in pairs]
    n = len(pairs)
    return {"brier": round(sum(briers) / n, 5), "mae": round(sum(maes) / n, 5), "n": n}


def score_ledger_records(records: Any, finals: Mapping[str, bool]) -> dict[str, Any]:
    """Score model vs market over ledger records whose game has a final outcome.

    Reported on THREE populations, because they answer different questions and
    conflating them is how a number gets quoted for the wrong thing:

      `all_records`   every forecast, so a game whose line moved ten times
                      contributes ten. This is calibration over time.
      `last_per_game` one forecast per game — the model's final word. This is
                      the per-game hit rate, and it is the smaller n.
      `priceable`     restricted to rows the board would actually have SHOWN.
                      Scoring only these measures the publish gate; scoring all
                      of them measures the model. `priceable` is a field, not a
                      filter, precisely so both are available.
    """
    model_all: list[tuple[float, bool]] = []
    market_all: list[tuple[float, bool]] = []
    model_priceable: list[tuple[float, bool]] = []
    market_priceable: list[tuple[float, bool]] = []
    last: dict[str, tuple[str, float, float | None, bool]] = {}
    unscored: dict[str, int] = {}
    considered = 0

    for rec in records if isinstance(records, (list, tuple)) else []:
        if not isinstance(rec, Mapping):
            continue
        considered += 1
        key = str(rec.get("game_pk") or rec.get("event_id") or "").strip()
        if key not in finals:
            unscored[_UNSCORED_NO_OUTCOME] = unscored.get(_UNSCORED_NO_OUTCOME, 0) + 1
            continue
        model_p = _finite_prob(rec.get("model_home_win_prob"))
        if model_p is None:
            unscored[_UNSCORED_NO_MODEL_PROB] = unscored.get(_UNSCORED_NO_MODEL_PROB, 0) + 1
            continue
        won = bool(finals[key])
        market_p = _finite_prob(rec.get("market_fair_prob"))

        model_all.append((model_p, won))
        if market_p is not None:
            market_all.append((market_p, won))
        if bool(rec.get("priceable")):
            model_priceable.append((model_p, won))
            if market_p is not None:
                market_priceable.append((market_p, won))
        # LATEST record per game, chosen by `recorded_at` rather than by file
        # order. The ledger is append-only so the two normally agree -- but
        # "normally" is not a guarantee, and a merged or re-pulled file would
        # silently make file order mean nothing. `recorded_at` is ISO-8601 UTC,
        # so lexical comparison IS chronological.
        stamp = str(rec.get("recorded_at") or "")
        prev = last.get(key)
        if prev is None or stamp >= prev[0]:
            last[key] = (stamp, model_p, market_p, won)

    model_last = [(p, w) for _s, p, _m, w in last.values()]
    market_last = [(m, w) for _s, _p, m, w in last.values() if m is not None]

    def _delta(a: dict[str, Any], b: dict[str, Any]) -> float | None:
        if a.get("brier") is None or b.get("brier") is None:
            return None
        return round(a["brier"] - b["brier"], 5)

    all_model, all_market = _score(model_all), _score(market_all)
    lp_model, lp_market = _score(model_last), _score(market_last)
    pr_model, pr_market = _score(model_priceable), _score(market_priceable)

    return {
        "records_considered": considered,
        "games_with_outcome": len(last),
        "unscored": unscored,
        "all_records": {
            "model": all_model,
            "market": all_market,
            # NEGATIVE means the model beat the market. Named in full rather
            # than as "skill" so nobody has to guess the sign.
            "model_minus_market_brier": _delta(all_model, all_market),
        },
        "last_per_game": {
            "model": lp_model,
            "market": lp_market,
            "model_minus_market_brier": _delta(lp_model, lp_market),
        },
        "priceable_only": {
            "model": pr_model,
            "market": pr_market,
            "model_minus_market_brier": _delta(pr_model, pr_market),
        },
    }
