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

THAT IS THE h2h RULE, AND IT IS THE h2h RULE ONLY. For totals and spreads the
market's price is ~0.50 by construction and its VIEW is the LINE, so those are
scored on the model's POINT FORECAST against the line (contract 3, 2026-09-08;
see `_POINT_FORECAST_FAMILIES`). A row that cannot be measured is counted under
`unmeasured` by reason, and a row on a game segment is resolved only through a
segment-actual reader (`SegmentActualLookup`), never the full-game final.

WHAT IS DELIBERATELY NOT IMPORTED. `intelligence_evaluation._calibration`
already computes Brier and MAE, and reusing it would normally be right. It is
not imported here because this runs inside the per-build artifact path on
refresh-worker, which has a live OOM lane and a standing rule that periodic
worker work is never free (`#241`). Pulling a large evaluation module into every
build to reuse three lines of arithmetic trades a real memory cost for a
cosmetic one. The arithmetic is inlined and this paragraph is why.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any, Optional

# A record with no outcome is not scored, and the count is reported rather than
# dropped: "we had no outcome" and "the model was wrong" must never look alike.
_UNSCORED_NO_OUTCOME = "no_final_outcome_for_game"
_UNSCORED_NO_MODEL_PROB = "record_carries_no_model_probability"
# A market in NEITHER table below. Its own reason because "a market nobody
# classified" is a bug report, and folding it into a known refusal would hide
# the bug report behind the volume of the refusal.
_UNSCORED_MARKET_UNKNOWN = "record_carries_no_recognised_market"

# THE ONLY MARKET WHOSE PROBABILITY IS A HOME-WIN PROBABILITY -- scored by
# comparing PROBABILITIES, because for h2h the de-vigged price IS the market's
# view (market-leg sd 0.251, measured 2026-09-05).
#
# **THIS SET WAS THE FIX FOR A REAL DEFECT, MEASURED 2026-08-30.** The ledger
# stores `live_gameline.model_prob` under the field name `model_home_win_prob`,
# and that name is only true for `h2h`. `live_gameline_join.attach_live_gamelines`
# deliberately prices three markets (`h2h` plus `_DIST_MARKETS` = totals and
# spreads), and `live_gameline_ledger.build_records` writes all three. On a
# totals row that field holds **P(over)**; on a spreads row, **P(home covers)**.
#
# This loop had no market branch at all, so every one of them was scored against
# `won = did the home team win`. Measured on the served MLB board that day: of
# the 6 rows carrying a `live_gameline` block, **1 was h2h** -- 3 totals, 2
# spreads. So ~5/6 of the sample was a category error, and it is why the
# accumulated history (`reports/live_gameline_accuracy/history.jsonl`, pooled
# `priceable_only` +0.05749 over 118 games) says nothing about the model.
#
# **Why the market appeared to win.** A totals/spread line is set to make its own
# market a coin flip, so the de-vigged market prob sits near 0.5 by construction
# (0.3798/0.4425/0.4927/0.4919/0.4765 on that board). Against an event it is not
# predicting, that is near-OPTIMAL: Brier for an uninformative forecast is
# minimised at the base rate. The model's numbers are genuinely spread (0.25-0.45)
# and took the quadratic penalty at chance. The market was not beating the model;
# it was hedging an unrelated question.
_SCOREABLE_MARKETS: frozenset[str] = frozenset({"h2h"})

# THE MARKETS WHOSE VIEW IS THE LINE -- scored on the model's POINT FORECAST,
# never on a probability comparison. Scorer contract 3, 2026-09-08. From
# 2026-08-30 until then these were refused by name; the comment above is why,
# and the ledger recorded no `line` before 2026-08-30 so nothing earlier can be
# scored retroactively.
#
# WHY A PROBABILITY COMPARISON IS WRONG HERE, established in `816c93c0` and
# implemented first in `scripts/bucket_realised_performance.py`. Books quote
# totals and spreads about -110/-110, so the de-vigged `market_fair_prob` is
# ~0.50 WHATEVER the line is: market-leg sd totals 0.058, spreads 0.132; the
# within-game slope of P(over) against the line is -0.005 per run where a real
# total needs ~-0.12, and 44% of within-game line pairs were INVERTED. That is
# not a defect, it is what -110/-110 pricing MEANS. Comparing an informative
# model probability to that constant manufactures edge out of nothing -- the
# fake ~90% ATS result `subset_edge_scan` produced, and the +14pp `spreads
# q4_late` "realised edge" the harness reported before this correction.
#
# The market expresses its view as the LINE, so the model's own point forecast
# competes with the line on the actual outcome:
#
#   totals    `model_total_mean`  vs `line`  on the actual total   (away + home)
#   spreads   `model_margin_mean` vs `line`  on the actual margin  (home - away)
#
# The model backs over/home when its mean sits above the line; the observation
# is whether the actual landed on that side. A 0.50 baseline is legitimate for
# this directional read PRECISELY because the book prices the line as a coin
# flip. `actual == line` is a push and is not an observation. A row without
# the mean is UNMEASURED by name and is never folded into a probability
# comparison as a substitute: `market_fair_prob` is not read on these rows.
#
# THE LINE FRAME. `line` is the grid row's canonical away/over-frame line
# (`#262`), and `live_gameline_join.price_distribution_market` records the
# consequence for spreads: with the margin home-positive, home covers when
# `margin > line`. `model_margin_mean` is `hit["home_margin"]`, the same frame,
# so `mean > line` and `actual > line` are compared directly -- identical to
# `bucket_realised_performance.point_forecast_side`, the formulation this
# mirrors and must not drift from.
#
# THE MARKET SETS ARE IMPORTED FROM THE PRODUCER, NOT RE-TYPED HERE. A hand-copy
# was already wrong on its first attempt -- it had `spread` and lacked
# `run_line` and `ats`, so an MLB run-line row would have fallen through to
# `unknown`. Drift between the set that DECIDES WHAT TO PRICE and the set that
# DECIDES WHAT THAT PRICE MEANS is the class of defect this module exists to
# stop, and `live_gameline_join` is already resident in this build path.
from syndicate.features.shared.live_gameline_join import (
    _SPREAD_MARKETS as _SPREAD_MARKET_KEYS,
    _TOTALS_MARKETS as _TOTALS_MARKET_KEYS,
)

