"""Detect price divergence between Kalshi and Polymarket US on the SAME
two-team moneyline -- the piece the user asked for once both venues had a
real, joinable catalogue.

--------------------------------------------------------------------------
DETECTION ONLY. NOTHING HERE PLACES AN ORDER, ON EITHER VENUE.
--------------------------------------------------------------------------

This module reports where two venues disagree on the same bet, with enough
detail (both raw prices, the fee assumption, the join path) for a human to
decide whether to act on it. Turning a detected gap into two real orders is a
separate, harder problem -- it needs BOTH fills to land (a one-sided fill is
not an arb, it is a naked position) and neither venue's order module is wired
to this one. That is future work, explicitly not started here.

--------------------------------------------------------------------------
WHY MONEYLINE, AND ONLY MONEYLINE
--------------------------------------------------------------------------

Measured 2026-08-24T20:46:21Z (`.syndicate/deploys.md`): `sportsMarketTypeV2`
carried exactly ONE value across the first 2,000 real Polymarket US rows --
`SPORTS_MARKET_TYPE_MONEYLINE`. **That was a sampling artifact of paging from
offset 0, corrected same day**: the venue's game slate also carries SPREAD,
TOTAL and PROP markets (`.syndicate/deploys.md`, 2026-08-24T21:45:58Z --
`game_types=[..MONEYLINE,PROP,SPREAD,TOTAL,DRAWABLE_OUTCOME]`), just not in
the first 2,000 id-ordered rows this module's earlier read happened to see.
So spread/total ARE observable on this venue -- a Kalshi spread now has
something real to join to. This module still scopes to moneyline only
because that is the one market type built and tested here; widening to
spread/total is a real next step, not started, not because the data does
not exist.

--------------------------------------------------------------------------
THE JOIN IS DRIVEN FROM KALSHI'S SIDE, ON PURPOSE
--------------------------------------------------------------------------

Kalshi's own event identity (which two teams, which game) is resolved from
`event_blob_from_ticker`/`match_event_blob` against Syndicate's OWN board
rows (`pipeline.intelligence_state.read_layer2_shortlist`) -- the same
resolver `kalshi_board_join.py` already uses for game lines, reused rather
than reimplemented so a fix to alias matching there is not silently missed
here.

Polymarket's `slug` (`aec-nfl-lac-ten-2025-11-02`) is NOT parsed for team
identity or order, deliberately -- ONE real example is not a grammar, and
guessing which slug position is home vs away from a sample of one is exactly
the mistake `kalshi_board_join.py`'s own header describes Kalshi costing a
full day on. `outcomes` (real team names, e.g. `["Titans","Chargers"]`) is
used instead, matched by NAME through `kalshi_board_join._side_for_team` --
NOT `team_aliases.canonical_team` directly, because Polymarket's real
`outcomes` field carries bare NICKNAMES ("Titans", not "Tennessee Titans" or
"TEN"), which `canonical_team` alone returns `None` for. `_side_for_team`
already solves exactly this (it is how Kalshi's own city-only titles, "Texas
wins?", get resolved against a game's two full names) via a token-subset
match, reused rather than re-solved. The two Polymarket outcomes are checked
against Kalshi's resolved (home, away) pair individually, never assigned by
array position -- see `join_kalshi_polymarket_moneylines`'s own docstring for
the full reasoning and the test that proves it (Polymarket's two teams listed
in the OPPOSITE order from Kalshi's ticker blob still join correctly).

--------------------------------------------------------------------------
KALSHI'S SERIES REGISTRY IS PER-PROCESS STATE -- THIS MODULE OWNS ENSURING
IT IS POPULATED, RATHER THAN HOPING SOMETHING ELSE ALREADY DID
--------------------------------------------------------------------------

`kalshi_catalogue.classify_market` resolves a market's sport via
`SERIES_SPORT` (a small hand-registered dict, ZERO moneyline series in it --
every entry is a player-prop series) falling back to `_DISCOVERED`, a
MODULE-LEVEL dict populated only by `kalshi_odds_refresh.ensure_series_
discovered()` or `kalshi_discovery.run_kalshi_discovery()`, both of which are
normally reached through Kalshi's own refresh cycle or the intelligence-state
board-build loop -- NEITHER of which is guaranteed to have run yet by the
time this module's scan runs. Measured 2026-08-24T21:26:00Z
(`.syndicate/deploys.md`): a boot-probe run of this scan, in
`scripts/run_refresh_worker.py`, executes ~120 lines before that file even
calls `start_intelligence_state_background_loop()` -- so `_DISCOVERED` was
provably empty, and `kalshi_moneylines_resolved` came back 0 with
`kalshi_refusals={}` (not one Kalshi market was even attempted, because
`classify_market` refused every one of them at `unmapped_series` before ever
parsing a title). `run_arb_scan` now calls
`kalshi_odds_refresh.ensure_series_discovered()` itself, first -- it is
idempotent (`_DISCOVERY_DONE`-guarded, "once per process") and cheap to call
defensively, and its own docstring already invites exactly this: "any process
that prices Kalshi gets the same series list." A scan that resolves zero
Kalshi moneylines should mean Kalshi genuinely has none today, not that this
process asked before the catalogue was ever read.

--------------------------------------------------------------------------
FEES ARE A CONSERVATIVE PLACEHOLDER, NOT A MEASURED SCHEDULE
--------------------------------------------------------------------------

Neither venue's real fee formula is in this codebase. Kalshi's was measured
at ~1.9% on exactly ONE real fill (`.syndicate/deploys.md`, elsewhere this
session) -- a data point, not a schedule. Polymarket US carries a per-market
`feeCoefficient`, but its UNITS have never been observed against a real trade
(percentage? bps? a raw multiplier?), so this module does NOT compute a
precise net-of-fees edge from it. Every opportunity is reported at TWO tiers:
`raw_edge` (the price gap before any fee -- real, but overstates what is
capturable) and `edge_after_buffer` (after `DEFAULT_FEE_BUFFER`, a single
conservative placeholder covering both venues' unknown costs combined). Only
`edge_after_buffer` should be read as an actionable signal, and even that
needs a human to verify real fees before anything gets executed on it.
`feeCoefficient` rides on the output raw, unconverted, so a reviewer can
sanity-check it against a real fill once one exists.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

__all__ = [
    "KalshiPolymarketArbError",
    "DEFAULT_FEE_BUFFER",
    "resolve_kalshi_moneylines",
    "resolve_polymarket_moneylines",
    "join_kalshi_polymarket_moneylines",
    "detect_arb_opportunities",
    "run_arb_scan",
]

_MONEYLINE_TYPE = "SPORTS_MARKET_TYPE_MONEYLINE"

# See the module header's FEES section. This is NOT a measured number for
# either venue -- it exists so a raw price gap smaller than typical combined
# vig/fees is not reported as though it were capturable.
DEFAULT_FEE_BUFFER = 0.04


class KalshiPolymarketArbError(RuntimeError):
    """Raised only where continuing would report a result never actually
    computed from real inputs."""


def resolve_kalshi_moneylines(
    kalshi_markets: Sequence[Mapping[str, Any]],
    board_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Every Kalshi moneyline market, resolved to a real game.

    Returns `{"markets": [...], "refusals": {reason: count}}` -- a market
    that is not a moneyline at all is simply not counted (most of Kalshi's
    catalogue is props; that is not a refusal, it is the wrong question for
    this scan). A moneyline that IS found but cannot be resolved to a real
    game, dated, or priced counts under a named refusal, same discipline
    `join_kalshi_to_board` uses for the identical reason: "Kalshi has nothing
    to compare" and "our resolver is broken" must never share a number.
    """
    from syndicate.features.shared.kalshi_board_join import _side_for_team
    from syndicate.features.shared.kalshi_catalogue import (
        GRAMMAR_MONEYLINE,
        classify_market,
        event_blob_from_ticker,
        game_date_from_ticker,
        match_event_blob,
    )
    from syndicate.features.shared.opportunity_signals import implied_probability

    # Candidate games per sport, deduped by event_id -- the same shape
    # `kalshi_board_join._resolve_event` builds from board rows.
    games_by_sport: dict[str, dict[str, dict[str, Any]]] = {}
    for row in board_rows or []:
        sport = str(row.get("sport") or "").strip().lower()
        event_id = str(row.get("event_id") or "").strip()
        if not sport or not event_id:
            continue
        games_by_sport.setdefault(sport, {}).setdefault(
            event_id,
            {
                "event_id": event_id,
                "home_team": row.get("home_team"),
                "away_team": row.get("away_team"),
            },
        )

    resolved: list[dict[str, Any]] = []
    reasons: dict[str, int] = {}

    def _refuse(reason: str) -> None:
        reasons[reason] = reasons.get(reason, 0) + 1

    for market in kalshi_markets or []:
        verdict = classify_market(market)
        if verdict.get("status") != "ok" or verdict.get("grammar") != GRAMMAR_MONEYLINE:
            continue

        sport = verdict.get("sport")
        blob = event_blob_from_ticker(verdict.get("ticker"))
        if not blob:
            _refuse("no_blob")
            continue

        games = list((games_by_sport.get(sport) or {}).values())
        resolution = match_event_blob(blob, games, sport=sport)
        if resolution.get("status") != "ok":
            _refuse(f"event_{resolution.get('status') or 'unresolved'}")
            continue

        game_date = game_date_from_ticker(verdict.get("ticker"))
        if not game_date:
            _refuse("undatable")
            continue

        side = _side_for_team(verdict.get("subject"), resolution, sport=sport)
        if side is None:
            _refuse("team_side_unresolved")
            continue

        named_probability = implied_probability(market.get("yes_american"))
        other_probability = implied_probability(market.get("no_american"))
        if named_probability is None:
            _refuse("no_price")
            continue

        if side == "home":
            home_probability, away_probability = named_probability, other_probability
        else:
            away_probability, home_probability = named_probability, other_probability

        resolved.append(
            {
                "sport": sport,
                "event_id": resolution["event_id"],
                "home_team": resolution["home_team"],
                "away_team": resolution["away_team"],
                "game_date": game_date,
                "home_probability": home_probability,
                "away_probability": away_probability,
                "ticker": verdict.get("ticker"),
            }
        )

    return {"markets": resolved, "refusals": reasons}


