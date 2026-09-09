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
one: **`_SCORE_SIM_WEIGHT` is 0.125, capped at 1.5 EV points**
(`opportunity_signals.py`, env `SYNDICATE_SCORE_SIM_WEIGHT` /
`SYNDICATE_SCORE_SIM_CAP_PCT`, neither set in production). The board is
**price-led with the sim breaking ties** -- not "our model found these", and not
"the sim contributes nothing" either. The cap is what makes it a screen rather
than a validation: it proves the weight cannot repeat the 2026-08-08 arithmetic
failure (`ev -5, model_edge +12` scored `+1.00` at 0.5 and scores `-3.50` at
0.125-capped), and it proves nothing about whether the sim is RIGHT. That still
needs `settled > 0` and CLV decomposed by component.

**THIS LINE HAS NOW BEEN STALE IN BOTH DIRECTIONS, WHICH IS THE ACTUAL LESSON.**
It said `0.5` while the constant was `0.0` until 2026-08-16, and a session brief
and an audit both inherited `0.5` from here and built on it. The fix at the time
was a note saying "if you change that constant, change this line in the same
commit" -- and then the constant moved to `0.125` and this line went on saying
`0.0` until 2026-09-04, when `portfolio_commit`'s copy of the same claim was
found to be the entire basis of `side_picked_by`'s reasoning.

Measured on the served board 2026-09-04T01:2xZ, 25,830 rows carrying a score
breakdown: **`sim_component` is non-zero on 5,108**, min -1.5000, median 0.2737,
max 1.5000, with 448 rows flagged `sim_capped`.

**SO DO NOT REPAIR THIS BY EDITING THE NUMBER AGAIN.** A comment naming a
constant's VALUE is a copy, and copies drift; the warning not to let them drift
is not a mechanism that stops it. Read the assignment in
`opportunity_signals.py`, then check for an env override on every service that
runs the code. The one-query empirical check is better than either: a non-zero
`sim_component` on any served row falsifies "the sim contributes nothing".

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
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Iterable, Mapping

from syndicate.features.shared import book_shortlist, opportunity_gate
from syndicate.features.shared.book_margin_model import market_family as _market_family
from syndicate.features.shared.odds_book_quotes import _FAIR_PAIR_TOLERANCE_S
from syndicate.features.shared.opportunity_signals import (
    american_price,
    blended_score,
    consensus_fair_probability,
    devig,
    expected_value_pct,
    hold_pct,
)
from syndicate.features.shared.probability_refusal import refuse_published_certainty
from syndicate.features.shared.sharp_books import EXCHANGE_ANCHOR_PRIORITY, SHARP_ANCHOR_PRIORITY

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
def _shortlist_rows_per_sport() -> int:
    """How many rows per sport reach the persisted board. Env-overridable.

    RAISED 100 -> 400 `[user decision, 2026-08-22: "we should let everything
    flow"]`, and NOT removed, because removing it breaks the board outright.

    THE BINDING CONSTRAINT IS THE KEYVALUE WRITE, NOT READABILITY. The original
    comment sized this as "a readability bound, not a memory bound" against a
    2.4MB state. The real ceiling is `refresh_state_store._keyvalue_max_bytes`
    = **8MB**, and that number is itself measured rather than chosen: an
    intelligence state at 8.9MB reproducibly gets "Connection closed by server".

    So the arithmetic, at the ~1.0 KB/row measured on production 2026-08-07:

        100/sport x 4 active   ~0.4 MB    (today)
        400/sport x 4 active   ~1.6 MB    (this change)
        400/sport x 8 active   ~3.2 MB    (a full winter slate)
        UNCAPPED               soccer ALONE is 20,025 grid rows, ~20 MB

    Uncapped is not a bigger board, it is a board that fails to persist and
    therefore serves nothing. 400 keeps a full eight-sport slate under half the
    ceiling while quadrupling what a reader sees.

    `persisted_bytes` is already reported on every build and is now checked
    against the ceiling below, so the next raise can be made on a reading
    instead of on this arithmetic.
    """
    raw = str(os.environ.get("SYNDICATE_LAYER2_ROWS_PER_SPORT") or "").strip()
    try:
        value = int(raw) if raw else 400
    except ValueError:
        value = 400
    # Floor of 1: a zero or negative override would empty the board silently,
    # which is the failure mode every other bound in this file guards against.
    return max(1, value)


SHORTLIST_ROWS_PER_SPORT = _shortlist_rows_per_sport()


def _shortlist_rows_total() -> int:
    """The WHOLE board's row budget, across every sport. Env-overridable.

    WHY A TOTAL AS WELL AS A PER-SPORT CAP (`#525`). The binding constraint is
    one keyvalue write, and that write does not care how the rows are divided --
    but `per_sport` scales the payload with the number of sports IN SEASON,
    which is a calendar fact nobody sets and nobody reviews.

    Measured on production 2026-08-23T00:0xZ, four sports at the 400 cap:

        LAYER2_SHORTLIST rows=1600
        KEYVALUE_WRITE_LARGE size_bytes=5,747,257  max_bytes=8,388,608   68.5%

    That is 3,592 bytes/row and ~735 rows of headroom -- less than two more
    sports at cap. NCAAF opens ~08-29 (-> ~7.19MB, 86%) and NCAAB in November
    (-> breach). The cliff is on the CALENDAR, so it arrives whether or not
    anyone touches this file, and it arrives as a silent board freeze: the
    write raises, both call sites catch it, and the board serves its last good
    copy forever.

    A total budget removes the cliff by construction -- a fifth in-season sport
    redistributes the same 1,600 rows instead of adding 400 more. Default is
    exactly today's measured board so this change is a NO-OP on a four-sport
    slate and only ever binds when a fifth arrives.

    `per_sport` stays and stays a CEILING: it is what stops one sport with
    20,025 grid rows from taking the whole budget on a quiet day.
    """
    raw = str(os.environ.get("SYNDICATE_LAYER2_ROWS_TOTAL") or "").strip()
    try:
        value = int(raw) if raw else 1600
    except ValueError:
        value = 1600
    # Same reasoning as the per-sport floor: a zero would empty the board.
    return max(1, value)


SHORTLIST_ROWS_TOTAL = _shortlist_rows_total()


def allocate_row_budget(
    available: Mapping[str, int], *, total: int, per_sport: int, minimum: int = 0
) -> dict[str, int]:
    """Split `total` across sports by water-filling. Pure, so it is testable.

    THE NAIVE SPLIT WASTES THE BUDGET. `total // n` gives every sport the same
    allowance whether it has 2,000 rows to offer or 23 -- measured tonight, NFL
    held 275 of a 400 allowance while soccer had 20,025 grid rows and was capped.
    A fifth sport would then shrink the four that can fill their share in order
    to hand slots to one that cannot.

    So: give every sport the smaller of its fair share and what it actually has,
    then re-divide what the small sports could not use among the ones still
    asking. Repeat until nothing moves. Converges in at most one round per sport
    because each round either exhausts the budget or satisfies a sport for good.

    `per_sport` is a hard ceiling per sport and `minimum` a floor, both applied
    inside the loop so redistribution can never push a sport past either.
    """
    slugs = [str(slug) for slug in available]
    if not slugs:
        return {}
    ceiling = max(0, int(per_sport))
    floor = max(0, int(minimum))
    remaining = max(0, int(total))
    allocation: dict[str, int] = {slug: 0 for slug in slugs}
    # Sorted for determinism: the remainder of an uneven split has to land
    # somewhere, and it must land in the same place on every build or two
    # identical pools would produce two different boards.
    open_slugs = sorted(slugs)

    while open_slugs and remaining > 0:
        share = remaining // len(open_slugs)
        if share <= 0:
            # Fewer rows left than sports still asking. Hand them out one each,
            # in the same deterministic order, rather than dropping them.
            for slug in open_slugs[:remaining]:
                want = min(int(available.get(slug, 0)), ceiling)
                if allocation[slug] < want:
                    allocation[slug] += 1
                    remaining -= 1
            break
        still_open: list[str] = []
        for slug in open_slugs:
            want = min(int(available.get(slug, 0)), ceiling)
            grant = min(share, max(0, want - allocation[slug]))
            allocation[slug] += grant
            remaining -= grant
            if allocation[slug] < want:
                still_open.append(slug)
        if still_open == open_slugs and share == 0:
            break
        if not still_open:
            break
        if len(still_open) == len(open_slugs) and remaining <= 0:
            break
        open_slugs = still_open

    if floor:
        for slug in slugs:
            want = min(int(available.get(slug, 0)), ceiling)
            allocation[slug] = max(allocation[slug], min(floor, want))
    return allocation

# Each kind is guaranteed this many slots before merit takes over.
#
# A pure score ranking would not mix: MLB carries 1,221 prop rows against 229
# game rows, so props would plausibly take all 50 and the game board would
# vanish. A hard 25/25 is the opposite error -- it would drop a clearly better
# prop to seat a worse game line. Floor-then-merit gets the mix without paying
# for it in quality, and an unused floor flows to the other kind rather than
# being wasted on a sport that has only one.
SHORTLIST_KIND_FLOOR = 30

# Slots guaranteed to rows kicking off ON the board's own date, before merit
# takes over. Env: SYNDICATE_SHORTLIST_IMMINENCE_FLOOR. 0 disables.
#
# THE RANKING HAS NO NOTION OF WHEN A GAME STARTS. `_score_of` is pure EV/model
# merit, so a sport whose horizon spans several days competes today's slate
# against every future fixture in the window on equal terms -- and loses,
# because there are simply more future rows.
#
# MEASURED on the served shortlist 2026-08-21, soccer, 100 rows: **4** were for
# that day's four fixtures and 96 were dated 08-22 through 08-27. One of the
# four -- Marseille v Strasbourg, kicking off in three hours -- had ZERO rows,
# while Newcastle v Liverpool the following day held 6. The board a person opens
# to bet today's slate was 96% about other days.
#
# This is deliberately a FLOOR and not a re-ranking: today's rows are seated
# first, then merit fills the rest exactly as before, so a genuinely better
# future row still makes the board. Sized under the kind floors so the two
# guarantees together cannot consume the per-sport budget. An unused floor
# flows to merit rather than being wasted, the same way `kind_floor` behaves
# for a sport with only one kind.
SHORTLIST_IMMINENCE_FLOOR = 25

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
    """The value this row is ADMITTED on, in EV points.

    **Prefers the BLENDED value, not raw `ev_pct`** `[changed 2026-08-22, user
    decision]`. This used to read `ev_pct` first and fall back to
    `score.value_pct` only when EV was absent -- and `ev_pct` is present on
    essentially every scored row, so the fallback almost never fired. The
    consequence was that the simulation could REORDER the board (`_score_of`
    ranks on `score.score`) but could never get a row ONTO it: admission was
    decided by price alone, upstream of anything the sim had to say.

    `score.value_pct` is `ev_pct` + the capped sim term + the capped movement
    term, all three in EV points, so it is unit-comparable with the
    hold-derived floor it is tested against -- which is the only reason this
    substitution is legitimate rather than a category error.

    **What this can and cannot do is bounded by the same cap as everything
    else.** The sim may carry a row across the value floor by at most
    `_SCORE_SIM_CAP_PCT` (1.5 EV points), so it can rescue a row that was
    marginally below and can never rescue a materially bad price. That bound is
    the whole reason admission can be handed to the blend at all: an uncapped
    sim term here would let an unvalidated model admit arbitrarily bad prices,
    which is the 2026-08-08 failure with a wider blast radius than ranking.

    Falls back to `ev_pct` when there is no score block, so a row that was never
    scored is judged exactly as before.
    """
    score = row.get("score")
    if isinstance(score, Mapping):
        blended = _as_float(score.get("value_pct"))
        if blended is not None:
            return blended
    return _as_float(row.get("ev_pct"))


def _row_admitted_by_blend(row: Mapping[str, Any], floor: float) -> bool:
    """True when the blend cleared the floor and raw EV would not have.

    Counted and reported, because a rule that changes what reaches the board
    silently is one nobody can tell apart from a different slate -- this file's
    own repeated lesson (`rows_implausible_book`, `rows_uninformative_ev`,
    `#373`, `#381`, `#397`). It is also the direct measure of the change the
    2026-08-22 scoring re-evaluation was made for: how many rows the simulation
    actually put on the board.
    """
    raw_ev = _as_float(row.get("ev_pct"))
    if raw_ev is None or raw_ev >= floor:
        return False
    blended = _row_value_pct(row)
    return blended is not None and blended >= floor


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


def _canonical_team_key(sport: str, name: str) -> str | None:
    """Canonical club name for the chip join, or None if unresolvable.

    Deliberately swallowing: this feeds a DISPLAY join. A club the alias map
    has never heard of must degrade to the existing name-based lookups, not
    take out the row it is stamped on.

    `chip_join_key`, NOT `canonical_team` -- the SAME function
    `game_chip_scoreboard._side_key` stamps the chip half with, so the two ends
    of this join cannot resolve on different vocabularies. It adds NCAAF, whose
    `_alias_map` is empty on purpose; see its docstring for why filling that map
    instead would be a regression.
    """
    if not sport or not name:
        return None
    try:
        from syndicate.features.shared.team_aliases import chip_join_key

        return chip_join_key(sport, name)
    except Exception:
        return None


#: `SYNDICATE_FAIR_ANCHOR` -- WHAT THE BOARD'S FAIR PROBABILITY IS ANCHORED TO.
#:
#:   median  (default)  today's behaviour, bit for bit: de-vig every book against
#:                      itself and take the MEDIAN per selection (`#384`).
#:   sharp              try a SHARP book's own two-sided market first
#:                      (`sharp_books.SHARP_ANCHOR_PRIORITY`: Pinnacle), then a
#:                      two-sided EXCHANGE mid (`EXCHANGE_ANCHOR_PRIORITY`) --
#:                      GATED, see below -- and only then the median chain,
#:                      unchanged.
#:   sharp_only         the Pinnacle tier, then straight to the median chain. No
#:                      exchange tier at all.
#:
#: Read per call rather than at import, for the same reason
#: `_model_value_term_mode` is: a test flips it with `monkeypatch`, and a worker
#: picks up an env change on its next build.
FAIR_ANCHOR_ENV = "SYNDICATE_FAIR_ANCHOR"
FAIR_ANCHOR_MEDIAN = "median"
FAIR_ANCHOR_SHARP = "sharp"
FAIR_ANCHOR_SHARP_ONLY = "sharp_only"
_FAIR_ANCHOR_MODES: tuple[str, ...] = (FAIR_ANCHOR_MEDIAN, FAIR_ANCHOR_SHARP, FAIR_ANCHOR_SHARP_ONLY)

#: THE EXCHANGE TIER'S TWO GATES (P1b). Measured on the first `sharp` board
#: (refresh-worker d8ed991a, 2026-09-08 23:10Z, 2,000 rows, 331 anchored):
#: Pinnacle's mean |sharp - median| was 0.885 pp with ONE row past 5 pp;
#: Kalshi's was 2.699 pp with SEVENTEEN, and the ten largest gaps on the board
#: were all `exchange_mid` -- nine Kalshi MLB totals at deep or in-play lines
#: (under 3.5: fair 0.093 against a median of 0.380), one Polymarket prop with
#: `books=1`. A wide or thin two-sided exchange quote has a mid; that mid is not
#: a fair. So an exchange pair anchors only when it is BOTH:
#:
#:   TIGHT         its own two-side hold (`opportunity_signals.hold_pct`, the
#:                 same figure the board publishes as a book's margin) is at
#:                 most `SYNDICATE_FAIR_EXCHANGE_MAX_HOLD_PCT` (default 4.0 --
#:                 under the canonical -110/-110 book's 4.55%, so a quote no
#:                 tighter than a soft book cannot outrank the soft-book
#:                 median). Refused as `exchange_hold_too_wide`.
#:   CORROBORATED  the row's `books_quoting` -- the grid's count of books with
#:                 a fresh price on the side, the exchange itself included -- is
#:                 at least `SYNDICATE_FAIR_EXCHANGE_MIN_BOOKS` (default 3). A
#:                 lone exchange with nobody else on the line is refused as
#:                 `exchange_uncorroborated`. Unknown counts are refused, not
#:                 admitted. The PINNACLE tier is exempt on purpose: Pinnacle is
#:                 the corroboration, and its one `>5pp` row does not justify a
#:                 gate on the tier the flag was built for.
#:
#: A refused row falls through to the consensus chain exactly as if no exchange
#: had quoted, and carries `fair_anchor_refusal` naming the gate. Both tiers
#: carry `fair_anchor_hold_pct` so the next reading can be cut by hold without
#: a rerun.
FAIR_EXCHANGE_MAX_HOLD_PCT_ENV = "SYNDICATE_FAIR_EXCHANGE_MAX_HOLD_PCT"
FAIR_EXCHANGE_MAX_HOLD_PCT_DEFAULT = 4.0
FAIR_EXCHANGE_MIN_BOOKS_ENV = "SYNDICATE_FAIR_EXCHANGE_MIN_BOOKS"
FAIR_EXCHANGE_MIN_BOOKS_DEFAULT = 3
FAIR_ANCHOR_REFUSAL_HOLD_TOO_WIDE = "exchange_hold_too_wide"
FAIR_ANCHOR_REFUSAL_UNCORROBORATED = "exchange_uncorroborated"

