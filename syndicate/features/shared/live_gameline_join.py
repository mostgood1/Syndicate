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

# WHICH `source` STAMP COUNTS AS A LIVE LENS, PER SPORT.
#
# Keying on `source` rather than on the probability's presence is deliberate and
# is explained at `live_gameline_from_lens` -- the `first1/3/5` lanes carry a
# `modelHomeWinProb` too, so presence would accept a lens the re-sim never
# touched. That guarantee must NOT be weakened to admit a second sport, which is
# why this is an explicit per-sport table and not a relaxed check.
#
# Measured on production 2026-08-16 22:2xZ against a real live WNBA slate
# (CHI @ SEA 58-53, IND @ ATL 51-58): wnba stamps `source: "live_projection"` on
# exactly the live games (2 of 3 lenses) and `"pregame"` on the one that had not
# tipped. So the stamp is as discriminating for wnba as `live_mc` is for mlb --
# it is simply spelled differently.
LIVE_LENS_SOURCES_BY_SPORT: dict[str, tuple[str, ...]] = {
    "mlb": (LIVE_STATE_LENS_SOURCE,),
    "wnba": ("live_projection",),
}
_DEFAULT_LENS_SOURCES: tuple[str, ...] = (LIVE_STATE_LENS_SOURCE,)


def lens_sources_for_sport(sport: Any) -> tuple[str, ...]:
    """Accepted `source` stamps for this sport, defaulting to MLB's.

    An unknown sport gets MLB's stamp rather than "anything": a sport whose
    lens shape nobody has looked at must fail to join and be counted, not be
    admitted on a guess.
    """
    return LIVE_LENS_SOURCES_BY_SPORT.get(str(sport or "").strip().lower(), _DEFAULT_LENS_SOURCES)

# Withheld reasons. Every zero must be diagnosable by reason -- the shape
# `live_edge_policy` established, and the reason a counter of 0 was mysterious
# for so long on the prop side.
REASON_NO_LIVE_PROJECTION = "no_live_gameline_projection"
REASON_NOT_PRICEABLE = "prob_interval_swamps_edge"
REASON_TOTALS_MEAN = "totals_mean_not_distribution"
REASON_NO_MARKET_PRICE = "no_two_sided_market_price"
REASON_UNUSABLE_SIMS = "sim_count_unusable"
# The live re-sim publishes a FULL-GAME win probability. The grid carries the
# same h2h market once per segment (full / first5 / first3 / first1), so
# joining without this filter prices a full-game projection against a
# FIRST-INNING market. Measured 2026-08-16, SD @ CLE: model 0.9667 against
# mkt 0.8750 (full) = +9.17 pp, and against mkt 0.5424 (first1) = **+42.43 pp**
# -- an edge that is entirely an artifact of the mismatched segment.
REASON_SEGMENT_NOT_FULL_GAME = "segment_is_not_full_game"
_FULL_GAME_SEGMENTS = frozenset({"full", "full_game", "game"})

# `REASON_TOTALS_MEAN` above is now a LEGACY path, not the normal one. It fires
# only against a lens written before the producer carried `totalRunsDist` --
# i.e. an old snapshot -- and is deliberately kept so that case stays
# distinguishable from a genuinely absent projection.
REASON_NO_LIVE_DISTRIBUTION = "live_resim_published_no_distribution_for_this_market"
REASON_NO_LINE = "row_carries_no_line_to_price_against"
REASON_UNKNOWN_SIDE = "unrecognised_side_token"
REASON_UNSUPPORTED_MARKET = "market_not_priced_from_a_live_distribution"

# The alt families are the SAME market at another line, and the distribution
# prices any line -- which is the whole reason a histogram beats a mean. Leaving
# them out would have repeated the pregame defect `prop_projections:615` records:
# 53 of 107 live game-line rows carrying no projection at all, every one of them
# `spreads_alt` or `totals_alt`, because neither key was in the set.
_TOTALS_MARKETS = frozenset({"totals", "total", "totals_alt", "alternate_totals"})
_SPREAD_MARKETS = frozenset({"spreads", "run_line", "ats", "spreads_alt", "alternate_spreads"})
_DIST_MARKETS = _TOTALS_MARKETS | _SPREAD_MARKETS


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
    # AGRESTI-COULL, not Wald. The Wald form `sqrt(p(1-p)/n)` is **0.0 at p=0 and
    # p=1**, which is not "perfectly precise" -- it is undefined, and it is a
    # LIVE case: the re-sim quantises to k/n, so 0/120 and 120/120 occur on real
    # slates. Measured 2026-08-16: `PHI @ MIN model=0.0 se=0.0` was published
    # PRICEABLE with a 2-sigma bar of ZERO, so every edge cleared it. This
    # module's own docstring warned that a 0.0 here "would make every edge
    # priceable" and then returned one for degenerate-but-valid input.
    #
    # Add-two smoothing shifts the estimate off the boundary and widens by the
    # same token, so the tails are conservative rather than infinitely confident.
    successes = p * float(n)
    n_adj = float(n) + 4.0
    p_adj = (successes + 2.0) / n_adj
    return math.sqrt(max(0.0, p_adj * (1.0 - p_adj)) / n_adj)


