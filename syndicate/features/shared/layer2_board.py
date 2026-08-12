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
from syndicate.features.shared.opportunity_signals import (
    blended_score,
    devig,
    expected_value_pct,
)

# Identity carried from the market row onto every candidate. Kept explicit
# rather than copying the whole row: the grid row holds `cells` (every book x
# every side), which is large and has no business in a shortlist payload.
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
SHORTLIST_MAX_QUOTE_AGE_SECONDS = 24 * 3600


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
# 2.0 = "a market may hold up to twice what this sport typically holds". Below
# that it is normal pricing; beyond it the price is materially worse than the
# sport's own market structure explains.
SHORTLIST_HOLD_MULTIPLE = 2.0

# Fewest two-sided markets needed before a sport's measured hold is trusted.
# Under this the flat default is used, because a median over three markets is
# not a market-structure measurement -- it is noise with a decimal point.
SHORTLIST_HOLD_MIN_MARKETS = 8


def _measured_floor_for_pool(rows: Iterable[Mapping[str, Any]], *, multiple: float, fallback: float) -> tuple[float, dict[str, Any]]:
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
    from syndicate.features.shared.opportunity_signals import hold_pct

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


def _row_quote_age_seconds(row: Mapping[str, Any]) -> float | None:
    quote = row.get("quote")
    return _as_float(quote.get("book_age_seconds")) if isinstance(quote, Mapping) else None


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
    prices = [(_as_float((best.get(side) or {}).get("price")), side) for side in sides]
    if len(prices) >= 2 and all(price is not None for price, _ in prices):
        probabilities = devig([price for price, _ in prices])
        if probabilities and len(probabilities) == len(prices):
            return ({side: probabilities[i] for i, (_, side) in enumerate(prices)}, "two_sided")

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
                "suspect_stale": bool(side_best.get("suspect_stale")),
            }

            candidate: dict[str, Any] = {field: row.get(field) for field in _IDENTITY_FIELDS}
            candidate["side"] = side
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
    """Line/odds movement for a tracked market, or nothing (`#368`).

    The untracked case is labelled in `_layer2_board_columns`, not here, so that
    a row still gets its "not tracked" marker even when the shard is unreadable.
    """
    if not _movement_is_tracked(row.get("market")):
        return {}
    sport = str(row.get("sport") or "").strip().lower()
    shard = str(row.get("commence_time") or "")[:10]
    if not sport or not shard:
        return {}
    key = (sport, shard)
    if key not in cache:
        try:
            from syndicate.features.shared.odds_control_plane import load_odds_history_payload_for_sport

            cache[key] = load_odds_history_payload_for_sport(sport, shard)
        except Exception:
            # Unreadable history must not take the shortlist build down. The row
            # simply carries no movement, which renders as the same dash it does
            # today -- a strictly-no-worse failure.
            cache[key] = None
    movement = _line_movement_for_row(row, cache.get(key))
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
    """Fair American price from a no-vig probability. Mirrors
    `wnba/cards.py::_american_from_prob` rather than inventing a second
    convention, including its 2%-98% clamp."""
    prob = _as_float(probability)
    if prob is None:
        return None
    prob = max(0.02, min(0.98, prob))
    if prob >= 0.5:
        return round(-100.0 * prob / max(0.001, 1.0 - prob), 0)
    return round(100.0 * (1.0 - prob) / max(0.001, prob), 0)


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


def _within_horizon(row: Mapping[str, Any], now: datetime, horizon_days: int | None) -> bool:
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
    by_sport: dict[str, list[Mapping[str, Any]]] = {}
    beyond_horizon = 0
    below_value_floor = 0
    beyond_quote_age = 0
    implausible_book = 0
    stale_kickoff = 0
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
        kept: list[Mapping[str, Any]] = []
        for row in rows:
            value_pct = _row_value_pct(row)
            if value_pct is not None and value_pct < sport_floor:
                below_value_floor += 1
                continue
            kept.append(row)
        rows = kept

        ranked = sorted(rows, key=_score_of, reverse=True)
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
        # `#369`: named separately from the value floor, because "the book is
        # impossible" and "this row is priced below our floor" are different
        # rejections and collapsing them would hide a feed problem as taste.
        "rows_implausible_book": implausible_book,
        "rows_beyond_quote_age": beyond_quote_age,
        "rows_stale_kickoff": stale_kickoff,
        "persisted_bytes": len(json.dumps(selected, default=str)),
    }