def _decode_list(value: Any) -> list[Any] | None:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return None
        return decoded if isinstance(decoded, list) else None
    return None


def resolve_polymarket_moneylines(markets: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Every Polymarket US moneyline row, with its two teams and prices.

    Input is `polymarket_us_markets.trimmed_row` output (or the raw venue
    row -- both carry the same field names). Does NOT filter live/settled
    itself -- pass `drop_settled=True` to the caller that built `markets`
    (`polymarket_us_markets.fetch_markets`), since that module already owns
    the settled/live distinction and reimplementing it here risks the two
    drifting apart.
    """
    resolved: list[dict[str, Any]] = []
    reasons: dict[str, int] = {}

    def _refuse(reason: str) -> None:
        reasons[reason] = reasons.get(reason, 0) + 1

    for row in markets or []:
        if row.get("sportsMarketTypeV2") != _MONEYLINE_TYPE:
            continue

        outcomes = _decode_list(row.get("outcomes"))
        prices = _decode_list(row.get("outcomePrices"))
        if not (isinstance(outcomes, list) and isinstance(prices, list)):
            _refuse("outcomes_undecodable")
            continue
        if len(outcomes) != 2 or len(prices) != 2:
            _refuse(f"not_two_sided:{len(outcomes)}v{len(prices)}")
            continue

        try:
            price_a = float(prices[0])
            price_b = float(prices[1])
        except (TypeError, ValueError):
            _refuse("bad_price")
            continue
        if not (0.0 < price_a < 1.0 and 0.0 < price_b < 1.0):
            _refuse("price_out_of_range")
            continue

        game_start = str(row.get("gameStartTime") or "")
        game_date = game_start[:10] if len(game_start) == 20 and game_start[10] == "T" else None
        if not game_date:
            _refuse("no_game_start")
            continue

        resolved.append(
            {
                "market_id": row.get("id"),
                "teams": [(outcomes[0], price_a), (outcomes[1], price_b)],
                "game_date": game_date,
                "fee_coefficient": row.get("feeCoefficient"),
                "tick": row.get("orderPriceMinTickSize"),
                "min_qty": row.get("minimumTradeQty"),
                "status": row.get("status"),
            }
        )

    return {"markets": resolved, "refusals": reasons}


def join_kalshi_polymarket_moneylines(
    kalshi_resolved: Sequence[Mapping[str, Any]],
    polymarket_resolved: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Pair each resolved Kalshi moneyline with the Polymarket moneyline for
    the SAME game -- matched by team identity + date, never by slug position
    (see module header). A Kalshi game with no Polymarket counterpart, or vice
    versa, is expected and common; only genuine ambiguity (two Polymarket
    rows matching the same Kalshi game) is refused rather than guessed at.

    **REUSES `kalshi_board_join._side_for_team` FOR THE MATCH ITSELF, NOT
    `team_aliases.canonical_team` DIRECTLY.** `canonical_team` needs a name
    the alias map's keys actually contain -- codes or full names ("CWS",
    "chicago white sox") -- and Polymarket's real `outcomes` field carries
    bare NICKNAMES ("Titans", "Chargers"), which `canonical_team` returns
    `None` for. `_side_for_team` already solves exactly this (it is how
    Kalshi's own city-only titles, "Texas wins?", get resolved against a
    game's two full names) via a token-subset match, so it is reused here
    rather than re-solving the identical problem with a function that does
    not handle it.
    """
    from syndicate.features.shared.kalshi_board_join import _side_for_team

    by_date: dict[str, list[Mapping[str, Any]]] = {}
    for row in polymarket_resolved or []:
        by_date.setdefault(row["game_date"], []).append(row)

    matches: list[dict[str, Any]] = []
    reasons: dict[str, int] = {}

    def _refuse(reason: str) -> None:
        reasons[reason] = reasons.get(reason, 0) + 1

    for k in kalshi_resolved or []:
        sport = k["sport"]
        resolution = {"home_team": k["home_team"], "away_team": k["away_team"]}

        hits = []
        for p in by_date.get(k["game_date"], []):
            sides = {_side_for_team(name, resolution, sport=sport) for name, _ in p["teams"]}
            if sides == {"home", "away"}:
                hits.append(p)
        if not hits:
            _refuse("no_polymarket_match")
            continue
        if len(hits) > 1:
            _refuse("ambiguous_polymarket_match")
            continue
        p = hits[0]

        # WHICH polymarket outcome is home vs away -- by NAME (via
        # `_side_for_team`), never position.
        home_probability_pm = away_probability_pm = None
        for name, price in p["teams"]:
            side = _side_for_team(name, resolution, sport=sport)
            if side == "home":
                home_probability_pm = price
            elif side == "away":
                away_probability_pm = price
        if home_probability_pm is None or away_probability_pm is None:
            _refuse("polymarket_side_unresolved")
            continue

        matches.append(
            {
                "sport": sport,
                "event_id": k["event_id"],
                "home_team": k["home_team"],
                "away_team": k["away_team"],
                "game_date": k["game_date"],
                "kalshi_home_probability": k["home_probability"],
                "kalshi_away_probability": k["away_probability"],
                "kalshi_ticker": k["ticker"],
                "polymarket_home_probability": home_probability_pm,
                "polymarket_away_probability": away_probability_pm,
                "polymarket_market_id": p["market_id"],
                "polymarket_fee_coefficient": p["fee_coefficient"],
                "polymarket_tick": p["tick"],
                "polymarket_min_qty": p["min_qty"],
            }
        )

    return {"matches": matches, "refusals": reasons}


def net_edge_per_contract(
    kalshi_price: float,
    polymarket_price: float,
    *,
    kalshi_fee_multiplier: float,
    polymarket_fee_bound: bool = True,
) -> dict[str, Any]:
    """The edge on ONE complementary pair, net of each venue's own fee model.

    --------------------------------------------------------------------------
    THIS REPLACES A FLAT 4% BUFFER THAT WAS WRONG IN BOTH DIRECTIONS
    --------------------------------------------------------------------------

    `DEFAULT_FEE_BUFFER = 0.04` was a single flat number standing in for two
    venues' unknown costs. Against the measured schedule it is far too
    PESSIMISTIC, in two compounding ways:

    - **The fee is quadratic, not flat.** Kalshi charges `rate * P * (1-P)`, so
      at P=0.05 the full-rate cost is 0.0033/contract, not 0.04 -- twelve times
      smaller. Lopsided in-play lines (WSH at 0.94 tonight) are exactly where
      the cheapest crossings live, and a flat buffer hid every one of them.
    - **MLB is half rate.** Every MLB game/total/spread/K series carries
      `fee_multiplier: 0.5` (read live 2026-08-29), so Kalshi's WORST case
      there -- even money, the peak of the parabola -- is 0.00875/contract,
      about a fifth of the flat buffer.

    Over-stating a cost sounds like the safe error and is not: it reports zero
    opportunities on a book that may well have had some, and a detector that
    never fires is indistinguishable from a market with no arb in it. That is
    the same confusion `kalshi_client`'s header warns about for empty lists,
    and it is why this returns a computed cost rather than a margin of safety.

    --------------------------------------------------------------------------
    SIZE-FREE, ON PURPOSE
    --------------------------------------------------------------------------

    Kalshi's fee is `rate * C * P * (1-P)`, so the fee PER CONTRACT is
    `rate * P * (1-P)` -- independent of C except for the rounding, which is to
    a hundredth of a cent and cannot move a per-contract edge materially. The
    edge therefore does not depend on how much we would bet, which is what
    makes it a property of the market rather than of our sizing.

    --------------------------------------------------------------------------
    THE POLYMARKET LEG IS A BOUND, NOT A COST
    --------------------------------------------------------------------------

    `fees_dollars` is null on all 13 of our filled Polymarket orders, and the
    per-market `feeCoefficient` has never had its units observed. So the
    Polymarket half uses `venue_fees.polymarket_worst_case_fee_dollars`, which
    is deliberately more expensive than the venue we HAVE measured. An
    opportunity that survives it is real even if Polymarket turns out to cost
    more than we think; one that only appears with a cheaper number is not
    evidence of anything. `polymarket_fee_bound=False` refuses instead, for a
    caller that would rather have no number than a bound.
    """
    from syndicate.features.shared.venue_fees import (
        kalshi_taker_fee_dollars,
        polymarket_fee_dollars,
        polymarket_worst_case_fee_dollars,
    )

    gross_cost = float(kalshi_price) + float(polymarket_price)
    # Per ONE contract on each leg. See the size-free note above.
    kalshi_fee = kalshi_taker_fee_dollars(1.0, kalshi_price, fee_multiplier=kalshi_fee_multiplier)
    if polymarket_fee_bound:
        polymarket_fee = polymarket_worst_case_fee_dollars(1.0, polymarket_price)
        polymarket_fee_basis = "worst_case_bound"
    else:
        polymarket_fee = polymarket_fee_dollars(1.0, polymarket_price)  # raises
        polymarket_fee_basis = "measured"

    # Fees at a single contract round up to a full grain each, which at C=1
    # over-weights the rounding. Compute the unrounded per-contract rate too,
    # so a 1,000-contract execution is not judged on a 1-contract rounding.
    from syndicate.features.shared.venue_fees import (
        KALSHI_BASE_TAKER_RATE,
        POLYMARKET_ASSUMED_WORST_CASE_RATE,
        POLYMARKET_MEASURED_NOTIONAL_RATE,
    )

    kalshi_rate_cost = (
        KALSHI_BASE_TAKER_RATE * float(kalshi_fee_multiplier)
        * float(kalshi_price) * (1.0 - float(kalshi_price))
    )
    # THE FLAG DECIDES THE RATE, not merely the rounded single-contract figure.
    # It did not, and a test caught it: `polymarket_fee_bound=False` returned a
    # net edge identical to the bounded one, because the rate below was always
    # the worst case. A flag whose name says "measured" and whose behaviour says
    # "bound" is worse than no flag.
    # POLYMARKET'S FEE IS NOT A PARABOLA. Kalshi's vanishes at the tails;
    # Polymarket's is a flat proportion and does not. Modelling it quadratically
    # -- as this line did -- understates the tails by an order of magnitude, and
    # the tails are exactly where in-play pairs live. Measured: at P=0.94
    # Kalshi's MLB fee is 0.0020/contract and Polymarket's 0.0150.
    pmp = float(polymarket_price)
    if polymarket_fee_bound:
        polymarket_rate_cost = POLYMARKET_ASSUMED_WORST_CASE_RATE * pmp * (1.0 - pmp)
    else:
        # Flat per contract, independent of price -- the measured shape.
        polymarket_rate_cost = POLYMARKET_MEASURED_NOTIONAL_RATE
    total_rate_cost = kalshi_rate_cost + polymarket_rate_cost

    return {
        "gross_cost": gross_cost,
        "raw_edge": 1.0 - gross_cost,
        "kalshi_fee_per_contract": kalshi_rate_cost,
        "polymarket_fee_per_contract": polymarket_rate_cost,
        "polymarket_fee_basis": polymarket_fee_basis,
        "total_fee_per_contract": total_rate_cost,
        "net_edge_per_contract": 1.0 - gross_cost - total_rate_cost,
        # The rounded, single-contract figures, kept so a reader can see what
        # one contract literally costs rather than only the rate.
        "kalshi_fee_one_contract_rounded": kalshi_fee,
        "polymarket_fee_one_contract_rounded": polymarket_fee,
    }


def detect_arb_opportunities(
    matches: Sequence[Mapping[str, Any]],
    *,
    fee_buffer: float = DEFAULT_FEE_BUFFER,
) -> list[dict[str, Any]]:
    """For every matched game, the cost of buying the complementary sides on
    opposite venues -- both cross-venue combinations, since either could be
    the cheap one.

    A combo's cost under 1.0 is a raw arithmetic edge (buy both sides, one is
    guaranteed to pay $1, total cost is `combo`). `fee_buffer` is subtracted
    from 1.0 before comparing -- see module header: this is a conservative
    placeholder, not either venue's real fee schedule, and a flagged
    opportunity still needs manual fee verification before anything acts on
    it. Every match is returned (not just flagged ones), each carrying both
    combo costs and whether either cleared the buffered threshold -- so a
    caller can see how close a near-miss was, not just a binary yes/no.
    """
    threshold = 1.0 - float(fee_buffer)
    results: list[dict[str, Any]] = []
    for m in matches:
        combo_home_kalshi = m["kalshi_home_probability"] + m["polymarket_away_probability"]
        combo_away_kalshi = m["kalshi_away_probability"] + m["polymarket_home_probability"]

        best_combo, best_cost = (
            ("home_on_kalshi_away_on_polymarket", combo_home_kalshi)
            if combo_home_kalshi <= combo_away_kalshi
            else ("away_on_kalshi_home_on_polymarket", combo_away_kalshi)
        )

        # THE MEASURED FEE MODEL DECIDES `is_opportunity`. THE FLAT BUFFER IS
        # NOW A REPORTED COMPARISON, NOT THE GATE.
        #
        # `net_edge_per_contract` existed for hours with NO CALLER: the model
        # was written, tested and documented while this function went on gating
        # every opportunity on `DEFAULT_FEE_BUFFER = 0.04`. An unwired model is
        # indistinguishable from no model, and the deploy that would have
        # shipped it changed nothing.
        #
        # WHY IT MATTERS HERE SPECIFICALLY: the flat 4.00c sat ABOVE MLB
        # break-even at EVERY price (3.38c at even money, 0.39c at 0.97), so
        # `is_opportunity` could never once be True on the sport with the most
        # volume. With Kalshi's real per-series schedule and Polymarket
        # MEASURED AT ZERO, the bar at even money is 0.88c.
        if best_combo.startswith("home_on_kalshi"):
            kalshi_price, polymarket_price = m["kalshi_home_probability"], m["polymarket_away_probability"]
        else:
            kalshi_price, polymarket_price = m["kalshi_away_probability"], m["polymarket_home_probability"]
        try:
            detail = net_edge_per_contract(
                kalshi_price,
                polymarket_price,
                kalshi_fee_multiplier=float(m.get("kalshi_fee_multiplier") or 1.0),
                # MEASURED, not the bound: the bound is a quadratic stand-in and
                # would understate the tails now that the real shape is known.
                polymarket_fee_bound=False,
            )
            net_edge = detail["net_edge_per_contract"]
            fee_basis = detail["polymarket_fee_basis"]
            modelled_fee = detail["total_fee_per_contract"]
        except Exception as exc:  # noqa: BLE001
            # A row we cannot price is NOT an opportunity. Named, never
            # silently downgraded to the flat buffer -- that would be the old
            # gate wearing the new one's clothes.
            net_edge, fee_basis, modelled_fee = None, f"unpriceable:{type(exc).__name__}", None

        results.append(
            {
                **m,
                "combo_home_on_kalshi_away_on_polymarket": combo_home_kalshi,
                "combo_away_on_kalshi_home_on_polymarket": combo_away_kalshi,
                "best_combo": best_combo,
                "best_combo_cost": best_cost,
                "raw_edge": 1.0 - best_cost,
                # Kept and REPORTED so the old threshold stays visible beside
                # the new one -- the gap between them IS the finding.
                "edge_after_buffer": threshold - best_cost,
                "fee_buffer_used": fee_buffer,
                # The measured model, and the gate.
                "modelled_fee_per_contract": modelled_fee,
                "net_edge_per_contract": net_edge,
                "polymarket_fee_basis": fee_basis,
                "is_opportunity": bool(net_edge is not None and net_edge > 0),
            }
        )
    return results


def run_arb_scan(
    *,
    selected_date: str,
    fee_buffer: float = DEFAULT_FEE_BUFFER,
) -> dict[str, Any]:
    """The end-to-end scan for one slate date: reads Kalshi's persisted
    catalogue and the board's own rows (both already-computed artifacts, no
    new fetch), then calls Polymarket US's catalogue LIVE (the one piece with
    no standing artifact yet) via `polymarket_us_markets.fetch_game_markets`
    -- read-only import, never touches `polymarket_us_orders`.

    **Was a single page at offset 0 -- fixed same day the coverage gap was
    measured.** The open (`closed=false`) catalogue is id-ordered with the
    real game slate (moneyline/spread/total/prop) as a contiguous block at
    the HIGH end -- season-level futures/politics/culture fill the low end.
    A single page at offset 0 could see only futures, never a game.
    `fetch_game_markets` (the other session's, `polymarket_us_markets.py`)
    binary-searches the boundary each call rather than trusting a constant
    (ids grow daily, so the boundary moves -- measured 17513 one hour, 16000
    the hour before) and pages to exhaustion from there. Measured
    2026-08-24T21:45:58Z: `games=7585 truncated=False pages=18
    duplicate_ids=0`, the full slate, ~33 signed calls total.

    Never raises for a missing input -- reports which stage is empty by name,
    same discipline every artifact-dependent function in this lane uses,
    because "Kalshi has no markets today" and "the artifact read failed" need
    to stay distinguishable.
    """
    from syndicate.features.shared.refresh_state_store import read_json_file, reports_root

    try:
        from pipeline.intelligence_state import read_layer2_shortlist

        shortlist = read_layer2_shortlist(selected_date)
    except Exception as exc:
        return {"status": "error", "reason": f"shortlist_read_failed: {type(exc).__name__}: {exc}"}
    board_rows = (shortlist or {}).get("rows")
    if not isinstance(board_rows, list):
        return {"status": "error", "reason": "no_board_rows", "date": selected_date}

    try:
        kalshi_payload = read_json_file(reports_root() / "intelligence" / "kalshi_markets.json")
    except Exception as exc:
        return {"status": "error", "reason": f"kalshi_artifact_read_failed: {type(exc).__name__}: {exc}"}
    # Through the merge helper -- see `venue_quote_adapters.kalshi_outcome`.
    # `markets` is no longer a persisted top-level key; the markets live under
    # `series[<ticker>]["markets"]` and reading the old key returns None on
    # every real artifact.
    from pipeline.kalshi_odds_refresh import markets_from_state

    # PRESENCE IS THE TEST, NOT EMPTINESS. An artifact holding zero markets is
    # a real state the scan handles (it finds no arbs and says so); a document
    # carrying NEITHER shape is a broken read. Collapsing the two would turn a
    # quiet slate into an error and, worse, an error into a quiet slate.
    from collections.abc import Mapping as _Mapping

    payload = kalshi_payload if isinstance(kalshi_payload, _Mapping) else {}
    if not isinstance(payload.get("series"), _Mapping) and not isinstance(
        payload.get("markets"), list
    ):
        return {"status": "error", "reason": "no_kalshi_markets"}
    kalshi_markets = markets_from_state(payload)

    try:
        from syndicate.features.shared import polymarket_us_markets

        pm_result = polymarket_us_markets.fetch_game_markets()
    except Exception as exc:
        return {"status": "error", "reason": f"polymarket_fetch_failed: {type(exc).__name__}: {exc}"}
    if pm_result.get("status") != "ok":
        return {"status": "error", "reason": f"polymarket_fetch_not_ok: {pm_result.get('reason')}"}
    polymarket_rows = pm_result.get("markets") or []

    # MUST run before resolve_kalshi_moneylines -- see module header. Without
    # it, every Kalshi moneyline is refused at `unmapped_series` before its
    # title is ever parsed, on any process that has not already priced Kalshi
    # once. Idempotent (`_DISCOVERY_DONE`-guarded) and never fatal: a failed
    # catalogue read still lets the hand-registered series (props) resolve,
    # same as `run_kalshi_odds_refresh`'s own tolerance for this failure.
    try:
        from pipeline.kalshi_odds_refresh import ensure_series_discovered

        discovery = ensure_series_discovered()
    except Exception as exc:
        discovery = {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}

    kalshi_resolved = resolve_kalshi_moneylines(kalshi_markets, board_rows)
    polymarket_resolved = resolve_polymarket_moneylines(polymarket_rows)
    joined = join_kalshi_polymarket_moneylines(kalshi_resolved["markets"], polymarket_resolved["markets"])
    opportunities = detect_arb_opportunities(joined["matches"], fee_buffer=fee_buffer)

    flagged = [o for o in opportunities if o["is_opportunity"]]
    return {
        "status": "ok",
        "date": selected_date,
        "kalshi_discovery": discovery.get("status"),
        "kalshi_moneylines_resolved": len(kalshi_resolved["markets"]),
        "kalshi_refusals": kalshi_resolved["refusals"],
        "polymarket_moneylines_resolved": len(polymarket_resolved["markets"]),
        "polymarket_refusals": polymarket_resolved["refusals"],
        "matched_games": len(joined["matches"]),
        "join_refusals": joined["refusals"],
        "opportunities": opportunities,
        "flagged_count": len(flagged),
        "fee_buffer_used": fee_buffer,
    }