def live_gameline_from_lens(
    lens_rows: Any, *, sources: tuple[str, ...] | None = None
) -> dict[str, Any] | None:
    """The live-state moneyline projection from a snapshot's `gameLens`.

    Only the `live`/`full` lanes are ever stamped `live_mc`, and only when
    `estimate_live` actually returned. The `first1/3/5` lanes carry a
    `modelHomeWinProb` too -- derived from `_live_margin_win_prob` over a
    segment interpolation -- so keying on the probability's PRESENCE would
    silently accept a lens the re-sim never touched. Key on `source`.
    """
    if not isinstance(lens_rows, list):
        return None
    accepted = tuple(sources) if sources else _DEFAULT_LENS_SOURCES
    for lens in lens_rows:
        if not isinstance(lens, Mapping):
            continue
        if str(lens.get("source") or "").strip().lower() not in accepted:
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
            # THE SHAPES, not just the means. Without these a totals row can
            # only be refused (`REASON_TOTALS_MEAN`) and a spreads row cannot be
            # answered at all -- which is why every live totals/spreads row on
            # the board carried a PREGAME projection while the moneyline, the
            # one market a bare probability can price, worked.
            #
            # Absent on any lens written before the producer carried them, and
            # `{}` reads as "no distribution" everywhere downstream, so an old
            # snapshot degrades to exactly the previous behaviour rather than
            # to a wrong number.
            "total_runs_dist": projection.get("totalRunsDist") or {},
            "margin_dist": projection.get("marginDist") or {},
            "as_of": lens.get("liveStateAsOf"),
            "carried_forward": bool(lens.get("liveStateCarriedForward")),
            "lane": lens.get("key"),
        }
    return None


def price_distribution_market(
    *,
    dist: Any,
    line: Any,
    side: str,
    market: str,
    market_prob: Any,
    sims: Any,
    sigma: float = PRICEABLE_SIGMA,
) -> dict[str, Any]:
    """Price a live TOTALS or SPREADS row off the re-sim's own histogram.

    Same contract as `price_moneyline`: always a dict, never a bare None, and
    the refusal is named. The precision gate is identical -- a distribution does
    not make 120 sims more precise, it only makes a LINE answerable at all.

    THE LINE FRAME IS THE AWAY/OVER ONE and is not re-derived here. `#262` made
    the grid row's `line` canonical, and `prop_projections.project_game_market`
    already encodes what that means for spreads: with `L` the away-frame line,
    home covers when `margin > L`, so the home branch must NOT negate. Getting
    this backwards produced measured home probabilities of 0.67-0.74 on
    underdogs and 19-28 point phantom edges on 2026-08-08. The same helpers are
    imported rather than reimplemented so the two paths cannot drift -- a second
    copy of this rule is how the first one rotted.

    `margin_dist` is home-positive (`home_final - away_final`), matching
    `run_margin_dist`'s frame, so the pregame rule transfers unchanged.
    """
    from syndicate.features.shared.prop_projections import _dist_prob_below, _dist_prob_over

    out: dict[str, Any] = {
        "model_prob": None,
        "market_prob": None,
        "edge_pp": None,
        "prob_std_err": None,
        "priceable": False,
        "withheld_reason": None,
        "sigma": float(sigma),
    }
    if not isinstance(dist, Mapping) or not dist:
        out["withheld_reason"] = REASON_NO_LIVE_DISTRIBUTION
        return out
    try:
        line_value = float(line)
    except (TypeError, ValueError):
        out["withheld_reason"] = REASON_NO_LINE
        return out

    key = str(market or "").strip().lower()
    token = str(side or "").strip().lower()
    if key in _TOTALS_MARKETS:
        if token in {"over", "o"}:
            model_prob = _dist_prob_over(dist, line_value)
        elif token in {"under", "u"}:
            model_prob = _dist_prob_below(dist, line_value)
        else:
            out["withheld_reason"] = REASON_UNKNOWN_SIDE
            return out
    elif key in _SPREAD_MARKETS:
        # See the frame note above: no negation on the home branch.
        if token in {"home", "1"}:
            model_prob = _dist_prob_over(dist, line_value)
        elif token in {"away", "2"}:
            model_prob = _dist_prob_below(dist, line_value)
        else:
            out["withheld_reason"] = REASON_UNKNOWN_SIDE
            return out
    else:
        out["withheld_reason"] = REASON_UNSUPPORTED_MARKET
        return out

    if model_prob is None:
        out["withheld_reason"] = REASON_NO_LIVE_DISTRIBUTION
        return out
    out["model_prob"] = float(model_prob)

    try:
        market_p = float(market_prob)
    except (TypeError, ValueError):
        out["withheld_reason"] = REASON_NO_MARKET_PRICE
        return out
    if not (0.0 < market_p < 1.0):
        out["withheld_reason"] = REASON_NO_MARKET_PRICE
        return out
    out["market_prob"] = market_p

    std_err = prob_std_err(model_prob, sims)
    if std_err is None:
        out["withheld_reason"] = REASON_UNUSABLE_SIMS
        return out
    out["prob_std_err"] = std_err
    edge = _edge_pp(float(model_prob), market_p)
    out["edge_pp"] = round(edge, 2)
    # THE SAME BAR AS THE MONEYLINE, deliberately. A histogram answers "what is
    # P(over 8.5)"; it does not narrow the interval around that answer, which is
    # still set by the sim count. Releasing distribution-based edges at a looser
    # threshold would publish exactly the noise the moneyline gate exists to
    # withhold, and it would look more rigorous for having come from a shape.
    if abs(edge) < float(sigma) * std_err * 100.0:
        out["withheld_reason"] = REASON_NOT_PRICEABLE
        return out
    out["priceable"] = True
    return out


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