#: P1c -- THE PINNACLE TIER'S TWO GATES AND THE EXCHANGE TIER'S THIRD. Three
#: production readings, all refresh-worker served boards of 2,000 rows:
#:
#:   2026-09-09 00:04Z `sharp` + P1b     Kalshi SURVIVORS of the hold and
#:                                       corroboration gates: n=66, mean
#:                                       |mid - median| 3.089 pp, 14 rows past
#:                                       5 pp, at a mean hold of 1.41%. The hold
#:                                       gate removed rows without selecting the
#:                                       accurate ones -- TIGHT BUT WRONG. A
#:                                       tight pair is not evidence the pair is
#:                                       ON the market the soft books price.
#:                                       Pinnacle the same night: n=60, 1.640 pp,
#:                                       3 past 5 pp, holds up to 7.26% at
#:                                       midnight on an in-play slate.
#:   2026-09-09 00:55Z `sharp_only`      Pinnacle n=203, mean 1.136 pp, p90 2.11,
#:                                       2 rows past 5 pp -- BOTH in-play MLB
#:                                       `spreads_alt` with `books=1` (Pinnacle
#:                                       the lone book on the line) at a 5.8%
#:                                       hold. NCAAF pregame n=124 at 1.027;
#:                                       MLB in-play n=79 at 1.307.
#:
#: So the Pinnacle tier now refuses a pair that is either
#:
#:   WIDE            own hold over `SYNDICATE_FAIR_SHARP_MAX_HOLD_PCT` (default
#:                   5.0 -- above the exchange's 4.0 on purpose: Pinnacle's
#:                   normal pregame margin sits at 2-3%, and 5.0 admits every
#:                   row of the 00:55Z reading except the two it was built to
#:                   stop). Refused as `sharp_hold_too_wide`.
#:   ALONE IN-PLAY   the row is live (`_row_is_live`: the grid's `game.state`,
#:                   the same field `build_layer2_rows` translates to
#:                   `is_live` on the candidate) and its `books_quoting` is
#:                   under `SYNDICATE_FAIR_SHARP_MIN_BOOKS_LIVE` (default 2).
#:                   Refused as `sharp_uncorroborated_live`. PREGAME Pinnacle
#:                   with `books=1` still anchors: a pregame Pinnacle line IS
#:                   the corroboration, and P1b's reading rests on exactly that.
#:                   In-play, an alt line only Pinnacle posts is a line the
#:                   market has not yet found, and a 5.8% hold on it says
#:                   Pinnacle knows so. An unknown count on a live row is
#:                   refused, not admitted.
#:
#: and the exchange tier, AFTER hold and corroboration, refuses a pair whose
#: power-de-vigged mid sits more than `SYNDICATE_FAIR_EXCHANGE_MAX_MEDIAN_GAP_PP`
#: (default 3.0 pp) from the consensus median on any side -- refused as
#: `exchange_far_from_median`. An exchange mid inside 3 pp of the median is a
#: sharper estimate of the SAME thing; one far outside is either a stale or
#: thin contract or an alt line the soft books are not on, and the readings
#: could not tell which -- so neither may anchor until CLV says otherwise. When
#: the row has no median to check against (fewer than two two-sided books in
#: `cells`) the pair is refused as `exchange_no_median_to_check`: unknown does
#: not default permissive, and a "median" of one book is not a median.
#:
#: THE PINNACLE TIER IS DELIBERATELY FREE OF THE DISTANCE GATE. A Pinnacle-vs-
#: median gap is the signal the whole flag exists to surface -- the sharp book
#: disagreeing with the soft consensus is where the edge is -- and gating it
#: on that distance would define the anchor back into the median. Pinnacle is
#: gated on its OWN quality (hold, in-play corroboration) and nothing else.
#:
#: STAMPS. `fair_anchor_refusal` names the FIRST refusal in tier order
#: (Pinnacle, then each exchange in priority order) on a row where no tier
#: anchored; `fair_anchor_refusals` lists EVERY refusal that fired, on every
#: row, including an anchored one where Pinnacle was passed over;
#: `fair_anchor_median_gap_pp` is the anchor's gap to the median on an
#: anchored row and the first refused candidate's otherwise. All None under
#: `median`. A refused Pinnacle falls through to the exchange tier (when the
#: mode has one) and then to consensus, exactly as if Pinnacle had not quoted.
FAIR_SHARP_MAX_HOLD_PCT_ENV = "SYNDICATE_FAIR_SHARP_MAX_HOLD_PCT"
FAIR_SHARP_MAX_HOLD_PCT_DEFAULT = 5.0
FAIR_SHARP_MIN_BOOKS_LIVE_ENV = "SYNDICATE_FAIR_SHARP_MIN_BOOKS_LIVE"
FAIR_SHARP_MIN_BOOKS_LIVE_DEFAULT = 2
FAIR_EXCHANGE_MAX_MEDIAN_GAP_PP_ENV = "SYNDICATE_FAIR_EXCHANGE_MAX_MEDIAN_GAP_PP"
FAIR_EXCHANGE_MAX_MEDIAN_GAP_PP_DEFAULT = 3.0
FAIR_ANCHOR_REFUSAL_SHARP_HOLD_TOO_WIDE = "sharp_hold_too_wide"
FAIR_ANCHOR_REFUSAL_SHARP_UNCORROBORATED_LIVE = "sharp_uncorroborated_live"
FAIR_ANCHOR_REFUSAL_FAR_FROM_MEDIAN = "exchange_far_from_median"
FAIR_ANCHOR_REFUSAL_NO_MEDIAN = "exchange_no_median_to_check"

#: The two anchor tiers, as `_anchored_fair` tells them apart. Each names the
#: refusal its hold gate and its corroboration gate emit, so one loop serves
#: both tiers without a `sharp_` row ever reading `exchange_uncorroborated`.
_ANCHOR_TIER_SHARP = "sharp"
_ANCHOR_TIER_EXCHANGE = "exchange"
_TIER_REFUSALS: dict[str, dict[str, str]] = {
    _ANCHOR_TIER_SHARP: {
        "hold": FAIR_ANCHOR_REFUSAL_SHARP_HOLD_TOO_WIDE,
        "books": FAIR_ANCHOR_REFUSAL_SHARP_UNCORROBORATED_LIVE,
    },
    _ANCHOR_TIER_EXCHANGE: {
        "hold": FAIR_ANCHOR_REFUSAL_HOLD_TOO_WIDE,
        "books": FAIR_ANCHOR_REFUSAL_UNCORROBORATED,
    },
}

#: Game states that AFFIRM the game is in progress, for the Pinnacle tier's
#: in-play corroboration gate. Narrower than `_STARTED_GAME_STATES` on purpose:
#: a final game is not in play, and an unrecognised or absent state is not
#: affirmed live -- it takes the pregame rule (a lone Pinnacle anchors), which
#: is the rule P1b's reading validated and the one `game_state_of` resolves
#: the ambiguous rest to.
_LIVE_GAME_STATES = frozenset({"live", "in", "in_progress", "inprogress"})

#: `SYNDICATE_FAIR_DEVIG_METHOD` -- the de-vig applied INSIDE EACH BOOK on the
#: consensus chain: `multiplicative` (default) or `power`. Independent of the
#: anchor. The median can be taken over power-de-vigged books with no sharp
#: anchor at all, and the anchor tiers are power-de-vigged regardless of this.
FAIR_DEVIG_METHOD_ENV = "SYNDICATE_FAIR_DEVIG_METHOD"
_FAIR_DEVIG_METHODS: tuple[str, ...] = ("multiplicative", "power")

#: The anchor tiers' de-vig. POWER, because an anchor is ONE book, and a single
#: book puts more of its margin on the longshot side than on the favourite --
#: multiplicative would leave the longshot's fair overstated. The median chain
#: is robust to that by construction (many books, middle value); one book is
#: not. See `opportunity_signals.devig`.
_ANCHOR_DEVIG_METHOD = "power"

#: `fair_method` labels for the two anchor tiers. Distinct from `consensus` so
#: a fair that is ONE book's opinion can never be read as a market median.
FAIR_METHOD_SHARP_ANCHOR = "sharp_anchor"
FAIR_METHOD_EXCHANGE_MID = "exchange_mid"


def _fair_anchor_mode() -> str:
    raw = str(os.environ.get(FAIR_ANCHOR_ENV) or "").strip().lower()
    return raw if raw in _FAIR_ANCHOR_MODES else FAIR_ANCHOR_MEDIAN


def _fair_devig_method() -> str:
    raw = str(os.environ.get(FAIR_DEVIG_METHOD_ENV) or "").strip().lower()
    return raw if raw in _FAIR_DEVIG_METHODS else _FAIR_DEVIG_METHODS[0]


def _fair_exchange_max_hold_pct() -> float:
    """`SYNDICATE_FAIR_EXCHANGE_MAX_HOLD_PCT`; the default on absent or unparseable."""
    value = _as_float(os.environ.get(FAIR_EXCHANGE_MAX_HOLD_PCT_ENV))
    return value if value is not None and value >= 0.0 else FAIR_EXCHANGE_MAX_HOLD_PCT_DEFAULT


def _fair_exchange_min_books() -> int:
    """`SYNDICATE_FAIR_EXCHANGE_MIN_BOOKS`; the default on absent or unparseable."""
    value = _as_float(os.environ.get(FAIR_EXCHANGE_MIN_BOOKS_ENV))
    return int(value) if value is not None and value >= 1.0 else FAIR_EXCHANGE_MIN_BOOKS_DEFAULT


def _fair_sharp_max_hold_pct() -> float:
    """`SYNDICATE_FAIR_SHARP_MAX_HOLD_PCT`; the default on absent or unparseable."""
    value = _as_float(os.environ.get(FAIR_SHARP_MAX_HOLD_PCT_ENV))
    return value if value is not None and value >= 0.0 else FAIR_SHARP_MAX_HOLD_PCT_DEFAULT


def _fair_sharp_min_books_live() -> int:
    """`SYNDICATE_FAIR_SHARP_MIN_BOOKS_LIVE`; the default on absent or unparseable."""
    value = _as_float(os.environ.get(FAIR_SHARP_MIN_BOOKS_LIVE_ENV))
    return int(value) if value is not None and value >= 1.0 else FAIR_SHARP_MIN_BOOKS_LIVE_DEFAULT


def _fair_exchange_max_median_gap_pp() -> float:
    """`SYNDICATE_FAIR_EXCHANGE_MAX_MEDIAN_GAP_PP`; the default on absent or unparseable."""
    value = _as_float(os.environ.get(FAIR_EXCHANGE_MAX_MEDIAN_GAP_PP_ENV))
    return value if value is not None and value >= 0.0 else FAIR_EXCHANGE_MAX_MEDIAN_GAP_PP_DEFAULT


@dataclass(frozen=True)
class _FairResolution:
    """What `_resolve_fair` decided, with everything needed to audit it per row."""

    fair_by_side: dict[str, float]
    method: str | None
    #: The ONE book whose own sides produced `fair_by_side` (an anchor tier, or
    #: the same-book fallback). None on the consensus chain, where no single
    #: book did, and on the margin model.
    anchor_book: str | None
    #: The de-vig that produced `fair_by_side`: `power` on an anchor tier, the
    #: `SYNDICATE_FAIR_DEVIG_METHOD` value on the consensus chain, None when the
    #: fair came from the margin model or from nothing.
    devig_method: str | None
    #: The MEDIAN consensus that applies under `median` -- computed on EVERY row
    #: regardless of mode, so a sharp-vs-median gap is measurable per row from
    #: the served payload without a rerun. Empty when no book quotes every side.
    consensus_by_side: dict[str, float]
    #: The two-side hold (pp) of the pair the anchor tiers EVALUATED: the
    #: anchor's own when a tier anchored, the first refused exchange's when
    #: `anchor_refusal` is set, None when no anchor pair was ever fresh (and
    #: always None under `median`). Read it with `method`/`anchor_refusal`; a
    #: value on a `consensus` row means an exchange was looked at and refused.
    anchor_hold_pct: float | None = None
    #: Why NO tier anchored although a candidate quoted both sides fresh: the
    #: FIRST refusal in tier order (Pinnacle, then each exchange by priority) --
    #: `sharp_hold_too_wide`, `sharp_uncorroborated_live`,
    #: `exchange_hold_too_wide`, `exchange_uncorroborated`,
    #: `exchange_far_from_median` or `exchange_no_median_to_check`. None when a
    #: tier anchored (a non-None value means "on consensus BECAUSE of a gate"),
    #: when no candidate pair was fresh, and under `median`.
    anchor_refusal: str | None = None
    #: P1c. EVERY refusal that fired on the row, in tier order, including on an
    #: anchored row where Pinnacle was refused and an exchange took it -- so
    #: the next reading can count "exchange_mid rows that exist because
    #: Pinnacle was gated" without a rerun. An empty tuple under an anchor mode
    #: where nothing was refused; None under `median`, where no tier ran.
    anchor_refusals: tuple[str, ...] | None = None
    #: P1c. The distance in pp between the pair the anchor tiers evaluated and
    #: `consensus_by_side` -- the anchor's on an anchored row, the first refused
    #: candidate's otherwise (`max` over sides; equal on both sides of a two-way
    #: market). None when no candidate pair was fresh or de-viggable, when the
    #: row has no consensus, and under `median`.
    anchor_median_gap_pp: float | None = None


@dataclass(frozen=True)
class _AnchorAttempt:
    """One tier's verdict: an anchor, or the reason the best candidate was refused.

    `refusal`, `hold_pct` and `median_gap_pp` describe the anchor when
    `anchored`, else the FIRST refused pair in priority order; `refusals` is
    every refusal the tier emitted, one per refused pair, in that order.
    """

    fair_by_side: dict[str, float] | None
    book: str | None
    hold_pct: float | None
    refusal: str | None
    median_gap_pp: float | None = None
    refusals: tuple[str, ...] = ()

    @property
    def anchored(self) -> bool:
        return self.fair_by_side is not None and self.book is not None


_NO_ANCHOR = _AnchorAttempt(None, None, None, None)


def _two_sided_prices_by_book(cells: Any, sides: list[str]) -> dict[str, dict[str, Any]]:
    """The books in `cells` quoting EVERY side, as {book: {side: price}}.

    The filter half of `_consensus_fair`, split out (P1c) so the exchange
    tier's distance gate can ask HOW MANY books the median rests on without
    re-deriving the filter. Same code, same answer.
    """
    if not isinstance(cells, Mapping):
        return {}
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
    return prices_by_book


def _consensus_fair(cells: Any, sides: list[str], *, method: str) -> dict[str, float]:
    """`#384`: de-vig EACH BOOK against itself, then the MEDIAN across books.

    The body is the consensus branch of `_fair_by_side` as it stood before the
    anchor tiers existed, moved here verbatim so the default path is unchanged
    and so the anchor mode can compute the median it did NOT use.
    """
    prices_by_book = _two_sided_prices_by_book(cells, sides)
    if prices_by_book:
        consensus = consensus_fair_probability(prices_by_book, method=method)
        if consensus and len(consensus) == len(sides):
            return {str(side): value for side, value in consensus.items()}
    return {}


def _anchor_pair(cells: Mapping[str, Any], book: str, sides: list[str]) -> list[float] | None:
    """`book`'s OWN price on every side, if it quoted them all together.

    None -- and the caller tries the next book -- when any side is missing, any
    cell is flagged `stale` by the grid, any cell's age is unknown, or the sides
    were observed more than `_FAIR_PAIR_TOLERANCE_S` apart (the same 600s
    `odds_book_quotes._fair_value_fields` enforces, imported rather than
    restated). Unknown is REFUSED, not admitted: an anchor is one book standing
    in for the whole market, and `learnings.md`'s rule that unknown must not
    default permissive applies with full force to the number every EV on the
    row is measured against.

    The age is `age_seconds`, which BOTH cell writers stamp -- `book_grid` from
    `observed_at`, `venue_quote_fanin._reprice_live_benchmark` from the venue
    quote -- so a venue cell and an OddsAPI cell are judged on the same field.
    """
    sides_map = cells.get(book)
    if not isinstance(sides_map, Mapping):
        return None
    prices: list[float] = []
    ages: list[float] = []
    for side in sides:
        cell = sides_map.get(side)
        if not isinstance(cell, Mapping) or cell.get("stale") is True:
            return None
        price = _as_float(cell.get("price"))
        age = _as_float(cell.get("age_seconds"))
        if price is None or age is None:
            return None
        prices.append(price)
        ages.append(age)
    if len(prices) < 2 or (max(ages) - min(ages)) > _FAIR_PAIR_TOLERANCE_S:
        return None
    return prices


def _row_books_quoting(row: Mapping[str, Any], sides: list[str]) -> int | None:
    """The grid's fresh-book count for the row; None when it carries none.

    `book_grid` stamps `books_quoting` on the row (books with any fresh price)
    and on each side's `best` (books fresh on THAT side). The row-level count is
    the corroboration question -- how many books are on this line at all -- and
    the per-side counts are the fallback for a row built without it.
    """
    count = _as_float(row.get("books_quoting"))
    if count is None:
        best = row.get("best") or {}
        per_side = [_as_float((best.get(side) or {}).get("books_quoting")) for side in sides]
        known = [value for value in per_side if value is not None]
        count = max(known) if known else None
    return int(count) if count is not None else None


def _row_is_live(row: Mapping[str, Any]) -> bool:
    """Does the row AFFIRM its game is in play? P1c's in-play corroboration gate.

    Reads the grid's `game.state` -- the field `build_layer2_rows` translates
    into the candidate's `game_state`/`is_live` AFTER `_resolve_fair` has run,
    so at this point it is the only place the state lives on a grid row -- and
    the top-level `game_state` / `market_state` / `is_live` for a row handed
    in already translated. Only a recognised in-play token (or `is_live` True)
    is live; absent, `pregame`, `final` and anything unrecognised are NOT, and
    take the pregame rule. That direction is chosen, not defaulted: the
    pregame rule is the stricter tier's OWN validated behaviour (a lone
    pregame Pinnacle anchors), so an unknown state gains nothing from being
    called live except a refusal the readings do not support.
    """
    game = row.get("game")
    state = str((game or {}).get("state") or "") if isinstance(game, Mapping) else ""
    if not state:
        state = str(row.get("game_state") or row.get("market_state") or "")
    if state.strip().lower() in _LIVE_GAME_STATES:
        return True
    return row.get("is_live") is True


def _median_gap_pp(fair_by_side: Mapping[str, float], consensus: Mapping[str, float]) -> float | None:
    """|anchor - median| in pp, the LARGEST over the sides both carry.

    On a two-way market the sides move together and the two gaps are equal; on
    a three-way one the widest leg is the one the gate should see. None when
    the two share no side -- there is no median to be far from.
    """
    gaps = [
        abs(float(fair_by_side[side]) - float(consensus[side])) * 100.0
        for side in fair_by_side
        if side in consensus
    ]
    return max(gaps) if gaps else None