# family -> (ledger column carrying the model's mean, actual from (away, home)).
# The column is `model_total_mean`, NOT `total_mean`: reading the latter returns
# None on every row and looks exactly like an unfed field.
_POINT_FORECAST_FAMILIES: dict[str, tuple[str, Callable[[float, float], float]]] = {
    "totals": ("model_total_mean", lambda away, home: away + home),
    "spreads": ("model_margin_mean", lambda away, home: home - away),
}
_POINT_FORECAST_FAMILY_BY_MARKET: dict[str, str] = {
    **{m: "totals" for m in _TOTALS_MARKET_KEYS},
    **{m: "spreads" for m in _SPREAD_MARKET_KEYS},
}
POINT_FORECAST_BASELINE = 0.5

# UNMEASURED, BY NAME: every reason a line-priced row produced no observation.
# "We could not measure" and "the model was wrong" must never look alike, and
# neither may "no mean" and "push" -- the first is a pipeline gap (an unfed
# field, exactly the failure `model_engine_standard.md` exists for), the
# second is the game.
_UNMEASURED_NO_FINAL = "no_final_outcome_for_game"
_UNMEASURED_NO_FINAL_SCORE = "no_final_score_for_game"
_UNMEASURED_NO_MEAN = "record_carries_no_model_point_forecast"
_UNMEASURED_NO_LINE = "record_carries_no_line"
_UNMEASURED_PUSH = "push_actual_landed_on_the_line"
_UNMEASURED_NO_LEAN = "model_mean_equals_the_line"
# A row whose `segment` is not the full game needs a SEGMENT actual, and the
# full-game final is not one. See `SegmentActualLookup`.
_UNMEASURED_SEGMENT_ACTUAL_UNAVAILABLE = "segment_actual_unavailable"
_UNMEASURED_SEGMENT_LEVEL = "segment_actual_level_for_h2h"

# THE INTERFACE FOR SEGMENT ACTUALS: `(game_key, segment) -> (away, home)` as
# they stood at the END OF THAT SEGMENT, or None when the reader has nothing.
# `game_key` is tried as the record's `game_pk` and then its `event_id` -- the
# same two identifiers the finals join uses -- and `segment` is the ledger's
# own token (`first5`, `first_half`, ...), lower-cased. A Mapping keyed
# `(game_key, segment)` is accepted in place of the callable.
#
# THE DEFAULT IS NONE: FULL-GAME FINALS ONLY. Every ledger row today is
# `segment=full` by construction of the join, and the per-sport segment-actual
# readers are being built separately. `bet_status_*` is deliberately NOT
# imported here: this runs on every board build, and that module's cost is
# not this module's to pay (`#241`). Until a reader is passed in, a segment
# row is UNMEASURED under `segment_actual_unavailable` -- it is NEVER graded
# against the full-game final, which would score a first-five forecast on
# nine innings and call the result a measurement.
SegmentActualLookup = Callable[[str, str], Optional[tuple[float, float]]]

# WHAT A LEVEL FINAL MEANS, PER SPORT. Two EXPLICIT tables rather than one table
# and a relaxed default, for the reason `live_gameline_join.lens_sources_for_sport`
# is also explicit: a sport that appears in NEITHER must be visible as unknown,
# not quietly absorbed into whichever branch happens to be the fallthrough.
#
# Draw-bearing. A level final is a real result and the home side did not win.
DRAW_IS_A_REAL_OUTCOME: frozenset[str] = frozenset({
    "soccer",
    # Regulation ties survive overtime in both, rare but legitimate -- and a tie
    # is genuinely "the home side did not win". Listed BEFORE either has a live
    # game-line ledger, because the failure this table fixes is precisely a
    # sport-blind rule meeting a sport nobody re-checked it against.
    "nfl",
    "ncaaf",
})

# Cannot draw: a level final is a corrupt row and must not be scored.
LEVEL_FINAL_IS_A_BAD_ROW: frozenset[str] = frozenset({
    "mlb", "nba", "wnba", "ncaab",
    # Hockey resolves every game by overtime or shootout, so a FINAL is never
    # level on the scoreline this grid carries.
    "nhl",
})


# THE QUOTE THE MODEL WAS SCORED AGAINST MUST HAVE BEEN ALIVE.
#
# **WITHOUT THIS CUT THIS MODULE REPORTS THE MODEL AS BETTER THAN IT IS, WHICH
# IS THE DANGEROUS DIRECTION FOR AN INSTRUMENT TO BE WRONG IN.** Measured
# 2026-09-01 over 12 dates / 72,587 retained MLB records / 157 games, h2h scored
# against StatsAPI finals (`lane mlb-live-gameline-skill-audit`):
#
#   quote age at record time   n     model    market   model-minus-market
#   <= 120s                    954   0.20000  0.17403  +0.02597
#   300-600s                   320   0.16264  0.17011  -0.00747
#   600-1800s                  501   0.16326  0.19047  -0.02721
#   > 1800s                    592   0.16459  0.21897  -0.05438
#
# The model does not improve as the quote ages -- the MARKET decays, because a
# price that has not moved in half an hour is a worse forecast of an outcome it
# has not seen. Pooled over every age the model looked like it was at parity
# (-0.00202). On quotes that were actually alive it LOSES by +0.01096, bootstrap
# 95% CI over games [+0.00167, +0.02111]. Those are opposite conclusions drawn
# from one file, and the difference is entirely which prices were included.
#
# `FRESH_QUOTE_SECONDS` is the research cut -- the population any model change
# must be validated on. It is deliberately TIGHTER than
# `live_gameline_join.max_quote_age_seconds()` (the publish gate, 600s): a
# safety ceiling and an evidence standard are different questions and coupling
# them would let a product decision move the measurement.
FRESH_QUOTE_SECONDS = 120.0

