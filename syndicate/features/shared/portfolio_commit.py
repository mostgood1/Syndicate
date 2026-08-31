"""Stage A -- turn the Layer 2 shortlist into a COMMITTED portfolio.

A ranked board says "here are 108 rows, best first". A portfolio says "these
nine, at these dollars, totalling this". This module is the step between, and
it is the first thing in the system that converts a fraction into money.

**WORKER-SIDE. It must not be called from a request path**, and
`commit_portfolio` refuses if it is. That is CLAUDE.md's load-bearing rule, and
`layer2_board.py`'s header states the second, stronger reason: *a board computed
per request cannot be settled.* A portfolio computed per request cannot be
settled either, which would make Stage C's CLV gate impossible -- so the refusal
is protecting the measurement, not just the web dyno.

--------------------------------------------------------------------------
THE DEFECT THIS MODULE WAS WRITTEN AROUND, measured 2026-08-22
--------------------------------------------------------------------------

`_attach_board_stakes` (`intelligence_state.py:4216`) attaches `stake` to
`global_pool` -- the LAYER 1 pool. The Layer 2 shortlist is built separately by
`build_layer2_shortlist` from the market grid and is a different set of row
objects. **Layer 2 rows carry no `stake`, and never have.** Verified by reading
every `candidate["..."]` assignment in `layer2_board.py`: a shortlist row
carries `side`, `line`, `quote`, `game`, `projection`, `movement`, `ev_pct`,
`model_edge_pct`, `score`, `board_lane` -- and nothing else.

That matters far more than it looks, because of what `compute_bet_size` does
with a row that lacks its inputs (`bankroll_manager.py:115-127`):

    model_probability   absent -> defaults to 0.5
    implied_probability absent -> derived from `odds`, also absent -> 0.5
    edge = 0.5 - 0.5    = 0.0
    kelly_fraction      = 0.0
    stake               = $0

**Every position would be sized at exactly zero, silently, with no exception
and no log line** -- a portfolio that is empty because it was never fed,
presented identically to a portfolio that is empty because the model found
nothing. That is the exact failure `docs/ai_context/model_engine_standard.md`
exists for ("26 input fields the simulation reads and nothing feeds ... a
neutral default makes an unfed field indistinguishable from a working
feature").

So this module does three things instead of calling `compute_bet_size` on a raw
row:

1. **Derives the sizing inputs explicitly** (`sizing_inputs_from_row`), by
   inverting the board's own arithmetic rather than guessing.
2. **Refuses by name when an input is missing.** No neutral defaults. A row
   that cannot be sized is counted under a reason a person can read, so a small
   portfolio is always attributable.
3. **Is gated by an input checklist** (`scripts/portfolio_commit_input_checklist.py`)
   that walks `dataclasses.fields(SizingInputs)` -- never a name grep -- and
   exits non-zero if any field is unpopulated or unconsumed.

--------------------------------------------------------------------------
THE DERIVATION, and why it is exact rather than approximate
--------------------------------------------------------------------------

`ev_pct` on a shortlist row is `expected_value_pct(price, fair)`:

    ev/100 = p*profit - (1 - p)          [opportunity_signals.py:293]

which inverts exactly, given the same price the row was scored at:

    p_fair = (ev/100 + 1) / (profit + 1)

and `model_edge_pct` is `(model_prob - fair) * 100` in probability POINTS
(`prop_projections.py:978`, bounded by `_MODEL_EDGE_MAX_POINTS = 15.0`), so:

    p_model = p_fair + model_edge_pct/100

Both come off the row; neither is assumed.

**`odds` is passed to the sizer and `implied_probability` deliberately is NOT.**
`compute_bet_size` computes `edge / (decimal - 1)`, which equals textbook Kelly
`(p(b+1) - 1)/b` only when the subtracted probability is the price's OWN
implied probability including vig -- not the de-vigged consensus fair. Passing
`p_fair` there would look more sophisticated and would silently compute a
different, larger number. So the price goes in and the sizer derives its own
implied probability, exactly as its arithmetic assumes.

**`price_reliability` is applied HERE, explicitly, and not by handing it to the
sizer as `confidence`.** That was the first implementation and the input
checklist caught it as inert on the first run. Measured 2026-08-22:

    kelly_fraction 0.0241 -> stake 0.00151   (x0.25 Kelly, x0.25 credibility)
    cap_fraction   0.0446                    (0.02 + 0.03 x confidence)

`compute_board_stake` shrinks the RAW `kelly_fraction` and then applies
`cap_fraction` as a ceiling -- and `confidence` feeds only that ceiling, which
sits ~30x above the stake and therefore never binds. Dropping the trust weight
from 0.82 to 0.32 moved the cap 0.0446 -> 0.0296 and moved the stake **not at
all**. So `confidence` is structurally inert in this path, and passing
reliability through it would have looked wired and done nothing -- the exact
failure `model_engine_standard.md` was written for.

**This is a property of `bankroll_manager`, not of this adapter**, so it is also
true of `_attach_board_stakes` on the Layer 1 pool: whatever `confidence` a
board candidate carries, it does not move the served stake. `bankroll_manager.py`
is read-only for this lane -- recorded here and in `lanes.md`, not fixed.

`confidence` is still passed, because the cap should be right on the rare row
where it does bind. But the trust discount is applied as its own named
multiplier, and both the factor and the pre-discount fraction ride on the
position so the number can be argued with. They remain different quantities and
neither is ever published under the other's name (`learnings.md` 2026-08-21,
FORBIDDEN).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, fields as dataclass_fields
from datetime import datetime, timezone
from typing import Any, Mapping

from syndicate.features.bankroll_manager import apply_exposure_budgets, compute_board_stake
from syndicate.features.shared.clv_position_join import opening_key_for_row
from syndicate.features.shared.portfolio_settings import PortfolioSettings, resolve_settings
from syndicate.features.shared.request_path_guard import refuse_if_compute_in_request_path

# Carried onto every position so a committed bet can be found again -- in the
# shortlist it came from, in the ledger it lands in, and at the venue that
# fills it.
_POSITION_IDENTITY_FIELDS = (
    "sport",
    "event_id",
    "kind",
    "market",
    "segment",
    "player_name",
    "home_team",
    "away_team",
)

# `commence_time` USED TO BE IN THE TUPLE ABOVE AND IT PUT REAL MONEY ON THE
# BOARD TWICE.
#
# Measured 2026-08-30, live, found by the USER on Polymarket's own Orders
# screen:
#
#     C6H7WE0DPKDJ  $4.06  16:42:22Z  tsc-mlb-lad-det-2026-08-30-7pt5 under 7.5 @ -104
#     C6HN0XD92KDE  $5.44  17:19:26Z  tsc-mlb-lad-det-2026-08-30-7pt5 under 7.5 @ -104
#
# ~$9.12 resting where ONE bet was intended. Every identity field byte-identical
# except `commence_time`: `17:41:00Z -> 18:11:00Z`. The Dodgers-Tigers start was
# restated 30 minutes between board builds, `position_key` changed,
# `idempotency_key` is derived from it, and `record_order` saw a bet it had
# never seen.
#
# **THE GUARD DID NOT FAIL -- IT WAS NEVER CONSULTED.** `execution_ledger` says
# "the same bet computed twice yields the same key, so the second write is
# refused" and "`filled`, `submitted` and `failed` all mean the venue may hold
# this order". Both hold only while every hashed input is stable, and
# `commence_time` is the one input a sports feed is EXPECTED to restate.
#
# THE CLINCHER: `opening_key`, built for the same joining purpose, ALREADY
# excludes `commence_time` -- and it was identical across both orders. Two keys
# for the same bet disagreed about what a bet is, and the unstable one was the
# one driving idempotency. `event_id` already names the game; the tuple was
# mixing immutable facts about the BET with mutable attributes of the FIXTURE.
#
# THE TRIGGER THRESHOLD IS ZERO, and an earlier version of this comment said
# "every rain delay, postponement and doubleheader restatement", which
# UNDERSTATES IT badly enough to mislead. Framed as delays, a reader concludes
# this is rare and seasonal. It is neither: ANY restatement at all mints a new
# key, because the whole string is hashed.
#
#     +1 second   -> new key
#     +3m38s      -> new key
#     +30 min     -> new key
#
# A SECOND CONFIRMED INSTANCE, and this one FILLED AND LOST -- found by lane
# `position-key-commence-time-instability` grouping 398 live orders by
# `opening_key`, the stable identity:
#
#     HOU@NYY  h2h away  2026-08-26   BOTH FILLED, BOTH LOST
#       15:04:15  stake 3.41  fill 0.465  pnl -3.41   commence 23:05:00Z
#       01:33:16  stake 1.27  fill 0.040  pnl -0.78   commence 23:08:38Z
#
# **A 3m38s delta** -- ordinary feed jitter restating first pitch to the second,
# not a delay. **$0.78 of real loss on a bet nobody intended**, placed 2h33m
# AFTER first pitch into a 4-cent longshot on a game already in progress. It is
# also `h2h` with an empty `line`, so this is not confined to totals.
#
# TWO IS A FLOOR, NOT A COUNT: that scan only sees pairs where BOTH legs survive
# in the book sharing an `opening_key`. A pair whose other leg was hidden,
# refused, or aged out of retention is invisible to it.
#
# Raised by lane `position-key-commence-time-instability`; verified here against
# both key builders before changing anything.
_LEGACY_POSITION_IDENTITY_FIELDS = _POSITION_IDENTITY_FIELDS + ("commence_time",)


@dataclass(frozen=True)
class SizingInputs:
    """Everything the sizer needs, stated explicitly.

    One field per quantity, no optionals: a `SizingInputs` that exists is
    complete by construction, so "could not size this row" is expressed by
    returning None WITH a reason and never by a half-populated object. The
    checklist walks these fields, so adding one here forces it to be both
    populated and consumed or the gate fails.
    """

    american_price: float
    market_fair_probability: float
    model_probability: float
    price_reliability: float


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _net_profit_per_unit(american: float) -> float | None:
    """Decimal odds minus one -- what a winning unit returns as profit."""
    if american == 0:
        return None
    return (american / 100.0) if american > 0 else (100.0 / abs(american))


def sizing_inputs_from_row(row: Mapping[str, Any]) -> tuple[SizingInputs | None, str | None]:
    """Derive sizing inputs from a Layer 2 shortlist row, or say why not.

    Returns `(inputs, None)` or `(None, reason)`. Never returns a partially
    populated object and never substitutes a neutral default -- see the module
    docstring for what a neutral default costs here.
    """
    if not isinstance(row, Mapping):
        return None, "row_not_a_mapping"

    quote = row.get("quote")
    price = _as_float(quote.get("price")) if isinstance(quote, Mapping) else None
    if price is None:
        return None, "no_quote_price"
    profit = _net_profit_per_unit(price)
    if profit is None:
        return None, "unusable_price"

    ev_pct = _as_float(row.get("ev_pct"))
    if ev_pct is None:
        # The row was ranked on something other than EV, or had no fair price to
        # score against. Either way there is no market probability to recover.
        return None, "no_ev_pct"

    fair = (ev_pct / 100.0 + 1.0) / (profit + 1.0)
    if not (0.0 < fair < 1.0):
        return None, "derived_fair_probability_out_of_range"

    model_edge_pct = _as_float(row.get("model_edge_pct"))
    if model_edge_pct is None:
        # Roughly 40% of the served board: 65 of 108 rows carried
        # `model_edge_pct` when measured 2026-08-16. Those rows rank on market
        # EV and price shopping alone, which is a legitimate way to RANK and not
        # a basis on which to SIZE -- without a model view, `model_probability`
        # would equal `fair` and Kelly would be exactly zero anyway. Refused by
        # name so the board's unsizable half is visible rather than inferred.
        return None, "no_model_edge_pct"

    model_probability = fair + (model_edge_pct / 100.0)
    if not (0.0 < model_probability < 1.0):
        return None, "derived_model_probability_out_of_range"

    score = row.get("score")
    price_reliability = _as_float(score.get("price_reliability")) if isinstance(score, Mapping) else None
    if price_reliability is None:
        return None, "no_price_reliability"

    return (
        SizingInputs(
            american_price=price,
            market_fair_probability=fair,
            model_probability=model_probability,
            price_reliability=price_reliability,
        ),
        None,
    )


def sizing_candidate(row: Mapping[str, Any], inputs: SizingInputs) -> dict[str, Any]:
    """The mapping `compute_board_stake` actually reads, built explicitly.

    Deliberately NOT `{**row, ...}`. Splatting the row would let any future
    field on a shortlist row start steering the sizer by name collision --
    `bankroll_manager` reads `adjusted_edge`, `edge`, `confidence`,
    `volatility_score` and `odds` off whatever mapping it is handed. Listing the
    keys here means the sizer's inputs are exactly the four derived above plus
    the identity needed to group exposure, and adding a fifth is a visible edit.
    """
    return {
        # `implied_probability` is deliberately absent; the sizer derives it
        # from `odds`. See the module docstring.
        "odds": inputs.american_price,
        "model_probability": inputs.model_probability,
        # Feeds `cap_fraction` only, which almost never binds -- see the
        # module docstring. The real trust discount is applied by
        # `apply_price_reliability` below, not here.
        "confidence": inputs.price_reliability,
        # Read by `_exposure_group_key` so correlated legs on one game are
        # budgeted together rather than treated as independent.
        "sport": row.get("sport"),
        "sport_slug": row.get("sport"),
        "event_id": row.get("event_id"),
        # Read by `apply_exposure_budgets` to decide which leg in a game keeps
        # its full stake. The board's own blended score is the right ordering.
        "adjusted_score": _score_value(row),
    }


def _score_value(row: Mapping[str, Any]) -> float | None:
    score = row.get("score")
    if isinstance(score, Mapping):
        return _as_float(score.get("score"))
    return None


def position_key(row: Mapping[str, Any]) -> str:
    """A stable identity for one committed bet.

    Hashed over the identity tuple PLUS the side, the line and the book, because
    those three are what make it a different bet rather than a different view of
    the same market. `learnings.md` is explicit that a wrongly resolved identity
    "prices a projection against a different human being, which is worse at any
    stake than no bet" -- and this key is what Stage B's idempotency and Stage
    C's settlement join will both hang off, so it is an identity or it is
    nothing.
    """
    return _position_key_over(row, _POSITION_IDENTITY_FIELDS)


def legacy_position_key(row: Mapping[str, Any]) -> str:
    """The PRE-2026-08-30 key, with `commence_time` still in the tuple.

    Emitted alongside the real key so the duplicate guard can recognise orders
    placed before the fix. WITHOUT THIS, THE FIX CAUSES THE BUG IT REMOVES:
    `idempotency_key` takes `position_key` as its first component, so changing
    the formula changes the key of EVERY open position at once, and the very
    next commit would see the entire open book as bets it had never placed.

    One duplicate is what prompted this change; deploying it naively would have
    produced one per open position, simultaneously, on live money.

    Delete this and its plumbing once no ledger row predates the change --
    which is a date, not a judgement: no order older than the deploy remaining
    in a non-terminal state.
    """
    return _position_key_over(row, _LEGACY_POSITION_IDENTITY_FIELDS)


def _position_key_over(row: Mapping[str, Any], fields: tuple[str, ...]) -> str:
    quote = row.get("quote") if isinstance(row.get("quote"), Mapping) else {}
    parts = [str(row.get(field) or "") for field in fields]
    parts.append(str(row.get("side") or ""))
    parts.append(str(row.get("line") if row.get("line") is not None else ""))
    parts.append(str(quote.get("bookmaker") or ""))
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def commit_portfolio(
    rows: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    *,
    selected_date: str,
    settings: PortfolioSettings | None = None,
    settled_sample_size_by_sport: Mapping[str, int] | None = None,
    prefer_placeable: bool = False,
) -> dict[str, Any]:
    """Rank -> size -> budget -> cut. Returns the committed plan.

    Every row that does not make it is counted under a named reason, and the
    reasons sum to `rows_in`. That is not bookkeeping for its own sake: a plan
    with zero positions is a routine outcome (a thin slate, a strict floor) and
    an alarming one (nothing is being fed) and the only thing that tells them
    apart is which reason the rows landed under.
    """
    refuse_if_compute_in_request_path("commit_portfolio")

    resolved = settings or resolve_settings()
    samples = dict(settled_sample_size_by_sport or {})
    refusals: dict[str, int] = {}
    # WHICH MARKETS DIE WHERE. The bare `refusals` counter says 98 rows had no
    # model edge and 78 missed the EV floor; it cannot say whether those were
    # props or game lines, so "why are no prop positions being taken" is
    # unanswerable from it. Kalshi's inventory is prop-heavy -- its
    # `sources_offered` sample is batter_home_runs, strikeouts, player_threes --
    # which makes that exactly the question its refusals need to answer.
    #
    # Same defect twice fixed elsewhere tonight: a counter that names a problem
    # while withholding the data needed to act on it.
    refusals_by_market: dict[str, dict[str, int]] = {}
    rows_in = 0

    def refuse(reason: str, row: Any = None) -> None:
        refusals[reason] = refusals.get(reason, 0) + 1
        market = ""
        if isinstance(row, Mapping):
            market = str(row.get("market") or "").strip().lower()
        # `unkeyed` rather than dropping the count: a refusal whose row carries
        # no market is still a refusal, and silently omitting it would make the
        # per-market totals disagree with `refusals` for no visible reason.
        bucket = refusals_by_market.setdefault(reason, {})
        key = market or "unkeyed"
        bucket[key] = bucket.get(key, 0) + 1

    priced: list[dict[str, Any]] = []
    for row in rows or ():
        rows_in += 1
        if not isinstance(row, Mapping):
            refuse("row_not_a_mapping", None)
            continue
        inputs, reason = sizing_inputs_from_row(row)
        if inputs is None:
            refuse(reason or "unknown", row)
            continue

        ev_pct = _as_float(row.get("ev_pct"))
        if ev_pct is None or ev_pct < resolved.min_ev_pct:
            refuse("below_min_ev_pct", row)
            continue

        sport = str(row.get("sport") or "").strip().lower()
        candidate = sizing_candidate(row, inputs)
        try:
            candidate["stake"] = compute_board_stake(
                candidate, settled_sample_size=samples.get(sport, 0)
            )
        except Exception:
            refuse("sizing_failed", row)
            continue
        if (_as_float(candidate["stake"].get("stake_fraction")) or 0.0) <= 0.0:
            refuse("zero_kelly_stake", row)
            continue
        apply_price_reliability(candidate, inputs)
        attribution = stake_attribution(
            row, inputs, settled_sample_size=samples.get(sport, 0)
        )
        priced.append(
            {"row": row, "inputs": inputs, "candidate": candidate, "attribution": attribution}
        )

    # Exposure budgeting BEFORE the count cut, so the per-game cap sees every
    # correlated leg rather than only the ones that survived truncation --
    # trimming first would let two legs of a three-leg group look independent.
    exposure = apply_exposure_budgets([item["candidate"] for item in priced])

    # THE CUT IS BY SCORE, AND IN A VENUE PLAN THAT IS NOT ENOUGH.
    #
    # A venue-scoped row priced from the AGGREGATOR carries no venue contract
    # id and can never be bought at that venue -- `scope_rows_to_venue` records
    # which book priced it in `price_source`. Ranking those against placeable
    # rows lets a bet we cannot make consume one of `max_positions` (12) slots
    # and push out one we can.
    #
    # Measured 2026-08-25 5:17:58 PM Central, the first Kalshi plan that ever
    # priced off Kalshi's own book: 161 of 233 rows were venue-priced, 40 were
    # cut here, and the single position that survived was
    # `price_source=aggregator` -- unplaceable, and holding the only slot that
    # mattered. `ORDER_PATH venue=kalshi` refused it `no_venue_ticker`.
    #
    # PLACEABILITY IS PRIMARY, NOT A TIEBREAK, and that is the whole decision:
    # an unplaceable row's score is a statement about a bet we cannot hold, so
    # ranking it above one we can optimises a book nobody can own. Nothing is
    # DROPPED -- aggregator rows still fill whatever slots remain, and the
    # restricted-vs-unrestricted comparison still has its full population.
    #
    # OFF BY DEFAULT so the main plan is provably unchanged: its rows carry no
    # `price_source` at all, and an implicit "is the field present" test would
    # make that guarantee depend on a field nobody set. The venue loop opts in.
    def _rank(item: Mapping[str, Any]) -> tuple[int, float]:
        score = _score_value(item["row"]) or float("-inf")
        if not prefer_placeable:
            return (0, score)
        placeable = str(item["row"].get("price_source") or "") == "venue_feed"
        return (1 if placeable else 0, score)

    priced.sort(key=_rank, reverse=True)
    if len(priced) > resolved.max_positions:
        for dropped in priced[resolved.max_positions :]:
            refuse("beyond_max_positions", dropped["row"])
        priced = priced[: resolved.max_positions]

    # The slate ceiling. Scaled proportionally rather than truncated: Kelly
    # fractions are meaningful relative to each other, so shrinking the whole
    # book preserves the portfolio's composition where dropping its tail would
    # change which bets are in it. The factor is reported so the reduction is
    # never silent.
    total_fraction = sum(
        _as_float((item["candidate"].get("stake") or {}).get("stake_fraction")) or 0.0
        for item in priced
    )
    ceiling = resolved.max_slate_exposure_fraction
    slate_scale = 1.0
    if total_fraction > ceiling and total_fraction > 0:
        slate_scale = ceiling / total_fraction

    positions: list[dict[str, Any]] = []
    sim_dollars = 0.0
    for item in priced:
        row, inputs, candidate = item["row"], item["inputs"], item["candidate"]
        stake = dict(candidate.get("stake") or {})
        pre_budget = _as_float(stake.get("stake_fraction_pre_exposure"))
        fraction = (_as_float(stake.get("stake_fraction")) or 0.0) * slate_scale
        dollars = round(fraction * resolved.bankroll_units, 2)
        if dollars < resolved.min_stake_units:
            # Not rounded up. A position too small to place is not a position,
            # and inflating it to the minimum would silently overbet the row
            # the sizer just said to bet least on.
            refuse("below_min_stake", row)
            continue
        # Scale the EV-only counterfactual by whatever the budgeting and the
        # slate ceiling did to the real stake, so the two are comparable at the
        # size actually committed rather than at the pre-budget one.
        raw = item["attribution"]
        budget_scale = (fraction / pre_budget) if pre_budget else 1.0
        # Quantise the counterfactual to the SAME precision the committed
        # fraction carries. `apply_exposure_budgets` rounds to 5dp and
        # `apply_price_reliability` to 6dp, and differencing across that
        # mismatch reported a 2e-06 artifact as a 0.15% sim contribution on a
        # row whose sim edge was exactly zero. A decomposition that invents a
        # component out of rounding is worse than none.
        ev_only = round(raw["_ev_only_basis"] * budget_scale, 5)
        sim_delta = round(fraction - ev_only, 6)
        # NOT clamped at zero. A small NEGATIVE sim edge still clears Kelly on a
        # good enough price, so the sim can legitimately SHRINK a position it
        # did not veto -- and that is exactly the kind of contribution S6 needs
        # to be able to score. Clamping would hide the sim's losses and keep
        # only its gains, which is how a component gets credited for an edge it
        # does not have.
        attribution = {
            "stake_fraction_ev_only": ev_only,
            "stake_fraction_sim_delta": sim_delta,
            "sim_share_of_stake": round(sim_delta / fraction, 4) if fraction else None,
            "stake_dollars_ev_only": round(ev_only * resolved.bankroll_units, 2),
            "stake_dollars_sim_delta": round(sim_delta * resolved.bankroll_units, 2),
            "side_picked_by": raw["side_picked_by"],
        }
        sim_dollars += attribution["stake_dollars_sim_delta"]
        quote = row.get("quote") if isinstance(row.get("quote"), Mapping) else {}
        position = {field: row.get(field) for field in _POSITION_IDENTITY_FIELDS}
        position.update(
            {
                # WHAT A POSITION *IS* AND WHAT IT *CARRIES* ARE TWO LISTS, and
                # this line used to be the only one. The projection above is
                # over the IDENTITY tuple, so the moment `commence_time` left
                # that tuple -- correctly, it had put ~$9.12 on the board where
                # one bet was intended -- it also left the position PAYLOAD,
                # the `OrderRequest` built from it, and every ledger row after.
                #
                # MEASURED 2026-08-31, a perfect temporal split across 59 live
                # orders and every sport:
                #     WITH commence_time    28   submitted 16:41:53 .. 18:59:26
                #     WITHOUT               31   submitted 19:05:14 .. 03:40:39
                # Zero overlap. It reads as a SOCCER gap (18 of 19 missing)
                # only because soccer's orders are the recent ones; MLB and
                # WNBA lose it identically after the cutover.
                #
                # It is restored HERE, in the carried block, and deliberately
                # NOT in `_POSITION_IDENTITY_FIELDS` -- putting it back there
                # would re-create the double-bet this repo just paid for. A
                # restated kickoff must not mint a new position; it must still
                # be legible on the order.
                "commence_time": row.get("commence_time"),
                "position_key": position_key(row),
                # Carried so `record_order` can recognise a pre-fix order. See
                # `legacy_position_key`.
                "legacy_position_key": legacy_position_key(row),
                # STAMPED FROM THE SAME ROW, IN THE SAME RUN. `record_openings`
                # wrote this row's opening moments earlier in
                # `layer2_shortlist.py`, from this same row -- so computing the
                # ledger's key here is exact by construction rather than a
                # reconstruction that has to be trusted. Stage C's whole gate is
                # a CLV number, and a CLV number needs the opening this bet was
                # taken against; `#505` is what a join keyed on a reconstruction
                # costs (4,560 `no_key_match` of 8,276). `None` when the row
                # cannot be keyed at all, which is the ledger's own rule applied
                # by the ledger's own code.
                "opening_key": opening_key_for_row(row),
                # THE SPORT'S OWN GAME ID, carried because live win/loss needs
                # it and `event_id` is not it. MLB's live feed is keyed by
                # `gamePk`; an order holding only the OddsAPI event id cannot
                # be looked up at all, which is what stopped `bet_status` from
                # having a resolver. Copied from whichever field the row
                # carries -- `gamePk` on MLB/NFL rows, `game_id` elsewhere.
                # DELIBERATELY NOT `row.get("game_pk")`, which the board sets
                # from `event_id` -- the OddsAPI hash, a different id space from
                # StatsAPI's numeric gamePk (`intelligence_contracts` documents
                # the split). Stamping it would produce a field that LOOKS
                # populated and is the wrong id, which is worse than None:
                # `bet_status_mlb` can recover a real gamePk from the matchup,
                # but only if it is not handed a plausible-looking wrong one
                # first. Leave this None when the row has no native id.
                "game_pk": row.get("gamePk") or row.get("game_id") or None,
                "side": row.get("side"),
                "line": row.get("line"),
                "book": quote.get("bookmaker"),
                # American odds, the price this was committed at. Stage B's
                # ledger records it again at submit time; a difference between
                # the two IS the slippage and must stay visible.
                "price": inputs.american_price,
                # DOLLARS. Named so it can never be confused with
                # bankroll_manager's `stake_units`, which is percent-of-bankroll
                # x 100 and is a different quantity entirely.
                "stake_dollars": dollars,
                "stake_fraction": round(fraction, 6),
                "ev_pct": _as_float(row.get("ev_pct")),
                "model_edge_pct": _as_float(row.get("model_edge_pct")),
                # THE PRICE COST OF BEING RESTRICTED TO THIS VENUE, carried
                # through from `venue_scope`. On an unrestricted row these are
                # absent and stay None -- there is no "best book elsewhere" when
                # the row already took the best book.
                #
                # These were being DROPPED here: `venue_scope` set them on the
                # scoped row, the position was built from an explicit field list
                # that did not name them, and paper2's comparison table read them
                # anyway. It rendered nothing for months because paper2 had zero
                # positions; the first slate that produced one 500'd the page.
                # Half of what the two-book comparison exists to show is exactly
                # this gap, so carrying them is the fix and the template guard is
                # only the seatbelt.
                "unrestricted_price": _as_float(row.get("unrestricted_price")),
                "unrestricted_ev_pct": _as_float(row.get("unrestricted_ev_pct")),
                "unrestricted_bookmaker": row.get("unrestricted_bookmaker"),
                "venue": row.get("venue"),
                "price_source": row.get("price_source"),
                # The exchange contract this position would be placed on. None
                # on an unrestricted row -- there is no single contract when the
                # price came from an aggregator's best-of-many.
                "venue_ticker": row.get("venue_ticker"),
                "model_probability": round(inputs.model_probability, 5),
                "market_fair_probability": round(inputs.market_fair_probability, 5),
                "price_reliability": round(inputs.price_reliability, 5),
                "board_score": _score_value(row),
                # THE S6 INPUT. See `stake_attribution` -- this is what lets
                # settlement decompose CLV by component and is the stated
                # condition for ever raising `_SCORE_SIM_WEIGHT` off 0.0.
                "attribution": attribution,
                # The full breadcrumb, so the number is inspectable rather than
                # trusted: which Kelly fraction, shrunk by how much, on what
                # settled evidence.
                "sizing": {
                    "kelly_fraction": stake.get("kelly_fraction"),
                    "kelly_multiplier": stake.get("kelly_multiplier"),
                    "sample_credibility": stake.get("sample_credibility"),
                    "settled_sample_size": stake.get("settled_sample_size"),
                    "cap_fraction": stake.get("cap_fraction"),
                    "price_reliability_factor": stake.get("price_reliability_factor"),
                    "stake_fraction_pre_reliability": stake.get("stake_fraction_pre_reliability"),
                    "stake_fraction_pre_exposure": stake.get("stake_fraction_pre_exposure"),
                    "exposure_capped": stake.get("exposure_capped"),
                    "exposure_group_size": stake.get("exposure_group_size"),
                    "slate_scale_factor": round(slate_scale, 6),
                },
            }
        )
        positions.append(position)

    staked_dollars = round(sum(item["stake_dollars"] for item in positions), 2)
    return {
        "selected_date": selected_date,
        "generated_at": _utc_now(),
        "bankroll_units": resolved.bankroll_units,
        "settings": resolved.as_dict(),
        "positions": positions,
        "totals": {
            "positions": len(positions),
            "staked_dollars": staked_dollars,
            "staked_fraction": round(
                (staked_dollars / resolved.bankroll_units) if resolved.bankroll_units else 0.0, 6
            ),
            "slate_scale_factor": round(slate_scale, 6),
            "slate_exposure_ceiling_dollars": round(resolved.max_slate_exposure_units(), 2),
            # Plan-level answer to "how much of tonight's money is the model?"
            # -- reportable on the surface, and the aggregate S6 needs.
            "staked_dollars_sim_attributed": round(sim_dollars, 2),
            "sim_share_of_staked": (
                round(sim_dollars / staked_dollars, 4) if staked_dollars else None
            ),
            "positions_where_sim_picked_the_side": sum(
                1 for item in positions if item["attribution"]["side_picked_by"] == "simulation"
            ),
        },
        # THE SIM'S ACTUAL REACH, as a first-class number rather than something
        # to infer from the refusal counts.
        #
        # WHY IT IS REPORTED HERE AND NOWHERE ELSE. The board's own
        # `sim_component` cannot answer this: it is
        # `_SCORE_SIM_WEIGHT * value_sim` with the weight at 0.0, so it is
        # **structurally** `0.0` for every row that HAS a sim view and `None`
        # for every row that does not. It can never be non-zero, which makes
        # "the board is 0% sim" true and also uninformative -- it says nothing
        # about whether the sim produced anything.
        #
        # `rows_with_sim_edge` is the honest version: how many rows carried a
        # probability-space `model_edge_pct` at all. Measured on the served
        # shortlist 2026-08-16, that was 65 of 108. This counts it every run.
        "sim_coverage": {
            "rows_in": rows_in,
            "rows_with_sim_edge": rows_in - refusals.get("no_model_edge_pct", 0),
            "rows_without_sim_edge": refusals.get("no_model_edge_pct", 0),
            "share_with_sim_edge": (
                round((rows_in - refusals.get("no_model_edge_pct", 0)) / rows_in, 4)
                if rows_in
                else None
            ),
        },
        "rows_in": rows_in,
        "sized": len(priced),
        # Sums to `rows_in` together with `len(positions)`. A plan that cannot
        # account for every row it was given is not a plan.
        "refusals": dict(sorted(refusals.items())),
        "refusals_by_market": {
            reason: dict(sorted(markets.items(), key=lambda kv: (-kv[1], kv[0])))
            for reason, markets in sorted(refusals_by_market.items())
        },
        "exposure": exposure,
    }


def stake_attribution(
    row: Mapping[str, Any],
    inputs: SizingInputs,
    *,
    settled_sample_size: int = 0,
) -> dict[str, Any]:
    """How much of this stake is the SIM, and how much is price shopping.

    **This is the measurement `_SCORE_SIM_WEIGHT`'s own comment says nobody has
    been able to supply.** That comment (`opportunity_signals.py:352-390`) sets
    exactly one condition for raising the weight off 0.0: *"S6: `settled > 0`
    and CLV decomposed BY COMPONENT, so the EV term and the sim term can be
    compared on outcomes rather than on taste."* Decomposing CLV by component
    requires knowing, per bet, which component put the money there. Nothing
    recorded that, so the condition could never be met no matter how long
    settlement ran.

    The decomposition is exact rather than estimated, because the counterfactual
    is available: re-size the identical row with the sim's edge set to zero.
    What remains is the pure de-vig price edge -- the stake this position would
    have carried on line shopping alone.

        stake_fraction            full, as committed
        stake_fraction_ev_only    the same row with model_edge_pct = 0
        stake_fraction_sim_delta  the difference
        sim_share_of_stake        delta / full

    Measured 2026-08-22 on a representative row (`ev_pct 4.5`, `model_edge_pct
    3.2`, -110, reliability 0.82): full 0.003132, EV-only 0.001328, **sim share
    57.6%**. So the simulation is already the majority owner of the money in a
    committed position, while contributing exactly nothing to the ranking.

    **`side_picked_by` is the other half, and it matters more than the split.**
    At `_SCORE_SIM_WEIGHT = 0.0` the ranking provably cannot pick a side: the
    same comment shows `blended_score` reduces to `ev_pct`, and EV against a
    proportional de-vig is `1/overround - 1`, IDENTICAL for every side of a
    market. So the shortlist orders markets by hold and breaks ties arbitrarily.
    What actually chooses a side downstream is THIS module's refusals -- a row
    whose sim edge points the other way sizes to zero and is dropped as
    `zero_kelly_stake`. When the EV-only counterfactual would also have been
    positive, price shopping picked the side; when it would not, the sim did,
    and the position exists only because the model said so.
    """
    ev_only_row = dict(row)
    ev_only_row["model_edge_pct"] = 0.0
    ev_inputs, _ = sizing_inputs_from_row(ev_only_row)
    ev_only_fraction = 0.0
    if ev_inputs is not None:
        ev_candidate = sizing_candidate(ev_only_row, ev_inputs)
        ev_candidate["stake"] = compute_board_stake(
            ev_candidate, settled_sample_size=settled_sample_size
        )
        apply_price_reliability(ev_candidate, ev_inputs)
        ev_only_fraction = _as_float((ev_candidate.get("stake") or {}).get("stake_fraction")) or 0.0
    return {
        "stake_fraction_ev_only": round(ev_only_fraction, 6),
        # Filled in by the caller once exposure budgeting and the slate scale
        # have run, so the numbers describe the stake actually committed rather
        # than the pre-budget one.
        "_ev_only_basis": ev_only_fraction,
        "side_picked_by": "price_shopping" if ev_only_fraction > 0.0 else "simulation",
    }


def apply_price_reliability(candidate: dict[str, Any], inputs: SizingInputs) -> None:
    """Discount the stake by how much the PRICE can be trusted.

    Mutates `candidate["stake"]` in place, before `apply_exposure_budgets`,
    which reads the same `stake_fraction`. Records both the factor and the
    pre-discount value: a shrunk stake that cannot be un-shrunk on paper is a
    number nobody can check.

    Exists as its own step because `compute_board_stake` cannot do it -- see the
    module docstring for the measurement.
    """
    stake = dict(candidate.get("stake") or {})
    before = _as_float(stake.get("stake_fraction")) or 0.0
    factor = max(0.0, min(1.0, inputs.price_reliability))
    stake["stake_fraction_pre_reliability"] = round(before, 6)
    stake["price_reliability_factor"] = round(factor, 5)
    stake["stake_fraction"] = round(before * factor, 6)
    candidate["stake"] = stake


def sizing_input_field_names() -> tuple[str, ...]:
    """For the checklist. `dataclasses.fields`, never a name grep."""
    return tuple(f.name for f in dataclass_fields(SizingInputs))