def _anchored_fair(
    cells: Any,
    sides: list[str],
    books: tuple[str, ...],
    *,
    tier: str,
    max_hold_pct: float | None = None,
    min_books: int | None = None,
    books_quoting: int | None = None,
    consensus: Mapping[str, float] | None = None,
    max_median_gap_pp: float | None = None,
    consensus_books: int = 0,
) -> _AnchorAttempt:
    """The first book in `books` quoting every side fresh, power-de-vigged.

    Returns an `_AnchorAttempt` that is anchored, or one carrying the refusals
    when no book in the tier qualifies -- including when `devig` refuses the
    pair's overround, which is evidence the legs are not one market and must
    not become an anchor (that pair is skipped, not named: nothing was
    evaluated against a gate).

    THE GATES apply only when the caller passes them; `tier` picks the
    refusal names (`_TIER_REFUSALS`) so the Pinnacle tier's hold refusal reads
    `sharp_hold_too_wide` and the exchange tier's `exchange_hold_too_wide`.
    In the order applied to each fresh pair:

      `min_books`          the row's `books_quoting` must reach it, or the pair
                           is the tier's `books` refusal
                           (`sharp_uncorroborated_live` /
                           `exchange_uncorroborated`). The Pinnacle tier's
                           caller passes it ONLY on a live row. A None count is
                           unknown, and unknown is refused.
      `max_hold_pct`       the pair's own `hold_pct` must not exceed it, or the
                           pair is the tier's `hold` refusal.
      `max_median_gap_pp`  (exchange tier only -- see the P1c block for why
                           Pinnacle is exempt) the power-de-vigged pair must
                           sit within it of `consensus` on every side, or it is
                           `exchange_far_from_median`; and `consensus_books`
                           must be at least 2 for there to BE a median, or it
                           is `exchange_no_median_to_check`.

    A refused pair does not end the tier -- a tighter or closer venue further
    down the priority may still anchor -- but if none does, the attempt
    carries the FIRST refusal in priority order with that pair's hold and
    median gap, so the row can say which gate stopped the deepest venue that
    quoted it. `refusals` carries every refusal in order, one per refused pair.

    The median gap is computed for EVERY fresh pair, refused or not, so a
    `sharp_hold_too_wide` row still stamps how far Pinnacle sat from the
    median -- that gap is the reading the next tuning pass needs.
    """
    if not isinstance(cells, Mapping):
        return _NO_ANCHOR
    refusals: list[str] = []
    refused_hold: float | None = None
    refused_gap: float | None = None
    names = _TIER_REFUSALS[tier]

    def _refuse(name: str, hold: float | None, gap: float | None) -> None:
        nonlocal refused_hold, refused_gap
        if not refusals:
            refused_hold, refused_gap = hold, gap
        refusals.append(name)

    for book in books:
        prices = _anchor_pair(cells, book, sides)
        if prices is None:
            continue
        hold = hold_pct(prices)
        probabilities = devig(prices, method=_ANCHOR_DEVIG_METHOD)
        fair_by_side = (
            {str(side): probabilities[i] for i, side in enumerate(sides)}
            if probabilities and len(probabilities) == len(sides)
            else None
        )
        gap = _median_gap_pp(fair_by_side, consensus) if fair_by_side and consensus else None
        if min_books is not None and (books_quoting is None or books_quoting < min_books):
            _refuse(names["books"], hold, gap)
            continue
        if max_hold_pct is not None and (hold is None or hold > max_hold_pct):
            _refuse(names["hold"], hold, gap)
            continue
        if fair_by_side is None:
            continue
        if max_median_gap_pp is not None:
            if consensus_books < 2 or gap is None:
                _refuse(FAIR_ANCHOR_REFUSAL_NO_MEDIAN, hold, gap)
                continue
            if gap > max_median_gap_pp:
                _refuse(FAIR_ANCHOR_REFUSAL_FAR_FROM_MEDIAN, hold, gap)
                continue
        return _AnchorAttempt(fair_by_side, book, hold, None, gap, tuple(refusals))
    return _AnchorAttempt(None, None, refused_hold, refusals[0] if refusals else None, refused_gap, tuple(refusals))


def _resolve_fair(row: Mapping[str, Any], sides: list[str]) -> _FairResolution:
    """`_fair_by_side` with its working shown. See that docstring for the rules."""
    anchor_mode = _fair_anchor_mode()
    devig_method = _fair_devig_method()
    cells = row.get("cells")
    best = row.get("best") or {}

    # Computed FIRST and on every row -- it is the counterfactual the anchor
    # mode is measured against, not only the default answer.
    consensus = _consensus_fair(cells, sides, method=devig_method)

    # What the anchor tiers decided when they did NOT anchor, carried onto
    # whichever resolution the row falls to so the refusal is visible on the
    # row. `refusals` is None under `median` (no tier ran) and a tuple --
    # possibly empty -- under the anchor modes; the single-valued stamps are
    # the FIRST refused pair's in tier order.
    refusals: tuple[str, ...] | None = None
    refused_hold: float | None = None
    refused_gap: float | None = None

    def _note(attempt: _AnchorAttempt) -> None:
        nonlocal refusals, refused_hold, refused_gap
        if refusals is None:
            refusals = ()
        if not refusals and attempt.refusals:
            refused_hold, refused_gap = attempt.hold_pct, attempt.median_gap_pp
        refusals = refusals + attempt.refusals

    if anchor_mode in (FAIR_ANCHOR_SHARP, FAIR_ANCHOR_SHARP_ONLY):
        books_quoting = _row_books_quoting(row, sides)
        # P1c: the Pinnacle tier is gated on its OWN quality -- hold always,
        # corroboration only in play -- and never on its distance from the
        # median. See the P1c block.
        attempt = _anchored_fair(
            cells,
            sides,
            SHARP_ANCHOR_PRIORITY,
            tier=_ANCHOR_TIER_SHARP,
            max_hold_pct=_fair_sharp_max_hold_pct(),
            min_books=_fair_sharp_min_books_live() if _row_is_live(row) else None,
            books_quoting=books_quoting,
            consensus=consensus,
        )
        _note(attempt)
        if attempt.anchored:
            return _FairResolution(
                attempt.fair_by_side, FAIR_METHOD_SHARP_ANCHOR, attempt.book, _ANCHOR_DEVIG_METHOD, consensus,
                anchor_hold_pct=attempt.hold_pct, anchor_refusals=refusals,
                anchor_median_gap_pp=attempt.median_gap_pp,
            )
    if anchor_mode == FAIR_ANCHOR_SHARP:
        attempt = _anchored_fair(
            cells,
            sides,
            EXCHANGE_ANCHOR_PRIORITY,
            tier=_ANCHOR_TIER_EXCHANGE,
            max_hold_pct=_fair_exchange_max_hold_pct(),
            min_books=_fair_exchange_min_books(),
            books_quoting=_row_books_quoting(row, sides),
            consensus=consensus,
            max_median_gap_pp=_fair_exchange_max_median_gap_pp(),
            consensus_books=len(_two_sided_prices_by_book(cells, sides)),
        )
        _note(attempt)
        if attempt.anchored:
            return _FairResolution(
                attempt.fair_by_side, FAIR_METHOD_EXCHANGE_MID, attempt.book, _ANCHOR_DEVIG_METHOD, consensus,
                anchor_hold_pct=attempt.hold_pct, anchor_refusals=refusals,
                anchor_median_gap_pp=attempt.median_gap_pp,
            )

    refusal = refusals[0] if refusals else None
    if consensus:
        return _FairResolution(
            consensus, "consensus", None, devig_method, consensus,
            anchor_hold_pct=refused_hold, anchor_refusal=refusal,
            anchor_refusals=refusals, anchor_median_gap_pp=refused_gap,
        )

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
        probabilities = devig([price for price, _ in prices], method=devig_method)
        if probabilities and len(probabilities) == len(prices):
            return _FairResolution(
                {side: probabilities[i] for i, (_, side) in enumerate(prices)},
                "two_sided_same_book",
                next(iter(books_used)),
                devig_method,
                consensus,
                anchor_refusals=refusals,
            )

    modelled = row.get("modelled_fair") or {}
    out: dict[str, float] = {}
    for side in sides:
        probability = _as_float((modelled.get(side) or {}).get("fair_probability"))
        if probability is not None:
            out[side] = probability
    return _FairResolution(
        out, "book_margin_model" if out else None, None, None, consensus, anchor_refusals=refusals
    )


def _fair_by_side(row: Mapping[str, Any], sides: list[str]) -> tuple[dict[str, float], str | None]:
    """No-vig fair probability per side, and how it was obtained.

    Two-sided is the real thing (#238). The margin model fills one-sided rows
    and is labelled differently on purpose, so a modelled fair can never be
    mistaken for a measured consensus.

    THE TIERS, in the order tried. `fair_method` names which one answered.

      sharp_anchor         `SYNDICATE_FAIR_ANCHOR=sharp` or `sharp_only`. ONE
                           sharp book's own two sides
                           (`sharp_books.SHARP_ANCHOR_PRIORITY`), observed
                           together, power-de-vigged. Gated (P1c) on its OWN
                           quality only: own hold <=
                           `SYNDICATE_FAIR_SHARP_MAX_HOLD_PCT` (5.0), and on a
                           LIVE row `books_quoting` >=
                           `SYNDICATE_FAIR_SHARP_MIN_BOOKS_LIVE` (2). Never on
                           its distance from the median -- that gap is the
                           signal. A refused Pinnacle falls through exactly as
                           if it had not quoted.
      exchange_mid         `sharp` only -- `sharp_only` has no exchange tier.
                           ONE two-sided exchange's pair, the same way
                           (`EXCHANGE_ANCHOR_PRIORITY`), and ONLY when the pair
                           is TIGHT (own hold <= `SYNDICATE_FAIR_EXCHANGE_MAX_HOLD_PCT`,
                           4.0), CORROBORATED (row `books_quoting` >=
                           `SYNDICATE_FAIR_EXCHANGE_MIN_BOOKS`, 3) and CLOSE
                           (P1c: power-de-vigged mid within
                           `SYNDICATE_FAIR_EXCHANGE_MAX_MEDIAN_GAP_PP`, 3.0 pp,
                           of the consensus median, which must rest on at
                           least two books). A refused row falls through and
                           names the gate in `fair_anchor_refusal`, with every
                           gate that fired in `fair_anchor_refusals` and the
                           gap in `fair_anchor_median_gap_pp`; see the
                           `FAIR_EXCHANGE_*` and P1c blocks for the production
                           readings that made these.
      consensus            `#384` -- de-vig EACH book against itself, then the
                           MEDIAN per selection across books. THE DEFAULT, and
                           the whole chain from here down is unchanged.
      two_sided_same_book  `best` on every side from ONE book, de-vigged.
      book_margin_model    one-sided rows; a modelled fair, labelled as such.

    WHY EVERY TIER DE-VIGS WITHIN ONE BOOK -- including the anchor. `#384`:
    this used to de-vig the BEST price on each side, which routinely takes the
    two sides from two different books. Measured on the served board
    2026-08-12: 29 of 52 two-sided groups drew their sides from different
    bookmakers, and `edge == ev_vs_fair_pct` on 127 of 127 rows.
    `opportunity_signals.fair_probability_by_book` says exactly why: the best
    over at one book and the best under at another sum to less than a real
    market, and normalising THAT to 1.0 "silently launders a line-shopping
    edge into the 'fair' price -- which then makes the edge disappear from the
    EV it was supposed to measure." An anchor built from Pinnacle's home and
    an exchange's away would launder the same way, so the anchor is Pinnacle's
    home AND Pinnacle's away or it is nothing, and the same for each exchange.

    THE ANCHOR NEVER TOUCHES THE PRICE SIDE OF `ev_pct`. It replaces only the
    fair probability; the price EV is measured at stays the best BETTABLE
    book, selected in `build_layer2_rows` after this returns.

    THE EXCHANGE TIER'S FILL RISK IS NOT PRICED HERE. An exchange's posted pair
    is what could be hit at that instant for some size; the mid de-vigged from
    it is a REFERENCE, and nothing in this function accounts for depth,
    commission, or whether an order at that price would fill. That belongs to
    the execution side (`venue_fees`, `venue_basis_edge`), not to the fair.

    `SYNDICATE_FAIR_DEVIG_METHOD` (`multiplicative` default | `power`) chooses
    the per-book de-vig on the consensus and same-book tiers, independently of
    the anchor. Under the defaults this function is `#384`'s code, bit for bit.
    """
    resolved = _resolve_fair(row, sides)
    return (resolved.fair_by_side, resolved.method)


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

#: The ceiling a MODEL-DERIVED value term may reach in the ranking, in EV points.
#: Env: `SYNDICATE_MODEL_EDGE_VALUE_CAP_PCT`.
#:
#: WHY 5.0. Measured on the served shortlist 2026-09-04 (n=1,200), the RANKING
#: value by basis:
#:
#:     market_fair    n=840   median -0.92   p90 2.25   max  5.14
#:     model_edge     n=360   median +0.14   p90 7.30   max 14.99
#:
#: So every row above 5.14 was NECESSARILY a model disagreement -- a real price
#: dislocation physically could not reach there. `batter_home_runs` was 340 of
#: 1,200 rows, EVERY ONE an `over`, and 25 of the top 50. USER-REPORTED as
#: "a lot of long shots at the top", and the mechanism is arithmetic, not taste:
#: a one-sided prop has no two-sided fair, so its `ev_pct` collapses to `-hold`
#: and it ranks on the modelled edge instead, at FULL value.
#:
#: 5.0 says: the model may argue a row up to what the best real price
#: dislocation achieves, and no further.
#:
#: AND THE EVIDENCE SAYS IT SHOULD NOT REACH EVEN THAT UNCHALLENGED. The CLV
#: decomposition run 2026-09-04 over 14,111 resolved rows found the sim's
#: contribution does NOT predict close: game lines -0.186pp [-0.340, -0.033],
#: props -0.113pp, props dose-response monotone the WRONG way. This is the one
#: signal measured as non-predictive, and it owned the top of the board.
_MODEL_EDGE_VALUE_CAP_PCT = _env_float("SYNDICATE_MODEL_EDGE_VALUE_CAP_PCT", 5.0)


def _compress_model_value(value: float | None) -> float | None:
    """Bound a model-derived ranking value WITHOUT creating ties at the ceiling.

    SATURATING, NOT CLAMPING, and the difference is the whole design. This
    file's own `_model_edge_for` rejects a hard clamp for a stated reason --
    "Clamping would keep an unusable number in the ranking at the ceiling value
    and make every affected row tie at the top -- a wrong answer wearing a
    plausible one's clothes" -- and that objection is correct. `tanh` is
    strictly monotone, so ordering among model rows is preserved exactly: a
    13-point edge still outranks a 12-point one. What changes is that neither
    can outrank the whole market-priced board.

    Near zero it is the IDENTITY to first order (`tanh(x) ~ x`), so the small
    genuine edges this path exists to surface are untouched -- 5.0*tanh(1/5) =
    0.993 for an edge of 1.0. It bends only where the number was implausible
    anyway.

    Applied to BOTH branches. `model_ev` needs it at least as much as
    `model_edge`: it is `expected_value_pct(price, model_prob)`, which near fair
    is `edge / p`, so it AMPLIFIES by 1/p -- measured on this board at
    edge 4.11 -> ev 50.92 on a p=0.067 shot, which is exactly how longshots
    sweep a ranking.

    `ev_pct` on the candidate is NOT touched. `portfolio_commit` back-derives
    the market fair from that field and reaches the model probability by adding
    `model_edge_pct`; compressing what the SIZER reads would change stake sizes,
    and this is a RANKING fix. Same reason the model substitution happens on the
    value term and nowhere else.
    """
    if value is None:
        return None
    cap = _MODEL_EDGE_VALUE_CAP_PCT
    if not (cap > 0.0):
        # Explicitly disabled -- restores the pre-2026-09-04 behaviour rather
        # than silently flooring the model out of the ranking.
        return value
    return cap * math.tanh(float(value) / cap)

# The real fix is an explicit `basis` on the projection, which #263's own filing
# already argued for ("each sport emitting the strongest claim its source
# actually supports, labelled with its basis"). That was written as a parity
# principle; this is why it is a correctness requirement. Until projections
# carry it, this bound is the guard -- and it is a GUARD, not a calibration.


EV_BASIS_MARKET = "market_fair"
EV_BASIS_MODEL = "model_probability"
# The model row ranked on its EDGE (probability points) rather than on EV.
# A SEPARATE BASIS BECAUSE THE UNITS GENUINELY DIFFER -- probability points vs
# EV percent -- so this string is load-bearing, not decoration. `#242`: a
# modelled number must not wear a measured one's clothes, and neither may a
# probability-scale number wear an EV's.
EV_BASIS_MODEL_EDGE = "model_edge"


def _model_value_term() -> str:
    """Rank a model-priced row on its EDGE or on its EV? Default `edge`.

    ------------------------------------------------------------------
    WHY EV AMPLIFIES, MEASURED
    ------------------------------------------------------------------

    `_model_value_ev` returns `expected_value_pct(price, model_prob)`, and near
    fair that is `edge / p`. So EV multiplies the edge by `1/p`, and the served
    shortlist shows it exactly (2026-08-31):

        edge 10.18 -> ev 85.13   ratio  8.36   1/p =  9.62  (p=0.104)
        edge  4.11 -> ev 50.92   ratio 12.39   1/p = 14.99  (p=0.067)
        edge 12.43 -> ev 41.80   ratio  3.36   1/p =  4.18  (p=0.239)

    A SMALLER edge on a LONGER shot outranks a bigger edge on a shorter one:
    4.11 points at 6.7% beats 12.43 points at 24%. Mechanical, not a judgement
    about the bets. Result: 23 of the top 25 were `hr_1plus`.

    THE STRUCTURAL ARGUMENT, and it is the strongest one `[peer session
    1c88bcca, who wrote the EV path and raised this against their own work]`:
    `blended_score` CAPS the model's influence when it arrives as `model_edge`
    (`_MODEL_EDGE_MAX_POINTS`, `_SCORE_SIM_CAP_PCT`) -- and the same information
    was then routed through `value_ev`, which has NO cap. The top row's own
    breakdown says it: `sim_component None, movement_component None,
    ev_component 85.13`. The model was capped in one path and given an uncapped
    one in the next line.

    AND IT AMPLIFIES MODEL ERROR HARDEST WHERE THE MODEL IS WEAKEST. At p=0.10 a
    2-point probability error moves EV ~20 points; at p=0.50 it moves ~4. These
    rows carry `model_skill.sample_games: 0`.

    ------------------------------------------------------------------
    THE DEFAULT IS `edge` BY USER DECISION, 2026-08-31
    ------------------------------------------------------------------

    **`[2026-08-31, user decision: "rank on edge, flip the default"]`. This
    SUPERSEDES `[2026-08-30: "Price EV vs the model everywhere"]` FOR THE
    RANKING TERM ONLY** -- EV against the model is still computed, still
    published as `model_ev_pct`, and still what the row reports. What changed is
    which number the SCORE sorts on.

    Recorded at this length because the 08-30 decision is still in `state.md`,
    and a reader who finds only that one will read this as a regression rather
    than as a later ruling by the same person.

    It shipped DEFAULTING TO THE OLD BEHAVIOUR first, deliberately: two Claude
    sessions agreeing does not reverse a user's decision, so the flag existed to
    make the alternative measurable and put it to them. The default moved only
    after they ruled. `SYNDICATE_LAYER2_MODEL_VALUE_TERM=ev` is now the
    reverse-out rather than the opt-in.

    Simulated on the served board before shipping -- top 25 `hr_1plus`
    23 -> 8, and the new #1 is a totals row at `ev_pct` +3.88, market-anchored
    and positive. Reachability, which is what the 08-30 decision was FOR, is
    preserved: the edges are 3.79-12.43 against a #50 that was +0.64.
    """
    raw = str(os.environ.get("SYNDICATE_LAYER2_MODEL_VALUE_TERM") or "").strip().lower()
    # Absent means EDGE. Only the exact word `ev` reverts, so an unrecognised
    # value cannot silently restore the 1/p amplification.
    return "ev" if raw == "ev" else "edge"