# Reported as a breakdown so a shift in the AGE MIX can never again be mistaken
# for a shift in model quality.
_QUOTE_AGE_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("le_120s", 0.0, 120.0),
    ("120_300s", 120.0, 300.0),
    ("300_600s", 300.0, 600.0),
    ("600_1800s", 600.0, 1800.0),
    ("gt_1800s", 1800.0, float("inf")),
)

# THE SAME AXIS, CUMULATIVE. The disjoint buckets above answer "where does the
# quality change"; these answer the question a gate asks -- "what is the
# number on the population I would actually publish". MLB's live publish gate
# is 120s per sport (`_MAX_QUOTE_AGE_BY_SPORT`) and the historical ceiling was
# 600s, so both are named. `all` is every row, age present or not, and is
# there so a reader never has to add the other two to the absent count.
_CUMULATIVE_QUOTE_AGE_BUCKETS: tuple[tuple[str, float], ...] = (
    ("le_120s", 120.0),
    ("le_600s", 600.0),
    ("all", float("inf")),
)


# WHAT THIS SCORER IS, ANSWERABLE WITHOUT A SAMPLE.
#
# **WHY THIS EXISTS: THE PAYLOAD COULD NOT SAY WHETHER THE SCORER WAS DEPLOYED
# UNLESS IT HAD SOMETHING TO SCORE.** Measured 2026-09-01T16:56:16Z, 56 seconds
# after the staleness gate went live: the board carried 300 pregame rows and no
# finals, so `book_grid_artifact` took its `no_final_games_on_this_grid` branch
# and hand-built a four-key dict. `fresh_quote_seconds` was absent, and there
# was NO WAY from the served payload to tell "the new scorer shipped and had
# nothing to do" from "the new scorer did not ship". Both look like a null.
#
# That is the instrument-blindness shape this module already documents twice: a
# healthy-looking reading is evidence only once you know what makes it read
# unhealthy. These are CONSTANTS -- they need no records, no finals and no
# slate -- so there is no reason for them to be conditional on having a sample.
#
# `scorer_contract` is the deploy discriminator AND the pooling boundary.
# Absent means a build from before 2026-09-01, which is also every build that
# scored totals and spreads against "did the home team win" (see
# `_SCOREABLE_MARKETS`). Bump it when the SCORING RULE or the SHAPE of what
# this module returns changes, not when a number moves -- and never pool the
# accuracy history across a bump (`learnings.md`: a number pooled across a
# scorer boundary measures the fix, not the model).
#
#   1  h2h, totals and spreads all scored against a home win (the defect)
#   2  h2h only; totals/spreads refused by name; quote-age cut  (2026-09-01)
#   3  totals/spreads scored on the POINT FORECAST against the line, with
#      `unmeasured` reasons; segment-aware; cumulative quote-age buckets
#      (2026-09-08). The h2h arithmetic is UNCHANGED from 2, so h2h rows from
#      2 and 3 remain poolable; `point_forecast` exists only from 3.
SCORER_CONTRACT = 3


def scorer_capabilities() -> dict[str, Any]:
    """The invariant facts about this scorer, for stamping on every branch.

    Callers must spread this into the payload on the no-finals and error paths
    too, not only the path that scored something. A branch that omits it is
    indistinguishable from an old deploy.
    """
    return {
        "scorer_contract": SCORER_CONTRACT,
        "scored_markets": sorted(_SCOREABLE_MARKETS),
        "fresh_quote_seconds": FRESH_QUOTE_SECONDS,
        "quote_age_buckets": [name for name, _lo, _hi in _QUOTE_AGE_BUCKETS],
        "quote_age_cumulative_buckets": [name for name, _hi in _CUMULATIVE_QUOTE_AGE_BUCKETS],
        # Contract 3: the line-priced markets and the rule they are scored by.
        "point_forecast_markets": sorted(_POINT_FORECAST_FAMILIES),
        "point_forecast_baseline": POINT_FORECAST_BASELINE,
    }



