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

# AN ANALYTIC ESTIMATOR'S ERROR BAR, WHERE THERE IS NO SIM COUNT TO DERIVE ONE.
#
# `prob_std_err` answers "how noisy is this Monte-Carlo estimate" from `n`.
# WNBA has no `n`: `state.md` records that WNBA deliberately does NOT re-sim
# live -- `#481`'s live probability is an ANALYTIC transform of the pregame sim
# (a logistic on the live margin, blended toward the pregame anchor). So the
# sims gate refused every WNBA row forever, and the counter said
# `sim_count_unusable`. Measured on production 2026-08-21 01:3xZ against a live
# IND@DAL: `rows_live_gameline_considered: 194`, `priceable: 0`.
#
# THE BAR IS STILL A MEASUREMENT, NOT A WAIVER. This is the whole point of the
# module's first refusal, so an analytic estimator does not get to skip it --
# it has to bring its own honest interval. `#481` refit that transform against
# outcomes and reported a HELD-OUT worst calibration gap of **0.054** over
# 36,482 samples on a game-level split (before the refit it was 0.240). That
# gap -- the largest observed distance between predicted and realised frequency
# in any bucket -- is the conservative reading of "how wrong this estimator is
# allowed to be", and it is used directly as the standard error.
#
# Consequences, stated so nobody reads a quiet board as a bug: at
# `PRICEABLE_SIGMA = 2.0` a WNBA live moneyline edge must clear **10.8 pp**
# before it prices. That is deliberately harsher than MLB's ~9.1 pp at n=120,
# p=0.5, because a calibration gap is a bias and does not shrink with more
# ticks. The honest lever is re-fitting the transform (which narrows the gap),
# exactly as the honest lever on the MLB side is raising the sim count.
#
# A sport ABSENT from this table and carrying no sims is still refused. Absence
# must not read as "no uncertainty" -- that is the `0.0` substitution this
# module's own `prob_std_err` docstring calls the worst available.
ANALYTIC_LIVE_STD_ERR_BY_SPORT: dict[str, float] = {
    "wnba": 0.054,
}

# PER-MARKET OVERRIDE, where a market has its own measurement. `#499` graded the
# live TOTALS transform over 249 games / 23,712 samples and refit its scale
# (test Brier 0.1744 -> 0.1477), so "never backtested" no longer holds -- but
# the number that came out is FOUR TIMES the win path's.
#
# 0.150 IS THE WORST CALIBRATION GAP BY PREDICTED BUCKET on held-out data, and
# the choice of that denominator is the whole point. By MINUTES-LEFT bucket the
# worst gap is 0.023, which would have set a 4.6pp bar -- and it is an artifact
# of averaging: within a time bucket the +0.109 error at p=0.35 and the -0.150
# at p=0.65 cancel to about -0.02. That is `#481`'s own finding restated ("the
# aggregate means were unbiased, so the failure was DISPERSION"), and taking the
# aggregate here would have flooded the board with noise priced at a bar six
# times too tight.
#
# At 2 sigma this is a **30pp bar**, so almost nothing will price. That is the
# CORRECT outcome for an estimator whose probabilities are still visibly
# under-dispersed (predicted 0.65 -> actual 0.796), not a disappointment. What
# it buys over the old blanket refusal is that each row is now refused by
# `prob_interval_swamps_edge` against its OWN edge, which is data-driven and
# per-row, instead of by a category-wide "never measured".
#
# The honest follow-up: calibration improves monotonically as the scale narrows
# (0.208 at a=8.0, 0.150 at the shipped a=3.2, 0.125 at a=2.0) and the held-out
# set prefers a=2.0 on Brier too. That was NOT adopted -- the scale was fitted on
# TRAIN and switching to the test-preferred value is leakage. Refit on train with
# calibration in the objective, then this number moves.
ANALYTIC_LIVE_STD_ERR_BY_MARKET: dict[tuple[str, str], float] = {
    ("wnba", "totals"): 0.150,
}