def _model_value_ev(
    row: Mapping[str, Any], side: str, price: Any, fair_method: Any
) -> float | None:
    """EV against the MODEL's probability, for a row whose EV is a hold restatement.

    `[2026-08-30, user decision]` — and the reason it is confined to these rows.

    `book_margin_model` prices a one-sided market as `fair = implied x (1-hold)`,
    so `expected_value_pct(price, fair)` is `fair/implied - 1`: the price
    cancels and the EV is **-hold for every such row regardless of the bet**
    (`_row_ev_is_hold_restatement` states this and it is exact). That number
    carries no information about the bet, and because it is roughly -6 points it
    buries whatever the model says underneath it. MEASURED 2026-08-30 after the
    `#601` join fixes: 2,611 rows that had just gained a correct model edge
    scored a maximum of **-4.73** against a live shortlist whose #50 was +0.64.
    Every one of them was priced, correct, attributable — and unreachable.

    EV against the model's own probability is the honest alternative and a
    genuinely different question: "if the model is right, what does this bet
    return". It is NOT a better estimate of the same quantity, which is exactly
    why it goes in its own field with its own basis (`#242`).

    CONFINED TO HOLD-RESTATEMENT ROWS ON PURPOSE. Where a real two-sided
    consensus exists, `ev_pct` is a MEASURED market EV and the model's view
    already enters through `blended_score`'s capped sim term. Substituting there
    would replace a measured number with a modelled one on rows that do not need
    it — the failure this repo has paid for most often.

    THE HONEST LIMIT, recorded at the point of use: the models behind most of
    these rows carry `model_skill: {"sample_games": 0, "status": "unmeasured"}`.
    Soccer's goal-scorer and shots props are the bulk of the population. This EV
    is exactly as good as they are, and the row says so — `model_skill` travels
    on the projection and `ev_basis` travels on the candidate, so nothing
    downstream can read this as a measured market EV.
    """
    if str(fair_method or "").strip() != "book_margin_model":
        return None
    model_prob = _model_prob_for_side(row, side)
    if model_prob is None:
        return None
    if not (0.0 < float(model_prob) < 1.0):
        # A degenerate probability produces an unbounded EV. `#414`'s lesson in
        # a different shape: an already-decided outcome priced as a live one is
        # the largest fake number on the board.
        return None
    return expected_value_pct(price, model_prob)


MODEL_EDGE_BASIS_MARKET = "market_fair"
MODEL_EDGE_BASIS_MODELLED = "modelled_fair"


def _modelled_fair_edge_for(projection: Mapping[str, Any], side: str) -> float | None:
    """The edge against the MODELLED fair, for THIS row's side, or None.

    THE SIDE CHECK IS THE WHOLE SAFETY ARGUMENT. `edge_vs_modelled_fair_pct` is
    priced for one specific side and `modelled_fair_side` names it. Unlike a
    two-sided market there is NO complement identity to fall back on: each side
    of a one-sided quote is priced from its own book's measured hold, so the two
    sides do not sum to one and negating this number answers nothing. So a row
    whose side does not match is DROPPED rather than negated -- the same rule
    `_model_edge_for` applies to a three-way market for the same reason.

    Bounded by the same ceiling as the measured edge. A hold-model fair on a
    longshot is the weakest term on this board; letting it past a guard the
    measured number has to clear would invert the confidence ordering.
    """
    edge = _as_float(projection.get("edge_vs_modelled_fair_pct"))
    if edge is None:
        return None
    priced_side = str(projection.get("modelled_fair_side") or "").strip().lower()
    if not priced_side or priced_side != str(side or "").strip().lower():
        return None
    if abs(edge) > _MODEL_EDGE_MAX_POINTS:
        return None
    return edge


#: Two-way markets, in the row-side vocabulary the board actually serves
#: (measured on `/api/intelligence/query` 2026-09-03, 1,344 rows: the complete
#: set of `side` values is over/under/home/away/draw/yes/no/None). A pair here
#: licenses the `1 - p` / `-edge` identity and NOTHING ELSE does -- see
#: `_projection_side_in_row_frame`.
#: A stated framing this cannot place. NOT "" -- see
#: `_projection_side_in_row_frame`. Deliberately a token no side vocabulary
#: contains, so an accidental `== row_side` is impossible.
_SIDE_UNPLACEABLE = "__unplaceable__"

_TWO_WAY_OPPOSITE_SIDE: Mapping[str, str] = {
    "over": "under",
    "under": "over",
    "home": "away",
    "away": "home",
    "yes": "no",
    "no": "yes",
    "1": "2",
    "2": "1",
}


def _projection_side_in_row_frame(row: Mapping[str, Any], projection: Mapping[str, Any]) -> str:
    """`projection["side"]`, restated in the row's own side vocabulary.

    THE PRODUCERS AND THE ROWS DO NOT SPEAK THE SAME LANGUAGE, and until now
    both `_model_edge_for` and `_model_prob_for_side` compared them as bare
    strings. Three producers -- `ncaaf/game_projections.py`,
    `shared/nfl_game_projections.py` and `shared/wnba_game_projections.py` --
    frame a game-line projection on the HOME TEAM and write its NAME:

        projection["side"] = str(row.get("home_team"))   # "Georgia Tech Yellow Jackets"
        row["side"]        = "home"

    Those tokens can never be equal, so EVERY side of every such market fell
    into the "not my framing" branch and was negated. Both sides of a two-way
    market therefore received the SAME number, and the side the projection was
    actually about received `1 - p`.

    MEASURED on the served board 2026-09-03, NCAAF moneylines, **17 of 17 pairs
    identical on both sides**:

        Georgia Tech (home, -223)   0.35     Colorado (away, +217)  0.35
        Colorado State (home, -148) 0.56     Wyoming  (away, +147)  0.56
        Illinois (home, -2532)      0.0067   <- the sim says 0.9933

    The last row is the shape of the damage: a 96%-implied favourite served with
    a model probability of 0.67% in a column headed **Win%**.

    THREE OUTCOMES, AND THE THIRD IS THE ONE THAT MATTERS:

        "home"/"over"/...   placed. Compare it.
        ""                  the projection states NO side. Fall back to the
                            field's own definition (`model_prob_over` IS the
                            over, and for a game market the home) exactly as
                            before -- this branch is unchanged.
        `_SIDE_UNPLACEABLE` a side WAS stated and could not be placed. Callers
                            must DROP the row. Folding this into "" would put
                            an unknown framing on the permissive branch, which
                            is the same class of mistake as the one above.
    """
    raw = str(projection.get("side") or "").strip().lower()
    if not raw:
        return ""
    if raw in _TWO_WAY_OPPOSITE_SIDE or raw in {"draw", "tie", "x"}:
        return raw
    # A TEAM NAME. Resolve it against THIS ROW'S OWN teams rather than against
    # any alias map: the projection and the row came from the same grid row, so
    # the strings are the same feed's spelling and no canonicalisation is needed
    # or wanted (`ncaaf-chip-compact` records why filling `_alias_map("ncaaf")`
    # is FORBIDDEN -- it re-opens the cross-game token collisions `#603` fixed).
    home = " ".join(str(row.get("home_team") or "").strip().lower().split())
    away = " ".join(str(row.get("away_team") or "").strip().lower().split())
    if home and raw == home:
        return "home"
    if away and raw == away:
        return "away"
    return _SIDE_UNPLACEABLE


#: How far past the line the sim has to land before the board says so, as a
#: FRACTION OF THE LINE.
#:
#: RELATIVE, NOT ABSOLUTE, and that is the only part of this number that is
#: forced rather than chosen. The same field carries NCAAF points, MLB runs and
#: soccer goals; three points is noise on a 53.5 total and three goals is a
#: different sport. There is no shared unit, so there cannot be a shared
#: absolute threshold.
#:
#: THE MAGNITUDE IS A LOUDNESS CHOICE AND IS NOT DERIVED FROM THE SIM BEING
#: RIGHT -- state that plainly, because a number in a constant reads as a
#: measurement. What the sim's error against OUTCOMES looks like is unmeasured
#: for NCAAF totals ("No model-vs-market accuracy measurement exists for totals
#: at all" -- `football/pick_gate.py`), and NCAAF has 0 graded rows and 0 orders
#: ever, so nothing can be fitted to it today.
#:
#: What IS measured is the gap distribution itself, on the served board
#: 2026-09-03, 141 NCAAF totals rows over 43 games:
#:
#:     |projected - line| / line      p25 0.071   p50 0.154   p75 0.252
#:     rows contradicted at   0%   71 (50%)   <- a chip on half the board
#:                           10%   43 (30%)
#:                           25%   17 (12%)
#:
#: 0.10 sits between the p25 and the median: loud enough that the tag is not on
#: half the rows, quiet enough that it still catches the 14.3-point Under that
#: started this. Set `SYNDICATE_SIM_CONTRADICTION_MIN_GAP=0` to tag every
#: contradiction; it is one env key and no deploy.
_SIM_CONTRADICTION_MIN_GAP = _env_float("SYNDICATE_SIM_CONTRADICTION_MIN_GAP", 0.10)

#: The rails. Identical to the producer-side certainty clamp WNBA already ships
#: (`_CERTAINTY_FLOOR/_CERTAINTY_CEILING = 0.01, 0.99`), held here under its own
#: name so the two cannot drift silently.
_SIM_CERTAINTY_FLOOR = 0.01
_SIM_CERTAINTY_CEILING = 0.99


def _sim_direction_contradiction(row: Mapping[str, Any], projection: Mapping[str, Any]) -> float | None:
    """How far the sim's own projection lands on the WRONG side of this row's line.

    Returns the signed gap IN THE STAT'S OWN UNITS, positive and only positive:
    a return value is by construction a contradiction. `None` means either that
    the sim cannot be read on this row or that it points the same way we do.

    This is a claim about DIRECTION, which is a different thing from
    `model_edge_pct`'s claim about RATING, and the board had no word for it.
    Worked example, the row the 2026-09-03 report was written about:

        UMass @ Rutgers   line 53.5   pick UNDER   projected 67.803
        -> the sim wants the OVER by 14.3 points, and we are recommending the
           UNDER, at score +1.67, second-best row on the board, untagged.

    ONLY AN OVER/UNDER MARKET. A spread's `line` does not state which side it
    belongs to (`ncaaf/game_projections.py` carries that finding as
    `probability_unavailable_reason`, inherited verbatim from NFL), so a guessed
    sign would invert the verdict while looking plausible -- the exact failure
    `_model_prob_for_side` exists to prevent. Moneylines have no line at all;
    their degeneracy is reported separately, by `sim_probability_railed`.
    """
    projected = _as_float(projection.get("projected"))
    if projected is None:
        projected = _as_float(row.get("projected"))
    line = _as_float(row.get("line"))
    if projected is None or line is None or line == 0:
        return None
    side = str(row.get("side") or "").strip().lower()
    if side == "under":
        gap = projected - line
    elif side == "over":
        gap = line - projected
    else:
        return None
    if gap <= 0:
        return None
    if abs(gap) / abs(line) < _SIM_CONTRADICTION_MIN_GAP:
        return None
    return round(gap, 3)


def model_edge_basis(row: Mapping[str, Any], side: str, fair: Any = None) -> str | None:
    """Which fair the row's `model_edge_pct` was priced against, or None.

    Published on the candidate so a consumer can tell a measured disagreement
    from a modelled one WITHOUT re-deriving it -- the `basis` discipline `#263`
    asked for, and the thing that keeps this fallback from reading as the
    measured number it deliberately is not.

    `fair` IS THIS ROW'S OWN SIDE FAIR and must be passed wherever the answer
    could be a three-way leg. It is optional only so callers that already know
    the row is two-way keep working; omitting it there costs nothing because
    the first branch answers.

    THE THREE-WAY BRANCH IS WHY THIS TAKES `fair` AT ALL `[2026-09-07]`.
    `62937ea4` made `_model_edge_for` return a MARKET-priced edge in the case
    where `edge_vs_market_pct` is None -- a home leg the precision gate withheld,
    whose draw/away legs are still priced against their own bars. This function
    decided `market` off that same field being non-None, and
    `_modelled_fair_edge_for` is strictly side-matched so it declines a
    draw/away row too. The label therefore fell through to None on a genuinely
    measured edge: 4 of 77 served soccer moneyline rows on 2026-09-07 (SC
    Telstar away +4.52, FC Porto draw +5.47, Braga draw -5.20, PSG @ Brest away
    -5.95), each one a row whose home leg was withheld.

    That is the same defect the `62937ea4` postmortem is about -- a field
    acquiring a state its consumer does not enumerate -- introduced while fixing
    it. Diagnostic only: nothing in `.py`/`.html`/`.js` reads this field but its
    own tests, and the edge VALUE was always correct.

    IT CALLS `_three_way_leg_edge` RATHER THAN RESTATING THE TEST. Two
    independent answers to "did this leg price" is exactly how the basis and the
    number drift apart again; sharing the helper makes them agree by
    construction.
    """
    projection = row.get("projection")
    if not isinstance(projection, Mapping):
        return None
    if _as_float(projection.get("edge_vs_market_pct")) is not None:
        return MODEL_EDGE_BASIS_MARKET
    leg = _three_way_leg_edge(projection, side, fair)
    if leg is not _NO_THREE_WAY and leg is not None:
        return MODEL_EDGE_BASIS_MARKET
    if _modelled_fair_edge_for(projection, side) is not None:
        return MODEL_EDGE_BASIS_MODELLED
    return None


#: `_three_way_leg_edge` found no three-way vector at all, which is NOT the same
#: as finding one and refusing the leg. Both would be `None`, and collapsing them
#: is the exact defect this sentinel exists to stop -- see `_model_edge_for`'s
#: `edge is None` branch, where one `None` already came to mean two things.
_NO_THREE_WAY = "__no_three_way_vector__"


def _three_way_leg_edge(projection: Mapping[str, Any], row_side: str, fair: Any) -> Any:
    """This row's own leg of a three-way market, priced against ITS OWN bar.

    Returns a float (priced), None (there IS a vector and this leg is refused),
    or `_NO_THREE_WAY` (no draw leg -- caller should do something else).

    ONE IMPLEMENTATION, TWO CALL SITES. `_model_edge_for` reaches this from two
    different states -- a home leg that priced, and a home leg the precision gate
    withheld -- and a second copy of the pricing rule for the second state is how
    the first one rots. `live_gameline_join` says it in those words.

    NEGATION IS A TWO-WAY IDENTITY AND SOCCER h2h IS THREE-WAY. `-edge_home` is
    the other side's edge only when there is exactly one other side, because
    P(away) = 1 - P(home) makes the two errors equal and opposite. With a draw
    leg the three edges sum to zero but are otherwise unrelated.
    """
    draw_prob = _as_float(projection.get("draw_probability"))
    if draw_prob is None:
        return _NO_THREE_WAY

    model_prob = {
        "home": _as_float(projection.get("model_prob_over")),
        "draw": draw_prob,
        "away": _as_float(projection.get("away_probability")),
    }.get(str(row_side or "").strip().lower())
    fair_prob = _as_float(fair)
    if model_prob is None or fair_prob is None:
        # A three-way side we cannot price is DROPPED, not negated. Falling back
        # to the two-way identity here is how the sign inversion this branch
        # exists to fix would survive its own fix.
        return None

    # THE PRECISION GATE. `price_moneyline` is CALLED, not reimplemented: it owns
    # the Agresti-Coull point estimate, the standard error and the 2-sigma bar,
    # and it applies them in the one correct order -- the SE comes off the RAW
    # `p`, because `prob_std_err` reconstructs `successes = p * n` and smoothing
    # first would apply add-two twice and over-widen the bar ~39% at the boundary.
    from syndicate.features.shared.live_gameline_join import price_moneyline

    verdict = price_moneyline(
        model_prob=model_prob,
        market_prob=fair_prob,
        sims=projection.get("sims_run"),
    )
    if not verdict.get("priceable"):
        return None
    direct = float(verdict["edge_pp"])
    if abs(direct) > _MODEL_EDGE_MAX_POINTS:
        return None
    return round(direct, 4)