def _quote_age(value: Any) -> float | None:
    """Seconds, or None. A bool is not a number here."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    age = float(value)
    if age != age or age < 0.0:  # NaN-safe
        return None
    return age



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


def build_final_scores_index(
    grid: Any,
    *,
    sport: Any = None,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, tuple[float, float]]:
    """`game_pk` -> `(away_score, home_score)`, for games FINAL on this grid.

    Keyed on `game_pk` because that is what the ledger stores as its join key.
    `build_finals_index` derives the home-won boolean from this; the scores
    themselves are what totals and spreads are scored on (contract 3), so the
    walk of the grid happens once and both views agree by construction.

    **A LEVEL FINAL MEANS DIFFERENT THINGS IN DIFFERENT SPORTS, AND TREATING IT
    ONE WAY FOR ALL OF THEM SILENTLY DELETED A THIRD OF SOCCER.** This used to
    skip every `h == a` row unconditionally, reasoning that "baseball does not
    tie, so a final with equal scores is a bad row". That is correct FOR MLB and
    wrong for any sport that can draw -- and this function is sport-agnostic and
    serves all of them.

    Measured 2026-08-27 over the retained soccer ledger: **08-22 42 finals of
    which 16 were draws (38%), 08-23 30/5 (17%), 08-24 6/2 (33%)**, and on
    08-24 and 08-26 `games_with_outcome` came out at EXACTLY finals-minus-draws
    (4 and 1). So soccer's model-vs-market Brier was being computed on a
    population **conditioned on the outcome variable itself** -- draws removed
    after the fact, while both the model's and the market's home-win
    probabilities were formed unconditionally. Neither number meant what it
    looked like.

    THE FIX IS NOT "COERCE A WINNER". A draw is not a missing outcome needing a
    guess; for the binary event this scorer measures -- *did the home side win*
    -- a draw is a perfectly well-defined **False**. That is the unbiased
    treatment and the only one that keeps the scoring rule proper. Excluding
    draws is what injected the bias; including them as False removes it without
    inventing anything.

    Where a level final really IS a bad row (baseball), it is still skipped --
    but now it is COUNTED under `finals_skipped_level` instead of vanishing.
    That counter is the whole reason this went unnoticed for as long as it did.

    **AN UNKNOWN SPORT DOES NOT GET THE PERMISSIVE BRANCH.** `sport=None` or a
    sport not in either table is skipped and counted under
    `finals_skipped_level_sport_unknown`, never folded into the draw-bearing
    branch -- calling a level final "not a home win" for a sport that cannot
    draw would fabricate outcomes exactly the way the original comment feared.
    """
    diag = diagnostics if isinstance(diagnostics, dict) else None
    key_sport = str(sport or "").strip().lower()
    draws_are_real = key_sport in DRAW_IS_A_REAL_OUTCOME
    sport_known = key_sport in DRAW_IS_A_REAL_OUTCOME or key_sport in LEVEL_FINAL_IS_A_BAD_ROW
    if diag is not None:
        diag.update({
            "sport": key_sport or None,
            "sport_known": sport_known,
            "draws_scored_as_not_a_home_win": draws_are_real,
            "finals_seen": 0,
            "finals_level": 0,
            "finals_skipped_level": 0,
            "finals_skipped_level_sport_unknown": 0,
            "finals_skipped_no_numeric_score": 0,
            "finals_skipped_no_numeric_score_games": 0,
        })

    out: dict[str, tuple[float, float]] = {}
    # DISTINCT GAMES behind the skipped ROWS. `finals_seen` and `finals_level`
    # count rows, and a row is one market on one game -- 196 rows was ONE game
    # on 2026-08-28. A row count alone therefore cannot answer the only
    # question anyone asks of this block ("how many games did we lose?"), so
    # the games are counted separately rather than left to be inferred from a
    # ratio that does not hold.
    skipped_no_score_games: set[str] = set()
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
            # COUNTED, NOT DROPPED IN SILENCE. This `continue` sits BEFORE
            # `finals_seen` is incremented, so a final with no numeric score
            # used to leave no trace in ANY counter -- and it is the LARGEST
            # cause of a capped `games_with_outcome`, not a rare edge.
            #
            # Measured on production 2026-08-29 (`/api/board/book-grid?
            # sport=mlb&date=2026-08-28`, artifact regenerated 14:31:06Z): the
            # grid carried **15 games, 12 of them `final`, and exactly ONE with
            # numeric scores**. The other 11 were `home_score: None,
            # away_score: None` -- nulled upstream by `game_chip_scoreboard`'s
            # `level_final_impossible_for_sport`, which is CORRECT (a 0-0 MLB
            # "final" is the schedule placeholder) but leaves this scorer with
            # nothing to score. Result: `games_with_outcome: 1`, and 6,137 of
            # 6,466 ledger records reported as `no_final_outcome_for_game`.
            #
            # Every counter that DID exist read healthy at that instant --
            # `finals_seen: 196`, `finals_level: 0`, `finals_skipped_level: 0`,
            # `finals_skipped_level_sport_unknown: 0` -- so the diagnostics
            # pointed at the ledger and the JOIN, which were both fine. The
            # eleven missing games were invisible by construction.
            #
            # This RECOVERS NO GAMES and moves no number: the scores are absent
            # upstream and refusing them is right. It makes the refusal
            # ATTRIBUTABLE from the served payload alone, which is the only
            # reason the cap needed a live investigation to explain at all.
            if diag is not None:
                diag["finals_skipped_no_numeric_score"] = (
                    int(diag["finals_skipped_no_numeric_score"]) + 1
                )
                # Same identifier precedence the index itself uses below, so a
                # game counted here is one that COULD have been indexed. A row
                # carrying no identifier at all is still counted as a skipped
                # ROW -- it is one -- but cannot be attributed to a game, and
                # inventing a key for it would inflate the game count.
                lg_skipped = (
                    row.get("live_gameline")
                    if isinstance(row.get("live_gameline"), Mapping)
                    else {}
                )
                for ident in (
                    row.get("game_pk"),
                    game.get("game_pk"),
                    lg_skipped.get("game_pk"),
                    row.get("event_id"),
                    game.get("event_id"),
                ):
                    ident_key = str(ident or "").strip()
                    if ident_key:
                        skipped_no_score_games.add(ident_key)
                        break
            continue
        if diag is not None:
            diag["finals_seen"] = int(diag["finals_seen"]) + 1
        if h == a:
            if diag is not None:
                diag["finals_level"] = int(diag["finals_level"]) + 1
            if not draws_are_real:
                if diag is not None:
                    reason = ("finals_skipped_level" if sport_known
                              else "finals_skipped_level_sport_unknown")
                    diag[reason] = int(diag[reason]) + 1
                continue
        # INDEX UNDER EVERY IDENTIFIER THE ROW CARRIES, because the ledger and
        # the grid do not agree on one.
        #
        # Measured in production 2026-08-17 01:48Z, and this is exactly the
        # failure the `unscored` counter exists to expose: **3,706 records
        # considered, 0 games with an outcome, 3,706 `no_final_outcome_for_game`**
        # — while 14 games sat FINAL on that same grid. The ledger stores
        # `game_pk` (taken from the live_gameline block), but a grid ROW has no
        # `game_pk` at top level: it lives inside `row["live_gameline"]`. So a
        # `game_pk`-keyed lookup against an `event_id`-keyed index missed every
        # single record, and reported it as "no outcome" rather than silently
        # scoring nothing.
        lg = row.get("live_gameline") if isinstance(row.get("live_gameline"), Mapping) else {}
        for ident in (
            row.get("game_pk"),
            game.get("game_pk"),
            lg.get("game_pk"),
            row.get("event_id"),
            game.get("event_id"),
        ):
            key = str(ident or "").strip()
            if key:
                out[key] = (a, h)
    if diag is not None:
        # NOT the raw set: a game can be skipped for want of a score on one row
        # and indexed from another, and it is not "lost" in that case. Reported
        # net of what actually made it into the index, so this number always
        # means "games this scorer could not score BECAUSE no score was
        # published" -- which is the number that explains a capped
        # `games_with_outcome` and the one a reader will subtract.
        diag["finals_skipped_no_numeric_score_games"] = len(
            skipped_no_score_games - set(out)
        )
    return out


def finals_from_scores(scores: Mapping[str, tuple[float, float]]) -> dict[str, bool]:
    """The home-won view of a scores index. A level score is False, and it is
    only present at all for sports where `build_final_scores_index` admitted it
    (draw-bearing), so the draw rule lives in one place."""
    return {key: h > a for key, (a, h) in scores.items()}


def build_finals_index(
    grid: Any,
    *,
    sport: Any = None,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, bool]:
    """`game_pk` -> did HOME win, for games that are FINAL on this grid.

    The h2h view. Every rule about which finals are admitted -- level finals,
    unknown sports, missing scores, the identifier precedence -- is documented
    on `build_final_scores_index`, which this derives from.
    """
    return finals_from_scores(
        build_final_scores_index(grid, sport=sport, diagnostics=diagnostics)
    )


def _score(pairs: list[tuple[float, bool]]) -> dict[str, Any]:
    """Brier and MAE over (probability, outcome). Empty is None, never 0.0."""
    if not pairs:
        return {"brier": None, "mae": None, "n": 0}
    briers = [(p - (1.0 if won else 0.0)) ** 2 for p, won in pairs]
    maes = [abs(p - (1.0 if won else 0.0)) for p, won in pairs]
    n = len(pairs)
    return {"brier": round(sum(briers) / n, 5), "mae": round(sum(maes) / n, 5), "n": n}


def _finite_number(value: Any) -> float | None:
    """A finite float, or None. A bool is not a number; a numeric string is.

    Strings are admitted because `line` reaches the ledger from the grid row
    verbatim and the harness this mirrors (`point_forecast_side`) accepts them
    -- refusing "9.5" here would read as an unfed line on a row that has one.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if not isinstance(value, (int, float)):
        return None
    x = float(value)
    if x != x or x in (float("inf"), float("-inf")):  # NaN-safe
        return None
    return x


