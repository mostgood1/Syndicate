"""Join the live Monte-Carlo GAME-LINE projection onto board rows.

Drop 3 of lane `live-game-line-projection`. Spec:
`.syndicate/spec_live_game_line_projection.md`.

WHAT THIS IS NOT. It is not `live_projection_join`, which is entirely
prop-shaped: its input is `liveModelProbOver` on prop rows and its counter is
`rows_live_edged`. **This module does not move `rows_live_edged`** — that zero
has its own two causes (the prop sever at `mlb/live_lens.py:1109` and a 91%
market-alias miss) and its own owning lane. Saying otherwise was a trap the
brief invited; the counters below are deliberately a separate family.

THE INPUT EXISTS AND IS MEASURED. `estimate_live` runs on live-odds-worker,
120 sims per live game, off the current inning/outs/bases/score, and its result
reaches the published snapshot as `gameLens` lanes stamped `source: "live_mc"`
carrying `modelHomeWinProb`. Confirmed in production 2026-08-15: the worker's
own tally read `{live_mc: 6, segment_projection: 52, unknown: 8}` while the
served surface read `live_mc=6` — producer and served agreeing at 6.

TWO REFUSALS ARE BUILT IN, AND THEY ARE THE POINT.

1. **PRECISION.** A win probability from n Bernoulli trials has standard error
   `sqrt(p(1-p)/n)`; at n=120, p=0.5 that is **±4.56 pp**. Publishing a 2-point
   edge off a 4.5-point interval is publishing noise with a decimal point. Per
   the recorded user decision on spec §8.1 — *publish, refuse to price* — every
   row carries `prob_std_err`, and an edge is released only when it clears
   `PRICEABLE_SIGMA` standard errors. **The refusal is the feature.** Raising
   `MLB_LIVE_GAME_MC_SIMS` later narrows the interval and turns pricing on with
   no change here.

   The noise also does NOT average out. `estimate_live` is seeded
   `seed=int(gamePk)`, so the estimator is deterministic per game: the error is
   a state-correlated bias, not tick-to-tick jitter. Smoothing consecutive ticks
   would look reassuringly stable while being wrong by the same 4 points all
   inning. Do not add a rolling mean here and call it a fix.

   **THE BAR MOVES WITH `p`, and that is deliberate.** `sqrt(p(1-p)/n)` is
   widest at p=0.5 and narrows toward the tails, so a 7-point edge is refused on
   a coin-flip game (bar ~9.13 pp) and published on a 0.90 blowout (bar ~5.48
   pp). The interval belongs to the estimate being published, not to the market.
   This surprised a test into failing during the build; it is pinned by
   `test_the_bar_moves_with_the_model_probability` so nobody reads an
   inconsistent-looking pair of verdicts as a bug.

2. **TOTALS ARE NOT PRICEABLE FROM A MEAN.** The re-sim publishes `total` as an
   expected run count, not a distribution, and P(over) cannot be derived from a
   mean without assuming a shape nobody has fitted. This repo already refuses
   exactly this in `soccer_projections` (`player_shots` maps to a mean and is
   refused by design). So moneyline joins and prices; totals join and are
   withheld with `totals_mean_not_distribution`. That is a refusal to fix
   upstream by publishing a distribution, not a gap to paper over here.

FINAL GAMES STILL REFUSE even though the projection is live-aware — a settled
or pulled market has no price to beat. That rule is `live_edge_policy`'s and is
delegated to it rather than re-implemented.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from typing import Any

# How many standard errors an edge must clear before it is published. 2.0 is a
# ~95% one-sided statement that the edge is not the estimator's own noise.
# Deliberately a constant and not a tunable: the honest lever is the sim count,
# which narrows the interval, rather than a threshold that just lets more noise
# through while the interval stays 4.5 points wide.
PRICEABLE_SIGMA = 2.0

_DEFAULT_MIN_SIMS = 20

LIVE_STATE_LENS_SOURCE = "live_mc"

# Withheld reasons. Every zero must be diagnosable by reason -- the shape
# `live_edge_policy` established, and the reason a counter of 0 was mysterious
# for so long on the prop side.
REASON_NO_LIVE_PROJECTION = "no_live_gameline_projection"
REASON_NOT_PRICEABLE = "prob_interval_swamps_edge"
REASON_TOTALS_MEAN = "totals_mean_not_distribution"
REASON_NO_MARKET_PRICE = "no_two_sided_market_price"
REASON_UNUSABLE_SIMS = "sim_count_unusable"


def _min_sims() -> int:
    """Below this the interval is so wide the number is not worth publishing."""
    raw = str(os.environ.get("MLB_LIVE_GAMELINE_MIN_SIMS") or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_MIN_SIMS
    return value if value > 0 else _DEFAULT_MIN_SIMS


def prob_std_err(probability: Any, sims: Any) -> float | None:
    """`sqrt(p(1-p)/n)`, or None when it cannot be computed.

    Returns None rather than 0.0 on bad input. A 0.0 here would read as
    "perfectly precise" and would make every edge priceable -- the single worst
    substitution available in this module, and the same shape as the `0.0`-for-a
    -missing-price bug this repo has already paid for.
    """
    try:
        p = float(probability)
        n = int(sims)
    except (TypeError, ValueError):
        return None
    if not (0.0 <= p <= 1.0) or n <= 0:
        return None
    return math.sqrt(max(0.0, p * (1.0 - p)) / float(n))


def live_gameline_from_lens(lens_rows: Any) -> dict[str, Any] | None:
    """The live-state moneyline projection from a snapshot's `gameLens`.

    Only the `live`/`full` lanes are ever stamped `live_mc`, and only when
    `estimate_live` actually returned. The `first1/3/5` lanes carry a
    `modelHomeWinProb` too -- derived from `_live_margin_win_prob` over a
    segment interpolation -- so keying on the probability's PRESENCE would
    silently accept a lens the re-sim never touched. Key on `source`.
    """
    if not isinstance(lens_rows, list):
        return None
    for lens in lens_rows:
        if not isinstance(lens, Mapping):
            continue
        if str(lens.get("source") or "").strip().lower() != LIVE_STATE_LENS_SOURCE:
            continue
        prob = lens.get("modelHomeWinProb")
        if prob is None:
            continue
        try:
            p = float(prob)
        except (TypeError, ValueError):
            continue
        if not (0.0 <= p <= 1.0):
            continue
        projection = lens.get("projection") if isinstance(lens.get("projection"), Mapping) else {}
        return {
            "home_win_prob": p,
            "sims_run": lens.get("simsRun"),
            "total_mean": projection.get("total"),
            "home_margin": projection.get("homeMargin"),
            "as_of": lens.get("liveStateAsOf"),
            "carried_forward": bool(lens.get("liveStateCarriedForward")),
            "lane": lens.get("key"),
        }
    return None


def _edge_pp(model_prob: float, market_prob: float) -> float:
    """Model minus market, in percentage POINTS, not percent-of-percent."""
    return (float(model_prob) - float(market_prob)) * 100.0


def price_moneyline(
    *,
    model_prob: Any,
    market_prob: Any,
    sims: Any,
    sigma: float = PRICEABLE_SIGMA,
) -> dict[str, Any]:
    """Price one side, or refuse it by name.

    Always returns a dict carrying `prob_std_err` and `priceable` so a caller
    can render the refusal. Never returns a bare None -- an absent verdict is
    how "withheld" silently becomes "not considered".
    """
    out: dict[str, Any] = {
        "model_prob": None,
        "market_prob": None,
        "edge_pp": None,
        "prob_std_err": None,
        "priceable": False,
        "withheld_reason": None,
        "sigma": float(sigma),
    }
    try:
        p = float(model_prob)
    except (TypeError, ValueError):
        out["withheld_reason"] = REASON_NO_LIVE_PROJECTION
        return out
    out["model_prob"] = p

    try:
        n = int(sims)
    except (TypeError, ValueError):
        n = 0
    if n < _min_sims():
        out["withheld_reason"] = REASON_UNUSABLE_SIMS
        return out

    se = prob_std_err(p, n)
    if se is None:
        out["withheld_reason"] = REASON_UNUSABLE_SIMS
        return out
    out["prob_std_err"] = se

    try:
        q = float(market_prob)
    except (TypeError, ValueError):
        out["withheld_reason"] = REASON_NO_MARKET_PRICE
        return out
    if not (0.0 < q < 1.0):
        out["withheld_reason"] = REASON_NO_MARKET_PRICE
        return out
    out["market_prob"] = q

    edge = _edge_pp(p, q)
    out["edge_pp"] = edge

    # The gate. `se` is a probability, `edge` is in points -- convert once, here,
    # rather than letting a unit mismatch decide what gets published.
    if abs(edge) < float(sigma) * se * 100.0:
        out["withheld_reason"] = REASON_NOT_PRICEABLE
        return out

    out["priceable"] = True
    return out


def withhold_totals() -> dict[str, Any]:
    """Totals always refuse: the re-sim gives a mean, not a distribution."""
    return {
        "model_prob": None,
        "market_prob": None,
        "edge_pp": None,
        "prob_std_err": None,
        "priceable": False,
        "withheld_reason": REASON_TOTALS_MEAN,
        "sigma": float(PRICEABLE_SIGMA),
    }


def new_coverage() -> dict[str, Any]:
    """The counter family. Separate from the prop family on purpose."""
    return {
        "rows_live_gameline_considered": 0,
        "rows_live_gameline_projected": 0,
        "rows_live_gameline_priceable": 0,
        "rows_live_gameline_edged": 0,
        "rows_live_gameline_withheld": 0,
        "withheld_by_reason": {},
    }


def record(coverage: dict[str, Any], verdict: Mapping[str, Any], *, projected: bool) -> None:
    """Fold one verdict into the counters.

    `considered` counts every row the join looked at, so `edged / considered` is
    a rate with a real denominator. A counter without its denominator is how a
    zero gets argued about instead of diagnosed.
    """
    coverage["rows_live_gameline_considered"] += 1
    if projected:
        coverage["rows_live_gameline_projected"] += 1
    if verdict.get("priceable"):
        coverage["rows_live_gameline_priceable"] += 1
        coverage["rows_live_gameline_edged"] += 1
        return
    coverage["rows_live_gameline_withheld"] += 1
    reason = str(verdict.get("withheld_reason") or "unspecified")
    by_reason = coverage.setdefault("withheld_by_reason", {})
    by_reason[reason] = int(by_reason.get(reason, 0)) + 1


def _norm_team(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def build_live_gameline_index(snapshot: Any) -> dict[tuple[str, str], dict[str, Any]]:
    """(away_team, home_team) -> the live moneyline projection.

    JOINED ON FULL TEAM NAMES, WHICH MATCH EXACTLY. Verified against production
    2026-08-15: the snapshot carries `matchup.home.name` "San Francisco Giants"
    and the grid row carries `home_team` "San Francisco Giants". **No alias
    table is involved, and that is deliberate** -- the prop join's 91% miss
    (`miss_no_market_alias` 903 of 989) comes from aliasing market NAMES, and
    reproducing that machinery here would import its failure mode for no gain.
    If this join ever starts missing, the counter says so by name rather than
    silently returning zero coverage.
    """
    index: dict[tuple[str, str], dict[str, Any]] = {}
    if not isinstance(snapshot, Mapping):
        return index
    games = snapshot.get("games")
    if not isinstance(games, list):
        return index
    for game in games:
        if not isinstance(game, Mapping):
            continue
        matchup = game.get("matchup") if isinstance(game.get("matchup"), Mapping) else {}
        away = matchup.get("away") if isinstance(matchup.get("away"), Mapping) else {}
        home = matchup.get("home") if isinstance(matchup.get("home"), Mapping) else {}
        key = (_norm_team(away.get("name")), _norm_team(home.get("name")))
        if not key[0] or not key[1]:
            continue
        projection = live_gameline_from_lens(game.get("gameLens"))
        if projection is None:
            continue
        projection = dict(projection)
        projection["game_pk"] = game.get("gamePk")
        index[key] = projection
    return index


def attach_live_gamelines(grid: Any, index: Mapping[tuple[str, str], Mapping[str, Any]]) -> dict[str, Any]:
    """Overlay the live game-line projection on live moneyline rows.

    Mirrors `attach_live_projections`' contract deliberately: a row the join
    MISSES keeps whatever suppression it already had rather than silently
    gaining an edge, and a row it hits is marked `live_aware` so
    `live_edge_policy` stops refusing it for being live. The precision gate is
    applied ON TOP of that -- being allowed to price is not the same as being
    precise enough to.

    FINAL GAMES ARE NOT TOUCHED. The policy refuses them even when live-aware,
    and re-deciding that here would put two rules on one question.
    """
    coverage = new_coverage()
    coverage["index_size"] = len(index)
    if not isinstance(grid, (list, tuple)):
        return coverage

    for row in grid:
        if not isinstance(row, Mapping):
            continue
        game = row.get("game") if isinstance(row.get("game"), Mapping) else {}
        if str(game.get("state") or "").strip().lower() not in {"live", "in_progress"}:
            continue
        if str(row.get("kind") or "") != "game":
            continue
        if str(row.get("market") or "").strip().lower() != "h2h":
            continue

        key = (_norm_team(row.get("away_team")), _norm_team(row.get("home_team")))
        hit = index.get(key)
        if hit is None:
            record(coverage, {"priceable": False, "withheld_reason": REASON_NO_LIVE_PROJECTION}, projected=False)
            continue

        projection = row.get("projection") if isinstance(row.get("projection"), Mapping) else {}
        verdict = price_moneyline(
            model_prob=hit.get("home_win_prob"),
            # `market_fair_prob_over` is the de-vigged HOME probability on an
            # h2h row -- confirmed against production: home -21759 -> 0.9954,
            # away +3878 -> 0.0251, sum 1.0205, 0.9954/1.0205 = 0.9754, which is
            # the value the row carries. Reading it rather than re-de-vigging
            # keeps one devig ordering in the board path.
            market_prob=projection.get("market_fair_prob_over"),
            sims=hit.get("sims_run"),
        )

        if isinstance(row, dict):
            block = dict(verdict)
            block["game_pk"] = hit.get("game_pk")
            block["home_win_prob"] = hit.get("home_win_prob")
            block["sims_run"] = hit.get("sims_run")
            block["total_mean"] = hit.get("total_mean")
            block["as_of"] = hit.get("as_of")
            block["carried_forward"] = hit.get("carried_forward")
            row["live_gameline"] = block
            updated = dict(projection)
            updated["live_aware"] = True
            if verdict.get("priceable"):
                updated["edge_vs_market_pct"] = verdict.get("edge_pp")
                updated["edge_unavailable_reason"] = None
            else:
                updated["edge_vs_market_pct"] = None
                updated["edge_unavailable_reason"] = verdict.get("withheld_reason")
            row["projection"] = updated

        record(coverage, verdict, projected=True)

    return coverage