def _model_edge_for(row: Mapping[str, Any], side: str, fair: Any = None) -> float | None:
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
        # THE MODELLED FAIR IS THE ONLY VIEW A ONE-SIDED MARKET CAN HAVE, and
        # until now nothing read it. `board_enrichment.attach_modelled_fair_edges`
        # prices `edge_vs_modelled_fair_pct` on rows with no two-sided fair;
        # this function was the SECOND of the two breaks in series that kept
        # that number off the board. Measured on production 2026-08-30, pregame
        # only: 2,709 rows carried a projection AND a `modelled_fair` and
        # reported `one-sided market: no two-sided fair to price against` --
        # 2,654 soccer, 55 MLB. Every one of them ranked on EV alone, and EV
        # against a `book_margin_model` fair is `-hold` for every such row
        # regardless of the bet (see `_row_ev_is_hold_restatement`), so the
        # board was sorting them by which book quoted.
        #
        # SEPARATE FIELD, SEPARATE BASIS, and `blended_score` is told which it
        # got. `#242`'s rule is that a modelled number must not wear a measured
        # one's clothes -- so this is a FALLBACK reached only when the measured
        # term does not exist, never a substitute for one that does.
        #
        # AND THAT LAST SENTENCE IS WHY THE THREE-WAY CHECK GOES ABOVE IT.
        # `edge_vs_market_pct is None` acquired a SECOND meaning on 2026-09-06
        # when the soccer precision gate shipped: it now also means "there WAS a
        # two-sided fair, the leg was priced against it, and the edge was inside
        # its own Monte-Carlo noise". Both states are a bare `None` here, and
        # this fallback was written for only one of them.
        #
        # The collision is not a bug in either half. The early return is correct
        # for a one-sided quote; the gate is correct for an imprecise estimate.
        # What is wrong is a single sentinel carrying both, which is why nothing
        # failed and why the per-side withheld counts were measuring two things
        # at once.
        #
        # MEASURED on the 2026-09-07 pregame slate, deployed code over production
        # projections: **3 of 10 draw/away legs cleared their OWN 2-sigma bar and
        # were dropped anyway** because the HOME leg of the same match had been
        # withheld -- among them a +10.13 pp away edge (Getafe, model .385 vs
        # fair .2848). A leg's precision is a property of THAT leg: the three
        # probabilities are different numbers with different edges and different
        # bars, and one being imprecise says nothing about the others.
        #
        # Not a safety hole before this fix -- `_modelled_fair_edge_for` is
        # side-matched and returned None rather than an ungated number, so the
        # cost was COVERAGE. It is still worth fixing at the source rather than
        # leaving the board quietly narrower than the gate intends.
        gated = _three_way_leg_edge(projection, side, fair)
        if gated is not _NO_THREE_WAY:
            # A vector exists, so the MEASURED term exists for this leg -- either
            # a priced edge or a named refusal. Falling through to the modelled
            # fair from here is precisely the substitution the paragraph above
            # forbids.
            return gated
        return _modelled_fair_edge_for(projection, side)
    if abs(edge) > _MODEL_EDGE_MAX_POINTS:
        # Dropped, not clamped. Clamping would keep an unusable number in the
        # ranking at the ceiling value and make every affected row tie at the
        # top -- a wrong answer wearing a plausible one's clothes (#242).
        return None
    # RESTATED IN THE ROW'S FRAME FIRST. A bare string compare treats the
    # home-team NAME that NCAAF/NFL/WNBA write here as "not my side" and negates
    # BOTH sides of the market -- see `_projection_side_in_row_frame` for the
    # 17-of-17 production reading.
    projected_side = _projection_side_in_row_frame(row, projection)
    row_side = str(side).strip().lower()
    if projected_side == _SIDE_UNPLACEABLE:
        return None
    if not projected_side or projected_side == row_side:
        return edge

    # NEGATION IS A TWO-WAY IDENTITY AND SOCCER h2h IS THREE-WAY.
    #
    # `-edge_home` is the other side's edge only when there IS exactly one other
    # side, because P(away) = 1 - P(home) makes the two errors equal and
    # opposite. With a draw leg the three edges sum to zero but are otherwise
    # unrelated, so negating the home-framed edge answers a question about a
    # different outcome.
    #
    # MEASURED on the served shortlist 2026-08-21, soccer h2h, 49 rows -- 23
    # away and 13 draw take this branch:
    #
    #   RC Lens v Auxerre, away:  published +1.63  TRUE -1.65   SIGN INVERTED
    #   Orlando v Real Salt Lake: published +9.47  TRUE +6.83
    #   Arsenal v Coventry, draw: published +0.16  TRUE +0.18
    #
    # It looks nearly right on a heavy favourite and inverts on a close one,
    # which is the worst available failure mode. `model_edge_pct` feeds
    # `blended_score` and `sim_view`, so RC Lens ranked and rendered as a side
    # the model LIKES while the model disliked it -- exactly the inversion this
    # function's own docstring says the bound exists to prevent.
    #
    # So: price this side DIRECTLY where the three-way vector is present. Both
    # terms stay in the unconditional three-way space, the property
    # `soccer_projections._price_against_market` documents as what makes the
    # comparison valid at all.
    # THE THREE-WAY LEG, priced against its own bar. Same helper the `edge is
    # None` branch above uses, deliberately: this function reaches three-way
    # pricing from two different states and they must not drift apart.
    #
    # THE DRAW LEG IS THE EXPOSED ONE, for a structural reason rather than a
    # statistical accident: a draw is a NARROW outcome, so once a second goal
    # separates the sides `draws / n` genuinely reaches zero. `0/400` is
    # ordinary late in a match here, where in baseball or football it is a tail
    # case. And `probability_refusal.refuse_published_certainty` -- the one
    # guard that would catch it -- reads `model_prob_over` and NOTHING ELSE, so
    # it covers the home leg and is blind to these two.
    #
    # `79149c94` fixed the ESTIMATOR half platform-wide and this path was missed
    # for exactly the reason it was fixed here: it never went through the shared
    # pricer, so neither the estimator nor the interval reached it.
    #
    # A REFUSAL RETURNS None, which is what this function already does for
    # everything else it declines: the row falls back to EV alone, which cannot
    # pick a side but also cannot invert one.
    three_way = _three_way_leg_edge(projection, row_side, fair)
    if three_way is not _NO_THREE_WAY:
        return three_way

    # Two-way market: the identity holds and MLB/WNBA behaviour is unchanged.
    #
    # BUT ONLY FOR AN ACTUAL OPPOSITE. `-edge` is "the other side's edge" only
    # when this row IS the other side; two tokens that merely fail to be equal
    # are not opposites. An unplaceable framing is DROPPED, which is the same
    # rule the three-way branch above already applies and the same rule
    # `_model_prob_for_side` states in its own last line.
    if _TWO_WAY_OPPOSITE_SIDE.get(projected_side) != row_side:
        return None
    return -edge


#: Keys a SPORT's own producer stamps when it has already calibrated the
#: probability it published. `basketball_props_edges` writes `model_prob_raw`
#: and `_prob_calibrated` beside `model_prob`; `nfl_game_projections` writes
#: `calibrated: True`. A row carrying any of these is calibrated UPSTREAM and
#: the pricing seam must not apply a second curve on top of the first.
_UPSTREAM_CALIBRATION_KEYS = (
    "calibrated",
    "prob_calibrated",
    "_prob_calibrated",
    "calibration_applied",
    "calibration_method",
    "model_prob_raw",
)

CALIBRATION_METHOD_UPSTREAM = "upstream"
CALIBRATION_METHOD_BYPASSED = "skipped_no_fair"
#: The methods that actually MOVE the probability; identity/upstream/bypassed
#: leave the edge and the model EV exactly as the producer priced them.
_CALIBRATION_METHODS_THAT_MOVE = frozenset({"affine_logit", "isotonic"})


def _calibrate_model_edge(
    row: Mapping[str, Any], side: str, fair: Any, model_edge: float | None
) -> tuple[float | None, dict[str, Any]]:
    """The pricing-plane calibration seam (`lane pricing-plane-v1`, P5).

    Takes the edge `_model_edge_for` priced for THIS row's side and returns
    `(edge, stamps)`. With `SYNDICATE_PRICING_CALIBRATION` absent or `off` it
    returns `(model_edge, {})` -- the same object, no stamps, bit-identical
    board. With it on, the sport's versioned per-(market, segment) curve
    (`probability_calibration`) is applied to the PROBABILITY and the edge is
    re-differenced against the same fair; identity when no curve exists.

    THE PROBABILITY IS RECOVERED AS `fair + edge/100`, the sizer's own
    definition (`portfolio_commit.py:311`), unless the projection carries an
    explicit `model_probability`. Not `model_prob_over`: soccer publishes the
    RAW `model_prob_over` and prices the SMOOTHED estimate into
    `edge_vs_market_pct` (`soccer_projections.py:828`), so re-deriving from the
    raw field would move the baseline on every soccer row before any curve was
    applied. Whatever number the edge was differenced from is the number the
    curve gets, and `model_probability_raw` records it.

    STAMPS GO ON THE CANDIDATE, NOT THE PROJECTION. `candidate["projection"]`
    is the grid row's own dict, shared by both sides of the market
    (`test_projection_reaches_the_candidate` pins it verbatim); writing a
    side-specific number into it would put the over's calibration on the
    under's row.

    IDENTITY RETURNS THE ORIGINAL FLOAT, not `round((p - fair) * 100)`, so a
    profile-less `on` differs from `off` only by the stamps.

    THE CERTAINTY REFUSAL STILL FIRES AFTER THE CURVE. A clamped isotonic cell
    can land on exactly 0.0/1.0, and `probability_refusal` runs upstream on the
    projection where it cannot see this number -- so the same rule is applied
    here: an exact certainty is refused, not priced.
    """
    if model_edge is None:
        return model_edge, {}
    from syndicate.features.shared import probability_calibration as _pc

    if not _pc.pricing_calibration_enabled():
        return model_edge, {}
    projection = row.get("projection")
    projection = projection if isinstance(projection, Mapping) else {}
    fair_prob = _as_float(fair)
    explicit = _as_float(projection.get("model_probability"))
    if fair_prob is None:
        # Nothing to re-difference against: an edge the producer computed
        # without a fair the board can see is left exactly as it is, and the
        # row says why.
        return model_edge, {
            "model_probability_raw": explicit,
            "model_probability_cal": explicit,
            "model_edge_pct_raw": model_edge,
            "calibration_version": None,
            "calibration_method": CALIBRATION_METHOD_BYPASSED,
        }
    p_raw = explicit if explicit is not None else fair_prob + float(model_edge) / 100.0
    p_raw = max(0.0, min(1.0, p_raw))
    sport = row.get("sport")
    stamps: dict[str, Any] = {
        "model_probability_raw": round(p_raw, 6),
        "model_probability_cal": round(p_raw, 6),
        "model_edge_pct_raw": model_edge,
        "calibration_version": None,
        "calibration_method": _pc.METHOD_IDENTITY,
    }
    if any(projection.get(key) not in (None, False) for key in _UPSTREAM_CALIBRATION_KEYS):
        stamps["calibration_method"] = CALIBRATION_METHOD_UPSTREAM
        return model_edge, stamps
    profile, _meta = _pc.cached_profile(sport)
    p_cal, meta = _pc.calibrate(sport, row.get("market"), row.get("segment"), p_raw, profile=profile)
    stamps["calibration_version"] = meta.get("version")
    stamps["calibration_method"] = meta.get("method")
    if meta.get("cell") is not None:
        stamps["calibration_cell"] = meta.get("cell")
    if meta.get("cell_error"):
        stamps["calibration_cell_error"] = meta.get("cell_error")
    if p_cal is None or meta.get("method") == _pc.METHOD_IDENTITY:
        return model_edge, stamps
    stamps["model_probability_cal"] = round(p_cal, 6)
    if float(p_cal) in (0.0, 1.0):
        stamps["calibration_refused"] = "exact_certainty"
        return None, stamps
    edge = round((float(p_cal) - fair_prob) * 100.0, 4)
    if abs(edge) > _MODEL_EDGE_MAX_POINTS:
        # Same rule as the raw edge: dropped, not clamped (#242).
        stamps["calibration_refused"] = "edge_exceeds_bound"
        return None, stamps
    return edge, stamps


def _model_prob_for_side(row: Mapping[str, Any], side: Any = None) -> float | None:
    """The model's probability for THIS ROW'S OWN side.

    `model_prob_over` is NOT that number. It is always the projection's own
    framing -- over, or home -- which this file already relies on twenty lines
    up, where `_model_edge_for` maps `"home": projection.get("model_prob_over")`.

    `_layer2_board_columns` published it as `model_probability` with no side
    awareness at all, and two surfaces then read it as if it were side-correct:

      - `intelligence.html:740` `displayProjection()` renders it as the
        **Projected** cell for h2h rows, its own comment asserting the field is
        "the model's probability for THIS row's own `selection`/`side`". It was
        not.
      - the **Win%** column (see `_layer2_board_columns`).

    So an AWAY moneyline pick rendered the HOME win probability beside a
    correctly-side-adjusted "sim disagrees" badge -- the two halves of one row
    disagreeing because only one of them knew which side it was about.

    Reproduced against these functions before the fix (sim likes home at 62%,
    market fair home .55 / away .45):

        home  -> sim_view=agrees     model_probability=0.62   correct
        away  -> sim_view=disagrees  model_probability=0.62   the home number

    The side logic here MIRRORS `_model_edge_for` deliberately -- same
    three-way/two-way split, same refusal to negate across a draw leg -- because
    two independent implementations of "which side is this" is exactly how the
    soccer h2h sign inversion documented in that function happened.

    ON LIVE ROWS THIS RETURNS THE LIVE NUMBER, and that is not a special case
    here: `live_projection_join` overwrites `projection["model_prob_over"]` with
    the re-sim's `live_prob_over` (`live_projection_join.py:465`), so reading
    the same field after the live overlay yields the live probability. Callers
    that need to know WHICH it is should read `projection["basis"]`.
    """
    projection = row.get("projection")
    if not isinstance(projection, Mapping):
        return None
    model_prob_over = _as_float(projection.get("model_prob_over"))
    row_side = str(side if side is not None else row.get("side") or "").strip().lower()

    # THREE-WAY FIRST, for the reason `_model_edge_for` states: with a draw leg
    # `1 - P(home)` is not `P(away)`, so the two-way identity below is not
    # merely imprecise, it answers a question about a different outcome.
    draw_prob = _as_float(projection.get("draw_probability"))
    if draw_prob is not None:
        by_side = {
            "home": model_prob_over,
            "draw": draw_prob,
            "away": _as_float(projection.get("away_probability")),
        }
        # A three-way side we cannot price is DROPPED, not negated.
        return by_side.get(row_side)

    if model_prob_over is None:
        return None
    # RESTATED IN THE ROW'S FRAME. See `_projection_side_in_row_frame`: three
    # producers write the home TEAM NAME here, which no bare compare against
    # "home"/"away" can ever match, so both sides of every NCAAF/NFL/WNBA game
    # market took the `1 - p` branch and received the SAME number.
    projected_side = _projection_side_in_row_frame(row, projection)
    if projected_side == _SIDE_UNPLACEABLE:
        return None
    if not row_side:
        return model_prob_over
    if projected_side:
        if projected_side == row_side:
            return model_prob_over
        # Two-way: P(other side) = 1 - P(this side). Exact, not an approximation
        # -- BUT ONLY BETWEEN ACTUAL OPPOSITES. "not equal" is not "opposite",
        # and negating on inequality is precisely how a team name became a
        # complement. A framing this cannot place is dropped, exactly as the
        # unplaceable ROW side is dropped at the bottom of this function.
        if _TWO_WAY_OPPOSITE_SIDE.get(projected_side) == row_side:
            return round(1.0 - model_prob_over, 6)
        return None

    # NO STATED FRAMING. Fall back to the field's OWN DEFINITION rather than to
    # its value.
    #
    # `prop_projections` sets `projection["side"]` on every projection it
    # attaches (`prop_projections.py:949`), so this is the path for a producer
    # that does not -- and returning `model_prob_over` unexamined there is the
    # exact defect this function exists to remove, just one layer further out.
    # The name is a guarantee: it is the OVER, and for a game market the HOME
    # (`_model_edge_for` relies on that same guarantee to map `"home"`).
    #
    # The vocabularies are `prop_projections`'s own, copied deliberately from
    # the two `next(...)` guards that pick `projected_side` there, so the two
    # files cannot disagree about which token is the "over" side.
    if row_side in {"over", "home", "yes", "1"}:
        return model_prob_over
    if row_side in {"under", "away", "no", "2"}:
        return round(1.0 - model_prob_over, 6)
    # A side this function cannot place is DROPPED, not guessed. A blank cell is
    # recoverable; a confident wrong probability on a betting board is not.
    return None