def _score_pair(value: Any) -> tuple[float, float] | None:
    """`(away, home)` as finite floats, or None."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    away, home = _finite_number(value[0]), _finite_number(value[1])
    if away is None or home is None:
        return None
    return away, home


def _segment_of(rec: Mapping[str, Any]) -> str:
    """The row's segment token, `full` when absent or blank."""
    return str(rec.get("segment") or "full").strip().lower() or "full"


def _as_segment_lookup(segment_actuals: Any) -> SegmentActualLookup | None:
    """Normalise the caller's reader to the callable form, or None."""
    if segment_actuals is None:
        return None
    if callable(segment_actuals):
        return segment_actuals
    if isinstance(segment_actuals, Mapping):
        table = segment_actuals
        return lambda key, segment: table.get((key, segment))
    raise TypeError(
        "segment_actuals must be a callable (game_key, segment) -> (away, home), "
        f"a Mapping keyed by that pair, or None; got {type(segment_actuals).__name__}"
    )


def _segment_actual(
    lookup: SegmentActualLookup | None, idents: list[str], segment: str
) -> tuple[float, float] | None:
    """The segment's (away, home), trying every identifier -- never `a or b`."""
    if lookup is None:
        return None
    for ident in idents:
        pair = _score_pair(lookup(ident, segment))
        if pair is not None:
            return pair
    return None


def _directional(obs: list[dict[str, Any]]) -> dict[str, Any]:
    """The point-forecast block over observations. Empty is None, never 0.0.

    `hit_rate` against `POINT_FORECAST_BASELINE`, with the standard error
    computed ON GAMES, not rows. The ledger writes a row per build per line
    per book set -- 42,692 MLB rows over ten days were 122 games, a median of
    334 rows per game -- and treating rows as independent understated sigma by
    ~18x and produced a "+14.63pp at +21 sigma" result that is impossible on
    its face (`bucket_realised_performance.py`). `n` is still the row count,
    because it is honest about what was averaged; `games` is the denominator
    a reader may quote a sigma on.

    `model_mae` / `line_mae` are the point errors themselves: whether the
    model's mean sat closer to the actual than the line did, on the same rows.
    NEGATIVE `model_minus_line_mae` means the model was closer.
    """
    n = len(obs)
    if not n:
        return {
            "n": 0, "games": 0, "hits": 0, "hit_rate": None,
            "baseline": POINT_FORECAST_BASELINE,
            "model_minus_baseline_pp": None, "se_pp_on_games": None,
            "model_mae": None, "line_mae": None, "model_minus_line_mae": None,
        }
    hits = sum(1 for o in obs if o["hit"])
    games = len({o["game"] for o in obs})
    rate = hits / n
    se = math.sqrt(max(rate * (1.0 - rate), 1e-9) / max(games, 1))
    model_mae = sum(o["model_abs_err"] for o in obs) / n
    line_mae = sum(o["line_abs_err"] for o in obs) / n
    return {
        "n": n,
        "games": games,
        "hits": hits,
        "hit_rate": round(rate, 5),
        "baseline": POINT_FORECAST_BASELINE,
        # POSITIVE means the model's side of the line landed more often than
        # the coin flip the book priced it as. Named in full so nobody has to
        # guess the sign.
        "model_minus_baseline_pp": round((rate - POINT_FORECAST_BASELINE) * 100.0, 3),
        "se_pp_on_games": round(se * 100.0, 3),
        "model_mae": round(model_mae, 5),
        "line_mae": round(line_mae, 5),
        "model_minus_line_mae": round(model_mae - line_mae, 5),
    }