def build_live_gameline_index(
    snapshot: Any, *, sources: tuple[str, ...] | None = None
) -> dict[tuple[str, str], dict[str, Any]]:
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
        # TWO SNAPSHOT SHAPES, AND NEITHER IS WRONG. MLB nests the teams under
        # `matchup`; WNBA's lens carries `away`/`home` at the top level (and
        # `away_name`/`home_name` beside them). Measured on production
        # 2026-08-16: wnba games have no `matchup` key at all, so a
        # matchup-only read indexed zero of them and the join reported a clean
        # empty rather than a mismatch.
        #
        # Fall through in order rather than merging: the first shape that yields
        # BOTH names wins, so a snapshot carrying a partial `matchup` cannot
        # half-match and produce a key built from two different games.
        matchup = game.get("matchup") if isinstance(game.get("matchup"), Mapping) else {}
        key: tuple[str, str] | None = None
        for away_raw, home_raw in (
            (matchup.get("away"), matchup.get("home")),
            (game.get("away"), game.get("home")),
            (game.get("away_name"), game.get("home_name")),
        ):
            away_name = away_raw.get("name") if isinstance(away_raw, Mapping) else away_raw
            home_name = home_raw.get("name") if isinstance(home_raw, Mapping) else home_raw
            candidate = (_norm_team(away_name), _norm_team(home_name))
            if candidate[0] and candidate[1]:
                key = candidate
                break
        if key is None:
            continue
        projection = live_gameline_from_lens(game.get("gameLens"), sources=sources)
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
        market_key = str(row.get("market") or "").strip().lower()
        # h2h prices off the win probability; totals/spreads price off the
        # histograms. Anything else is not a market this join answers, and it is
        # skipped rather than counted -- counting it would inflate the
        # denominator with rows nobody expected a live number for.
        if market_key != "h2h" and market_key not in _DIST_MARKETS:
            continue
        # Counted, then refused BY NAME -- a segment row is a real live h2h row
        # the join saw and declined, not one it never considered. An ABSENT
        # segment refuses too: unknown must not take the permissive branch.
        segment = str(row.get("segment") or "").strip().lower()
        if segment not in _FULL_GAME_SEGMENTS:
            record(coverage, {"priceable": False,
                              "withheld_reason": REASON_SEGMENT_NOT_FULL_GAME},
                   projected=False)
            continue

        key = (_norm_team(row.get("away_team")), _norm_team(row.get("home_team")))
        hit = index.get(key)
        if hit is None:
            record(coverage, {"priceable": False, "withheld_reason": REASON_NO_LIVE_PROJECTION}, projected=False)
            continue

        projection = row.get("projection") if isinstance(row.get("projection"), Mapping) else {}
        if market_key in _DIST_MARKETS:
            # THE SIDE THE PROJECTION DESCRIBES, taken from the row's own side
            # tokens rather than assumed. `market_fair_prob_over` is the de-vig
            # of the FIRST side in the grid's ordering -- `over` for totals,
            # `home` for spreads -- so the model probability must describe that
            # same side or the subtraction spans opposite outcomes. This is the
            # identical trap `layer1_board.html:770` records for `projection.side`.
            side_token = "over" if market_key in _TOTALS_MARKETS else "home"
            verdict = price_distribution_market(
                dist=(hit.get("total_runs_dist") if market_key in _TOTALS_MARKETS
                      else hit.get("margin_dist")),
                line=row.get("line"),
                side=side_token,
                market=market_key,
                market_prob=projection.get("market_fair_prob_over"),
                sims=hit.get("sims_run"),
            )
            _apply_verdict(row, projection, verdict, hit, coverage,
                           live_projected=verdict.get("model_prob"))
            continue

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

        _apply_verdict(row, projection, verdict, hit, coverage)

    return coverage