def build_layer2_rows(
    grid: Iterable[Mapping[str, Any]],
    openings: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fan a market grid out into ranked, gated one-side candidates.

    `openings` is the CLV opening-ledger index, loaded ONCE per build by the
    caller. It is needed HERE and not only in the card builder because movement
    is folded into the SCORE, and the score is computed before selection --
    computing movement later would rank on one number and display another.
    """
    candidates: list[dict[str, Any]] = []
    lanes: dict[str, int] = {}
    rows_in = 0
    sides_priced = 0
    scored = 0
    # `#444`. BOTH halves of the book restriction, because either alone is
    # ambiguous: `no_bettable_book` is what the filter REMOVED, and
    # `repriced_to_bettable` is what it MOVED to a worse price. Reporting only
    # the first makes a repriced board look untouched; reporting only the second
    # makes a shrinking board look like a thin slate. Same contract every other
    # selection rule in this module already follows.
    no_bettable_book = 0
    repriced_to_bettable = 0

    for row in grid:
        rows_in += 1
        sides = [str(side) for side in (row.get("sides") or []) if side]
        if not sides:
            continue
        fair_resolution = _resolve_fair(row, sides)
        fair_by_side, fair_method = fair_resolution.fair_by_side, fair_resolution.method
        best = row.get("best") or {}
        game = row.get("game") if isinstance(row.get("game"), Mapping) else None

        for side in sides:
            side_best = best.get(side) or {}
            price = side_best.get("price")
            if price is None:
                continue
            sides_priced += 1
            fair = fair_by_side.get(side)

            # `#444`: RECOMMEND ONLY A PRICE THE OPERATOR CAN ACTUALLY TAKE.
            #
            # The grid's `best` is the best of ~36 books. Measured on the served
            # shortlist 2026-08-16T16:20:21Z, that put **27 of 108** rows on a
            # book outside the operator's list (betopenly 16, betfair_ex_eu 9,
            # betsson 2) -- a recommendation nobody can place.
            #
            # Re-selected HERE, before `quote` and before `ev`, because EV is
            # computed against this price and settlement grades against it. A
            # filter applied after scoring would rank on a price it then did not
            # recommend -- the same class of defect as `#364`'s unit mismatch:
            # two numbers that have to be the same number.
            #
            # A row with no bettable book is DROPPED, not repriced. 9 of those
            # 27 were `h2h_lay` quoted only by `betfair_ex_eu` + `matchbook`;
            # there is no fallback price for them, and inventing one from an
            # unbettable book is exactly what this removes.
            side_prices = {
                str(book): cell[side]["price"]
                for book, cell in (row.get("cells") or {}).items()
                if isinstance(cell, Mapping)
                and isinstance(cell.get(side), Mapping)
                and cell[side].get("price") is not None
            }
            # FALL BACK TO THE BEST QUOTE'S OWN BOOK WHEN THERE ARE NO CELLS.
            #
            # `cells` is always populated by `build_book_grid`, but this function
            # is also called on hand-built rows, and reading the restriction
            # ONLY from cells meant a row with no cells lost its price entirely
            # -- the filter deleted rows it had no evidence against. Caught by
            # 8 existing tests whose fixtures carry `best` but no `cells`, which
            # is exactly the shape that would have been silently dropped in any
            # caller that builds rows the same way.
            #
            # The rule stated once: judge the books WE CAN SEE. Cells when we
            # have them, otherwise the single book on `best`.
            if not side_prices:
                fallback_book = side_best.get("bookmaker")
                if fallback_book is not None:
                    side_prices = {str(fallback_book): price}
            bettable = book_shortlist.best_bettable(side_prices)
            if bettable is None:
                # No book we can see is bettable. `side_prices` empty means we
                # could see NO book at all -- absent evidence, not evidence of
                # absence -- so the row is kept at its original price rather
                # than dropped on a fact we never established.
                if side_prices:
                    no_bettable_book += 1
                    continue
                bettable_book = str(side_best.get("bookmaker") or "") or None
            else:
                bettable_book, bettable_price = bettable
                if bettable_price != price or str(side_best.get("bookmaker") or "") != bettable_book:
                    repriced_to_bettable += 1
                price = bettable_price

            quote = {
                "price": price,
                "bookmaker": bettable_book,
                # The unrestricted best, kept so the COST of the restriction is
                # readable rather than inferred. A filter that silently changes
                # the headline price is a filter nobody can audit.
                "best_any_book": {
                    "bookmaker": side_best.get("bookmaker"),
                    "price": side_best.get("price"),
                },
                "book_age_seconds": side_best.get("age_seconds"),
                # Time since we last LOOKED, as opposed to `book_age_seconds`'
                # time since the price last MOVED. None when the date's quote
                # state predates last-seen tracking -- unknown, and scoring must
                # not read that as either fresh or stale.
                "quote_seen_age_seconds": side_best.get("seen_age_seconds"),
                "books_quoting": side_best.get("books_quoting"),
                "fair_probability": fair,
                "fair_method": fair_method if fair is not None else None,
                # THE PRICING PLANE'S WORKING, per row. `fair_method` alone
                # cannot say WHICH book anchored a `sharp_anchor` row, which
                # de-vig produced the fair, or what the median would have said
                # -- and without the last one a sharp-vs-median comparison needs
                # a rerun of the whole build. `fair_consensus_prob` is that
                # median for THIS side, on every row in every mode; under the
                # default it equals `fair_probability`, which is the check that
                # the default is unchanged.
                "fair_anchor_book": fair_resolution.anchor_book if fair is not None else None,
                "fair_devig_method": fair_resolution.devig_method if fair is not None else None,
                "fair_consensus_prob": fair_resolution.consensus_by_side.get(side),
                # P1b. The hold of the pair the anchor tiers evaluated -- the
                # anchor's on `sharp_anchor`/`exchange_mid` rows, the refused
                # exchange's when `fair_anchor_refusal` names a gate -- so the
                # next reading can be cut by hold without a rerun. Both None
                # under `median`, and None where no anchor pair was fresh.
                "fair_anchor_hold_pct": fair_resolution.anchor_hold_pct,
                "fair_anchor_refusal": fair_resolution.anchor_refusal,
                # P1c. EVERY refusal that fired, in tier order (Pinnacle, then
                # each exchange), and the evaluated pair's distance from the
                # median in pp -- so the next reading can split "refused by
                # hold" from "refused by distance", and count exchange_mid rows
                # that exist because Pinnacle was gated, without a rerun. None
                # under `median`; a list (possibly empty) under the anchor modes.
                "fair_anchor_refusals": (
                    list(fair_resolution.anchor_refusals) if fair_resolution.anchor_refusals is not None else None
                ),
                "fair_anchor_median_gap_pp": fair_resolution.anchor_median_gap_pp,
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
                # THE VENUE-BASIS VERDICT, carried through THIS EXACT FAN-OUT --
                # which is where `#382` above died, for the same reason and in
                # the same dict. `venue_quote_fanin` attaches it to
                # `best[side]["venue_basis"]`; this projection copies a FIXED
                # FIELD LIST, so an annotation not named here does not exist to
                # any consumer of the board. The module is DISPLAY-ONLY by
                # design, which makes reaching a surface not a nicety but the
                # entire point: unreachable, it is 500 lines that compute
                # nothing anyone can see, and it would read in production as
                # "no live venue edges" rather than as "never wired".
                #
                # COST MEASURED, NOT ASSUMED, before carrying the whole dict:
                # on the served 2026-08-29 board, 33 of 1047 rows are live AND
                # carry a venue price (kalshi 32, polymarket 9). At ~400 bytes
                # that is ~0.8% of a 1.96MB payload, so there is no case for a
                # trimmed variant that would drop the `reason` -- and the reason
                # is what makes a zero attributable instead of bare.
                #
                # Absent on every row the venue did not quote. Three states kept
                # distinct: absent (no venue quote), a refusal (quoted, and a
                # named guard declined), and a number.
                "venue_basis": side_best.get("venue_basis"),
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
                # BOTH SIDES AT SELECTION TIME. `#626`(g).
                #
                # MEASURED (lane `mlb-accuracy-assessment`, 2026-08-31): **0 of
                # 8,778** graded player-date-market-line keys carried both
                # sides -- only the side we took is ever recorded. Three
                # questions are therefore unanswerable from our own ledger:
                # was the side selection right, what did the two-way hold
                # actually cost, and what was the de-vigged fair at the instant
                # we chose. That lane had to reconstruct the opposite price
                # from a separately-captured odds history covering 81.5% of
                # groups, and price the whole inversion question on an
                # ESTIMATE of the opposite side's vig.
                #
                # PRICE AND BOOK ONLY, deliberately. The per-book fan-out
                # `book_prices` does for THIS side is what makes it useful and
                # also what makes it big. Repeating it per other side would
                # multiply a payload that is already mostly market data and
                # whose keyvalue ceiling has corrupted production once
                # (`state.md [layer2-board-keyvalue-ceiling]`). Two scalars per
                # other side answer all three questions above; the nested form
                # would answer a fourth nobody has asked and cost the artifact.
                #
                # Keyed BY SIDE rather than named "opposite" because three-way
                # markets exist (soccer `h2h_3_way`) and have two others, not
                # one. `None` when there is no other side, so absent stays
                # absent rather than becoming an empty dict on every one-way
                # row.
                "other_sides": {
                    str(other): {
                        "price": _as_float((best.get(other) or {}).get("price")),
                        "bookmaker": str((best.get(other) or {}).get("bookmaker") or "") or None,
                    }
                    for other in sides
                    if other != side and isinstance(best.get(other), Mapping)
                }
                or None,
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
                candidate["projection"] = refuse_published_certainty(projection)

            # THE LIVE RE-SIM'S BLOCK, carried for the same reason `#270`
            # carried `projection`: the enrichment stamps it on the GRID row and
            # this fan-out copies a fixed field list, so anything not named here
            # dies at the candidate boundary. `live_gameline_join` writes
            # `row["live_gameline"]` and folds `live_projected` into
            # `row["projection"]`; the first was being dropped, so a live game
            # line reached the board with no live number at all.
            live_gameline = row.get("live_gameline")
            if live_gameline is not None:
                candidate["live_gameline"] = live_gameline

            # Eligibility BEFORE scoring: a dead market should never be ranked,
            # and the gate is the one place that decision lives (#245).
            opportunity_gate.annotate(candidate, quote)
            lane = str(candidate.get("board_lane") or "unknown")
            lanes[lane] = lanes.get(lane, 0) + 1

            ev = expected_value_pct(price, fair) if fair is not None else None
            model_edge = _model_edge_for(row, side, fair)
            # THE PRICING-PLANE CALIBRATION SEAM. Inert (same float, no stamps)
            # unless `SYNDICATE_PRICING_CALIBRATION` is on -- see
            # `_calibrate_model_edge`.
            model_edge, calibration_stamps = _calibrate_model_edge(row, side, fair, model_edge)
            # THE VALUE TERM THE SCORE ACTUALLY RANKS AND ADMITS ON.
            #
            # `ev_pct` below is left EXACTLY as computed -- `portfolio_commit`
            # back-derives the market fair from it
            # (`fair = (ev_pct/100 + 1) / (profit + 1)`) and then reaches the
            # model probability as `fair + model_edge_pct/100`. Substituting a
            # model-based EV into that field would make the sizer re-add an edge
            # already baked into its own fair, double-counting it. So the
            # substitution happens HERE, on the term that feeds the score, and
            # nowhere else.
            model_ev = _model_value_ev(row, side, price, fair_method)
            if (
                model_ev is not None
                and model_edge is not None
                and calibration_stamps.get("calibration_method") in _CALIBRATION_METHODS_THAT_MOVE
            ):
                # A curve moved the probability, so the EV priced against the
                # model must move with it or the two fields describe different
                # models. Same price, calibrated probability.
                model_ev = expected_value_pct(price, calibration_stamps.get("model_probability_cal"))
            if model_ev is not None:
                # THE VALUE TERM, and only this. `ev_pct` below is untouched:
                # `portfolio_commit` back-derives the market fair from it and
                # refuses a row `no_model_edge_pct` at Kelly 0, so letting a
                # probability-scale number leak into that field would corrupt
                # the sizer rather than merely re-rank the board.
                if _model_value_term() == "edge" and model_edge is not None:
                    value_ev = _compress_model_value(model_edge)
                    ev_basis = EV_BASIS_MODEL_EDGE
                else:
                    value_ev = _compress_model_value(model_ev)
                    ev_basis = EV_BASIS_MODEL
                # `model_edge` is DROPPED from the blend for these rows, not
                # kept alongside. The two are the same information twice over --
                # `model_ev` is EV against the model probability and
                # `model_edge` is that probability minus the same fair -- so
                # passing both would count the model's disagreement in the value
                # term twice. It stays on the candidate for display and for the
                # sizer, which needs it.
                blend_model_edge = None
            else:
                value_ev = ev
                ev_basis = EV_BASIS_MARKET
                blend_model_edge = model_edge
            # Computed ONCE, here, and stamped onto the candidate so the card
            # builder reuses it rather than recomputing against the same index.
            # Ranking on a movement number the card does not show (or showing
            # one the ranking did not use) is the `#364` unit-mismatch shape:
            # two numbers that have to be the same number.
            movement = _movement_from_opening(candidate, openings)
            candidate["movement"] = movement
            # SAME CROSS-FILE HAZARD AS THE CARD BUILDER, one level down.
            # `opportunity_signals.py` is a separate blob and can be a deploy
            # behind this file, in which case `blended_score` has no
            # `movement_price_delta` parameter. Unguarded, that TypeError
            # propagates out of `build_layer2_rows` and takes the whole
            # shortlist with it -- strictly worse than the blank-cards case,
            # because there would be no rows either.
            #
            # Probed ONCE per process, not per row: `_blended_score_accepts`
            # is module-level and this loop runs thousands of times.
            score = blended_score(
                ev_pct=value_ev,
                model_edge=blend_model_edge,
                **(
                    {"movement_price_delta": movement.get("movement_price_delta")}
                    if _blended_score_accepts("movement_price_delta")
                    else {}
                ),
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
            # BOTH NUMBERS, ALWAYS, AND WHICH ONE THE SCORE USED. A reader who
            # sees a row ranked well on a -6% `ev_pct` must be able to find the
            # term that ranked it, and a consumer must never be able to mistake
            # a modelled EV for a measured one.
            candidate["model_ev_pct"] = model_ev
            candidate["ev_basis"] = ev_basis
            candidate["model_edge_pct"] = model_edge
            if calibration_stamps:
                # `model_probability_raw` / `model_probability_cal` /
                # `model_edge_pct_raw` / `calibration_version` /
                # `calibration_method`. Present ONLY when the seam is on, so an
                # off board serves exactly the fields it served yesterday.
                candidate.update(calibration_stamps)
            # WHICH FAIR THAT EDGE WAS PRICED AGAINST. Stamped beside the number
            # rather than left for a reader to infer, because a modelled fair
            # and a measured one are different confidences and `#242` forbids
            # letting the first wear the second's clothes.
            candidate["model_edge_basis"] = (
                # `fair` is THIS row's own side fair -- the same value
                # `_model_edge_for` was given two lines up. Passing it is what
                # lets a three-way leg be labelled `market_fair` instead of
                # falling through to None.
                model_edge_basis(row, side, fair) if model_edge is not None else None
            )
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
        "no_bettable_book": no_bettable_book,
        "repriced_to_bettable": repriced_to_bettable,
        "bettable_books": list(book_shortlist.DEFAULT_BOOKS),
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


# Markets where `side` names the team you are betting AGAINST, not for.
#
# `h2h_lay` is the exchange lay price (Betfair, Matchbook): laying the home side
# wins if the home side does NOT win. `side` still reads "home", so every
# team-name lookup in this module resolves it to the home team's name.
_LAY_MARKETS = ("_lay",)


def _is_lay_market(market: Any) -> bool:
    text = str(market or "").strip().lower()
    return any(token in text for token in _LAY_MARKETS)


def _pick_label(row: Mapping[str, Any]) -> str:
    """What the bettor is actually taking, as one readable string.

    A prop is the player; a game side is the team that side refers to. The
    board's card normaliser falls back through
    selection -> pick -> name -> player_name and defaults to the literal string
    "candidate", so a game row with no player name would render as "candidate"
    on every line without this.

    **A LAY MARKET IS A BET AGAINST THE NAMED TEAM AND MUST SAY SO.** Measured
    on the served board 2026-08-16: 9 `h2h_lay` rows rendered as a bare team
    name -- "Los Angeles Dodgers" for a bet that WINS WHEN THE DODGERS LOSE,
    typeset identically to a back bet on them. That is the single most dangerous
    string this function can emit, because it is not vague, it is inverted: a
    reader who acts on it takes the opposite of the intended position. `side`
    carries no hint (it still reads "home"), so the market key is the only
    signal, and it is checked here rather than at one call site because
    `display_name` and the `team` column read the same answer.
    """
    player = str(row.get("player_name") or "").strip()
    if player:
        return player
    side = str(row.get("side") or "").strip().lower()
    team = ""
    if side == "home":
        team = str(row.get("home_team") or "Home").strip()
    elif side == "away":
        team = str(row.get("away_team") or "Away").strip()
    if not team:
        return side.title() or "—"
    if _is_lay_market(row.get("market")):
        return f"LAY {team} (wins if {team} does not)"
    return team


def _row_team(row: Mapping[str, Any], home: str, away: str) -> str | None:
    """The team this row is ABOUT, or None when the row does not name one.

    Only `home`/`away` sides identify a team. `over`/`under` (props, totals) do
    not: the side names a direction, and for a prop the relevant team is the
    PLAYER's, which this row does not carry. None rather than a guess -- see the
    call site for what guessing cost.
    """
    side = str(row.get("side") or "").strip().lower()
    if side == "home":
        return home or None
    if side == "away":
        return away or None
    return None


def _live_projection_columns(row: Mapping[str, Any]) -> dict[str, Any]:
    """The LIVE re-sim's number and the live actual, under the names the
    board's Live and Actual columns read.

    `intelligence.html:640` resolves the column as
    `item.live_projection ?? item.live_total` for game lines and
    `item.live_projection` for props, and nothing on an L2-A card ever set
    either -- so "Live proj." rendered an em dash on every live row while the
    live re-sim's answer existed one level down. Same shape for Actual
    (`item.actual`, `intelligence.html:723`) -- added `layer2-live-
    projection-actual`, 2026-08-20, alongside the fix that stopped `Projected`
    itself from being overwritten with this same live number (see
    `live_projection_join.py`'s `sim_projected` comment); the three columns
    are meant to be read together (pregame / live / actual-so-far) and this
    function is now what feeds two of the three.

    THE PREGAME NUMBER IS NOT A SUBSTITUTE AND MUST NOT BE COPIED HERE.
    Measured on the served board 2026-08-16 19:16Z, 54 live rows: every one
    carried `projection.source = "game_simulation"`, a FULL-GAME PREGAME
    distribution. Showing 10.5 projected runs beside a live total of 11.5 in
    the BOTTOM OF THE 5TH is a full-game number against a remaining-game line --
    two different quantities, and the comparison is meaningless in the
    direction that matters. So this reads ONLY the keys the live joins write
    (`live_projected`, `live_model_prob_over`, `actual_so_far`,
    `live_gameline`) and emits nothing when the live join did not run.

    Absent stays absent. A live row with no live re-sim renders a dash, which
    is honest; a fabricated live number on a live board is the worst cell on
    the page.
    """
    projection = row.get("projection") if isinstance(row.get("projection"), Mapping) else {}
    gameline = row.get("live_gameline") if isinstance(row.get("live_gameline"), Mapping) else {}
    out: dict[str, Any] = {}

    # A GAME-LINE `live_projected` IS A PROBABILITY, NOT A COUNT — and it was
    # being published as both `live_projection` and `live_total`.
    #
    # `live_gameline_join._apply_verdict` is called with
    # `live_projected=verdict["model_prob"]` on the DISTRIBUTION branch (totals
    # and spreads), so where the value arrives at all it is 0..1. The board
    # then rendered it through `displayLiveProjection`'s `toFixed(1)`: a live
    # moneyline at 19% read **"0.2"** in the Live column, and a totals row
    # claimed a live projected total of 0.2 goals. That is worse than the blank
    # it replaced — an em dash says "we do not know", "0.2" says something false
    # about the match.
    #
    # `live_total` was the sharper error of the two: the name asserts a goal/run
    # total outright, and `displayLiveProjection` falls back to it for game rows
    # specifically.
    #
    # So a probability now goes ONLY to `live_model_probability` (below), which
    # is what it is, and the template renders that as a percentage for game
    # markets — mirroring what `displayProjection` already does for the pregame
    # column, which learned this same lesson on 2026-08-20 ("109 of 114 h2h rows
    # were blank here for exactly that reason").
    #
    # A PROP's `live_projected` is a genuine count (shots, points) and is
    # unaffected: it comes from `live_projection_join`, not from the gameline
    # block, and that path is left exactly as it was.
    live_value = _as_float(projection.get("live_projected"))
    if live_value is not None and not gameline:
        out["live_projection"] = live_value
        out["live_total"] = live_value
    elif gameline:
        # The one number on the gameline block that IS a count.
        total_mean = _as_float(gameline.get("total_mean"))
        if total_mean is not None:
            out["live_total"] = total_mean

    # **h2h GAME ROWS DELIBERATELY DO NOT REACH THIS, AND MUST NOT** `[2026-09-05,
    # lane edge-basis-moneyline]`. The comment above used to say `_apply_verdict`
    # is called with `live_projected=verdict["model_prob"]` for "EVERY game market
    # (h2h, totals AND spreads)". That was never true: the MONEYLINE branch of
    # `attach_live_gamelines` passes no `live_projected` at all, so an h2h row
    # carries no `live_model_prob_over` and this cell stays blank for it. The
    # wording is corrected above -- and the belief it encoded is what hid a real
    # defect for three weeks, because `live_gameline_join` was reading that same
    # parameter to decide `edge_basis` and therefore labelled every live h2h edge
    # `pregame` while pricing it off the LIVE probability.
    #
    # Making h2h feed this was the obvious fix there and was REJECTED for what it
    # would do HERE. `live_model_prob_over` on an h2h row is the HOME win
    # probability, and this maps it onto `live_model_probability` with no side
    # awareness -- so an AWAY moneyline row would render the home team's number
    # in the Live column. That is exactly the defect `_model_prob_for_side` below
    # was written to fix ("109 of 114 h2h rows", the pregame column, 2026-08-20),
    # on the same field, one column over. A blank is honest; the home number on an
    # away row is not. If this ever needs to serve h2h, it needs a side-aware
    # source, not the raw key.
    live_prob = _as_float(
        projection.get("live_model_prob_over")
        if projection.get("live_model_prob_over") is not None
        else projection.get("live_prob_over")
    )
    if live_prob is not None:
        out["live_model_probability"] = live_prob

    # `layer2-live-projection-actual`, 2026-08-20: the real box-score/current-
    # game-state value, under the name `displayLiveActual()` reads
    # (`intelligence.html:723`, `item.actual`). `live_projection_join.py`
    # writes it upstream as `actual_so_far` on every row it joins -- never
    # mapped here, so the Actual column had nothing to read regardless of
    # whether the join ran. `_as_float` rather than a plain None-check: a
    # real 0 (nothing has happened yet) must render as 0, not fall through
    # to the same em dash as "we have no live data for this row" -- same
    # class of bug the `live_projection` handling above already avoids.
    actual_value = _as_float(projection.get("actual_so_far"))
    if actual_value is not None:
        out["actual"] = actual_value

    if projection.get("live_aware") or gameline:
        out["live_aware"] = True
    return out


def _segment_label(segment: Any, sport: Any = None) -> str | None:
    """Which slice of the game this line is for, in words.

    Alt and interval lines were rendering as a bare number beside the market --
    `8.5 · totals_alt` sat next to `11.5 · totals` with nothing saying the first
    was FIRST FIVE INNINGS. Measured on the served board 2026-08-16, 30 of 102
    rows carried a non-`full` segment: `first5` (14), `first1` (3), `first3`
    (2), `h1` (1), `q4` (1) and alt variants. A total of 8.5 for five innings
    and a total of 8.5 for nine are different bets that read identically.

    Returns None for the full game, because labelling the common case adds
    noise to every row to disambiguate a minority.
    """
    token = str(segment or "").strip().lower()
    if not token or token in {"full", "full_game", "game"}:
        return None
    known = {
        "first1": "1st inning",
        "first3": "1st 3 innings",
        "first5": "1st 5 innings",
        "first7": "1st 7 innings",
        "h1": "1st half",
        "h2": "2nd half",
        "q1": "1st quarter",
        "q2": "2nd quarter",
        "q3": "3rd quarter",
        "q4": "4th quarter",
        "p1": "1st period",
        "p2": "2nd period",
        "p3": "3rd period",
    }
    if token in known:
        return known[token]
    # UNKNOWN SEGMENTS ARE SHOWN, NOT SWALLOWED. A segment this map has not
    # seen is exactly the case where the reader most needs telling that the
    # line is not for the full game -- returning None there would reproduce the
    # defect for every new interval market the feed adds.
    return token.replace("_", " ")


def layer2_rows_to_board_cards(
    rows: Iterable[Mapping[str, Any]],
    openings: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
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
                # WHOSE ROW THIS IS. `home if side == "home" else away` was
                # wrong for every prop on the board: a prop's side is
                # `over`/`under`, never `home`, so the expression fell to `away`
                # unconditionally -- **56 of 108 served cards** on 2026-08-16,
                # correct only by coincidence when the player happened to be on
                # the away team. Andy Pages (Los Angeles Dodgers, the HOME team)
                # was served as `"team": "Milwaukee Brewers"`, and
                # `intelligence.html:525` reads this field first.
                #
                # A player's team is not derivable from `side`, and it is not
                # carried on the row. So: resolve it for the sides that DO name
                # a team, and leave it absent otherwise. An absent team renders
                # blank; a wrong one puts a real player on a real opposing team.
                "team": _row_team(row, home, away),
                "home_team": home,
                "away_team": away,
                "matchup": f"{away} @ {home}" if home and away else "",
                # THE JOIN KEY THE CHIP CARRIES TOO. `matchup` is built from the
                # ODDS FEED's spelling and the live-scoreboard chip is built
                # from the league artifacts' spelling; for most clubs those
                # differ only cosmetically and the browser's normalisation
                # bridges them, but for some they are simply DIFFERENT NAMES
                # ("Athletic Bilbao" / "Athletic Club") and no normalisation
                # can or should bridge that -- see `_side_key` in
                # `game_chip_scoreboard.py` for the measurement and for why
                # trying is what collapses Manchester United into City.
                #
                # `canonical_team` is the server's own alias map and resolves
                # both spellings to one name, so stamping it on BOTH sides of
                # the join lets them match without either feed changing.
                # None where the map cannot resolve the club; the browser's
                # existing indexes still apply, so this only ever adds a join.
                "home_key": _canonical_team_key(sport, home),
                "away_key": _canonical_team_key(sport, away),
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
                # WHICH SLICE OF THE GAME. Both keys: `segment_label` is the
                # words, `segment` is the raw token a filter can group on.
                "segment_label": _segment_label(row.get("segment"), sport),
                **_layer2_board_columns(row, quote, score),
                **(row.get("movement") if isinstance(row.get("movement"), Mapping) else _movement_from_opening(row, openings)),
                **_live_projection_columns(row),
            }
        )
    return cards


_STEAM_PRICE_POINTS = 15.0    # American-odds move that counts as sharp
_STEAM_WINDOW_SECONDS = 3 * 3600


def movement_join_key(row: Mapping[str, Any]) -> str | None:
    """Identity of a BET across price and line movement.

    Deliberately EXCLUDES `line` and `bookmaker`, which is the opposite choice
    from `clv_opening_ledger._opening_key` -- and both are right, because they
    answer different questions.

    `_opening_key` must not collapse home -1.5 with home -2.5, nor two books'
    prices, because settlement grades a specific bet at a specific book. But
    **movement IS the detection of line and book change.** Keying on them means
    a row can only match its own opening if it did not move, so the metric is
    conditioned on the absence of the thing it measures.

    MEASURED, two artifacts 20 minutes apart (2026-08-16 21:01 -> 21:21):

        stable key (this one)          matched  20
        full key (+ line + bookmaker)  matched  14
           of the 20: line changed 6, book changed 5, either 7

    A third of matchable rows dropped, and they were exactly the rows with
    something to report. It is also why steam never fired: a sharp move usually
    comes with a line move or a best-book switch, which broke the key and
    erased the evidence.

    Nothing is lost by keying loosely -- the opening RECORD still carries
    `line`, `price`, `bookmaker` and `book_prices`, and it is `book_prices`
    that keeps the price comparison same-book even when the best book changed.

    `segment` and `player_name` stay IN: a first-five total and a full-game
    total are different bets, and four batters sharing one prop line collapse
    onto one key without the name (measured on 2026-08-14, 17 rows -> 7 keys).
    """
    event_id = str(row.get("event_id") or "").strip()
    market = str(row.get("market") or "").strip().lower()
    if not event_id or not market:
        return None
    return "|".join(
        (
            f"event_id={event_id}",
            f"market={market}",
            f"player={str(row.get('player_name') or '').strip().lower()}",
            f"segment={str(row.get('segment') or '').strip().lower()}",
            f"side={str(row.get('side') or '').strip().lower()}",
        )
    )


@lru_cache(maxsize=8)
def _blended_score_accepts(parameter: str) -> bool:
    """Does the DEPLOYED `blended_score` take this keyword?

    `opportunity_signals.py` deploys as its own blob onto a long-lived worker,
    so it can be a deploy behind this file. Passing it a keyword it does not
    have raises `TypeError` out of `build_layer2_rows` and loses the entire
    shortlist -- rows and cards both.

    Cached because the caller is a per-side loop over thousands of rows and the
    answer cannot change inside a process. `False` on any introspection failure:
    the fallback drops one scoring term, which is a board that ranks the way it
    did for months, while the alternative is no board.
    """
    try:
        import inspect

        return parameter in inspect.signature(blended_score).parameters
    except (TypeError, ValueError):
        return False


def _movement_from_opening(
    row: Mapping[str, Any], openings: Mapping[str, Mapping[str, Any]] | None
) -> dict[str, Any]:
    """Movement against the price WE published, not against a 20MB shard.

    `#372` DISABLED the previous implementation and the reason is the design
    constraint here, not a footnote: it called
    `load_odds_history_payload_for_sport` INSIDE the per-row card builder, and
    `#370` made it try two shard keys, so a miss loaded a second multi-megabyte
    payload. It stalled the shortlist build outright -- last good build
    00:22:21Z, then 70 minutes of reaching `EXPOSURE_BUDGETS_APPLIED` and never
    printing `LAYER2_SHORTLIST` again, with no exception and therefore no
    failure log. Every producer-side fix queued behind that build stopped
    shipping.

    That module's own docstring said where this belongs: *where the odds
    tracker already holds the data, not in a per-build read of a multi-megabyte
    artifact.* The CLV opening ledger is that place. It already records, for
    every row this board publishes, the line, the price, the bookmaker, every
    book's price and the capture time -- keyed by `_opening_key`, the same
    identity used here. `load_openings` reads ONE small JSONL of our own
    published rows (~100/sport), ONCE per build, OUTSIDE this function.

    **This function does no IO at all.** That is the property that makes it
    safe to re-enable, and it is why the index is a parameter rather than
    something fetched here.

    WHAT IT MEASURES, stated because it is NOT the same quantity the old one
    attempted: movement since WE FIRST PUBLISHED THE ROW, not since the market
    opened. That is the more actionable number -- it answers "has this moved
    since we flagged it" -- and it is the only one recoverable without the
    shard. Labelled `since: "our_open"` so nobody reads it as a true market
    open.

    Absence is REPORTED, never blank: `movement_state` distinguishes
    "no opening recorded" (this row is new, or the ledger was off) from
    "flat" (recorded and unchanged). `#368` exists because those two rendered
    identically as a bare dash and the whole column read as broken.
    """
    if not _movement_is_tracked(row.get("market")):
        return {"movement_not_tracked": True, "movement_state": "not_tracked"}
    if not openings:
        return {"movement_state": "no_openings"}
    key = movement_join_key(row)
    if not key:
        return {"movement_state": "unkeyable"}
    opened = openings.get(key)
    if not isinstance(opened, Mapping):
        return {"movement_state": "no_opening_for_row"}

    quote = row.get("quote") if isinstance(row.get("quote"), Mapping) else {}
    now_price = _as_float(quote.get("price"))
    open_price = _as_float(opened.get("price"))
    now_line = _as_float(row.get("line"))
    open_line = _as_float(opened.get("line"))

    out: dict[str, Any] = {
        "movement_state": "tracked",
        "movement_since": "our_open",
        "movement_opened_at": opened.get("captured_at"),
        "movement_open_price": open_price,
        "movement_open_line": open_line,
        "movement_open_bookmaker": opened.get("bookmaker"),
    }

    # PRICE DELTA IS ONLY MEANINGFUL AT THE SAME LINE. Measured in production
    # 2026-08-16 22:20Z, immediately after the loose join key shipped: **19 of
    # 23 tracked rows had a different opening line**, and their "movement" was
    # the price gap between two different bets --
    #
    #     Under totals   line 7.0   opening line 11.0   "delta" +242
    #     Rockies spreads line -1.5 opening line  +1.0  "delta" +226  -> STEAM
    #
    # That last one FIRED STEAM on a false positive. A +1.0 spread and a -1.5
    # spread are different bets; the price difference between them is not a
    # move, and `_opening_key`'s own docstring says so ("home -1.5 and home
    # -2.5 are different markets").
    #
    # So the JOIN stays loose -- that is what `#446` fixed, and it is why the
    # row is visible at all -- but the PRICE comparison is gated on the line
    # being unchanged. When the line moved, the LINE MOVE IS THE MOVEMENT and
    # is reported as such; a price at a different handicap is not a price move.
    # This keeps the coverage win (31% -> 96%) without buying it with nonsense.
    lines_comparable = (open_line is None and now_line is None) or (
        open_line is not None and now_line is not None and abs(open_line - now_line) < 1e-9
    )
    if not lines_comparable:
        out["movement_price_not_comparable"] = "line_moved"

    # SAME-BOOK, for the same class of reason. The board publishes the best of
    # N books, and the best book can change between builds -- differencing
    # across a book switch measures the switch, not the market. `book_prices`
    # on the opening record exists precisely so this can be same-book; fall
    # back to the headline pair only when labelled as such.
    open_books = opened.get("book_prices") if isinstance(opened.get("book_prices"), Mapping) else {}
    now_books = quote.get("book_prices") if isinstance(quote.get("book_prices"), Mapping) else {}
    book = str(quote.get("bookmaker") or "").strip().lower()
    same_book_open = _as_float((open_books or {}).get(book))
    same_book_now = _as_float((now_books or {}).get(book)) if now_books else now_price
    if not lines_comparable:
        # Deliberately no `movement_price_delta` at all, rather than a value
        # with a caveat attached. A number in that field feeds the score and
        # the steam detector, and a caveat in a neighbouring key does not stop
        # either of them reading it.
        out["movement_basis"] = "line_moved"
    elif same_book_open is not None and same_book_now is not None:
        out["movement_price_delta"] = round(same_book_now - same_book_open, 2)
        out["movement_basis"] = "same_book"
        out["movement_book"] = book
    elif open_price is not None and now_price is not None:
        out["movement_price_delta"] = round(now_price - open_price, 2)
        out["movement_basis"] = "best_of_n"

    if open_line is not None and now_line is not None:
        out["movement_line_delta"] = round(now_line - open_line, 2)

    delta = out.get("movement_price_delta")
    line_delta = out.get("movement_line_delta")
    if delta is None and line_delta is None:
        out["movement_state"] = "no_comparable_price"
        return out

    # DIRECTION IS ABOUT THE BETTOR, AND THE TWO INPUTS DISAGREE ABOUT HOW.
    #
    # PRICE is unambiguous: a larger American number always pays more, in both
    # signs. -125 -> -105 is +20 and is better; that needs no knowledge of the
    # side.
    #
    # LINE IS SIDE-DEPENDENT AND GETTING IT WRONG IS THE DEFECT THIS REPO HAS
    # PAID FOR MOST. A total moving 9.0 -> 8.5 is FAVOURABLE to an over and
    # hostile to an under; the first version of this function called it
    # "against" for both, because it compared the raw delta and never read
    # `side`. Same family as the spread-sign lane, whose whole finding was a
    # sign attached to the wrong perspective.
    #
    # So the two are reported SEPARATELY rather than reduced to one verdict,
    # and the line verdict is only emitted for sides whose preference is known.
    side = str(row.get("side") or "").strip().lower()
    if delta:
        out["movement_direction"] = "toward" if delta > 0 else "against"
    if line_delta:
        prefers_lower = side in {"over", "home", "away"}
        prefers_higher = side == "under"
        if prefers_lower or prefers_higher:
            favourable = (line_delta < 0) if prefers_lower else (line_delta > 0)
            out["movement_line_direction"] = "toward" if favourable else "against"
        else:
            # h2h and anything else has no line to have a direction about.
            out["movement_line_direction"] = "unknown_side"
    if not delta and not line_delta:
        out["movement_state"] = "flat"
        out["movement_direction"] = "flat"
    moved = bool(delta or line_delta)

    # STEAM: a sharp move in a short window. Both halves are required -- a 30
    # point drift over eight hours is not steam, and this is the distinction
    # the old implementation never made because it had no clock.
    age = None
    opened_at = str(opened.get("captured_at") or "")
    if opened_at:
        try:
            opened_dt = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
            if opened_dt.tzinfo is None:
                opened_dt = opened_dt.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - opened_dt).total_seconds()
            out["movement_age_seconds"] = round(age, 1)
        except Exception:
            age = None
    if (
        delta is not None
        and abs(delta) >= _STEAM_PRICE_POINTS
        and age is not None
        and age <= _STEAM_WINDOW_SECONDS
    ):
        out["steam"] = True
        out["steam_reason"] = (
            f"{'+' if delta > 0 else ''}{delta:.0f} at {book or 'best book'} "
            f"in {age / 60:.0f} min since we published it"
        )
    return out


def _layer2_movement_columns(row: Mapping[str, Any], cache: dict[tuple[str, str], Any]) -> dict[str, Any]:
    """SUPERSEDED by `_movement_from_opening` (see it for the `#372` history).

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

    # SIDE-CORRECT, via `_model_prob_for_side`. Publishing
    # `projection["model_prob_over"]` here was wrong on every row whose side is
    # not the projection's framing -- every AWAY and every DRAW -- and two
    # surfaces read it as if it were right. See that function for the repro.
    model_prob = _model_prob_for_side(row)
    if model_prob is not None:
        columns["model_probability"] = model_prob

    # `Win%` MUST BE A WIN PROBABILITY. It was the books-quoting multiplier.
    #
    # This published `score["book_confidence"]` as `confidence`, and
    # `intelligence.html:2180` renders `confidence` as the column labelled
    # **Win%**. `book_confidence` is `_book_confidence(books_quoting)` -- a
    # RELIABILITY factor from the `((1, 0.5), (2, 0.7), (4, 0.85))` ladder,
    # else 1.0. It is not a probability of anything.
    #
    # CONFIRMED ON A USER SCREENSHOT of the served board, 2026-08-21, five
    # distinct values mapping 1:1 onto the ladder with nothing left over:
    #
    #     BETMGM  (1 book)    Win%  50%    _book_confidence(1)  = 0.50
    #     BETMGM  (2 bks)     Win%  70%    _book_confidence(2)  = 0.70
    #     KALSHI  (3 bks)     Win%  85%    _book_confidence(3)  = 0.85
    #     NOVIG   (14 bks)    Win% 100%    _book_confidence(14) = 1.00
    #     KALSHI  (21 bks)    Win% 100%    _book_confidence(21) = 1.00
    #
    # So "Win% 100%" meant "five or more books quote this market" -- read by a
    # bettor as a certainty. That is the worst available failure mode for this
    # column, and it is why the fix is not a relabel: the number a reader wants
    # from a column called Win% is the model probability for the side being
    # recommended, which is exactly what `model_prob` above now is.
    #
    # BLANK WHERE THERE IS NO MODEL, deliberately. 43 of 108 rows carried no
    # projection at the last count in this file's own history, and those must
    # render an empty cell rather than a book count wearing a percent sign --
    # the same rule the PROJECTED column already follows ("an invented
    # projection on a betting board is worse than an empty cell").
    if model_prob is not None:
        columns["confidence"] = model_prob
    # The book-breadth factor is still carried, under its own name, so the
    # score breakdown keeps every term it always had. It is already inside
    # `board_score_components` below; naming it at the top level too means a
    # reader can find it without opening the tooltip.
    book_confidence = _as_float(score.get("book_confidence"))
    if book_confidence is not None:
        columns["book_confidence"] = book_confidence

    # `#445`: SAY WHEN OUR OWN SIM DISAGREES WITH THE BET WE ARE SHOWING.
    #
    # Measured on the served board 2026-08-16: **32 of 108** rows carried a
    # NEGATIVE `model_edge_pct` -- the projection says this side is worse than
    # the market price implies -- and nothing on the card said so. A further 43
    # carried no model at all, which is a DIFFERENT state and must not render
    # the same way: "the sim dissents" and "the sim has no view" need different
    # fixes and different words.
    #
    # LABELLED, NOT SUPPRESSED, by decision 2026-08-16. Suppressing would let a
    # model with `settled: 0` veto rows on EV grounds it has not earned, and a
    # filter would be a weight of -infinity smuggled in as a rule. The EV is
    # real even where the sim dissents; the reader is told and decides.
    #
    # `_SCORE_SIM_WEIGHT` was 0.0 when this was written and is now **0.125,
    # capped at 1.5 EV points** -- so the sim has a BOUNDED say in the ordering,
    # which is still a long way from the unbounded veto a filter would give it.
    # The argument holds; only the constant it cited has moved.
    # SAY WHICH SIM IT IS. A live row's verdict comes from the LIVE re-sim, and
    # until now the board could not tell the reader that.
    #
    # `live_projection_join` overwrites `projection["model_prob_over"]` with the
    # re-sim's `live_prob_over` and RECOMPUTES `edge_vs_market_pct` from it
    # (`live_projection_join.py:583`), so on a live row that the re-sim priced,
    # `model_edge_pct` -- and therefore this verdict -- is ALREADY the live
    # sim's. The defect was that nothing said so: "our pregame model dislikes
    # this" and "the re-sim, watching the game, dislikes this" rendered as the
    # same three words, and they are not remotely the same claim to a bettor
    # holding a live ticket.
    #
    # `basis` is the authority, not the game state: a row can be in a live game
    # and still carry its pregame projection (the re-sim's coverage is bounded
    # by the live lens' own -- `live_projection_join` records the ceiling at 81
    # indexable rows against 1,385 live board rows). Reading `is_live` here
    # would label those pregame numbers as live, which is the fabrication this
    # whole column exists to avoid.
    sim_basis = str(projection.get("basis") or "").strip().lower()
    sim_is_live = sim_basis == "live_resim" or projection.get("live_prob_over") is not None
    if sim_is_live:
        columns["sim_basis"] = "live_resim"

    model_edge = _as_float(row.get("model_edge_pct"))
    if model_edge is None:
        # `none` IS THE ANSWER ONLY IF THE SIM REALLY HAS NO VIEW, and until now
        # it was the answer whenever the sim had no PRICED view -- which is a
        # different and much larger set.
        #
        # `sim_view` reads exactly one field. Measured on the served
        # `/api/intelligence/query` 2026-09-03, 1,344 ranked rows:
        # `model_edge_pct` is non-null on **0 of 514 NCAAF rows**, 10 of 631 MLB,
        # 87 of 181 soccer. The badge is not mis-firing on NCAAF -- it is
        # UNREACHABLE there, because `ncaaf/game_projections.py` sets
        # `edge_vs_market_pct = None` on all three markets ON PURPOSE (margins
        # lose to the close by 3.563 MAE at t=17.20, n=2233; totals were never
        # scored against the close at all and run 1.67x over-dispersed).
        #
        # But the sim still SAID something on those rows, and the board printed
        # it: `projected` 67.803 in the PROJECTED column next to a recommended
        # **Under 53.5**, scored +1.67, untagged. That is a DIRECTION
        # contradiction, and `disagrees` -- whose whole claim is about RATING
        # ("worse than the price implies") -- has never covered it. A missing
        # concept, not a broken one.
        #
        # SO: fall back to the sim's own continuous projection where a priced
        # edge does not exist. Every input is already on the row.
        #
        #   MEASURED, same payload: 71 of 141 NCAAF totals rows (50%) point the
        #   opposite way to the sim, and 21 of those carry a POSITIVE score.
        #   Gap `projected - line` over 43 games: mean +4.80, median +5.48,
        #   per-event SD 9.81, 46% of rows past 10 points.
        #
        # `_SIM_CONTRADICTION_MIN_GAP` is what keeps this from being a chip on
        # half the board -- see its own comment for what it is and is not
        # derived from.
        contradiction = _sim_direction_contradiction(row, projection)
        if contradiction is None:
            # `none` STILL HAD TWO STATES IN IT, and naming the bucket printed
            # the wrong one. USER-REPORTED 2026-09-03, minutes after the badge
            # shipped: MLB rows labelled "no sim view" with a number in the
            # PROJECTED column beside them.
            #
            #   Corey Seager, batter_total_bases over 1.5
            #     projected 1.046  model_probability 0.2407  model_edge_pct None
            #
            # Measured the same minute on the served payload: 16,284 rows,
            # `sim_view: none` on 10,032, and **3,300 of those (32.9%) carry a
            # model number** -- ncaaf 2,364, mlb 732, soccer 204. The sim had a
            # view; it could not be PRICED into an edge, typically because only
            # one side is quoted so there is no two-sided fair
            # (`_edge_unavailable_reason`, "one-sided market").
            #
            # The direction fallback above rescues the subset that also points
            # the wrong way past the gap threshold. Everything else fell to
            # `none` and was published as "the sim has no view", which is false.
            #
            # SPLIT AT THE SOURCE, not only in the renderer, because `sim_view`
            # is about to be PERSISTED ONTO ORDERS for the ROI split. A field
            # that conflates "no model" with "model, unpriced" would make that
            # split wrong on its first day, and unlike a badge nobody would see
            # it. Renderers are one consumer; the ledger is another.
            has_view = (
                _as_float(projection.get("projected")) is not None
                or _as_float(row.get("projected")) is not None
                or _as_float(row.get("model_probability")) is not None
                or _as_float(projection.get("model_prob_over")) is not None
            )
            columns["sim_view"] = "unpriced" if has_view else "none"
        else:
            columns["sim_view"] = "live_contradicts" if sim_is_live else "contradicts"
            columns["sim_line_gap"] = contradiction
            columns["sim_view_basis"] = "projection_vs_line"
    elif model_edge < 0:
        columns["sim_view"] = "live_disagrees" if sim_is_live else "disagrees"
        columns["sim_disagreement_pct"] = round(model_edge, 4)
    elif model_edge > 0:
        columns["sim_view"] = "live_agrees" if sim_is_live else "agrees"
    else:
        # EXACTLY ZERO IS NOT AGREEMENT. It was folded into `agrees` by a `>= 0`
        # test: the sim landing precisely on the market's own de-vigged price is
        # the sim declining to take a view, and reporting that as endorsement
        # overstates what the model said. Its own bucket, so it can never again
        # be counted as support.
        columns["sim_view"] = "neutral"

    # `#445` follow-up: A RAILED PROBABILITY IS NOT A DISAGREEMENT, IT IS AN
    # INSTRUMENT READING OFF-SCALE, and it needs its own word.
    #
    # `WIN% 0%` sat beside a RECOMMENDED moneyline on the served board
    # 2026-09-03 (Rutgers, -3233). Nothing about `agrees`/`disagrees`/`none`
    # describes that: the sim did not dissent, it returned a certainty. Kept as
    # a SEPARATE field rather than folded into `sim_view`, because the two are
    # orthogonal -- a row can be `agrees` AND railed, and collapsing them would
    # throw away whichever half was written second.
    #
    # Rails are the repo's own (`_CERTAINTY_FLOOR/CEILING`, 0.01/0.99), so a
    # value at or past them is by this platform's existing definition a
    # certainty claim, which `wnba-accuracy-assessment` records as the thing
    # a served card must never make.
    if model_prob is not None and (
        model_prob <= _SIM_CERTAINTY_FLOOR or model_prob >= _SIM_CERTAINTY_CEILING
    ):
        columns["sim_probability_railed"] = True

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


def _kicks_off_on_date(row: Mapping[str, Any], now: datetime) -> bool:
    """Does this row's game start on the board's own date?

    A row with NO start time is NOT imminent. `_within_horizon` keeps such a row
    (dropping it would hide a whole sport if a feed stopped stamping starts),
    but that argument does not transfer: keeping an unknown row is safe, while
    SEATING one on a guarantee meant for today would spend today's reserved
    slots on rows that may not be today at all -- the permissive-default trap.
    """
    raw = row.get("commence_time")
    if not raw:
        return False
    try:
        start = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return start.astimezone(timezone.utc).date() == now.date()


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
    rows_total: int | None = None,
    kind_floor: int = SHORTLIST_KIND_FLOOR,
    imminence_floor: int | None = None,
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
    imminence_floor_value = (
        imminence_floor
        if imminence_floor is not None
        else int(_env_float("SYNDICATE_SHORTLIST_IMMINENCE_FLOOR", SHORTLIST_IMMINENCE_FLOOR))
    )
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
    # Rows the BLEND put on the board that raw EV would have rejected. The
    # direct measure of the 2026-08-22 scoring change; zero here means the sim
    # is admitting nothing and the change is inert.
    admitted_by_blend = 0
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

    # `#525`. THE BUDGET IS THE WHOLE BOARD'S, NOT EACH SPORT'S.
    #
    # `per_sport` alone scales the persisted payload with the number of sports
    # in season -- a calendar fact nobody sets. Measured 2026-08-23 at four
    # sports: 1,600 rows, 5,747,257 bytes, 68.5% of the 8MB keyvalue ceiling,
    # with NCAAF opening ~08-29. See `_shortlist_rows_total`.
    #
    # Allocated off the PRE-FILTER counts, deliberately. Doing it after each
    # sport's value floor would make one sport's allowance depend on another
    # sport's hold measurement, which is both surprising and unstable between
    # builds. Over-granting a sport that then filters down is harmless -- the
    # slots simply go unused, exactly as they did before this existed.
    budget = allocate_row_budget(
        {slug: len(pool) for slug, pool in by_sport.items()},
        total=int(rows_total) if rows_total is not None else _shortlist_rows_total(),
        per_sport=int(per_sport),
        # Never starve a sport below its two kind floors: a board that shows a
        # sport at all should show enough of it to be worth the tab.
        minimum=max(0, int(kind_floor)) * 2,
    )

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
            if _row_admitted_by_blend(row, row_floor):
                admitted_by_blend += 1
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
        # The allocator's answer, never above the per-sport ceiling. `.get` with
        # the ceiling as default rather than 0: an unallocated sport must fall
        # back to the pre-`#525` behaviour, not to an empty board.
        limit = max(0, min(int(per_sport), int(budget.get(sport, per_sport))))
        picked: list[Mapping[str, Any]] = []
        picked.extend(game[:floor])
        picked.extend(prop[:floor])

        # TODAY'S SLATE IS SEATED BEFORE MERIT, not instead of it.
        imminence_floor = max(0, int(imminence_floor_value))
        imminent_seated = 0
        if imminence_floor:
            already = {id(row) for row in picked}
            imminent = [
                row
                for row in ranked
                if id(row) not in already and _kicks_off_on_date(row, reference_now)
            ]
            seated = imminent[:imminence_floor]
            imminent_seated = len(seated)
            picked.extend(seated)

        chosen_ids = {id(row) for row in picked}
        remainder = [row for row in ranked + other if id(row) not in chosen_ids]
        remainder.sort(key=_score_of, reverse=True)
        picked.extend(remainder[: max(0, limit - len(picked))])

        # TRUNCATE THE MERIT TAIL, NOT THE GUARANTEES. The old line re-sorted
        # the whole list by score and cut, which silently discards the very rows
        # the floors above just guaranteed whenever the floors are large
        # relative to `limit` -- a guarantee that a later line can undo is not
        # one. Guaranteed rows keep their slots and are ordered by score among
        # themselves; only the merit fill absorbs the cut.
        guaranteed_count = min(len(picked), floor * 2 + imminent_seated)
        head = sorted(picked[:guaranteed_count], key=_score_of, reverse=True)
        tail = sorted(picked[guaranteed_count:], key=_score_of, reverse=True)
        picked = (head + tail)[:limit]
        selected.extend(dict(row) for row in picked)
        per_sport_report[sport] = {
            "available": len(rows),
            "selected": len(picked),
            "game": sum(1 for row in picked if str(row.get("kind") or "") == "game"),
            "prop": sum(1 for row in picked if str(row.get("kind") or "") == "prop"),
            # A RATE, NOT A COUNT: how much of the board is the day it claims to
            # be about. `selected_today` alone cannot say whether a low number
            # is crowding-out or simply a light slate -- `available_today` is the
            # denominator that separates them.
            "available_today": sum(1 for row in rows if _kicks_off_on_date(row, reference_now)),
            "selected_today": sum(1 for row in picked if _kicks_off_on_date(row, reference_now)),
            "imminence_seated": imminent_seated,
        }

    selected.sort(key=_score_of, reverse=True)
    persisted_bytes = len(json.dumps(selected, default=str))
    # Read from the store rather than hardcoded: if someone raises
    # SYNDICATE_KEYVALUE_MAX_BYTES, this percentage must move with it or it
    # becomes a second, silently-stale copy of the same limit.
    try:
        from syndicate.features.shared.refresh_state_store import _keyvalue_max_bytes

        _keyvalue_ceiling = int(_keyvalue_max_bytes())
    except Exception:
        _keyvalue_ceiling = 0
    # NO WARNING IS RAISED HERE, DELIBERATELY. This function can only see
    # `selected` — the ROWS — and the artifact that actually gets persisted also
    # carries `per_sport`, `cards`, `openings_records`, `clv_openings` and every
    # coverage payload. A guard on the rows fired silent while the real artifact
    # sat at 4,434,665 B (53% of the 8 MB ceiling), measured 2026-08-22
    # 20:56:30Z right after the cap went 100 -> 400. An all-clear from a
    # subset-measuring guard is worse than no guard at all.
    #
    # The warning now lives at `intelligence_state._warn_if_layer2_keys_near_ceiling`,
    # called from `write_layer2_shortlist` AFTER the shards are written, and it
    # measures ONE NUMBER PER KEY -- combined, each rows shard, each cards shard.
    #
    # It used to measure the whole payload, which was correct until the board was
    # sharded and then measured an object that is no longer written as one key:
    # `pct=93.3` on a perfectly healthy 1,600-row board on 2026-08-31, advising a
    # cap that was not the constraint. The store raises PER KEY; there is no
    # ceiling on "the payload".
    #
    # The two numbers below are kept because they are honest as long as they are
    # named for what they measure: `persisted_bytes` is the ROWS' contribution,
    # not the artifact's size, and the pct is derived from it.
    return {
        "rows": selected,
        "per_sport": per_sport_report,
        # Only sports with a slate consume budget; the rest contribute nothing.
        "active_sports": sorted(per_sport_report.keys()),
        "per_sport_limit": int(per_sport),
        # `#525`. BOTH numbers, because they answer different questions and the
        # ceiling alone stopped being the binding one the moment a total existed.
        # A board that shrank because a fifth sport came into season must not
        # look like a board that shrank because its pool did.
        "rows_total_budget": int(rows_total) if rows_total is not None else int(_shortlist_rows_total()),
        "rows_allocated_by_sport": dict(budget),
        "kind_floor": int(kind_floor),
        "imminence_floor": int(imminence_floor_value),
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
        # Reported beside the rejection it is the mirror of. `#397`'s
        # discipline: the counter ships in the SAME commit as the rule that
        # produces it, because a filter whose effect cannot be read is one
        # nobody can tell apart from a thin slate.
        "rows_admitted_by_blend": admitted_by_blend,
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
        # THE ROWS' CONTRIBUTION, not the artifact's size. Renamed from the
        # bare `persisted_bytes` it shipped as, because that name is what made a
        # subset read as the whole: the persisted artifact was 4.43 MB while
        # this number was comfortably under half the ceiling.
        "rows_bytes": persisted_bytes,
        # Kept under the old key so nothing downstream breaks, and its meaning
        # is now stated rather than implied.
        "persisted_bytes": persisted_bytes,
        "persisted_bytes_note": "rows only, and NOT what the store refuses -- since sharding, rows/cards live in per-sport keys; see LAYER2_KEY_LARGE for per-key sizes",
        "rows_pct_of_keyvalue_max": round(100.0 * persisted_bytes / _keyvalue_ceiling, 1)
        if _keyvalue_ceiling
        else None,
    }