def analytic_std_err_for_sport(sport: Any) -> float | None:
    """The analytic estimator's standard error for this sport, or None.

    None means "this sport has no measured analytic interval", which leaves the
    sims path in charge and, absent sims, leaves the row refused.
    """
    value = ANALYTIC_LIVE_STD_ERR_BY_SPORT.get(str(sport or "").strip().lower())
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out > 0.0 else None


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
# THE QUOTE MUST STILL BE A LIVE QUOTE.
#
# **THIS IS THE GATE THAT WAS MISSING, AND IT MANUFACTURED EDGES.** The
# precision gate below asks "is the edge bigger than the model's own noise". It
# never asked whether the PRICE the edge is measured against still exists. A
# live re-sim compared to a dead price produces a large, confident, and entirely
# fictional edge, and the size of the fiction grows with the staleness.
#
# MEASURED 2026-09-01 over the retained MLB ledger, 12 dates / 72,587 records /
# 157 games, h2h scored against StatsAPI finals (`lane
# mlb-live-gameline-skill-audit`):
#
#   quote age   n     model    market   model-minus-market
#   <= 120s     954   0.20000  0.17403  +0.02597   <- the model HONESTLY loses
#   300-600s    320   0.16264  0.17011  -0.00747
#   600-1800s   501   0.16326  0.19047  -0.02721
#   > 1800s     592   0.16459  0.21897  -0.05438   <- the model "wins"
#
# The model does not get better as the quote ages; the MARKET gets worse,
# because a stale number is a worse forecast of an outcome it has not seen. On
# the subset the board liked most -- late game, `|edge| >= 20pp` -- the MEDIAN
# quote age was **42.9 minutes** and p90 was ~21 hours, and that subset scored a
# fair-odds "return" of +98.7%. That number is not an edge. It is the arithmetic
# of pricing against a quote nobody could have taken.
#
# Across the whole file the ages are: p50 410s, p75 950s, p90 1,848s,
# p99 **74,997s**. So ~1 row in 100 was being priced off a price over 20 hours
# old, and 39.5% off one older than ten minutes.
#
# WHY 600s AND NOT 120s. 120s is the population the model was actually validated
# on and is the defensible research cut, but it keeps only 23.1% of rows and
# choosing it here would be a product decision disguised as a safety fix. 600s
# removes the population that is unambiguously dead -- an in-play baseball
# moneyline that has not moved in ten minutes is not a live quote -- and keeps
# 60.5%. Tighten with the env knob once someone owns that decision.
#
# ABSENT AGE IS REFUSED, NOT PASSED. `unknown must not default permissive` is a
# standing rule here. Every one of the 72,587 measured records carried
# `age_seconds`, so this branch should never fire; if it starts firing, that is
# the bug report, not a relaxed gate.
REASON_STALE_QUOTE = "quote_older_than_live_pricing_ceiling"
REASON_QUOTE_AGE_ABSENT = "row_carries_no_quote_age"
_DEFAULT_MAX_QUOTE_AGE_SECONDS = 600.0