def _point_forecast_block(obs: list[dict[str, Any]]) -> dict[str, Any]:
    """One family's (totals or spreads) populations, same cuts as h2h."""
    last: dict[tuple[str, str], dict[str, Any]] = {}
    for o in obs:
        k = (o["game"], o["segment"])
        prev = last.get(k)
        if prev is None or o["stamp"] >= prev["stamp"]:
            last[k] = o
    aged = [o for o in obs if o["age"] is not None]
    by_segment: dict[str, int] = {}
    for o in obs:
        by_segment[o["segment"]] = by_segment.get(o["segment"], 0) + 1
    return {
        "all_records": _directional(obs),
        "last_per_game": _directional(list(last.values())),
        "priceable_only": _directional([o for o in obs if o["priceable"]]),
        "fresh_quotes_only": _directional([o for o in aged if o["age"] <= FRESH_QUOTE_SECONDS]),
        "by_quote_age": {
            name: _directional([o for o in aged if lo <= o["age"] < hi])
            for name, lo, hi in _QUOTE_AGE_BUCKETS
        },
        "by_quote_age_cumulative": {
            name: _directional(obs if hi == float("inf") else [o for o in aged if o["age"] <= hi])
            for name, hi in _CUMULATIVE_QUOTE_AGE_BUCKETS
        },
        "quote_age_absent": len(obs) - len(aged),
        "games_with_outcome": len({o["game"] for o in obs}),
        "records_by_segment": by_segment,
    }