def _apply_verdict(
    row: Any,
    projection: Mapping[str, Any],
    verdict: Mapping[str, Any],
    hit: Mapping[str, Any],
    coverage: dict[str, Any],
    *,
    live_projected: Any = None,
) -> None:
    """Write one verdict onto the row, for BOTH the moneyline and distribution
    paths.

    Extracted rather than copied. The moneyline version of this block already
    existed and the distribution path needed the same six fields plus the
    projection rewrite; a second copy is how the two would drift, and this
    module has already paid for that once -- `#340` records the live-edge rule
    living in two per-sport copies while WNBA, which had neither, shipped 128
    live edges.
    """
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
        if live_projected is not None:
            # The LIVE model probability, kept next to the pregame one rather
            # than overwriting it. `projected` on a game row is the pregame
            # sim's number and stays readable; a reader comparing the two is a
            # legitimate thing to want, and silently replacing it is how a live
            # board loses its own provenance.
            updated["live_model_prob_over"] = live_projected
            updated["live_projected"] = live_projected
        if verdict.get("priceable"):
            updated["edge_vs_market_pct"] = verdict.get("edge_pp")
            # **WHICH PROBABILITY THIS EDGE IS COMPUTED AGAINST.** On a
            # live-joined row it is `live_model_prob_over`, NOT the pregame
            # `model_prob_over` set a few lines above -- different vintages, and
            # pairing them is wrong by tens of points.
            #
            # Measured on the served shortlist 2026-08-16: of 13 rows carrying
            # both an edge and the probability pair, the 7 whose
            # `edge_vs_market_pct` could NOT be reproduced from
            # `(model_prob_over - market_fair_prob_over)` were all `live_aware`,
            # and all 6 that reconciled were not -- 7/7 separation. On one row
            # the stated edge was `-39.93`, which is exactly
            # `(live_model_prob_over 0.1917 - market_fair_prob_over 0.591) * 100`;
            # the pregame pairing gives `+27.46`. Every number is correct. Only
            # the pairing is unstated, and a reader cannot recover it.
            #
            # **THIS IS THE FIX `layer2_board` SAYS IT IS WAITING FOR.** Beside
            # `_MODEL_EDGE_MAX_POINTS = 15.0` it reads: "The real fix is an
            # explicit `basis` on the projection... Until projections carry it,
            # this bound is the guard -- and it is a GUARD, not a calibration."
            # That 15-point bound is why the worst of these rows are dropped
            # rather than mispriced: the `-39.93` above never reaches the board.
            # `edge_basis` is what a future change would need before that bound
            # could be relaxed. Relaxing it is NOT part of this change.
            #
            # **This ADDS a key and changes no existing value, deliberately.**
            # `layer2_board._model_edge_for` reads `edge_vs_market_pct` directly
            # and it becomes the board's `model_edge_pct`, so moving the live
            # edge to a differently-named field would make the board price LIVE
            # rows off a PREGAME edge -- worse than the defect it fixes. That was
            # the first proposal here and it was withdrawn for exactly that.
            updated["edge_basis"] = "live" if live_projected is not None else "pregame"
            updated["edge_unavailable_reason"] = None
        else:
            updated["edge_vs_market_pct"] = None
            updated["edge_unavailable_reason"] = verdict.get("withheld_reason")
        row["projection"] = updated

    record(coverage, verdict, projected=True)