def max_quote_age_seconds() -> float:
    """Ceiling on how old a quote may be and still be priced live.

    `SYNDICATE_LIVE_GAMELINE_MAX_QUOTE_AGE_SECONDS`. A non-positive value or an
    unparseable one falls back to the default rather than disabling the gate --
    a knob that can be typo'd into "off" is the shape this repo has already been
    burned by (`#603` shipped inert twice).
    """
    raw = str(os.environ.get("SYNDICATE_LIVE_GAMELINE_MAX_QUOTE_AGE_SECONDS") or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_MAX_QUOTE_AGE_SECONDS
    return value if value > 0.0 else _DEFAULT_MAX_QUOTE_AGE_SECONDS


def quote_age_verdict(age_seconds: Any) -> dict[str, Any] | None:
    """`None` if the quote is fresh enough to price; a refusal verdict if not.

    Returns a verdict shaped like `price_moneyline`'s so `record` folds it into
    the same counters and the refusal is named in `withheld_by_reason`.
    """
    if isinstance(age_seconds, bool) or not isinstance(age_seconds, (int, float)):
        return {"priceable": False, "withheld_reason": REASON_QUOTE_AGE_ABSENT,
                "model_prob": None, "market_prob": None, "edge_pp": None}
    age = float(age_seconds)
    if age != age or age > max_quote_age_seconds():  # NaN-safe
        return {"priceable": False, "withheld_reason": REASON_STALE_QUOTE,
                "model_prob": None, "market_prob": None, "edge_pp": None}
    return None


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


def min_edge_pp() -> float:
    """An ABSOLUTE floor under the publish bar, in percentage points.

    **WHY THIS EXISTS: THE PRECISION GATE GETS LOOSER AS THE MODEL GETS MORE
    PRECISE, AND THAT IS BACKWARDS WHEN THE MODEL HAS NO MEASURED SKILL.** The
    gate below is `|edge| >= sigma * se * 100`, and `se = sqrt(p(1-p)/n)`. At
    MLB's 120 sims that bar is ~8.98pp at p=0.5. Raise `MLB_LIVE_GAME_MC_SIMS`
    to 1,000 -- which is a genuine accuracy improvement, worth ~0.0014 Brier of
    pure sampling noise -- and the bar falls to ~3.2pp, roughly TRIPLING the
    published volume as a side effect nobody asked for.

    That side effect is only acceptable if the extra rows are good. Measured
    2026-09-01 on fresh quotes (<=120s, the only prices anyone could take),
    h2h against StatsAPI finals:

        |edge|       n      model    market   model-minus-market
        0-10pp       2052   0.16061  0.15814  +0.00247
        10-20pp      452    0.24861  0.22264  +0.02597
        >= 20pp      70     0.35888  0.19584  +0.16305

    The model is worse than the market in EVERY band, and worst exactly where
    it claims the most. So widening publication is strictly harmful here, and
    the sim count must not be allowed to decide it.

    DEFAULT 0.0 -- OFF, so behaviour is unchanged today. This is the knob that
    must be set BEFORE `MLB_LIVE_GAME_MC_SIMS` is raised, not after.
    """
    raw = str(os.environ.get("SYNDICATE_LIVE_GAMELINE_MIN_EDGE_PP") or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return 0.0
    return value if value > 0.0 else 0.0



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


def _analytic_markets_from_lens(lens: Mapping[str, Any]) -> dict[str, Any]:
    """The lens's own per-market live probabilities, where it publishes them.

    Reads `markets.spread` / `markets.total` -- the shape WNBA's
    `_wnba_game_lens_markets` writes. Returns `{}` for a lens without them
    (MLB), so the caller's distribution path is reached exactly as before.
    """
    markets = lens.get("markets")
    if not isinstance(markets, Mapping):
        return {}
    out: dict[str, Any] = {}
    spread = markets.get("spread")
    if isinstance(spread, Mapping):
        line = spread.get("homeLine")
        prob = spread.get("p_win")
        # `selection` is always "home" on this lens's spread block, so `p_win`
        # IS P(home covers). Asserted rather than assumed: a lens that ever
        # publishes the away side would otherwise be read as its opposite.
        if line is not None and prob is not None and str(spread.get("selection") or "home").lower() == "home":
            out["spread"] = {"line": line, "p_home_cover": prob}
    total = markets.get("total")
    if isinstance(total, Mapping) and total.get("p_win") is not None:
        # Carried ONLY so the totals refusal can name itself; never priced.
        out["total"] = {"line": total.get("line"), "p_over": total.get("p_win")}
    return out


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
            # LINE-SPECIFIC ANALYTIC PROBABILITIES, where the producer publishes
            # them instead of a distribution. WNBA's lens carries a live cover
            # probability at ONE line (`#475`), which prices that line and no
            # other -- see `price_analytic_line_market`. Absent on MLB's lens,
            # so this is `{}` there and the distribution path is untouched.
            "analytic_markets": _analytic_markets_from_lens(lens),
            # THE GAME CLOCK, AND THE PREGAME NUMBER THE LIVE ONE REPLACED.
            #
            # Both were already on the lens and neither was ever read. Their
            # absence is why the 2026-09-01 skill audit had to use WALL-CLOCK
            # MINUTES SINCE A GAME'S FIRST LEDGER ROW as a proxy for how far the
            # game had gone -- a proxy that is wrong for every rain delay and
            # extra-inning game, and that cannot tell "bottom 9, tied, two outs"
            # from "top 5 of a blowout".
            #
            # `progress` carries {fraction, inning, half, outs, outsRecorded,
            # remainingOuts}. `baselineHomeWinProb` is the PREGAME probability
            # the live re-sim supersedes. Recording the baseline beside the live
            # number is what makes the next question answerable at all: the
            # audit's encompassing regression found the live model carries
            # almost no information the market lacks EARLY (weight 0.13 against
            # the market's 1.18) and most of it LATE (0.74 against 0.30) -- the
            # signature of a live estimate that discarded a prior it should have
            # kept. That blend cannot be fitted without both terms on one row.
            #
            # Read defensively: an older snapshot has neither key, and `{}` /
            # `None` degrade to exactly the previous behaviour downstream.
            "progress": lens.get("progress") if isinstance(lens.get("progress"), Mapping) else {},
            "pregame_home_win_prob": lens.get("baselineHomeWinProb"),
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
    analytic_std_err: Any = None,
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
        "std_err_basis": None,
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

    # TWO WAYS TO GET AN INTERVAL, AND NEVER A THIRD. Either the estimator ran
    # n trials (Monte Carlo, MLB) or it is analytic and brings a measured
    # calibration error (WNBA, `#481`). What is NOT allowed is pricing without
    # one -- see `ANALYTIC_LIVE_STD_ERR_BY_SPORT`. The sims path is tried first
    # so MLB's behaviour is bit-for-bit unchanged, including its refusals.
    try:
        n = int(sims)
    except (TypeError, ValueError):
        n = 0

    se: float | None = None
    basis = None
    if n >= _min_sims():
        se = prob_std_err(p, n)
        basis = "sim_count"
    if se is None:
        try:
            candidate = float(analytic_std_err) if analytic_std_err is not None else None
        except (TypeError, ValueError):
            candidate = None
        # `> 0.0` is load-bearing: a 0.0 here would read as perfect precision and
        # make every edge priceable, which is the exact substitution this
        # module has already paid for once (`PHI @ MIN se=0.0`).
        if candidate is not None and candidate > 0.0:
            se = candidate
            basis = "analytic_calibration"
    if se is None:
        # Unchanged for MLB: no usable sims and no analytic interval means the
        # row is refused by the SAME name it was before.
        out["withheld_reason"] = REASON_UNUSABLE_SIMS
        return out
    out["prob_std_err"] = se
    # Which interval decided this row. Without it, an analytic verdict and a
    # sim-derived one are indistinguishable in the ledger, and this module's
    # premise is that every zero is diagnosable by name.
    out["std_err_basis"] = basis

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
    # rather than letting a unit mismatch decide what gets published. The
    # absolute floor is applied with `max`, so it can only ever TIGHTEN the
    # precision bar; it is off (0.0) unless set. See `min_edge_pp`.
    bar = max(float(sigma) * se * 100.0, min_edge_pp())
    if abs(edge) < bar:
        out["withheld_reason"] = REASON_NOT_PRICEABLE
        return out

    out["priceable"] = True
    return out


REASON_ANALYTIC_LINE_MISMATCH = "analytic_probability_is_only_valid_at_its_own_line"
REASON_ANALYTIC_UNCALIBRATED = "analytic_estimator_never_backtested_for_this_market"

# WHICH ANALYTIC MARKETS MAY BE PRICED, AND THE ONE THAT MAY NOT.
#
# SPREAD: `#481` refit the live margin scale against outcomes and DELIBERATELY
# shared the fitted constant with the cover path, on the recorded argument that
# "cover asks will (margin + spread) end positive -- the SAME question about how
# a margin at time T predicts the final margin's sign that the win-prob fit
# measured, so the fitted dispersion transfers". The interval is inherited on
# that same argument. HONEST LIMIT: the 0.054 gap was measured on the WIN path;
# a cover-specific grade has never been run, so this is a reasoned transfer and
# not a direct measurement. Recorded here rather than in a commit message
# because the next reader needs it at the point of use.
#
# TOTAL: refused, and NOT because the shape is missing. `_wnba_live_total_over_prob`
# still carries `8.0 + 0.50 * min_left` -- a ported constant that has never been
# backtested. `#481` looked at it and explicitly declined to refit it, because a
# total is combined scoring rather than a margin's sign and "refitting needs
# historical market totals, unavailable here". Pricing it would publish an
# estimator whose error nobody has measured, which is precisely what this
# module's first refusal exists to prevent. The reason is spelled out so this
# reads as a KNOWN GAP with a known unblock (grade it against historical
# totals), not as the same "no distribution" shrug the spread path used to get.
#
# Reuses `_SPREAD_MARKETS` rather than restating the membership: `#`-alt keys
# (`spreads_alt`, `alternate_spreads`) were added to that set after 53 of 107
# rows were found carrying no projection because a second copy had drifted.
# Alt lines still route through here and are refused BY LINE below, which is
# the accurate reason -- they are not unpriceable markets, they are the same
# market at a number this probability does not describe.
_ANALYTIC_PRICEABLE_MARKETS = _SPREAD_MARKETS


def price_analytic_line_market(
    *,
    analytic: Any,
    market: Any,
    line: Any,
    market_prob: Any,
    analytic_std_err: Any,
    sigma: float = PRICEABLE_SIGMA,
    sport: Any = None,
) -> dict[str, Any] | None:
    """Price a spread row from a line-specific analytic probability.

    Returns None when this path does not apply at all, so the caller falls
    through to the distribution path unchanged -- an absent analytic block must
    not turn into a refusal that hides the real (distribution) reason.
    """
    if not isinstance(analytic, Mapping):
        return None
    sport_key = str(sport or "").strip().lower()
    market_key = str(market or "").strip().lower()
    if market_key in _TOTALS_MARKETS:
        block = analytic.get("total")
        if not isinstance(block, Mapping):
            return None
        # `#499` MEASURED IT, so the blanket refusal is retired -- but only for
        # a sport/market pair that HAS a measurement. Anything else still
        # refuses by the same name it did before.
        totals_sigma = ANALYTIC_LIVE_STD_ERR_BY_MARKET.get((sport_key, "totals"))
        if totals_sigma is None:
            out = withhold_totals()
            out["withheld_reason"] = REASON_ANALYTIC_UNCALIBRATED
            return out
        try:
            model_prob = float(block.get("p_over"))
            analytic_line = float(block.get("line"))
            row_line = float(line)
        except (TypeError, ValueError):
            return None
        if abs(analytic_line - row_line) > 1e-6:
            return {
                "model_prob": None, "market_prob": None, "edge_pp": None,
                "std_err_basis": None, "prob_std_err": None, "priceable": False,
                "withheld_reason": REASON_ANALYTIC_LINE_MISMATCH, "sigma": float(sigma),
            }
        return price_moneyline(
            model_prob=model_prob,
            market_prob=market_prob,
            sims=None,
            sigma=sigma,
            analytic_std_err=totals_sigma,
        )
    if market_key not in _ANALYTIC_PRICEABLE_MARKETS:
        return None
    block = analytic.get("spread")
    if not isinstance(block, Mapping):
        return None
    try:
        model_prob = float(block.get("p_home_cover"))
        analytic_line = float(block.get("line"))
        row_line = float(line)
    except (TypeError, ValueError):
        return None

    # THE LINE MUST MATCH. A single probability describes P(home covers THIS
    # number). The board carries alt spreads at many numbers, and answering them
    # from one probability would invent a distribution -- the exact thing the
    # distribution path exists to do honestly. Tolerance is exact-to-the-half
    # because that is the granularity lines are quoted at.
    if abs(analytic_line - row_line) > 1e-6:
        out: dict[str, Any] = {
            "model_prob": None, "market_prob": None, "edge_pp": None,
            "std_err_basis": None, "prob_std_err": None, "priceable": False,
            "withheld_reason": REASON_ANALYTIC_LINE_MISMATCH, "sigma": float(sigma),
        }
        return out

    verdict = price_moneyline(
        model_prob=model_prob,
        market_prob=market_prob,
        sims=None,
        sigma=sigma,
        analytic_std_err=analytic_std_err,
    )
    return verdict


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
    snapshot: Any,
    *,
    sources: tuple[str, ...] | None = None,
    analytic_std_err: float | None = None,
    sport: Any = None,
    diagnostics: dict[str, Any] | None = None,
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

    `diagnostics`, WHEN PASSED, IS FILLED WITH WHY THE INDEX IS THE SIZE IT IS.
    A bare `index=0` cannot distinguish an absent snapshot from a present one
    whose lanes are all stamped for a state this sport does not accept, and
    those have completely different owners. Measured 2026-08-25 04:21Z: WNBA
    read `index=0 considered=184` -- 184 board rows in a live game state asking
    a snapshot that yielded nothing -- and it was read as "no live model wired
    for WNBA", which is FALSE. `live_lens_loop` builds the WNBA lens every 60s
    (`TICK_COMPLETE results={'wnba': True}` on live-odds-worker at 04:24:08Z).

    What is conditional is the STAMP. `wnba/cards.py:1381`:

        source = "live_projection" if (is_live and live_margin is not None
                                       and elapsed_min is not None) else "pregame"

    Three preconditions, and `live_gameline_from_lens` accepts only
    `live_projection` for WNBA -- so any one of them failing produces a
    published, healthy, correctly-refused snapshot that looks identical to an
    absent one. The third is a KNOWN hole this repo already documents at
    `wnba/cards.py:1345`: the clock blanks between periods, so `elapsed_min`
    goes None and the lane reverts to `pregame` for the whole break (observed
    2026-08-21 IND@DAL, a ~20-minute gap).

    So the stamps actually SEEN are recorded, not just the ones accepted. That
    is the difference between "the producer is not wired" and "the producer is
    wired and the game is at halftime".
    """
    diag = diagnostics if isinstance(diagnostics, dict) else None
    if diag is not None:
        diag.update({
            "games_in_snapshot": 0,
            "indexed": 0,
            "skipped_no_team_names": 0,
            "skipped_no_accepted_lane": 0,
            "sources_seen": {},
            "accepted_sources": list(sources or _DEFAULT_LENS_SOURCES),
        })

    index: dict[tuple[str, str], dict[str, Any]] = {}
    if not isinstance(snapshot, Mapping):
        if diag is not None:
            diag["reason"] = "snapshot_is_not_a_mapping"
        return index
    games = snapshot.get("games")
    if not isinstance(games, list):
        if diag is not None:
            diag["reason"] = "snapshot_carries_no_games_list"
        return index
    if diag is not None:
        diag["games_in_snapshot"] = len(games)
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
            if diag is not None:
                diag["skipped_no_team_names"] = int(diag["skipped_no_team_names"]) + 1
            continue
        if diag is not None:
            # EVERY stamp on the lens, accepted or not. The rejected ones are
            # the answer -- a snapshot full of `pregame` lanes is a live
            # producer in a state it declines to call live, not a missing one.
            lanes = game.get("gameLens")
            for lens in lanes if isinstance(lanes, list) else ():
                if not isinstance(lens, Mapping):
                    continue
                stamp = str(lens.get("source") or "none").strip().lower()
                seen = diag["sources_seen"]
                seen[stamp] = int(seen.get(stamp, 0)) + 1
        projection = live_gameline_from_lens(game.get("gameLens"), sources=sources)
        if projection is None:
            if diag is not None:
                diag["skipped_no_accepted_lane"] = int(diag["skipped_no_accepted_lane"]) + 1
            continue
        projection = dict(projection)
        projection["game_pk"] = game.get("gamePk")
        # Stamped per HIT rather than read at pricing time so the interval and
        # the projection it describes travel together -- a later caller cannot
        # accidentally price one sport's probability against another's bar.
        if analytic_std_err is not None:
            projection["analytic_std_err"] = float(analytic_std_err)
        if sport is not None:
            projection["sport"] = str(sport).strip().lower()
        index[key] = projection
        if diag is not None:
            diag["indexed"] = int(diag["indexed"]) + 1
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

        # THE STALENESS GATE SITS HERE, ABOVE THE MARKET BRANCH, ON PURPOSE.
        # Below this line the code forks three ways (moneyline, distribution,
        # analytic) and a check placed in any one of them would leave the other
        # two pricing against dead quotes. `learnings.md`: fix the choke point
        # every caller shares, not the one you can see. See `REASON_STALE_QUOTE`
        # for the measurement that motivates it.
        #
        # `projected=False` because the row never reached a projection -- this
        # is a refusal to price against a dead MARKET quote, not a failure of
        # the model, and folding it into `projected` would misattribute it.
        stale = quote_age_verdict(row.get("age_seconds"))
        if stale is not None:
            record(coverage, stale, projected=False)
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
            dist = (hit.get("total_runs_dist") if market_key in _TOTALS_MARKETS
                    else hit.get("margin_dist"))
            verdict = None
            if not dist:
                # NO DISTRIBUTION, BUT MAYBE AN ANALYTIC PROBABILITY AT THIS LINE.
                # WNBA has no re-sim to histogram, but `#475`/`#481` already
                # publish a live cover probability on the lens. It prices ONE
                # line -- its own -- which is exactly why a distribution is
                # preferred and why this refuses every other line by name
                # instead of interpolating a shape nobody fitted.
                verdict = price_analytic_line_market(
                    analytic=hit.get("analytic_markets"),
                    market=market_key,
                    line=row.get("line"),
                    market_prob=projection.get("market_fair_prob_over"),
                    analytic_std_err=hit.get("analytic_std_err"),
                    # From the INDEX, never a default. A default of "wnba" here
                    # would price another sport's totals against WNBA's measured
                    # sigma -- the permissive-default shape this repo forbids,
                    # and the reason `lens_sources_for_sport` is an explicit
                    # table rather than a relaxed check.
                    sport=hit.get("sport"),
                )
            if verdict is None:
                verdict = price_distribution_market(
                    dist=dist,
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
            # Present only for a sport with a MEASURED analytic interval; None
            # everywhere else, which leaves the sims gate in charge.
            analytic_std_err=hit.get("analytic_std_err"),
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
        # v4 LEDGER FIELDS. This copy list is EXPLICIT, so a key added to
        # `live_gameline_from_lens` and to `build_records` but not here reaches
        # the ledger as `None` and the feature ships inert with every test
        # green. That is `presence != reachability`, and it is why the ledger
        # test below asserts on the VALUES rather than on the keys existing.
        block["progress"] = hit.get("progress")
        block["pregame_home_win_prob"] = hit.get("pregame_home_win_prob")
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