def score_ledger_records(
    records: Any,
    finals: Mapping[str, bool],
    *,
    final_scores: Mapping[str, tuple[float, float]] | None = None,
    segment_actuals: Any = None,
) -> dict[str, Any]:
    """Score model vs market over ledger records whose game has an outcome.

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

    TWO SCORING RULES, ONE PER KIND OF MARKET (contract 3):

      h2h             `finals` answers "did the home side win" and only h2h
                      carries a probability that answers it. Model and market
                      probabilities are Brier-scored on identical rows. This
                      path is byte-for-byte the contract-2 rule.
      totals/spreads  `final_scores` supplies `(away, home)` and the model's
                      POINT FORECAST is scored against the LINE on the actual
                      total / margin, baseline 0.50. See `_POINT_FORECAST_FAMILIES`
                      for why a probability comparison is refused for these. A
                      caller that passes only `finals` gets every such row
                      UNMEASURED under `no_final_score_for_game` -- never a
                      probability comparison as a substitute.

    SEGMENTS. A row whose `segment` is not `full` is resolved ONLY through
    `segment_actuals` (see `SegmentActualLookup`); with no reader it is
    UNMEASURED under `segment_actual_unavailable`. It is never graded against
    the full-game final.

    `unscored` carries the h2h refusals (unchanged names); `unmeasured` carries
    the point-forecast and segment ones. Both are counts by reason, so "we
    could not measure" never looks like "the model was wrong".
    """
    model_all: list[tuple[float, bool]] = []
    market_all: list[tuple[float, bool]] = []
    model_all_paired: list[tuple[float, bool]] = []
    model_priceable: list[tuple[float, bool]] = []
    market_priceable: list[tuple[float, bool]] = []
    model_priceable_paired: list[tuple[float, bool]] = []
    last: dict[tuple[str, str], tuple[str, float, float | None, bool]] = {}
    unscored: dict[str, int] = {}
    unmeasured: dict[str, int] = {}
    # THE MIX, REPORTED RATHER THAN INFERRED. The defect this module now refuses
    # was invisible for weeks precisely because nothing said which markets the
    # sample was made of -- the headline Brier looked like a model-vs-market
    # result and was 5/6 something else. Counted over records that reached the
    # market branch (i.e. already have an outcome), so it describes the
    # scoreable population, not the raw file.
    by_market: dict[str, int] = {}
    # --- THE FRESH-QUOTE CUT AND THE AGE MIX (see `FRESH_QUOTE_SECONDS`) ---
    model_fresh: list[tuple[float, bool]] = []
    market_fresh: list[tuple[float, bool]] = []
    model_fresh_paired: list[tuple[float, bool]] = []
    # bucket -> [model pairs, market pairs, model-paired pairs]
    age_buckets: dict[str, list[list[tuple[float, bool]]]] = {
        name: [[], [], []] for name, _lo, _hi in _QUOTE_AGE_BUCKETS
    }
    # (age or None, model_p, market_p or None, won) -- the cumulative view.
    h2h_rows: list[tuple[float | None, float, float | None, bool]] = []
    quote_age_absent = 0
    considered = 0
    # --- the point-forecast families ---
    scores: Mapping[str, tuple[float, float]] = (
        final_scores if isinstance(final_scores, Mapping) else {}
    )
    lookup = _as_segment_lookup(segment_actuals)
    pf_obs: dict[str, list[dict[str, Any]]] = {fam: [] for fam in _POINT_FORECAST_FAMILIES}

    def _bump(table: dict[str, int], reason: str) -> None:
        table[reason] = table.get(reason, 0) + 1

    for rec in records if isinstance(records, (list, tuple)) else []:
        if not isinstance(rec, Mapping):
            continue
        considered += 1
        # TRY EVERY IDENTIFIER, never `a or b`. That short-circuit was the second
        # half of the same join failure and it survived the first fix.
        #
        # A ledger record is written while the game is LIVE, so it carries
        # `game_pk` (lifted from the live_gameline block) AND `event_id`. A row
        # that has since gone FINAL carries no live_gameline at all -- the live
        # join refuses final games -- so it is indexed under `event_id` only.
        # With `game_pk or event_id` the record's non-empty `game_pk` won,
        # `event_id` was never tried, and all 3,727 records missed an index that
        # genuinely contained their game. Measured 02:01Z, after the first fix.
        idents = [
            k for k in (str(rec.get("game_pk") or "").strip(), str(rec.get("event_id") or "").strip())
            if k
        ]
        # ABSENT IS NOT h2h. An unrecognised or missing `market` takes the
        # REFUSING branch, never a scoring one: mapping unknown onto the
        # permissive side is what turns a failed classification into a silently
        # relaxed rule. Every ledger record written by `build_records` carries
        # `market`, so a null here is a real anomaly and is counted as one.
        market_key = str(rec.get("market") or "").strip().lower()
        family = _POINT_FORECAST_FAMILY_BY_MARKET.get(market_key)
        segment = _segment_of(rec)
        stamp = str(rec.get("recorded_at") or "")

        # ================= LINE-PRICED MARKETS: the POINT FORECAST =============
        if family is not None:
            col, actual_fn = _POINT_FORECAST_FAMILIES[family]
            if segment == "full":
                key = next((k for k in idents if k in finals or k in scores), "")
                if not key:
                    _bump(unmeasured, _UNMEASURED_NO_FINAL)
                    continue
                by_market[market_key] = by_market.get(market_key, 0) + 1
                pair = _score_pair(scores.get(key))
                if pair is None:
                    _bump(unmeasured, _UNMEASURED_NO_FINAL_SCORE)
                    continue
            else:
                pair = _segment_actual(lookup, idents, segment)
                if pair is None:
                    _bump(unmeasured, _UNMEASURED_SEGMENT_ACTUAL_UNAVAILABLE)
                    continue
                key = idents[0]
                by_market[market_key] = by_market.get(market_key, 0) + 1
            mean = _finite_number(rec.get(col))
            if mean is None:
                _bump(unmeasured, _UNMEASURED_NO_MEAN)
                continue
            line = _finite_number(rec.get("line"))
            if line is None:
                _bump(unmeasured, _UNMEASURED_NO_LINE)
                continue
            away, home = pair
            actual = actual_fn(away, home)
            if actual == line:
                _bump(unmeasured, _UNMEASURED_PUSH)
                continue
            if abs(mean - line) < 1e-9:
                _bump(unmeasured, _UNMEASURED_NO_LEAN)
                continue
            pf_obs[family].append({
                "hit": (mean > line) == (actual > line),
                "game": key,
                "segment": segment,
                "stamp": stamp,
                "priceable": bool(rec.get("priceable")),
                "age": _quote_age(rec.get("quote_age_seconds")),
                "model_abs_err": abs(mean - actual),
                "line_abs_err": abs(line - actual),
            })
            continue

        # ================= h2h: the PROBABILITY comparison (contract 2) ========
        if segment == "full":
            key = next((k for k in idents if k in finals), "")
            if not key:
                unscored[_UNSCORED_NO_OUTCOME] = unscored.get(_UNSCORED_NO_OUTCOME, 0) + 1
                continue
            won: bool | None = bool(finals[key])
        else:
            # An unknown market on a segment row is still an unknown market;
            # classify it BEFORE asking a reader for an actual it cannot use.
            if market_key not in _SCOREABLE_MARKETS:
                unscored[_UNSCORED_MARKET_UNKNOWN] = unscored.get(_UNSCORED_MARKET_UNKNOWN, 0) + 1
                by_market[market_key or "<absent>"] = by_market.get(market_key or "<absent>", 0) + 1
                continue
            pair = _segment_actual(lookup, idents, segment)
            if pair is None:
                _bump(unmeasured, _UNMEASURED_SEGMENT_ACTUAL_UNAVAILABLE)
                continue
            key = idents[0]
            # A level segment is a real state of the game and NOT a home win;
            # but a segment moneyline is graded as a push on it, so it is not
            # an observation of this probability either. Counted, not scored.
            won = None if pair[1] == pair[0] else pair[1] > pair[0]
        model_p = _finite_prob(rec.get("model_home_win_prob"))
        if model_p is None:
            unscored[_UNSCORED_NO_MODEL_PROB] = unscored.get(_UNSCORED_NO_MODEL_PROB, 0) + 1
            continue
        # THE PROBABILITY MUST DESCRIBE THE OUTCOME WE HOLD. `finals` answers
        # exactly one question -- did the home side win -- so only a market whose
        # probability answers that question may be scored against it. See
        # `_SCOREABLE_MARKETS`.
        if market_key not in _SCOREABLE_MARKETS:
            unscored[_UNSCORED_MARKET_UNKNOWN] = unscored.get(_UNSCORED_MARKET_UNKNOWN, 0) + 1
            by_market[market_key or "<absent>"] = by_market.get(market_key or "<absent>", 0) + 1
            continue
        by_market[market_key] = by_market.get(market_key, 0) + 1
        if won is None:
            _bump(unmeasured, _UNMEASURED_SEGMENT_LEVEL)
            continue
        market_p = _finite_prob(rec.get("market_fair_prob"))

        model_all.append((model_p, won))
        if market_p is not None:
            market_all.append((market_p, won))
            # THE MODEL, ON EXACTLY THE ROWS THE MARKET IS SCORED ON. See
            # `_paired` below for why the difference cannot use `model_all`.
            model_all_paired.append((model_p, won))
        if bool(rec.get("priceable")):
            model_priceable.append((model_p, won))
            if market_p is not None:
                market_priceable.append((market_p, won))
                model_priceable_paired.append((model_p, won))
        # AGE-STRATIFIED, over the same rows the populations above use. Kept
        # separate from `priceable` on purpose: freshness is a property of the
        # PRICE and priceability is a property of the EDGE, and conflating them
        # is how the pooled number came to describe neither.
        age = _quote_age(rec.get("quote_age_seconds"))
        h2h_rows.append((age, model_p, market_p, won))
        if age is None:
            quote_age_absent += 1
        else:
            if age <= FRESH_QUOTE_SECONDS:
                model_fresh.append((model_p, won))
                if market_p is not None:
                    market_fresh.append((market_p, won))
                    model_fresh_paired.append((model_p, won))
            for name, lo, hi in _QUOTE_AGE_BUCKETS:
                if lo <= age < hi:
                    age_buckets[name][0].append((model_p, won))
                    if market_p is not None:
                        age_buckets[name][1].append((market_p, won))
                        age_buckets[name][2].append((model_p, won))
                    break
        # LATEST record per game, chosen by `recorded_at` rather than by file
        # order. The ledger is append-only so the two normally agree -- but
        # "normally" is not a guarantee, and a merged or re-pulled file would
        # silently make file order mean nothing. `recorded_at` is ISO-8601 UTC,
        # so lexical comparison IS chronological. Keyed per (game, segment) so
        # a first-five moneyline can never be "the last word" on the full game.
        prev = last.get((key, segment))
        if prev is None or stamp >= prev[0]:
            last[(key, segment)] = (stamp, model_p, market_p, won)

    model_last = [(p, w) for _s, p, _m, w in last.values()]
    market_last = [(m, w) for _s, _p, m, w in last.values() if m is not None]
    model_last_paired = [(p, w) for _s, p, m, w in last.values() if m is not None]

    def _delta(a: dict[str, Any], b: dict[str, Any]) -> float | None:
        if a.get("brier") is None or b.get("brier") is None:
            return None
        return round(a["brier"] - b["brier"], 5)

    def _paired(model_full: dict[str, Any], model_pair: dict[str, Any],
                market: dict[str, Any]) -> dict[str, Any]:
        """One population's block, with the DIFFERENCE taken pairwise.

        **THE DIFFERENCE MUST NOT USE `model`.** A record carries
        `model_home_win_prob` whenever it is scored at all, but `market_fair_prob`
        can be absent -- so the market list is a SUBSET of the model list, and
        subtracting their Briers spans two different row sets. Measured
        2026-08-27 on pooled MLB `last_per_game`: **model n 94 vs market n 90**,
        a difference of +0.11825 that described no population at all. The module
        docstring had promised the opposite in bold ("both are scored on exactly
        the same rows") and `all_records` had ALREADY been caught doing this at
        1526 vs 1449 and written off as "UNSOUND" rather than fixed.

        `priceable_only` looked immune -- 25,504/25,504 -- but it has the same
        shape and was matched only because priceable rows happen to carry a
        price. That is a property of the data, not a guarantee, so it is paired
        here too rather than trusted.

        `model` is kept unchanged: the model's score over ALL its rows is a real
        quantity and dropping it would lose information. It simply is not the
        term the difference is entitled to use.
        """
        block = {
            "model": model_full,
            "market": market,
            "model_paired": model_pair,
            # The exclusion, COUNTED. Nothing counted it, which is why "n 94 vs
            # 90" had to be spotted by eye in a printout.
            "rows_without_market_prob": max(0, int(model_full.get("n") or 0) - int(market.get("n") or 0)),
            "populations_matched": (model_pair.get("n") or 0) == (market.get("n") or 0),
            # NEGATIVE means the model beat the market. Named in full rather
            # than as "skill" so nobody has to guess the sign.
            "model_minus_market_brier": _delta(model_pair, market),
        }
        return block

    def _paired_rows(rows: list[tuple[float | None, float, float | None, bool]]) -> dict[str, Any]:
        return _paired(
            _score([(p, w) for _a, p, _m, w in rows]),
            _score([(p, w) for _a, p, m, w in rows if m is not None]),
            _score([(m, w) for _a, _p, m, w in rows if m is not None]),
        )

    all_model, all_market = _score(model_all), _score(market_all)
    lp_model, lp_market = _score(model_last), _score(market_last)
    pr_model, pr_market = _score(model_priceable), _score(market_priceable)
    all_model_pair = _score(model_all_paired)
    lp_model_pair = _score(model_last_paired)
    pr_model_pair = _score(model_priceable_paired)

    return {
        "records_considered": considered,
        # h2h games, as it always was: this is the denominator the retained
        # history pools on, and the point-forecast families report their own.
        "games_with_outcome": len({game for game, _seg in last}),
        "unscored": unscored,
        "unmeasured": unmeasured,
        # Which markets the scoreable population was made of. `scored_markets`
        # is the set admitted to the PROBABILITY comparison and
        # `point_forecast_markets` the families scored on the LINE, so a reader
        # never has to know either table to interpret the number.
        "records_by_market": by_market,
        "scored_markets": sorted(_SCOREABLE_MARKETS),
        "point_forecast_markets": sorted(_POINT_FORECAST_FAMILIES),
        "segment_actuals_supplied": lookup is not None,
        "all_records": _paired(all_model, all_model_pair, all_market),
        "last_per_game": _paired(lp_model, lp_model_pair, lp_market),
        "priceable_only": _paired(pr_model, pr_model_pair, pr_market),
        # THE POPULATION A MODEL CLAIM MUST BE MADE ON. Listed after the
        # others rather than replacing them: `all_records` is still the honest
        # description of every row the ledger holds, it just answers a question
        # nobody is betting on.
        "fresh_quotes_only": _paired(
            _score(model_fresh), _score(model_fresh_paired), _score(market_fresh)
        ),
        "fresh_quote_seconds": FRESH_QUOTE_SECONDS,
        "quote_age_absent": quote_age_absent,
        "by_quote_age": {
            name: _paired(_score(b[0]), _score(b[2]), _score(b[1]))
            for name, b in age_buckets.items()
        },
        "by_quote_age_cumulative": {
            name: _paired_rows(
                h2h_rows if hi == float("inf")
                else [r for r in h2h_rows if r[0] is not None and r[0] <= hi]
            )
            for name, hi in _CUMULATIVE_QUOTE_AGE_BUCKETS
        },
        # THE LINE-PRICED MARKETS. Each family carries the same cuts as h2h
        # above, scored by `_directional` -- hit rate against the 0.50 the
        # book priced, and the point error against the line's own.
        "point_forecast": {
            "rule": "model mean vs line on the actual total/margin; push dropped",
            "baseline": POINT_FORECAST_BASELINE,
            "independent_unit": "games",
            **{fam: _point_forecast_block(obs) for fam, obs in pf_obs.items()},
        },
    }
