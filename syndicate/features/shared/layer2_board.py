"""L2-A candidate builder — turns the Layer 1 market grid into ranked bets.

**A WORKER-SIDE BUILDER. It must not be called from a request path.** Its output
belongs in an artifact that web reads; see the integration note at the bottom.
That is CLAUDE.md's load-bearing rule (web reads precomputed artifacts, workers
compute), and `_build_candidate_pool` already enforces it with
`refuse_if_compute_in_request_path`.

There is a second reason, specific to Layer 2 and arguably stronger: **a board
computed per request cannot be settled.** S6 needs a record of what was
recommended and at what price. Recompute it on every read and there is nothing
to grade against, so `settled: 0` stays 0 structurally rather than for want of a
settlement run.

WHY THIS EXISTS. Plan §3 is one row contract, five views. Layer 2 built its own
candidate pool while Layer 1 built a much better one, and they disagreed badly —
measured on production 2026-08-07, MLB:

    Layer 1   2,726 priced market instances   (1,221 prop rows with books)
    Layer 2     229 game candidates           (   18 prop rows)

L2's prop lane saw **18 rows against L1's 1,221**. Not stale — starved. And
props are where the sim differentiates us and where 95.5% of OddsAPI spend goes.

A ROW HERE IS A BET, NOT A MARKET. The grid row holds every side; Layer 2 ranks
one side at a time, because that is the thing you can actually place. So each
grid row fans out to at most one candidate per side.

WHAT IS NOT SOLVED HERE, stated so nobody reads a ranked board as a validated
one: `_SCORE_SIM_WEIGHT = 0.5` is a stated prior nobody has measured, and
`settled: 0` means it has never been checked against outcomes. This makes the
board *flow* and be *correct*; S6 is what would make it *proven*.

INTEGRATION (not yet wired — deliberately):
    `_build_candidate_pool` in `pipeline/intelligence_state.py` is where these
    rows belong, so they flow into the existing state artifact that web already
    reads via `read_intelligence_board_state`. That function is also the exact
    path that OOM-killed refresh-worker repeatedly, so feeding it a much larger
    row set is a memory change and must be measured, not assumed. Build first,
    measure, then wire.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from syndicate.features.shared import opportunity_gate
from syndicate.features.shared.book_margin_model import market_family as _market_family
from syndicate.features.shared.opportunity_signals import (
    american_price,
    blended_score,
    consensus_fair_probability,
    devig,
    expected_value_pct,
)

# Identity carried from the market row onto every candidate. Kept explicit
# rather than copying the whole row: the grid row holds `cells` (every book x
# every side), which is large and has no business in a shortlist payload.
def _side_line_from_cells(row: Mapping[str, Any], side: str) -> float | None:
    """The handicap THIS side is actually priced at, read off the book cells.

    Returns None when the cells cannot answer — no cells, no line on them, or
    the books disagree — so the caller keeps the row's own value rather than
    substituting a guess. Books disagreeing is a real production condition
    (`board_cross_book._complementary` documents it from 2026-08-07,
    `spreads_alt`: betmgm quoting `away -1.5` against betrivers' `away +1.5`),
    and it did NOT occur in the 525 cells measured on 2026-08-15 — but a silent
    majority-vote across a genuine disagreement would be exactly the kind of
    quiet wrong number this module refuses elsewhere.
    """
    values: set[float] = set()
    for cell in (row.get("cells") or {}).values():
        if not isinstance(cell, Mapping):
            continue
        leg = cell.get(side)
        if not isinstance(leg, Mapping):
            continue
        raw = leg.get("line")
        if raw is None:
            continue
        try:
            values.add(float(raw))
        except (TypeError, ValueError):
            continue
    if len(values) != 1:
        return None
    return next(iter(values))


# Identity carried from the market row onto every candidate. `line` is
# OVERWRITTEN per side below -- see `_side_line_from_cells`.
_IDENTITY_FIELDS = (
    "sport",
    "event_id",
    "kind",
    "market",
    "segment",
    "line",
    "player_name",
    "home_team",
    "away_team",
    "commence_time",
)


# The persisted SHORTLIST, per sport. Not a memory bound -- a readability one.
#
# Sized against measurement, and the headroom is deliberate: ~1.0 KB per row
# (11MB / 10,765 rows measured on production 2026-08-07), so 50 rows is ~50 KB
# per sport. Every one of the eight sports is never in season at once -- four
# had a slate on the day this was written -- so the realistic persisted cost is
# ~400 KB against a 2.4 MB state and a 24 MB export budget. An out-of-season
# sport contributes no rows and therefore no budget, automatically -- which is
# what buys the headroom for 100 rather than 50.
#
# NAMED FOR THE JOB IT DOES, per post-mortem rule 9: this bounds HOW MANY ROWS A
# PERSON READS. It is not a memory ceiling, and it must not be reused as one --
# `_MLB_CARDS_CONTEXT_CACHE_MAX_ENTRIES` bounded count while the caller needed
# bytes, and that was invisible for three weeks. The writer logs the bytes it
# actually persisted so the real constraint stays observable.
SHORTLIST_ROWS_PER_SPORT = 100

# Each kind is guaranteed this many slots before merit takes over.
#
# A pure score ranking would not mix: MLB carries 1,221 prop rows against 229
# game rows, so props would plausibly take all 50 and the game board would
# vanish. A hard 25/25 is the opposite error -- it would drop a clearly better
# prop to seat a worse game line. Floor-then-merit gets the mix without paying
# for it in quality, and an unused floor flows to the other kind rather than
# being wasted on a sport that has only one.
SHORTLIST_KIND_FLOOR = 30

# Most rows any ONE game may contribute. Env: SYNDICATE_SHORTLIST_ROWS_PER_GAME.
#
# 6, sized off the measured concentration: on the 200-row served board of
# 2026-08-12 the top game held 26 rows while 36 games shared 200 slots -- an even
# split is 5.6. So 6 lets a genuinely rich game run slightly ahead of average and
# makes a 26-row takeover impossible. 0 disables the cap.
SHORTLIST_ROWS_PER_GAME = 6

# Market substrings never seated on the shortlist. Env:
# SYNDICATE_SHORTLIST_EXCLUDED_MARKETS (comma-separated), empty string disables.
#
# **GOALSCORER PROPS, and this is a product decision rather than a defect fix.**
# Measured on the served board 2026-08-12: soccer contributed 100 of 200 sampled
# rows -- the largest single block -- and EVERY one was
# `player_first_goal_scorer` (45) or `player_last_goal_scorer` (55). Nothing
# else from the sport reached the board.
#
# They are structurally unfit for an ACTIONABLE board, for three reasons that
# compound:
#   1. One-sided by construction. A book quotes "will X score first" at +7000
#      and posts no opposing side, so there is no two-sided price to de-vig and
#      `#384`'s consensus path cannot run. All 100 fell back to
#      `book_margin_model` -- an ESTIMATE from a market-wide median hold.
#   2. That hold is measured mostly on moneylines and totals. Applying it to a
#      100:1 longshot is the least defensible use of the margin model;
#      `book_margin_model`'s own docstring notes a 4.5% moneyline hold and 12%
#      prop hold are both ordinary.
#   3. Uniformly negative EV. The whole family sat at roughly -6.9 with a 1.6
#      point spread, so it was never ranked ON merit -- it filled soccer's
#      per-sport allocation because nothing else qualified.
#
# `#391` caps any one GAME at 6 rows. Nothing capped a market FAMILY, which is
# how one prop type took half the board. Substring match, so `first`, `last` and
# `anytime` variants are all covered by one rule.
SHORTLIST_EXCLUDED_MARKETS = "goal_scorer"


# Minimum value% a row must carry to be shown. Env:
# SYNDICATE_SHORTLIST_MIN_VALUE_PCT.
#
# **A JUNK FILTER, NOT A VALUE GATE.** It exists to drop rows priced materially
# worse than a normal market, and nothing more. The board RANKS by score; the
# floor's only job is to stop floor-then-merit seating garbage, because
# `per_sport` and `kind_floor` guarantee slots get filled whether or not
# anything deserves them.
#
# **-2.0, AND 0.0 WAS WRONG.** `ev_pct` is measured against the consensus no-vig
# fair, so for any market where the book holds a margin it is
# `1/overround - 1` -- NEGATIVE on every side. A realistic 3-book market
# (-120/+105, -115/+100, -125/+110) scores **-1.0953 on BOTH sides**. A floor at
# 0.0 therefore rejects every normally-priced market and keeps only rows where
# cross-book dispersion beats consensus, silently converting the board from
# "ranked opportunities" into a line-shopping screen. It shipped at 0.0 and did
# exactly that (200 rows -> 103), and broke six wiring tests with `0 == 2`,
# which read like a broken join.
#
# That is also the SEMANTIC objection `65b15a03` raised when it withdrew an
# earlier `ev_pct >= 0` proposal -- "positive EV" is not what this quantity
# means. Its PLACEMENT objection is answered by living here, in selection on the
# display artifact, rather than in `opportunity_gate` (whose job `#245` fixed as
# "is this market live"); the ledger still carries every gated row for S6, so
# nothing is withheld from settlement by not displaying it.
#
# Sized from the served board, 2026-08-08, 200 rows before filtering:
#
#     p10 -7.120   p25 -5.700   p50 -0.666   p75 +1.118   p100 +4.243
#     healthy 3-book market: -1.095
#
# There is a real gap between -2 and -3 (3 rows), so -2.0 sits about one point
# below normal pricing and cuts the p25-and-below junk. Rows kept: 122 of 200 at
# -2.0, against 95 at 0.0 and 147 at -5.0. The TOP of the board is unaffected at
# any of these -- ranking is by score, and the excluded rows were never near it.
#
# **KNOWN BIAS, not yet fixed:** one global floor is sport-dependent, because
# natural hold is. Soccer's 3-way markets hold more than MLB's 2-way, so soccer
# rows sit legitimately lower -- soccer contributes 3 rows at -2.0 and 24 at
# -5.0. A per-sport floor derived from each sport's measured hold is the correct
# shape; see `#268`.
SHORTLIST_MIN_VALUE_PCT = -2.0

# Reject a row this long past its own commence_time when nothing can confirm the
# game is still live. Env: SYNDICATE_SHORTLIST_STALE_KICKOFF_SECONDS.
#
# **A market cannot be "pregame" after its own start time.** `opportunity_gate`'s
# dead-market rule is the real defence, but it is gated on `game.state`, and for
# nine of the ten soccer leagues that state is PERMANENTLY `pregame`:
# `_unsimulated_game` (`soccer/cards.py`) defaults `status_state` to `"pre"`, and
# fixtures come from the static season schedule which carries no live status.
# Only the SIMULATED path stamps a real status, and the sim runs for MLS alone.
# So the gate cannot fire, at any hour, for those leagues.
#
# Measured on the served board 2026-08-08 19:53Z: the **#1 and #2 ranked rows**
# were a match that kicked off **5.47 hours earlier**, still labelled `pregame`
# with `game.state: None`. A settled market ranked first. That is the
# "confident nonsense" failure `65b15a03` warns is worse than an empty board.
#
# This is a BACKSTOP, not a replacement for the gate. It fires only when the
# state is unusable, so it cannot mask a working `game.state`:
#   * a row with a real state (live/final) is left entirely to the gate
#   * MLB carries real state, so rain delays keep being handled properly there
#   * only rows with NO state evidence and a start time well past are dropped
#
# 2h is chosen to survive a delayed start in a sport that publishes no state,
# while still catching this case an order of magnitude over. It would have
# rejected the 5.47h match immediately.
SHORTLIST_STALE_KICKOFF_SECONDS = 2 * 3600

# Maximum book-clock age a quote may carry. Env:
# SYNDICATE_SHORTLIST_MAX_QUOTE_AGE_SECONDS.
#
# **DELIBERATELY LOOSE, AND THE DEFAULT IS NOT THE INTERESTING NUMBER.** The
# measurement that set it, same 200 rows:
#
#     mlb     n=100  min=11.46h  med=11.46h  max=11.48h   <- 1.2-minute spread
#     wnba    n= 36  min=12.47h  med=12.98h  max=13.00h
#     soccer  n= 64  min= 1.85h  med= 5.88h  max=22.20h   <- a real spread
#
# 100 MLB quotes did not independently stop moving inside the same 1.2 minutes.
# That is ONE capture event ~11.5h stale, not 100 stable markets, and the board
# is reading quotes far older than the odds file we know exists. A floor tight
# enough to act on that (<=6h) leaves **3 of 200 rows** and deletes two sports,
# so it would hide the symptom by emptying the board rather than fix the lag.
#
# So this is a backstop against genuinely dead quotes, NOT the instrument for
# the staleness problem -- `_freshness_factor` already discounts age
# multiplicatively in the score, which is the right shape while the cause is
# unknown. Tighten it only after the uniform-lag question is answered. Cost of
# each value, measured: <=12h keeps 142, <=6h keeps 37, <=4h keeps 13.
# FOURTEEN HOURS. Was 24h (a gate that never fired), then 1h for ~18 hours
# (`#371`), now 14h (`#380`, user decision).
#
# **THE 1h CEILING DELETED WHOLE SPORTS, AND THE TABLE ABOVE PREDICTED IT.**
# Read the per-sport minima again: mlb 11.46h, wnba 12.47h, soccer 1.85h. Those
# are MINIMA. Every sport's FRESHEST quote already exceeded a 1-hour ceiling, so
# for any sport whose capture cadence is slower than an hour the gate is not a
# filter, it is a delete. Measured on the served board at 15:20Z:
#
#     sport   ingested   available at selection   selected
#     mlb        4,790          4,452              100  (capped)
#     nfl        2,704             28               28  (99% eliminated)
#     wnba       1,506              0               --  (100% eliminated)
#
# The 1h rationale argued board size would hold because "excluded rows backfill
# from fresher candidates." That is true of MLB alone -- it has a 4,452-row pool
# holding captures fresher than the 100 sampled -- and was generalised to the
# board. NFL and WNBA have no such pool. Board landed at 128 of 200 slots, which
# is the falsification condition the 1h note itself named.
#
# **14h IS PINNED TO A BROKEN CAPTURE, NOT TO A PROPERTY OF WNBA.** Read this
# before treating it as a considered value.
#
# Measured directly 2026-08-12 16:10Z off the served shortlist, single fetch:
#
#     wnba   SEEN n=94  min=9.12  med=9.12  max=9.12   <- min == med == max
#     wnba   BOOK n=94  min=9.12  med=9.63  max=9.66
#     mlb    SEEN n=100 min=0.96  med=0.96  max=7.08
#
# 94 WNBA rows do not independently reach the same age to two decimals. That is
# ONE capture event, ~9.1h stale -- and 16:10Z minus 9.12h is ~07:00Z, which
# matches a WNBA odds sidecar last written 07:18:51Z while MLB published off the
# same launches. WNBA sweeps are selected, run, and write nothing; see the
# `ODDS_SWEEP_OUTCOME` instrumentation on live-odds-worker.
#
# **When that capture is fixed, WNBA's quotes go to minutes and this ceiling is
# ~14x looser than it needs to be.** Revisit it then rather than inheriting it.
#
# CORRECTION, recorded because it changed a decision: the value was first argued
# from a wnba span of 12.47h..13.00h, which was read off the measurement block
# ABOVE rather than measured -- those are older figures for a different capture.
# The real span was 9.12h..9.66h, so 12h would have cleared WNBA too and the
# extra 2h buys nothing. **A number in a comment is evidence about the day it was
# taken, not about today.** 14h is kept only because it is measured-safe and
# still cuts the 22.20h dead tail; it is not a tuned value.
#
# Deliberately a code constant rather than an env var: no
# SYNDICATE_SHORTLIST_MAX_QUOTE_AGE_SECONDS is set on any service or in
# render.yaml (re-checked 2026-08-12 against all three services' live env), so
# the default IS the live value, and a render.yaml edit would be a
# blueprint_sync production event for a number that belongs in review.
SHORTLIST_MAX_QUOTE_AGE_SECONDS = 14 * 3600


# How many times a sport's OWN typical hold a row may be worse before it is
# junk. Env: SYNDICATE_SHORTLIST_HOLD_MULTIPLE. Set to 0 to disable per-sport
# calibration and use the flat `SHORTLIST_MIN_VALUE_PCT` everywhere.
#
# **THE FLAT FLOOR IS AN MLB-SHAPED DEFAULT.** `ev_pct` is measured against the
# consensus no-vig fair, and for a normally-priced market that is exactly
# `1/overround - 1` -- so `ev_pct == -hold_pct`, verified to four decimals
# against `hold_pct()` on five price pairs (best -115/+110 -> hold 1.0953%,
# measured ev -1.0953). A row's value% is therefore its market's hold, negated.
#
# Natural hold is a property of MARKET STRUCTURE, not of quality: soccer's
# 3-way markets hold more than MLB's 2-way ones, so soccer rows sit structurally
# lower on `ev_pct` while being priced perfectly normally. One global number
# applied across both is not a neutral default -- it silently penalises every
# sport whose markets are not shaped like MLB's. Measured on the served board:
# soccer contributed 3 rows at -2.0 and 24 at -5.0.
#
# So the bar is expressed in units of the sport's own hold and CALIBRATED FROM
# THE POOL BEING FILTERED, not from a hand-written table. A table of eight
# numbers rots exactly the way the migration gate's hand-written per-sport
# blocks did; a formula with its measurement attached does not.
#
# 1.25 = "a market may hold up to a quarter more than its FAMILY typically
# holds". Below that it is normal pricing; beyond it the price is materially
# worse than that family's own market structure explains.
#
# **WAS 2.0, AND 2.0 REJECTED NOTHING ANYWHERE** -- measured on the served board
# 2026-08-12: floors of mlb -12.02, soccer -13.35, wnba -10.53, nfl -8.27 with
# `rows_below_value_floor = 0` board-wide. A junk filter that has never fired is
# indistinguishable from no filter.
#
# 1.25 is set off the per-family EV spread, not guessed (`#383`), n=200 served:
#
#     family        ev_med          within-family spread
#     moneyline     +0.35 / -0.11   tight
#     spread        +0.78 /  0.00
#     total         +0.46
#     player_prop   -6.00 mlb / -6.85 soccer / -6.78 wnba   -7.87..-6.28
#
# Against each family's own anchor, x1.0 cuts ~half of EVERY family (that is
# rejecting normal pricing, not junk) and x1.5 and x2.0 cut nothing. 1.25 is the
# tightest value that does not cut normally-priced rows.
#
# **HONEST LIMIT:** on today's pool 1.25 also rejects nothing, because nothing in
# the pool is junk RELATIVE TO ITS FAMILY. That is the filter working as
# specified -- it is a junk filter, not a value gate. It is NOT the instrument
# that will keep -6.5% props off the board; see `SHORTLIST_KIND_FLOOR`, which
# guarantees 30 prop slots per sport whether or not anything deserves them.
SHORTLIST_HOLD_MULTIPLE = 1.25

# Fewest two-sided markets needed before a sport's measured hold is trusted.
# Under this the flat default is used, because a median over three markets is
# not a market-structure measurement -- it is noise with a decimal point.
SHORTLIST_HOLD_MIN_MARKETS = 8


def _measured_floor_for_pool(
    rows: Iterable[Mapping[str, Any]],
    *,
    multiple: float,
    fallback: float,
    _split: bool = True,
) -> tuple[float, dict[str, Any]]:
    """A sport's value floor, derived from its own measured hold.

    Regroups the pool's one-side-per-row candidates back into markets, takes
    each market's best-price hold, and puts the floor at `multiple` times the
    median. Returns the floor AND the evidence, because a threshold that cannot
    show its own measurement is the class of constant this repo has paid for
    most often.

    Falls back to the flat floor when too few markets carry two sides -- which
    is not hypothetical: a 3-way soccer market whose third leg was gated out
    leaves one side, and the SHORTLIST (as opposed to the pool) keeps ~1 side of
    most soccer markets, which is why measuring here rather than downstream
    matters.
    """
    from syndicate.features.shared.book_margin_model import market_family
    from syndicate.features.shared.opportunity_signals import hold_pct

    # Materialised: the `#382` modelled-hold branch walks the pool a second
    # time, and the annotation says Iterable -- a generator would arrive empty.
    rows = list(rows)

    # `#383` -- SPLIT BY FAMILY BEFORE MEASURING ANYTHING.
    #
    # One floor per sport blends market structures that are 7 EV points apart.
    # Measured on the served board 2026-08-12, n=200:
    #
    #     moneyline +0.35   spread +0.78   total +0.46   player_prop -6.50
    #
    # A prop and a moneyline are not the same bet priced differently; books
    # charge a different margin for each, which is the exact distinction
    # `market_family` exists to draw and which the sport-wide median erased. The
    # blended floor then judged MLB's +0.35 moneylines and its -6.00 props by one
    # number, so it could only ever be too loose for one and too tight for the
    # other.
    #
    # Recursion is one level deep and cannot repeat: the recursive call passes a
    # single family's rows, so `by_family` below has one key and the branch is
    # skipped. Guarded on `_split` rather than on len() so that stays true if a
    # family ever measures empty.
    if _split:
        by_family: dict[str, list[Mapping[str, Any]]] = {}
        for row in rows:
            by_family.setdefault(market_family(row.get("market")), []).append(row)
        if len(by_family) > 1:
            per_family: dict[str, float] = {}
            evidence_by_family: dict[str, Any] = {}
            for family, family_rows in by_family.items():
                family_floor, family_evidence = _measured_floor_for_pool(
                    family_rows, multiple=multiple, fallback=fallback, _split=False
                )
                per_family[family] = family_floor
                evidence_by_family[family] = family_evidence
            # The scalar return stays the LOOSEST family floor so any caller that
            # ignores `by_family` cannot silently tighten a family it never
            # measured -- an unknown family must not land on a stricter rule than
            # the one it would have earned.
            return min(per_family.values()), {
                "method": "per_family",
                "by_family": per_family,
                "evidence_by_family": evidence_by_family,
            }

    markets: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        quote = row.get("quote") if isinstance(row.get("quote"), Mapping) else {}
        price = quote.get("price")
        if price is None:
            continue
        key = (row.get("event_id"), row.get("market"), row.get("segment"), str(row.get("line")), row.get("player_name"))
        markets.setdefault(key, {})[str(row.get("side"))] = price

    holds: list[float] = []
    for sides in markets.values():
        if len(sides) < 2:
            continue
        value = hold_pct(list(sides.values()))
        if value is not None:
            holds.append(float(value))

    if len(holds) < SHORTLIST_HOLD_MIN_MARKETS and multiple > 0:
        # `#382` -- SECOND ESTIMATOR, for sports whose pool is one-sided BY
        # CONSTRUCTION. The two-sided regrouping above needs both legs of a
        # market inside the POOL; soccer is 3-way and the draw leg is gated, so
        # the pool keeps ~1.1 sides per row and this measured exactly ZERO
        # markets for soccer on 2026-08-12 (mlb 1,986, wnba 722, nfl 107).
        # Soccer was then judged at the flat -2.0 while every other sport got a
        # floor 4-6x looser, and seated 0 of 2,359 opportunities.
        #
        # `assumed_hold_pct` is a real measurement of the same quantity, taken
        # where it IS measurable: `build_margin_profile` runs on the GRID, which
        # still holds every leg, and stamps the book's median hold onto each
        # one-sided row. So the rows this branch exists for are precisely the
        # rows that carry it.
        #
        # NOT a fallback constant and not an average of other sports -- it is
        # this sport's own hold, from this slate, via a different estimator.
        # Labelled `modelled_hold` so a floor derived this way can never be
        # mistaken for the two-sided one, per the same rule the margin model
        # follows for fair value itself.
        # Read from the CANDIDATE's own quote, which is where the fan-out now
        # carries it. It was first written against `modelled_fair`, the shape on
        # the GRID row -- correct logic, wrong side of a boundary, and it read
        # zero rows in production for two hours while its tests passed.
        modelled = [
            value
            for row in rows
            if isinstance(row.get("quote"), Mapping)
            and (value := _as_float(row["quote"].get("assumed_hold_pct"))) is not None
        ]
        if len(modelled) >= SHORTLIST_HOLD_MIN_MARKETS:
            modelled.sort()
            mid = len(modelled) // 2
            median_modelled = (
                modelled[mid] if len(modelled) % 2 else (modelled[mid - 1] + modelled[mid]) / 2.0
            )
            derived_modelled = -abs(median_modelled) * float(multiple)
            # Same clamp as the two-sided path: the floor may loosen from the
            # flat default but never tighten past it.
            floor_modelled = min(fallback, derived_modelled)
            return floor_modelled, {
                "method": "modelled_hold",
                "markets_measured": len(holds),
                "rows_modelled": len(modelled),
                "median_hold_pct": round(median_modelled, 4),
                "multiple": float(multiple),
                "derived_floor": round(derived_modelled, 4),
                "floor": round(floor_modelled, 4),
            }

    if len(holds) < SHORTLIST_HOLD_MIN_MARKETS or multiple <= 0:
        return fallback, {
            "method": "flat_default",
            "markets_measured": len(holds),
            "floor": fallback,
        }
    holds.sort()
    median_hold = holds[len(holds) // 2] if len(holds) % 2 else (holds[len(holds) // 2 - 1] + holds[len(holds) // 2]) / 2.0
    # `-` because ev_pct is the NEGATED hold. A sport whose best prices routinely
    # cross (negative hold, i.e. an arbitrage) would otherwise produce a floor
    # above zero and reject its own normal rows, so the floor is never allowed
    # to rise above the flat default.
    derived = -abs(median_hold) * float(multiple)
    floor = min(fallback, derived)
    return floor, {
        "method": "measured_hold",
        "markets_measured": len(holds),
        "median_hold_pct": round(median_hold, 4),
        "multiple": float(multiple),
        "derived_floor": round(derived, 4),
        "floor": round(floor, 4),
    }


def _env_float(name: str, default: float) -> float:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)


def _row_value_pct(row: Mapping[str, Any]) -> float | None:
    value = _as_float(row.get("ev_pct"))
    if value is not None:
        return value
    score = row.get("score")
    return _as_float(score.get("value_pct")) if isinstance(score, Mapping) else None


def _row_ev_is_hold_restatement(row: Mapping[str, Any]) -> bool:
    """True when this row's `ev_pct` is arithmetically the book's own margin.

    `book_margin_model` prices a one-sided market as `fair = implied x (1-hold)`,
    and `expected_value_pct(price, fair)` is `fair/implied - 1`, so the price
    cancels and the EV is `-hold` for every such row regardless of the bet.
    Ranking on it ranks on which book quoted, not on value.

    Keyed on `fair_method` rather than on a numeric closeness test between
    `ev_pct` and `assumed_hold_pct`. The method is the STATED provenance and is
    exact; a tolerance would be a magnitude test that drifts with the 4-dp
    rounding of `fair` (which at longshot probabilities is what turned three
    holds into nineteen apparent EV values in production).

    A row carrying a model view is NOT uninformative -- `blended_score` folds
    `model_edge` into `value`, so it ranks on the sim's disagreement rather than
    on the margin. That is the one thing that makes such a row explicable.
    """
    quote = row.get("quote")
    method = quote.get("fair_method") if isinstance(quote, Mapping) else None
    if str(method or "").strip() != "book_margin_model":
        return False
    return _as_float(row.get("model_edge_pct")) is None


def _row_quote_age_seconds(row: Mapping[str, Any]) -> float | None:
    """How stale is our OBSERVATION of this quote (`#370`).

    This feeds the shortlist's `max_quote_age_seconds` ceiling, and that gate
    asks "is our data too old to act on", not "has the price moved recently".
    Those are different questions and `book_quotes` only ever answered the
    second: it is a change log, so an unchanged price writes no row and a
    motionless market ages without limit.

    Measured on the served shortlist 2026-08-11, both clocks present on 200/200
    rows and disagreeing by more than 5x on a whole sport:

        sport   book_age median   seen_age median
        mlb              8.9m              2.2m
        nfl            331.6m            270.4m
        wnba           376.2m             68.5m

    WNBA prices had not moved in six hours; we had looked 68 minutes ago. Gating
    on the first would age out markets we are actively watching.

    NOT changed alongside this: `opportunity_gate`'s live/pregame lane checks
    also read `book_age_seconds`, and they should. Those ask whether the MARKET
    is still moving -- a book that has not touched its own timestamp during a
    live game is plausibly suspended -- which is the question `book_age` exists
    to answer. Same field, different question, deliberately left alone.

    Falls back to `book_age_seconds` when the sidecar produced no seen-age, so a
    source without the second clock is gated exactly as before rather than
    passing unmeasured.
    """
    quote = row.get("quote")
    if not isinstance(quote, Mapping):
        return None
    seen = _as_float(quote.get("quote_seen_age_seconds"))
    if seen is not None:
        return seen
    return _as_float(quote.get("book_age_seconds"))


# States that AFFIRMATIVELY say the game has started or finished. Only these
# protect a row from the kickoff clock, because only these are claims the clock
# could contradict.
_STARTED_GAME_STATES = frozenset({"live", "in", "in_progress", "inprogress", "final", "post", "completed", "closed"})


def _has_usable_game_state(row: Mapping[str, Any]) -> bool:
    """True only when the state AFFIRMS the game started or finished.

    **PRESENCE IS NOT EVIDENCE, and assuming it was let a finished match keep
    the top of the board.** The first version of this returned `bool(state)`.
    Hours later a concurrent fix (`60689dee`) repaired the team-branding read so
    soccer rows stopped carrying `game.state: None` and started carrying
    `"pregame"` -- and that turned this guard OFF for exactly the rows it was
    written for. Measured on the served board 2026-08-08 20:30Z: the same
    NEC Nijmegen v SC Telstar match still ranked **#1 and #2**, now
    `state='pregame'`, **6.02 hours** after kickoff.

    `pregame` after commence_time is a CONTRADICTION, not information. For nine
    of the ten soccer leagues it is also permanent -- `_unsimulated_game`
    defaults `status_state` to `"pre"` and only the simulated path (MLS) stamps
    a real one -- so treating it as trustworthy means never applying the clock
    to precisely the sport that needs it.

    An unrecognised state is deliberately treated as NOT affirming: this guard
    should fail toward applying the clock, and `opportunity_gate` still owns
    every row whose state genuinely says live or final.
    """
    game = row.get("game")
    state = str((game or {}).get("state") or "").strip().lower() if isinstance(game, Mapping) else ""
    return state in _STARTED_GAME_STATES


def _seconds_since_commence(row: Mapping[str, Any], now: datetime) -> float | None:
    raw = str(row.get("commence_time") or "").strip()
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        return None
    return (now - stamp).total_seconds()


def _as_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _fair_by_side(row: Mapping[str, Any], sides: list[str]) -> tuple[dict[str, float], str | None]:
    """No-vig fair probability per side, and how it was obtained.

    Two-sided is the real thing (#238). The margin model fills one-sided rows
    and is labelled differently on purpose, so a modelled fair can never be
    mistaken for a measured consensus.
    """
    best = row.get("best") or {}

    # `#384` -- DE-VIG WITHIN A BOOK, THEN TAKE THE MEDIAN ACROSS BOOKS.
    #
    # This used to de-vig the BEST price on each side, which routinely takes the
    # two sides from two different books. Measured on the served board
    # 2026-08-12: 29 of 52 two-sided groups drew their sides from different
    # bookmakers, and `edge == ev_vs_fair_pct` on 127 of 127 rows.
    #
    # `opportunity_signals.fair_probability_by_book` documents exactly why that
    # is wrong: the best over at one book and the best under at another sum to
    # less than a real market, and normalising THAT to 1.0 "silently launders a
    # line-shopping edge into the 'fair' price -- which then makes the edge
    # disappear from the EV it was supposed to measure." So the board's EV was a
    # cross-book arb surplus, identical on both sides by construction, wearing
    # the label of an edge against fair value.
    #
    # `consensus_fair_probability` is the correct implementation and already
    # existed -- it was reachable from one call site and used by neither board.
    # It de-vigs each book against itself, then takes the MEDIAN per selection,
    # so one stale or fat-fingered book cannot move the benchmark.
    cells = row.get("cells")
    if isinstance(cells, Mapping):
        # Nesting is {book: {selection: price}} -- the same shape `cells`
        # already has, and the shape `fair_probability_by_book` iterates. Passing
        # it inverted returns None rather than raising, so the board would have
        # fallen through to the modelled path everywhere and looked merely
        # thinner rather than broken.
        prices_by_book: dict[str, dict[str, Any]] = {}
        for book, sides_map in cells.items():
            if not isinstance(sides_map, Mapping):
                continue
            per_side = {
                side: price
                for side in sides
                if isinstance(sides_map.get(side), Mapping)
                and (price := _as_float(sides_map[side].get("price"))) is not None
            }
            # A book quoting only one leg has nothing to de-vig against; keeping
            # it would let a lone longshot price normalise to a "fair" of 1.0.
            if len(per_side) == len(sides) and len(per_side) >= 2:
                prices_by_book[str(book)] = per_side
        if prices_by_book:
            consensus = consensus_fair_probability(prices_by_book)
            if consensus and len(consensus) == len(sides):
                return ({str(side): value for side, value in consensus.items()}, "consensus")

    # SAME-BOOK fallback only. A two-sided de-vig is legitimate when both prices
    # come from ONE book -- that is what the per-book pass above does. It is the
    # CROSS-book case that launders, so this checks the bookmakers match rather
    # than reinstating the old behaviour when consensus is unavailable.
    prices = [(_as_float((best.get(side) or {}).get("price")), side) for side in sides]
    books_used = {str((best.get(side) or {}).get("bookmaker") or "") for side in sides}
    if (
        len(prices) >= 2
        and all(price is not None for price, _ in prices)
        and len(books_used) == 1
        and "" not in books_used
    ):
        probabilities = devig([price for price, _ in prices])
        if probabilities and len(probabilities) == len(prices):
            return ({side: probabilities[i] for i, (_, side) in enumerate(prices)}, "two_sided_same_book")

    modelled = row.get("modelled_fair") or {}
    out: dict[str, float] = {}
    for side in sides:
        probability = _as_float((modelled.get(side) or {}).get("fair_probability"))
        if probability is not None:
            out[side] = probability
    return (out, "book_margin_model" if out else None)


# A probability edge this large is a UNIT OR JOIN ERROR, not a finding.
#
# MEASURED on the first MLB pregame board carrying projections (2026-08-08):
# 93 of 100 shortlisted rows had NEGATIVE EV against the market's own no-vig
# price, ranked almost entirely by model edges of 9-48 points. On h2h rows the
# implication is explicit and impossible to defend:
#
#     fair_probability 0.468  +  model_edge 39.38  ->  model says ~86%
#     fair_probability 0.484  +  model_edge 40.60  ->  model says ~89%
#
# MLB games sit between roughly 35% and 65%. A model claiming 86-89% on a game
# the market prices near even, on 41 of 51 game rows and skewed 80% to the away
# side, is not sharp -- it disagrees with every market in one direction, which
# is the signature of a units mismatch or a home/away join fault.
#
# NOTE ON THE SAMPLE, because it caught me out: the shortlist is the top N BY a
# score this term dominates, so "every row has a huge edge" is partly a
# selection effect and says nothing about the full distribution. What does NOT
# wash out is the implied probability -- 86% is impossible regardless of how the
# row was selected.
#
# So the bound is on PLAUSIBILITY IN PROBABILITY SPACE, not on magnitude for its
# own sake: an edge is accepted only if the probability it implies is one a
# bettor could act on. Deliberately generous -- a genuine 15-point edge is
# enormous and still passes.
_MODEL_EDGE_MAX_POINTS = 15.0

# The real fix is an explicit `basis` on the projection, which #263's own filing
# already argued for ("each sport emitting the strongest claim its source
# actually supports, labelled with its basis"). That was written as a parity
# principle; this is why it is a correctness requirement. Until projections
# carry it, this bound is the guard -- and it is a GUARD, not a calibration.


def _model_edge_for(row: Mapping[str, Any], side: str) -> float | None:
    """The sim's disagreement with the market, in POINTS OF PROBABILITY.

    Only `edge_vs_market_pct` qualifies. A mean-based `edge_vs_line` (WNBA, and
    soccer away from its one probability line) is in units of the stat — runs,
    rebounds, goals — and adding that to an EV percentage would be adding
    rebounds to percent. Those rows rank on EV alone, which is correct: we have
    no probability-space model view for them.

    That guard filters by FIELD NAME, and 2026-08-08 showed the hole: a field
    called `edge_vs_market_pct` that is not in probability points sails through
    it. So the value is now bounded by what it implies as well as by where it
    came from — see `_MODEL_EDGE_MAX_POINTS`. Rejected rows fall back to EV
    alone, which cannot pick a side but also cannot invert one.
    """
    projection = row.get("projection")
    if not isinstance(projection, Mapping):
        return None
    edge = _as_float(projection.get("edge_vs_market_pct"))
    if edge is None:
        return None
    if abs(edge) > _MODEL_EDGE_MAX_POINTS:
        # Dropped, not clamped. Clamping would keep an unusable number in the
        # ranking at the ceiling value and make every affected row tie at the
        # top -- a wrong answer wearing a plausible one's clothes (#242).
        return None
    # The projection is stated from one side; flip it for the other.
    projected_side = str(projection.get("side") or "").strip().lower()
    if projected_side and projected_side != str(side).strip().lower():
        return -edge
    return edge


def build_layer2_rows(grid: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Fan a market grid out into ranked, gated one-side candidates."""
    candidates: list[dict[str, Any]] = []
    lanes: dict[str, int] = {}
    rows_in = 0
    sides_priced = 0
    scored = 0

    for row in grid:
        rows_in += 1
        sides = [str(side) for side in (row.get("sides") or []) if side]
        if not sides:
            continue
        fair_by_side, fair_method = _fair_by_side(row, sides)
        best = row.get("best") or {}
        game = row.get("game") if isinstance(row.get("game"), Mapping) else None

        for side in sides:
            side_best = best.get(side) or {}
            price = side_best.get("price")
            if price is None:
                continue
            sides_priced += 1
            fair = fair_by_side.get(side)
            quote = {
                "price": price,
                "bookmaker": side_best.get("bookmaker"),
                "book_age_seconds": side_best.get("age_seconds"),
                # Time since we last LOOKED, as opposed to `book_age_seconds`'
                # time since the price last MOVED. None when the date's quote
                # state predates last-seen tracking -- unknown, and scoring must
                # not read that as either fresh or stale.
                "quote_seen_age_seconds": side_best.get("seen_age_seconds"),
                "books_quoting": side_best.get("books_quoting"),
                "fair_probability": fair,
                "fair_method": fair_method if fair is not None else None,
                # `#382`. The margin model measures each book's hold on the GRID
                # (which still holds every leg) and stamps it at
                # `modelled_fair[side].assumed_hold_pct`. This fan-out copies a
                # fixed field list, so that measurement died here -- and
                # `_measured_floor_for_pool` runs on candidates, which is why the
                # modelled-hold floor read 0 rows in production while its unit
                # tests passed on hand-built input.
                #
                # Carried as ONE FLOAT on the side's own quote rather than the
                # whole `modelled_fair` dict: the floor needs the number, and the
                # dict would put a fair price and a prose note on every row of a
                # payload that is already 68% market data.
                "assumed_hold_pct": _as_float(
                    ((row.get("modelled_fair") or {}).get(side) or {}).get("assumed_hold_pct")
                ),
                "suspect_stale": bool(side_best.get("suspect_stale")),
                # EVERY BOOK'S PRICE FOR THIS SIDE, so CLV can be measured
                # same-book later. `best` is one book by definition, and pairing
                # a best-of-N opening against a different book's close is biased
                # upward -- measured at +6.2 pts and a 91% beat rate, which is
                # the selection effect, not skill.
                #
                # Same-book needs OUR price at a book the close is recorded for,
                # and we cannot know which that is at write time: odds history
                # keeps a **median of 2 books per (event, market)** while the
                # board picks the best of ~13. Measured 2026-08-14, mlb: the
                # exact (event, market, best_book) triple existed in history for
                # **3 of 55** game rows. Recording every book we saw makes the
                # overlap near-certain instead of a 1-in-6 guess.
                #
                # Flat {book: price}, not the whole cell: the ledger needs the
                # number, and a nested dict per book would put age/stale/rank on
                # every row of an artifact that is already mostly market data.
                "book_prices": {
                    str(book): cell[side]["price"]
                    for book, cell in (row.get("cells") or {}).items()
                    if isinstance(cell, Mapping)
                    and isinstance(cell.get(side), Mapping)
                    and cell[side].get("price") is not None
                },
            }

            candidate: dict[str, Any] = {field: row.get(field) for field in _IDENTITY_FIELDS}
            candidate["side"] = side
            # THE ROW'S `line` IS THE AWAY HANDICAP, NOT THIS SIDE'S.
            #
            # Measured on `/api/board/book-grid`, mlb 2026-08-15, **525 book
            # cells across 33 spreads rows**: `cell.home.line == -row["line"]` on
            # **525 of 525**, and every book's own home/away lines summed to zero
            # (525/525), so `cell.away.line == row["line"]` exactly. Away rows
            # were therefore already right; HOME rows published the away
            # handicap beside the home price.
            #
            # What that cost, both measured: in the CLV join a home `-1.5`
            # opening was differenced against a home `+1.5` close, producing a
            # `-29.90`/`+30.428` mirror pair on a market that never moved; and
            # `_board_row_selection` in the Ask adapter renders `f"{side} {line}"`,
            # so a home spread in the chat headline showed the wrong handicap.
            #
            # Taken from the SAME cell the price comes from rather than by
            # negating: negation would encode "row.line is always away", which is
            # an observation about one sport on one date, not an invariant. Cells
            # carry their own line, so read it. This is a NO-OP for away rows
            # (they already agree) and for h2h/props (no line at all).
            side_line = _side_line_from_cells(row, side)
            if side_line is not None:
                candidate["line"] = side_line
            candidate["quote"] = quote
            if game:
                candidate["game"] = dict(game)
                # The gate reads `game_state`/`is_live` at the TOP level; the
                # grid nests it as `game.state`. Without this translation every
                # row looks pregame to the gate, and a settled market ranks --
                # caught by test_dead_market_is_never_ranked, which is exactly
                # the kind of silent contract mismatch #245 exists to prevent.
                candidate["game_state"] = game.get("state")
                candidate["is_live"] = str(game.get("state") or "").strip().lower() == "live"

            # #270. The sim's projected value for this market. Carried here
            # explicitly rather than added to `_IDENTITY_FIELDS`, which is
            # identity -- this is a FACT about the market, and widening the
            # identity tuple to smuggle facts through is how that comment stops
            # being true.
            #
            # `attach_projections` already stamps it on the grid row, and every
            # sport's join agrees on the key (`wnba_projections.py:164`,
            # `soccer_projections.py:291`, `prop_projections.py:712` all write
            # `row["projection"]`). Nothing copied it onto the candidate, so the
            # board's "Projected" fact had nothing to render even where the
            # projection existed -- measured on production 2026-08-09, soccer
            # carried 216 rows_with_projection and wnba 83, and `projection`
            # appeared on zero served rows.
            #
            # Absent stays absent rather than becoming null: a missing
            # projection is unknown, and the props pipeline distinguishes
            # "no projection" from "projection of 0".
            projection = row.get("projection")
            if projection is not None:
                candidate["projection"] = projection

            # Eligibility BEFORE scoring: a dead market should never be ranked,
            # and the gate is the one place that decision lives (#245).
            opportunity_gate.annotate(candidate, quote)
            lane = str(candidate.get("board_lane") or "unknown")
            lanes[lane] = lanes.get(lane, 0) + 1

            ev = expected_value_pct(price, fair) if fair is not None else None
            model_edge = _model_edge_for(row, side)
            score = blended_score(
                ev_pct=ev,
                model_edge=model_edge,
                books_quoting=side_best.get("books_quoting") or row.get("books_quoting"),
                book_age_seconds=side_best.get("age_seconds"),
                quote_seen_age_seconds=side_best.get("seen_age_seconds"),
                # Without these the price-reliability term is inert and a
                # longshot's EV ranks on price alone -- which is exactly how a
                # +6000 soccer h2h reached #1 on the first production
                # shortlist. See _SCORE_DEVIG_ABS_ERROR_FLOOR.
                price=price,
                fair_prob=fair,
            )
            candidate["ev_pct"] = ev
            candidate["model_edge_pct"] = model_edge
            candidate["score"] = score
            if score is not None:
                scored += 1
            candidates.append(candidate)

    opportunities = [
        candidate
        for candidate in candidates
        if candidate.get("board_lane") == opportunity_gate.LANE_OPPORTUNITY
        and candidate.get("score") is not None
    ]
    # Highest blended score first. Rows with no score are excluded above rather
    # than sorted to the bottom: a row with neither EV nor a model view has
    # nothing to rank, and scoring it zero would place it above genuinely
    # negative rows (blended_score's own reasoning).
    opportunities.sort(key=lambda item: item["score"]["score"], reverse=True)

    return {
        "rows_in": rows_in,
        "sides_priced": sides_priced,
        "candidates": len(candidates),
        "scored": scored,
        "opportunities": opportunities,
        "by_lane": lanes,
    }


def _score_of(row: Mapping[str, Any]) -> float:
    score = row.get("score")
    if isinstance(score, Mapping):
        value = _as_float(score.get("score"))
        if value is not None:
            return value
    return float("-inf")


# How far ahead a row may start and still belong on TODAY's shortlist.
#
# MEASURED 2026-08-07, and it is the reason this parameter exists at all: the
# board was serving 1,244 NFL rows for "today" whose games start **34 to 156 days
# out** -- not one NFL game existed on the date being displayed. Meanwhile MLB
# had 2,168 rows today and 1,840 tomorrow. Under a flat per-sport cap NFL would
# spend a full allowance on markets nobody can act on this week.
#
# "Quoted today" is not "playing today", and conflating them is what made an
# empty sport look like a full board. 1 = today and tomorrow, which keeps the
# overnight boundary usable without importing next month.
#
# This does NOT delete forward-looking markets -- plan §4b wants them, and they
# are the softest lines we see. It scopes the SHORTLIST. A Forward view is a
# different projection over the same rows.
SHORTLIST_HORIZON_DAYS = 1


def _pick_label(row: Mapping[str, Any]) -> str:
    """What the bettor is actually taking, as one readable string.

    A prop is the player; a game side is the team that side refers to. The
    board's card normaliser falls back through
    selection -> pick -> name -> player_name and defaults to the literal string
    "candidate", so a game row with no player name would render as "candidate"
    on every line without this.
    """
    player = str(row.get("player_name") or "").strip()
    if player:
        return player
    side = str(row.get("side") or "").strip().lower()
    if side == "home":
        return str(row.get("home_team") or "Home").strip()
    if side == "away":
        return str(row.get("away_team") or "Away").strip()
    return side.title() or "—"


def layer2_rows_to_board_cards(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Translate L2-A rows into the shape the board card normaliser expects.

    THE BOARD IS NOT REWRITTEN TO FIT L2-A; L2-A IS TRANSLATED TO FIT THE BOARD.
    `build_intelligence_board_contract` -> `_recommendation_card` already owns
    the card contract and every surface downstream reads its output. Emitting a
    second, parallel card shape would be a second contract that can disagree
    with the first (rule 7, and #244's dead-market rule written twice is what
    that costs).

    The mapping is small because the normaliser is tolerant -- it falls back
    through several aliases per field. The fields that actually matter:

        selection  what is being taken   (player, else the side's team)
        market     which market
        line       the handicap/total, None for h2h
        odds       the PRICE WE RECOMMEND -- quote.price, not a consensus.
                   Settlement grades against this, so it must be the same
                   number the shortlist ranked.
        edge       the value term, EV against the no-vig fair price

    `score` is carried through untouched so a reader can see the components
    (ev, sim, book confidence, freshness, price reliability) rather than being
    asked to trust one opaque number.
    """
    cards: list[dict[str, Any]] = []
    # `#368`: one odds-history shard per (sport, date), loaded lazily and only
    # for rows whose market is actually tracked. The MLB shard is ~20MB, so
    # loading it per row -- or for a board of nothing but props -- would be a
    # real cost for no data. This runs worker-side inside the shortlist build,
    # never in a request path.
    history_cache: dict[tuple[str, str], Any] = {}
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        quote = row.get("quote") if isinstance(row.get("quote"), Mapping) else {}
        score = row.get("score") if isinstance(row.get("score"), Mapping) else {}
        sport = str(row.get("sport") or "").strip().lower()
        home = str(row.get("home_team") or "").strip()
        away = str(row.get("away_team") or "").strip()
        cards.append(
            {
                "sport": sport,
                "sport_slug": sport,
                "selection": _pick_label(row),
                # The card's TITLE. Measured running real L2-A rows through
                # `build_intelligence_board_contract`: every other display field
                # resolved (matchup, market, selection, line, odds, edge, team)
                # and this one came out empty, because the normaliser has no
                # alias that reaches it. A prop titles on the player, a game
                # line on the side being taken, and matchup is the last resort.
                "display_name": _pick_label(row) or (f"{away} @ {home}" if home and away else None),
                "player_name": row.get("player_name"),
                "market": row.get("market"),
                "market_key": row.get("market"),
                "line": row.get("line"),
                "odds": quote.get("price"),
                # `#364`: A FRACTION, because that is what the card contract means
                # by `edge`. `ev_pct` is in PERCENT units (1.6332 == 1.63%), and
                # the board renders this field as `(edge * 100).toFixed(1)`
                # (`intelligence.html:1115`, `:1497`, `:1840`), so assigning the
                # percent value straight across multiplied every edge on the board
                # by 100. Measured live 2026-08-11: 245 cards rendered a
                # percentage, 123 of them ABOVE 100%, ranging -725% to +163.3%,
                # for rows whose true edges are ~1.6%.
                #
                # `edgeValue(item) * 100 < state.minEdge` at `:944` confirms the
                # unit from the other side -- the min-edge selector is in percent
                # and its operand is a fraction.
                #
                # `ev_pct` below stays in percent: the name says so, and the
                # shortlist's own floors (`min_value_pct`) are expressed against
                # it. Only the alias that feeds the card is converted.
                "edge": (_as_float(row.get("ev_pct")) / 100.0) if _as_float(row.get("ev_pct")) is not None else None,
                "team": home if str(row.get("side") or "").lower() == "home" else away,
                "home_team": home,
                "away_team": away,
                "matchup": f"{away} @ {home}" if home and away else "",
                "commence_time": row.get("commence_time"),
                "event_id": row.get("event_id"),
                "game_pk": row.get("event_id"),
                "kind": row.get("kind"),
                "segment": row.get("segment"),
                "side": row.get("side"),
                # Carried verbatim so the board can show WHY a row ranks, and
                # so nothing downstream has to recompute a ranking that was
                # already decided (and persisted) on the worker.
                "score": dict(score),
                "quote": dict(quote),
                "board_lane": row.get("board_lane"),
                "market_state": row.get("market_state"),
                "gate": row.get("gate"),
                "ev_pct": row.get("ev_pct"),
                "model_edge_pct": row.get("model_edge_pct"),
                "surface_key": "layer2",
                "source": "layer2_shortlist",
                **_layer2_board_columns(row, quote, score),
                **_layer2_movement_columns(row, history_cache),
            }
        )
    return cards


def _layer2_movement_columns(row: Mapping[str, Any], cache: dict[tuple[str, str], Any]) -> dict[str, Any]:
    """DISABLED (`#372`). Was the `#368`/`#370` odds-history join.

    **IT STALLED THE SHORTLIST BUILD.** The join loaded
    `load_odds_history_payload_for_sport` INSIDE the builder -- a ~20MB MLB shard
    -- and `#370` then made it try two shard keys, so a miss on the first loaded
    a second multi-MB payload before giving up. Measured 2026-08-12: the last
    successful build was 00:22:21Z, minutes before `#370`; for the 70 minutes
    after it, execution reached `EXPOSURE_BUDGETS_APPLIED` (the statement
    immediately before the build) on every cycle and `LAYER2_SHORTLIST` never
    printed again. Entered and never returned -- no exception, so
    `LAYER2_SHORTLIST_FAILED` never fired either.

    The cost was not the column. **Every producer-side fix queued behind that
    build stopped shipping**, including `#369`'s plausibility filter, so the
    board kept serving the 00:22Z artifact with implausible arbs on top.

    WHAT I GOT WRONG, since the code read as careful: I measured the join's
    CORRECTNESS against real rows and never its COST, then wrote "loaded lazily,
    so a board of nothing but props loads nothing" as though that settled it. A
    lazy load is still a 20MB synchronous read the first time a tracked market
    appears, which is every MLB slate.

    The "Not tracked" labelling in `_layer2_board_columns` is KEPT: it is a
    string derived from the market name, does no IO, and is most of what made
    the column legible (179 of 200 rows).

    Re-landing this belongs where the odds tracker already holds the data, not
    in a per-build read of a multi-megabyte artifact.
    """
    return {}
    return {"line_odds_movement": movement} if movement else {}


# The markets `odds_control_plane` actually tracks history for. Measured against
# the live MLB shard 2026-08-11: 3,634 market keys covering 16 events, and only
# these three carry a per-event series (15 events each). The board's other eleven
# market types -- `h2h_lay`, `totals_alt`, `spreads_alt` and the prop families --
# have NO history rows at all.
#
# Overlap on the served board: event 10 of 19, event+market **11 of 73**. So a
# join that simply tried every row would light up about a fifth of the column and
# leave the rest indistinguishable from a bug. Restricting it, and SAYING SO on
# the rows outside it, is the difference between "no data" and "not measured".
_MOVEMENT_TRACKED_MARKETS = ("h2h", "totals", "spreads")


def _movement_is_tracked(market: Any) -> bool:
    # Exact match, not prefix: `totals_alt` and `spreads_alt` start with a tracked
    # name and are NOT tracked, so `startswith` here would relabel eleven of them
    # as "has history" and put the column straight back to looking broken.
    return str(market or "").strip().lower() in _MOVEMENT_TRACKED_MARKETS


def _movement_shard_keys(commence_time: Any) -> tuple[str, ...]:
    """Odds-history shard keys to try for a row, CENTRAL DATE FIRST (`#370`).

    `#368` sharded on `commence_time[:10]`, which is the UTC date, and that is
    wrong for exactly the games this board is about. A US evening game kicks off
    at `2026-08-12T00:08Z` -- so before midnight UTC it sharded to `08-11` and
    worked, and after midnight the SAME game sharded to `08-12` while its history
    sits under `08-11`. Measured at 00:27Z, four hours after I read this repo's
    own warning about it: 146 rows labelled "not tracked" correctly and **zero**
    rows carried movement, against 16 measured before midnight.

    A bug that is invisible for eighteen hours a day and total for six is worse
    than one that never works, because the pre-midnight measurement "proved" it.

    Central first because that is how the rest of the repo shards a slate
    (`central_today_iso`, `#331`'s capture-date-vs-game-date rule). UTC is kept
    as a second attempt rather than dropped: this is a LOOKUP, not a guard, so
    trying both costs one dict miss and covers a shard written under either
    convention. A guard would have to pick one.
    """
    text = str(commence_time or "").strip()
    if not text:
        return ()
    # A bare date is ALREADY a game date, not an instant. Converting it would
    # read it as midnight UTC and shift it a day backwards -- the same
    # off-by-one this function exists to fix, in the opposite direction.
    if "T" not in text and " " not in text:
        return (text[:10],)
    keys: list[str] = []
    try:
        from syndicate.features.shared.timezone import CENTRAL_TIMEZONE

        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        keys.append(stamp.astimezone(CENTRAL_TIMEZONE).date().isoformat())
    except Exception:
        pass
    utc_key = text[:10]
    if utc_key and utc_key not in keys:
        keys.append(utc_key)
    return tuple(keys)


def _line_movement_for_row(row: Mapping[str, Any], history: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """`line_odds_movement` for one row, from the odds-history shard (`#368`).

    Keyed on `event_id` + `market`, which works because the history shard and the
    L2-A row share the OddsAPI id space -- unlike the scoreboard chips, whose
    statsapi ids overlap these 0 of 27 (`#365`). Bookmaker is deliberately NOT in
    the key: the row's quote names the ONE book being recommended, while history
    tracks every book, and pinning to one loses the move whenever the best price
    changed hands. First matching series wins.

    Shape matches `recommendation_engine._line_odds_movement_summary`, because
    `intelligence.html:735` reads that structure and a second shape here would be
    a parallel contract that can disagree with it.
    """
    if not isinstance(history, Mapping):
        return None
    markets = history.get("markets")
    if not isinstance(markets, Mapping):
        return None
    event_id = str(row.get("event_id") or "").strip()
    market = str(row.get("market") or "").strip().lower()
    if not event_id or not market:
        return None
    for key, entry in markets.items():
        if not isinstance(entry, Mapping):
            continue
        text = str(key)
        if f"event_id={event_id}" not in text or f"|market={market}|" not in f"{text}|":
            continue
        first = entry.get("history_first") if isinstance(entry.get("history_first"), Mapping) else {}
        opening_line = _as_float(first.get("previous_line"))
        latest_line = _as_float(entry.get("closing_line"))
        opening_price = _as_float(first.get("previous_line"))
        latest_price = _as_float(entry.get("closing_price"))
        line_delta = None if (opening_line is None or latest_line is None) else round(latest_line - opening_line, 4)
        price_delta = None if (opening_price is None or latest_price is None) else round(latest_price - opening_price, 4)
        if line_delta is None and price_delta is None:
            continue

        def _direction(delta: float | None) -> str:
            if delta is None or abs(delta) < 1e-9:
                return "flat"
            return "up" if delta > 0 else "down"

        return {
            "opening_line": opening_line,
            "latest_line": latest_line,
            "line_delta": line_delta,
            "line_direction": _direction(line_delta),
            "opening_price": opening_price,
            "latest_price": latest_price,
            "price_delta": price_delta,
            "price_direction": _direction(price_delta),
        }
    return None


# `#369`. Minimum implied book total for a market to be considered real.
#
# `ev_pct` is the no-vig surplus, so implied total == 100/(1+ev_pct/100). This
# floor is therefore equivalent to `ev_pct <= 5.26`, and the equivalence is the
# point: the number is derived from "a book cannot price a market at 95% and
# survive", not picked to trim the board.
#
# Measured on the 200-row shortlist 2026-08-12: the distribution is BIMODAL --
# p50 implies a healthy 99.26% book, p75 implies 89.19%. There is no honest
# threshold that keeps the p75 group; an 11-point cross-book arb is a broken
# quote, and real ones run 0-3%.
#
# Rejects 86 of 200 at this setting. That is a large fraction and it is the
# finding, not a side effect: nearly half the board was priced off quotes no
# book ever offered.
_MIN_IMPLIED_BOOK_TOTAL_PCT = float(os.environ.get("SYNDICATE_SHORTLIST_MIN_IMPLIED_BOOK_TOTAL_PCT") or 95.0)


def _implied_book_total_pct(ev_pct: Any) -> float | None:
    ev = _as_float(ev_pct)
    if ev is None:
        return None
    denominator = 1.0 + ev / 100.0
    if denominator <= 0.0:
        return None
    return 100.0 / denominator


def _american_from_probability(probability: Any) -> float | None:
    """Fair American price from a no-vig probability.

    Delegates to `opportunity_signals.american_price`, the owner of this concept
    established by the Tier 3a differential
    (`.syndicate/audit_2026-08-15_probability_differential.md`) -- the only one
    of five implementations that met every requirement, and the only one that
    round-trips 9/9.

    **The 2%-98% clamp this used to carry was published wrong prices.** Measured
    on production 2026-08-15: `/api/intelligence/query` served 1346 `fair_price`
    values, 24 sitting exactly on +/-4900 with **not one beyond it**, and a
    row-wise join found mlb totals under at `fair_probability` 0.992056
    published as **-4900** where the correct price is **-12488**. A clamp is not
    a guard: it answers an out-of-range probability with a confident wrong
    number instead of refusing. `american_price` returns None instead, and
    `_layer2_board_columns` omits the column -- absent renders as absent, per
    the board contract shipped as web `932a1f71`.

    The percent-scale case is why this matters beyond the tails: `confidence` is
    stored 0-100 and probability 0-1 in the same rows, and the clamp turned a
    `50.0` unit error into a plausible-looking -4900 rather than a blank.
    """
    return american_price(_as_float(probability))


def _layer2_board_columns(
    row: Mapping[str, Any], quote: Mapping[str, Any], score: Mapping[str, Any]
) -> dict[str, Any]:
    """The board columns that rendered blank on every L2-A card (`#366`).

    `#363` made L2-A the board and the user's first look showed FAIR, EV,
    PROJECTED, CONFIDENCE and SCORE empty across all 258 rows. **The data was
    never missing** -- it was one level down, in `row["quote"]`,
    `row["projection"]` and `row["score"]`, under names the card contract does
    not read. So this is a naming gap, not a modelling one.

    Mapped against what the template ACTUALLY reads, verified in
    `intelligence.html` rather than guessed, because populating a field nothing
    reads is the inert fix this repo keeps paying for:

        Fair        fairPriceValue   -> item.fair_price | quote.fair_price   :1600
        EV          evVsFairValue    -> item.ev_vs_fair_pct | quote.ev_pct   :1605
        Projected   displayProjection-> item.sim_projection | .projected     :580
        Confidence  confidenceValue  -> item.confidence                      :292
        Score       boardScoreValue  -> item.board_score (+ _components)     :1978

    `ev_vs_fair_pct` gets `ev_pct` DELIBERATELY, and only because this is an
    L2-A row. `evVsFairValue`'s own comment warns "NOT item.ev_pct -- that is
    the legacy field computed against a VIGGED price" (`#238`), which is true of
    legacy candidates and false here: the shortlist's `ev_pct` is measured
    against the consensus no-vig line, which is exactly what that column wants.
    Same name, different provenance -- so the mapping is made here, on the rows
    where it holds, and not by widening the accessor for everyone.

    Only `projection` is genuinely sparse: 70 of 200 rows carry one (mlb 53,
    wnba 17), so PROJECTED stays blank on the rest. That is a real COVERAGE gap,
    not a plumbing one -- a parallel session is closing the WNBA game-line half
    of it -- and it must keep rendering blank rather than as a fabricated zero.
    An invented projection on a betting board is worse than an empty cell.
    """
    projection = row.get("projection") if isinstance(row.get("projection"), Mapping) else {}
    columns: dict[str, Any] = {}

    fair_price = _american_from_probability(quote.get("fair_probability"))
    if fair_price is not None:
        columns["fair_price"] = fair_price

    ev_pct = _as_float(row.get("ev_pct"))
    if ev_pct is not None:
        columns["ev_vs_fair_pct"] = ev_pct

    projected = _as_float(projection.get("projected"))
    if projected is not None:
        columns["projected"] = projected
        columns["sim_projection"] = projected

    model_prob = _as_float(projection.get("model_prob_over"))
    if model_prob is not None:
        columns["model_probability"] = model_prob

    confidence = _as_float(score.get("book_confidence"))
    if confidence is not None:
        columns["confidence"] = confidence

    composite = _as_float(score.get("score"))
    if composite is not None:
        columns["board_score"] = composite
        # The tooltip takes the number apart; carrying the components means a
        # reader can see WHY a row scores what it does, which is the whole
        # reason the breakdown is persisted.
        columns["board_score_components"] = dict(score)

    book_age = _as_float(quote.get("book_age_seconds"))
    if book_age is not None:
        columns["book_age_seconds"] = book_age

    # `#368`: say WHICH kind of empty this is. A market with no history and a
    # market whose history simply has not moved both rendered a bare dash, and
    # the first is "we do not measure this" while the second is "it is flat".
    # Conflating them is what made the whole column read as broken.
    if not _movement_is_tracked(row.get("market")):
        columns["movement_not_tracked"] = True
    return columns


def _sport_horizon_days(row: Mapping[str, Any], horizon_days: int | None) -> int | None:
    """This sport's slate window, not one global number (`#380`).

    A single `horizon_days=1` is correct only for sports whose slate IS one day.
    Measured live 2026-08-12, immediately after `#379` widened the READ window:
    soccer landed 16,065 quote rows and 2,359 opportunities in the pool, and the
    1-day horizon then discarded every one of them -- its fixtures were 08-14
    (4), 08-15 (25), 08-16 (24) and 08-17 (5), all 2-5 days out. `#379` fixed
    which dates were READ and left which dates were KEPT at one day, so the
    counter simply moved: `rows_beyond_horizon` went 2,670 -> 5,029.

    Reuses `slate_window_days` -- the same table Layer 1 boards by and `#379`
    reads by (soccer 7, nfl 5, ncaaf 3, everything else 1). A third independent
    notion of "which dates count" is what produced this bug in the first place.

    An explicit caller override still wins: a caller that asks for a specific
    horizon means it.
    """
    if horizon_days is None:
        return None
    sport = str(row.get("sport") or "").strip().lower()
    if not sport:
        return horizon_days
    try:
        from syndicate.features.shared.layer1_board import slate_window_days

        # `slate_window_days` counts DATES INCLUSIVE of the anchor (soccer 7 =
        # today plus six), while this compares a day DELTA -- so 7 dates is a
        # delta of 6. Off by one here would silently drop each sport's last day.
        window = int(slate_window_days(sport))
    except Exception:
        return horizon_days
    return max(int(horizon_days), window - 1)


def _within_horizon(row: Mapping[str, Any], now: datetime, horizon_days: int | None) -> bool:
    horizon_days = _sport_horizon_days(row, horizon_days)
    if horizon_days is None:
        return True
    raw = row.get("commence_time")
    if not raw:
        # No start time is not evidence of being today. Kept rather than dropped,
        # because dropping it would silently hide a whole sport if a feed stopped
        # stamping starts -- and every non-MLB sport currently ships game.state
        # as None, so this path is not hypothetical.
        return True
    try:
        start = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return True
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return (start.astimezone(timezone.utc).date() - now.date()).days <= int(horizon_days)


def select_shortlist(
    opportunities: Iterable[Mapping[str, Any]],
    *,
    per_sport: int = SHORTLIST_ROWS_PER_SPORT,
    kind_floor: int = SHORTLIST_KIND_FLOOR,
    horizon_days: int | None = SHORTLIST_HORIZON_DAYS,
    now: datetime | None = None,
    min_value_pct: float | None = None,
    rows_per_game: int | None = None,
    max_quote_age_seconds: float | None = None,
    stale_kickoff_seconds: float | None = None,
    hold_multiple_override: float | None = None,
) -> dict[str, Any]:
    """The rows that get PERSISTED. Everything else lives in the ledger.

    Two consumers wanted opposite things and sizing one number for both got both
    wrong: the board wants a shortlist (#243 cut 230 rows to 34 on purpose),
    while settlement wants breadth because CLV-derived weights converge on
    volume. They are separated -- this bounds the *display* artifact, and the
    append-only ledger carries every gated row for S6.

    Selection is FLOOR-THEN-MERIT per sport: guarantee each kind its floor, then
    fill the remainder purely by score. An unused floor (a sport with no props,
    or none that survived the gate) flows to the other kind instead of shrinking
    the shortlist.
    """
    reference_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    value_floor = (
        float(min_value_pct)
        if min_value_pct is not None
        else _env_float("SYNDICATE_SHORTLIST_MIN_VALUE_PCT", SHORTLIST_MIN_VALUE_PCT)
    )
    age_ceiling = (
        float(max_quote_age_seconds)
        if max_quote_age_seconds is not None
        else _env_float("SYNDICATE_SHORTLIST_MAX_QUOTE_AGE_SECONDS", SHORTLIST_MAX_QUOTE_AGE_SECONDS)
    )
    hold_multiple = (
        float(hold_multiple_override)
        if hold_multiple_override is not None
        else _env_float("SYNDICATE_SHORTLIST_HOLD_MULTIPLE", SHORTLIST_HOLD_MULTIPLE)
    )
    stale_kickoff_ceiling = (
        float(stale_kickoff_seconds)
        if stale_kickoff_seconds is not None
        else _env_float("SYNDICATE_SHORTLIST_STALE_KICKOFF_SECONDS", SHORTLIST_STALE_KICKOFF_SECONDS)
    )
    rows_per_game = (
        int(rows_per_game)
        if rows_per_game is not None
        else int(_env_float("SYNDICATE_SHORTLIST_ROWS_PER_GAME", SHORTLIST_ROWS_PER_GAME))
    )
    raw_excluded = os.environ.get("SYNDICATE_SHORTLIST_EXCLUDED_MARKETS")
    excluded_markets = tuple(
        token.strip().lower()
        for token in (
            SHORTLIST_EXCLUDED_MARKETS if raw_excluded is None else raw_excluded
        ).split(",")
        if token.strip()
    )
    by_sport: dict[str, list[Mapping[str, Any]]] = {}
    beyond_horizon = 0
    beyond_game_cap = 0
    excluded_market = 0
    below_value_floor = 0
    beyond_quote_age = 0
    implausible_book = 0
    stale_kickoff = 0
    uninformative_ev = 0
    for row in opportunities:
        if not _within_horizon(row, reference_now, horizon_days):
            beyond_horizon += 1
            continue
        # A market cannot be pregame after its own start time. Only fires when
        # `game.state` is unusable, so a working state is always left to
        # `opportunity_gate` rather than second-guessed here.
        if stale_kickoff_ceiling > 0 and not _has_usable_game_state(row):
            since_commence = _seconds_since_commence(row, reference_now)
            if since_commence is not None and since_commence > stale_kickoff_ceiling:
                stale_kickoff += 1
                continue
        age_seconds = _row_quote_age_seconds(row)
        # An unknown age is NOT treated as fresh -- same call `_freshness_factor`
        # makes (0.6, not 1.0) and for the same reason: sources that publish no
        # book clock would otherwise pass a bar they were never measured against.
        # It is not excluded either, because absence of a clock is not evidence
        # of staleness; the score already discounts it.
        if age_seconds is not None and age_ceiling > 0 and age_seconds > age_ceiling:
            beyond_quote_age += 1
            continue
        # `#369`: an IMPOSSIBLE BOOK is a bad feed, not an opportunity.
        #
        # `ev_pct` is the no-vig surplus, so the market's implied total is
        # exactly `1 / (1 + ev_pct/100)`. Measured on the served board
        # 2026-08-12 00:11Z: the #1 row was Baltimore +107 AND Minnesota +200 on
        # the same two-way h2h -- 48.3% + 33.3% = 81.6% implied, an 18-point
        # UNDERROUND, which became a 22.49% "edge" and ranked first. 20 of the
        # top 20 were this. `suspect_stale` caught 1 of 63, with quotes up to 84
        # minutes old.
        #
        # THE ARITHMETIC WAS NEVER WRONG -- `edge*100 == ev_pct` on 263 of 263.
        # The board was faithfully ranking bad prices to the top, and because
        # score folds EV in, worse price data ranked higher.
        #
        # This is a magnitude test on `ev_pct` and I said in `#369` not to use
        # one. The distinction that makes it legitimate: the threshold is
        # DERIVED from a stated impossibility (no real book prices a market
        # under `_MIN_IMPLIED_BOOK_TOTAL_PCT`), not chosen to trim the board.
        # A genuine cross-book arb runs 0-3%; 18 points is a broken quote.
        implied_total = _implied_book_total_pct(row.get("ev_pct"))
        if implied_total is not None and implied_total < _MIN_IMPLIED_BOOK_TOTAL_PCT:
            implausible_book += 1
            continue
        # `#400`: excluded market families. Applied HERE, before the per-sport
        # bucket, so an excluded row cannot be re-seated by `kind_floor` or by
        # `per_sport` running short -- the same ordering the value floor and the
        # game cap already follow, and for the same reason.
        market_text = str(row.get("market") or "").strip().lower()
        if excluded_markets and any(token in market_text for token in excluded_markets):
            excluded_market += 1
            continue
        # A0/A3, model audit 2026-08-14: AN EV THAT IS A RESTATEMENT OF THE HOLD
        # IS NOT A MEASUREMENT, AND MUST NOT SEAT A ROW.
        #
        # `book_margin_model` fills fair value on ONE-SIDED rows as
        # `fair = implied x (1 - hold)`. Substitute that into
        # `expected_value_pct` and the price cancels: `ev_pct` is identically
        # `-assumed_hold_pct`. It says nothing about the bet -- only what that
        # book charges on that market family.
        #
        # MEASURED on the served shortlist 2026-08-14: all 100 soccer rows were
        # this, every one with `books_quoting: 1`. Predicting `ev_pct` from
        # `round(implied x (1-h), 4) / implied - 1` reproduced the served value
        # on **100 of 100 rows, 0 mismatches, max abs error 0.0100pt** -- and
        # that residual is the 4-dp rounding of `fair`, which is also why THREE
        # distinct holds presented as NINETEEN distinct `ev_pct` values and
        # looked like a spread. All 100 carried a negative score.
        #
        # The value floor cannot catch them: `_measured_floor_for_pool` derives
        # it from the same modelled hold, so soccer's floor was
        # `-8.1425 = -1.25 x 6.514` against rows whose EV IS -6.514. A filter
        # and its input moving together is not a filter.
        #
        # Excluded only when the row has NO model view. With a projection the
        # `sim_component` is a real signal and the row ranks on something other
        # than the book's margin -- which is the whole distinction. Placed with
        # the other pre-bucket rules so `kind_floor`/`per_sport` cannot re-seat
        # what this rejected.
        if _row_ev_is_hold_restatement(row):
            uninformative_ev += 1
            continue
        sport = str(row.get("sport") or "unknown").strip().lower() or "unknown"
        by_sport.setdefault(sport, []).append(row)

    selected: list[dict[str, Any]] = []
    per_sport_report: dict[str, dict[str, Any]] = {}
    floor_report: dict[str, dict[str, Any]] = {}

    for sport, rows in by_sport.items():
        # PER-SPORT VALUE FLOOR, calibrated from this sport's own pool.
        #
        # Measured here rather than before bucketing for two reasons. It is
        # per-SPORT by definition, and the measurement needs the FULL pool: the
        # shortlist keeps roughly one side of most 3-way soccer markets, so a
        # hold measured downstream would see 1 usable market where the pool has
        # dozens.
        #
        # Still applied BEFORE the kind split below, which is the property that
        # matters: `kind_floor` guarantees slots, so a rejected row left in the
        # pool would be re-seated by the guarantee. That is exactly how 105
        # negative-value rows reached the served board.
        sport_floor, floor_evidence = _measured_floor_for_pool(
            rows, multiple=hold_multiple, fallback=value_floor
        )
        floor_report[sport] = floor_evidence
        # `#383`: judge each row against ITS OWN family's floor. `sport_floor` is
        # the loosest family and is used only for a family we did not measure --
        # never tighten a row on a rule derived from a different market type.
        family_floors = floor_evidence.get("by_family") or {}
        kept: list[Mapping[str, Any]] = []
        for row in rows:
            value_pct = _row_value_pct(row)
            row_floor = family_floors.get(_market_family(row.get("market")), sport_floor)
            if value_pct is not None and value_pct < row_floor:
                below_value_floor += 1
                continue
            kept.append(row)
        rows = kept

        ranked = sorted(rows, key=_score_of, reverse=True)

        # `#391` -- CAP ROWS PER GAME. There was a cap per sport (100) and a
        # floor per kind (30) and nothing per EVENT, so one game could own the
        # whole visible board. Measured 2026-08-12, 200 rows / 36 games: 26 from
        # one WNBA game, 19 from one MLB game, and the first ~14 rows a person
        # saw were a single matchup listed over/under/spread/alt/prop.
        #
        # The aggregate ("200 rows, 36 games") looked healthy, which is why no
        # endpoint check caught it and a screenshot did.
        #
        # **Sorts its own input rather than trusting `ranked`.** A first attempt
        # capped correctly by COUNT but kept each game's worst rows, which is the
        # signature of trimming an unsorted list. One explicit sort here costs
        # nothing and makes "keeps the best" true by construction instead of by
        # assumption about a variable set eight lines up.
        per_game = max(0, int(rows_per_game))
        if per_game:
            seen_per_game: dict[Any, int] = {}
            capped: list[Mapping[str, Any]] = []
            for row in sorted(ranked, key=_score_of, reverse=True):
                # Fall back to the matchup when there is no event_id -- an absent
                # key must not collapse unrelated games into one shared cap.
                key = row.get("event_id") or (
                    row.get("sport"),
                    row.get("home_team"),
                    row.get("away_team"),
                    row.get("commence_time"),
                )
                seen = seen_per_game.get(key, 0)
                if seen >= per_game:
                    beyond_game_cap += 1
                    continue
                seen_per_game[key] = seen + 1
                capped.append(row)
            ranked = capped

        game = [row for row in ranked if str(row.get("kind") or "") == "game"]
        prop = [row for row in ranked if str(row.get("kind") or "") == "prop"]
        other = [row for row in ranked if str(row.get("kind") or "") not in {"game", "prop"}]

        floor = max(0, int(kind_floor))
        limit = max(0, int(per_sport))
        picked: list[Mapping[str, Any]] = []
        picked.extend(game[:floor])
        picked.extend(prop[:floor])

        chosen_ids = {id(row) for row in picked}
        remainder = [row for row in ranked + other if id(row) not in chosen_ids]
        remainder.sort(key=_score_of, reverse=True)
        picked.extend(remainder[: max(0, limit - len(picked))])

        picked = sorted(picked, key=_score_of, reverse=True)[:limit]
        selected.extend(dict(row) for row in picked)
        per_sport_report[sport] = {
            "available": len(rows),
            "selected": len(picked),
            "game": sum(1 for row in picked if str(row.get("kind") or "") == "game"),
            "prop": sum(1 for row in picked if str(row.get("kind") or "") == "prop"),
        }

    selected.sort(key=_score_of, reverse=True)
    return {
        "rows": selected,
        "per_sport": per_sport_report,
        # Only sports with a slate consume budget; the rest contribute nothing.
        "active_sports": sorted(per_sport_report.keys()),
        "per_sport_limit": int(per_sport),
        "kind_floor": int(kind_floor),
        "horizon_days": horizon_days,
        "min_value_pct": value_floor,
        "hold_multiple": hold_multiple,
        "value_floor_by_sport": floor_report,
        "max_quote_age_seconds": age_ceiling,
        "stale_kickoff_seconds": stale_kickoff_ceiling,
        # Logged, not silently dropped: a sport vanishing from the shortlist
        # should be attributable to its schedule rather than look like an outage.
        # Same contract for the two quality floors -- a board that shrinks must
        # say which rule shrank it, or the next reader diagnoses an outage.
        "rows_beyond_horizon": beyond_horizon,
        "rows_below_value_floor": below_value_floor,
        # `#391`. Reported beside the other rejections for the reason `#373`
        # added `rows_implausible_book`: a rule that trims silently is a rule
        # nobody can tell apart from a thin slate.
        "rows_beyond_game_cap": beyond_game_cap,
        "rows_per_game": rows_per_game,
        "rows_excluded_market": excluded_market,
        "excluded_markets": list(excluded_markets),
        # A3. Rows whose `ev_pct` was a restatement of the book's own hold and
        # which carried no model view. Added in the SAME commit as the rule that
        # produces it -- `#397`'s discipline, after three rounds of shipping a
        # working filter with a counter nobody could read. It ALSO has to be
        # added to `/api/board/layer2-shortlist`'s explicit key list in
        # `syndicate/blueprints/intelligence.py`, which is held by another lane;
        # see this lane's entry in `lanes.md`.
        "rows_uninformative_ev": uninformative_ev,
        # `#369`: named separately from the value floor, because "the book is
        # impossible" and "this row is priced below our floor" are different
        # rejections and collapsing them would hide a feed problem as taste.
        # `#373`: the THRESHOLD next to the count, matching how every other rule
        # here reports (`min_value_pct` beside `rows_below_value_floor`). A
        # rejection count without its threshold cannot be judged -- "86 dropped"
        # is alarming or routine depending entirely on the floor that produced it.
        "min_implied_book_total_pct": _MIN_IMPLIED_BOOK_TOTAL_PCT,
        "rows_implausible_book": implausible_book,
        "rows_beyond_quote_age": beyond_quote_age,
        "rows_stale_kickoff": stale_kickoff,
        "persisted_bytes": len(json.dumps(selected, default=str)),
    }
