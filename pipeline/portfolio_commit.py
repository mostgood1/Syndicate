"""Stage A runner: read the Layer 2 shortlist, commit a portfolio, persist it.

Worker-side, like everything that computes. Web reads the artifact this writes.

**DARK BY DEFAULT.** `SYNDICATE_PORTFOLIO_COMMIT_ENABLED` gates it, absent means
off, and `run_portfolio_commit` returns a `skipped` status rather than raising
when it is off -- the same dark-launch discipline every autorun in this repo
uses, and the thing that makes the `off != on` reachability test meaningful:
with the flag off the artifact must be ABSENT, with it on it must be PRESENT for
the same date. A feature that writes either way cannot be shown to be reachable.

**Why the plan is its own artifact rather than a key on the board state:**
exactly `write_layer2_shortlist`'s reasoning one layer up -- the canonical board
state is written only under two flags that both default False and are off in
production, so a plan that lived only there would be built correctly and
deposited where nothing reads it.
"""

from __future__ import annotations

import time

import os
from pathlib import Path
from typing import Any, Mapping

from syndicate.features.shared.portfolio_commit import commit_portfolio
from syndicate.features.shared.venue_scope import (
    scope_rows_to_venue,
    venue_scope_report_line,
)
from syndicate.features.shared.order_clv import (
    clv_for_orders,
    order_clv_report_line,
)
from syndicate.features.shared.position_marks import (
    mark_orders_to_board,
    marks_report_line,
)
from syndicate.features.shared.clv_position_join import (
    join_positions_to_openings,
    join_report_line,
)
from syndicate.features.shared.execution_ledger import execution_mode
from syndicate.features.shared.portfolio_settings import resolve_settings
from syndicate.features.shared.refresh_state_store import (
    read_json_file,
    reports_root,
    write_json_file,
)


def portfolio_commit_enabled() -> bool:
    raw = str(os.environ.get("SYNDICATE_PORTFOLIO_COMMIT_ENABLED") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def portfolio_plan_path(selected_date: str) -> Path:
    # Date-tokened deliberately: this is a per-slate artifact and takes the
    # store's 10-day TTL, which comfortably covers settlement's 7-day
    # `EVALUATION_SETTLEMENT_LOOKBACK_DAYS` window.
    #
    # **Stage B's execution ledger must NOT copy this pattern.** A plan is a
    # recomputable recommendation; a record of money placed is not, and a
    # 10-day TTL on that would delete the evidence. See
    # `portfolio_settings._settings_path` for the date-free form.
    suffix = str(selected_date or "").strip().replace("-", "_")
    return reports_root() / "intelligence" / f"portfolio_plan_{suffix}.json"


def portfolio_plan_path_for_venue(selected_date: str, venue: str) -> Path:
    """`paper2`'s artifact -- a SEPARATE file, never a field on the main plan.

    Two portfolios that answer different questions must not share a document:
    `/portfolio/paper` reads the unrestricted plan and would otherwise have to
    know which positions were which, and Stage C's per-market aggregates would
    silently mix a best-book book with a Kalshi-only one. Same date-tokened
    shape and the same 10-day TTL reasoning as the main plan.
    """
    suffix = str(selected_date or "").strip().replace("-", "_")
    token = str(venue or "").strip().lower().replace("-", "_")
    return reports_root() / "intelligence" / f"portfolio_plan_{token}_{suffix}.json"


def read_ladder_plan_for_venue(selected_date: str | None, venue: str) -> dict[str, Any] | None:
    """The paper ladder plan for one venue (`paper_ladder`); its own artifact."""
    return read_portfolio_plan_for_venue(selected_date, f"{str(venue or '').strip().lower()}_ladder")


def read_portfolio_plan_for_venue(
    selected_date: str | None, venue: str
) -> dict[str, Any] | None:
    normalized = str(selected_date or "").strip()
    if not normalized:
        return None
    payload = read_json_file(portfolio_plan_path_for_venue(normalized, venue))
    return payload if isinstance(payload, dict) else None


# ---- the LIVE plan: only what a venue can actually take ---------------------
#
# `paper2`'s venue plan is a COMPARISON BOOK. It keeps every row the venue
# quotes, including rows `scope_rows_to_venue` priced from the AGGREGATOR, which
# carry no contract, because "what would this strategy have done at this venue"
# needs its whole population. It was ALSO the book live mode placed, so
# uncontracted rows held positions in a plan that could never buy them.
#
# Measured 2026-09-11 on production: `PAPER2_PLAN_WRITTEN date=2026-09-10
# venue=kalshi positions=22 ... placeable_committed=4/22`, and the live pass
# refused 16 of them `no_venue_ticker` (NCAAF spreads 9, totals 7, every one
# `price_source='aggregator'`). The executor's refusal (`332e596d`) is right
# and stays; the defect was upstream of it.
#
# So live gets its OWN plan, committed over only the rows the venue can take,
# and the comparison book stays exactly as it was. Sizing the live book over its
# own rows matters beyond the slot count: the slate ceiling and the per-game
# exposure budget are shared by every committed row, so an uncontracted row can
# shrink a contracted one's stake. Neither bound on the measured build
# (`slate_scale_factor=1.0`, one row cut at the cap), so there the change is 18
# unplaceable positions removed, not stakes raised.
PLAN_SOURCE_LIVE = "live"
PLAN_SOURCE_PAPER2_FALLBACK = "paper2_fallback"

# WHY A ROW IS NOT IN THE LIVE PLAN -- two reasons, because they call for
# opposite work. `aggregator_priced`: the venue's own feed never priced the
# row, i.e. the join did not pair it (on 2026-09-11, the per-series working-set
# cap in `kalshi_odds_refresh` had evicted Saturday's NCAAF rungs).
# `no_venue_contract`: the venue DID price it and the contract id was lost
# between the join and the plan, which is a defect in this pipeline.
REFUSAL_AGGREGATOR_PRICED = "aggregator_priced"
REFUSAL_NO_VENUE_CONTRACT = "no_venue_contract"


def live_portfolio_plan_path_for_venue(selected_date: str, venue: str) -> Path:
    """The plan LIVE placement reads -- a separate file from paper2's.

    Separate for `portfolio_plan_path_for_venue`'s own reason: two books that
    answer different questions must not share a document. Same date-tokened
    shape, so the store gives it the same 10-day TTL.
    """
    suffix = str(selected_date or "").strip().replace("-", "_")
    token = str(venue or "").strip().lower().replace("-", "_")
    return reports_root() / "intelligence" / f"portfolio_live_plan_{token}_{suffix}.json"


def read_live_portfolio_plan_for_venue(
    selected_date: str | None, venue: str
) -> dict[str, Any] | None:
    normalized = str(selected_date or "").strip()
    if not normalized:
        return None
    payload = read_json_file(live_portfolio_plan_path_for_venue(normalized, venue))
    return payload if isinstance(payload, dict) else None


def read_placeable_plan_for_venue(
    selected_date: str | None, venue: str
) -> tuple[dict[str, Any] | None, str]:
    """What LIVE placement reads, and WHICH file that was.

    The live plan when one exists. Otherwise paper2's venue plan -- the book
    live read before the live plan existed -- under `paper2_fallback`, so no
    reader has to infer the source. The fallback is not a relaxation: it is the
    previous behaviour exactly, and the executor's `no_venue_ticker` refusal
    still stops every uncontracted row in it before anything is written. It
    exists because the two workers deploy separately, and the reader must not
    stop placing because the writer has not shipped yet.
    """
    plan = read_live_portfolio_plan_for_venue(selected_date, venue)
    if isinstance(plan, dict):
        return plan, PLAN_SOURCE_LIVE
    return read_portfolio_plan_for_venue(selected_date, venue), PLAN_SOURCE_PAPER2_FALLBACK


def placeable_refusal(row: Any) -> str | None:
    """None when the venue can take this row; otherwise the reason it cannot.

    Both halves, because an order needs both: the venue's OWN price
    (`price_source == 'venue_feed'`) and its contract id (`venue_ticker`), which
    `scope_rows_to_venue` stamps from one match. The ticker test is the
    executor's own (`not request.venue_ticker`), so the plan and the refusal
    cannot disagree about what "no contract" means.
    """
    if not isinstance(row, Mapping):
        return "row_not_a_mapping"
    if str(row.get("price_source") or "") != "venue_feed":
        return REFUSAL_AGGREGATOR_PRICED
    ticker = row.get("venue_ticker")
    if not ticker or (isinstance(ticker, str) and not ticker.strip()):
        return REFUSAL_NO_VENUE_CONTRACT
    return None


def commit_live_venue_plan(
    scoped: list[Mapping[str, Any]],
    *,
    selected_date: str,
    settings: Any,
    settled_sample_size_by_sport: Mapping[str, int] | None = None,
    venue: str | None = None,
    bankroll_resolver: Any = None,
) -> dict[str, Any]:
    """paper2's scoped rows -> the plan live may place. Pure; writes nothing.

    `venue` turns on the compounding step (`_apply_compounding_bankroll`), which
    is itself a no-op unless `SYNDICATE_COMPOUNDING_BANKROLL` is shadow|on.
    `bankroll_resolver` replaces the stamp read, for tests.

    The SAME `commit_portfolio` over the rows that pass `placeable_refusal`, so
    every gate, the sizing and the refusal names are unchanged. The rows it
    drops are counted under their own reasons and folded into `refusals`, so the
    plan still accounts for every scoped row: `sum(refusals) + positions ==
    rows_in`, the contract `commit_portfolio` states for itself.
    """
    placeable: list[Mapping[str, Any]] = []
    dropped: list[tuple[str, Any]] = []
    rows_in = 0
    for row in scoped or ():
        rows_in += 1
        reason = placeable_refusal(row)
        if reason is None:
            placeable.append(row)
        else:
            dropped.append((reason, row))

    # OPTION C [user 2026-10-20]: with `SYNDICATE_LIVE_SMALL_EDGE_FRACTION` set
    # and compounding `on` with a one-contract minimum, the LIVE plan does not
    # apply the fixed-bankroll `min_stake_units` ($1 of $1,000 = a 0.1% stake
    # fraction). Those rows reach compounding, whose one-contract floor sizes
    # them, and the band leaves them there (`live_stake_band`). paper2 and the
    # main plan keep the $1 minimum: this changes only what live may place.
    commit_settings = settings
    small_edge = _small_edge_skip(venue)
    if small_edge is not None:
        try:
            import dataclasses

            commit_settings = dataclasses.replace(settings, min_stake_units=0.0)
        except Exception:
            small_edge = None
    plan = commit_portfolio(
        placeable,
        selected_date=selected_date,
        settings=commit_settings,
        settled_sample_size_by_sport=settled_sample_size_by_sport,
        prefer_placeable=True,
    )
    if small_edge is not None:
        plan["small_edge"] = {"fraction": small_edge, "fixed_min_stake_skipped": True}

    refusals = dict(plan.get("refusals") or {})
    by_market = {reason: dict(counts) for reason, counts in (plan.get("refusals_by_market") or {}).items()}
    by_sport = {reason: dict(counts) for reason, counts in (plan.get("refusals_by_sport") or {}).items()}
    for reason, row in dropped:
        refusals[reason] = refusals.get(reason, 0) + 1
        market = sport = ""
        if isinstance(row, Mapping):
            market = str(row.get("market") or "").strip().lower()
            sport = str(row.get("sport") or "").strip().lower()
        # `unkeyed`, the same contract `commit_portfolio`'s own counters keep,
        # so the per-market and per-sport totals still sum to `refusals`.
        market_bucket = by_market.setdefault(reason, {})
        market_bucket[market or "unkeyed"] = market_bucket.get(market or "unkeyed", 0) + 1
        sport_bucket = by_sport.setdefault(reason, {})
        sport_bucket[sport or "unkeyed"] = sport_bucket.get(sport or "unkeyed", 0) + 1

    def _ordered(table: Mapping[str, Mapping[str, int]]) -> dict[str, dict[str, int]]:
        return {
            reason: dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
            for reason, counts in sorted(table.items())
        }

    # THE ACCOUNT'S OWN SIZE, not the constant (lane `compounding-bankroll`).
    # Off unless `SYNDICATE_COMPOUNDING_BANKROLL` says shadow|on, and then it
    # either stamps (shadow) or applies (on) a bankroll derived from what the
    # venue actually holds. Its refusals land in the same tables, so the
    # `sum(refusals) + positions == rows_in` contract still holds after it.
    if venue is not None:
        _apply_compounding_bankroll(
            plan,
            venue=venue,
            settings=settings,
            refusals=refusals,
            by_market=by_market,
            by_sport=by_sport,
            resolver=bankroll_resolver,
        )
        # THE $5-$10 BAND (lane `live-stake-band`, user 2026-10-20). After
        # compounding, so it can bound each bet by the cash compounding stamped
        # for it. Off unless `SYNDICATE_LIVE_STAKE_BAND=on`.
        from syndicate.features.shared.live_stake_band import apply_live_stake_band

        apply_live_stake_band(
            plan,
            venue=venue,
            refusals=refusals,
            by_market=by_market,
            by_sport=by_sport,
        )

    # TAG what the 0% floor admitted (user: "tagged live_ev_floor=0"), so a
    # settled order can be split from the Suggested ones by its position_key.
    floor_keys = set()
    for row in placeable:
        if isinstance(row, Mapping) and row.get("live_ev_floor") == 0:
            try:
                from syndicate.features.shared.portfolio_commit import position_key as _position_key

                floor_keys.add(_position_key(row))
            except Exception:
                continue
    if floor_keys:
        for position in plan.get("positions") or []:
            if isinstance(position, dict) and position.get("position_key") in floor_keys:
                position["live_ev_floor"] = 0
                position["suggested"] = False
        plan["live_ev_floor"] = {
            "floor": 0,
            "extra_rows_in": len(floor_keys),
            "extra_positions": sum(
                1 for p in plan.get("positions") or [] if isinstance(p, Mapping) and p.get("live_ev_floor") == 0
            ),
        }

    plan["refusals"] = dict(sorted(refusals.items()))
    plan["refusals_by_market"] = _ordered(by_market)
    plan["refusals_by_sport"] = _ordered(by_sport)
    # `rows_in` is every scoped row, so the accounting holds; `sim_coverage`
    # keeps describing the rows that were actually sized.
    plan["rows_in"] = rows_in
    plan["placeable_rows_in"] = len(placeable)
    plan["plan_kind"] = PLAN_SOURCE_LIVE
    return plan


# Named so a plan that compounding emptied cannot be read as "the model found
# nothing": the venue's capital could not be read (stale/absent stamp, an
# unclear pending deposit, an unresolvable Kalshi shard), and sizing refused.
REFUSAL_COMPOUNDING_BANKROLL_UNKNOWN = "compounding_bankroll_unknown"
# A stake that fell under `min_stake_units` only BECAUSE the bankroll shrank to
# the real account. Distinct from `below_min_stake`, which `commit_portfolio`
# says about the fixed bankroll, so the cost of compounding is countable.
REFUSAL_BELOW_MIN_STAKE_COMPOUNDED = "below_min_stake_compounded"
# Under `SYNDICATE_COMPOUNDING_MIN_STAKE=one_contract` [user 2026-10-20, option
# (a)]: the compounded stake does not buy one whole contract at the plan price.
# The executor floors dollars to contracts and refuses a zero count anyway
# (`kalshi_orders.contracts_for_stake`); refusing here names it in the plan.
REFUSAL_BELOW_ONE_CONTRACT_COMPOUNDED = "below_one_contract_compounded"
# A contract price the plan cannot state -- refused, never guessed.
REFUSAL_NO_CONTRACT_PRICE_COMPOUNDED = "no_contract_price_compounded"
# Under `floor_one_contract` [user 2026-10-20, "(b) + floor"]: the stake was
# under one contract and the ONE contract it would be rounded up to costs more
# than the cash that must fund it (the order's Kalshi shard, or the venue), or
# that cash is unknown. Refused rather than floored past what can be paid.
REFUSAL_FLOOR_EXCEEDS_CASH = "floor_exceeds_funding_cash"


# ---- the LIVE EV floor at 0% net [user 2026-10-20] --------------------------
#
# "Build the live-only 0% net floor as shown (Suggested OR only-EV reasons, live
# venue plans only, opt-in key, tagged live_ev_floor=0), with a stop rule: revert
# to Suggested-only if live 0-2% rows show ROI below -5% after 100 settled bets."
#
# The 2% that binds live is the board's Suggested flag (`layer2_board.
# _stamp_suggested`, lane layer2-suggested-opps, NOT edited here): +2% net at the
# BEST book plus two-sided fair, plausible fresh quote and one side per line. A
# row whose ONLY reasons are EV ones passes every other part of that flag; the
# commit's own `below_min_ev_pct_net_of_fee` (EV net of the VENUE's fee > 0)
# still applies at the venue price. paper2 and the main book stay Suggested-only.
LIVE_EV_FLOOR_ENV = "SYNDICATE_LIVE_EV_FLOOR"
_EV_ONLY_REASONS = frozenset({"ev_below_min", "ev_net_of_fee_below_min"})
LIVE_EV_FLOOR_STOP_MIN_SETTLED = 100
LIVE_EV_FLOOR_STOP_ROI = -0.05
_LIVE_EV_FLOOR_LOG_LIMIT = 5000
_LIVE_EV_FLOOR_STOP_CACHE: dict[str, Any] = {}
_LIVE_EV_FLOOR_STOP_TTL_SECONDS = 1800.0


def live_ev_floor_requested() -> bool:
    """`SYNDICATE_LIVE_EV_FLOOR=0` turns it on; anything else (absent) is off."""
    raw = str(os.environ.get(LIVE_EV_FLOOR_ENV) or "").strip()
    try:
        return raw != "" and float(raw) == 0.0
    except ValueError:
        return False


def live_ev_floor_rows(raw_rows: Any) -> tuple[list, dict[str, int]]:
    """Suggested rows, plus rows refused by the Suggested flag ONLY for EV.

    The extra rows are COPIES tagged `live_ev_floor: 0`, so the shared shortlist
    rows the paper books read are never changed.
    """
    kept: list = []
    counts = {"suggested": 0, "ev_only_extra": 0, "other_reasons": 0, "flag_absent": 0}
    for row in raw_rows or ():
        if not isinstance(row, Mapping) or "suggested" not in row:
            counts["flag_absent"] += 1
            continue
        if row.get("suggested") is True:
            counts["suggested"] += 1
            kept.append(row)
            continue
        reasons = row.get("suggested_reasons") or []
        if reasons and set(reasons) <= _EV_ONLY_REASONS:
            counts["ev_only_extra"] += 1
            extra = dict(row)
            extra["live_ev_floor"] = 0
            kept.append(extra)
        else:
            counts["other_reasons"] += 1
    return kept, counts


def _live_ev_floor_log_path():
    # NO DATE TOKEN: the stop rule reads weeks of entries, and a dated path is
    # handed a 10-day TTL (`portfolio_settings._settings_path` says why).
    return reports_root() / "intelligence" / "live_ev_floor_positions.json"


def record_live_ev_floor_positions(plan: Mapping[str, Any], *, selected_date: str, venue: str) -> int:
    """Append each live position the 0% floor admitted, once. Never raises."""
    try:
        fresh = [
            p for p in (plan.get("positions") or [])
            if isinstance(p, Mapping) and p.get("live_ev_floor") == 0 and p.get("position_key")
        ]
        if not fresh:
            return 0
        existing = read_json_file(_live_ev_floor_log_path())
        entries = list(existing.get("entries") or []) if isinstance(existing, Mapping) else []
        seen = {
            (e.get("selected_date"), e.get("venue"), e.get("position_key"))
            for e in entries if isinstance(e, Mapping)
        }
        added = 0
        for position in fresh:
            key = (selected_date, venue, position.get("position_key"))
            if key in seen:
                continue
            seen.add(key)
            entries.append({
                "selected_date": selected_date,
                "venue": venue,
                "position_key": position.get("position_key"),
                "ev_pct": position.get("ev_pct"),
                "stake_dollars": position.get("stake_dollars"),
                "sport": position.get("sport"),
                "market": position.get("market"),
                "recorded_at": _utc_now_iso(),
            })
            added += 1
        if added:
            write_json_file(_live_ev_floor_log_path(), {"entries": entries[-_LIVE_EV_FLOOR_LOG_LIMIT:]})
        return added
    except Exception as exc:
        print(f"[portfolio_commit] LIVE_EV_FLOOR_LOG_FAILED error={type(exc).__name__}: {exc}", flush=True)
        return 0


def live_ev_floor_stop_state(*, force: bool = False) -> dict[str, Any]:
    """The stop rule over SETTLED LIVE orders the floor admitted. Cached 30 min.

    Tripped when >= 100 have settled and their ROI (pnl / staked) is below -5%.
    An unreadable ledger or log reports `unknown`, and `_live_ev_floor_population`
    treats that as STOPPED: unknown must not take the permissive branch
    (learnings: "Unknown must not default permissive").
    """
    import time

    now = time.time()
    cached = _LIVE_EV_FLOOR_STOP_CACHE.get("state")
    fresh_enough = now - float(_LIVE_EV_FLOOR_STOP_CACHE.get("at") or 0) < _LIVE_EV_FLOOR_STOP_TTL_SECONDS
    if cached is not None and not force and fresh_enough:
        return cached
    state: dict[str, Any] = {"settled": 0, "staked": 0.0, "pnl": 0.0, "roi": None, "tripped": False}
    try:
        from syndicate.features.shared.execution_ledger import LIVE, full_history_orders

        log = read_json_file(_live_ev_floor_log_path())
        keys = set()
        if isinstance(log, Mapping):
            for entry in log.get("entries") or []:
                if isinstance(entry, Mapping):
                    keys.add((entry.get("selected_date"), entry.get("position_key")))
        for order in full_history_orders():
            if str(order.get("mode") or "") != LIVE:
                continue
            if (order.get("selected_date"), order.get("position_key")) not in keys:
                continue
            if str(order.get("outcome") or "") not in {"won", "lost", "push"}:
                continue
            state["settled"] += 1
            state["staked"] += float(order.get("fill_stake_dollars") or order.get("requested_stake_dollars") or 0.0)
            state["pnl"] += float(order.get("pnl_dollars") or 0.0)
        if state["staked"] > 0:
            state["roi"] = round(state["pnl"] / state["staked"], 4)
        state["tripped"] = bool(
            state["settled"] >= LIVE_EV_FLOOR_STOP_MIN_SETTLED
            and state["roi"] is not None
            and state["roi"] < LIVE_EV_FLOOR_STOP_ROI
        )
        state["staked"] = round(state["staked"], 2)
        state["pnl"] = round(state["pnl"], 2)
    except Exception as exc:
        state["unknown"] = f"{type(exc).__name__}: {exc}"[:160]
    _LIVE_EV_FLOOR_STOP_CACHE.update({"state": state, "at": now})
    return state


def _live_ev_floor_population(shortlist: Any, normalized: str) -> list | None:
    """The live plans' row population for this build, or None (= Suggested-only)."""
    if not live_ev_floor_requested() or not isinstance(shortlist, Mapping):
        return None
    stop = live_ev_floor_stop_state()
    if stop.get("unknown"):
        # FAIL CLOSED: a stop rule that cannot read the ledger cannot say the
        # floor is safe, so the live plans go back to Suggested-only this build.
        print(
            f"[portfolio_commit] LIVE_EV_FLOOR_STOP_UNKNOWN date={normalized} error={stop.get('unknown')} "
            f"-- live plans are Suggested-only until the stop rule can read the ledger",
            flush=True,
        )
        return None
    if stop.get("tripped"):
        print(
            f"[portfolio_commit] LIVE_EV_FLOOR_STOPPED date={normalized} settled={stop.get('settled')} "
            f"roi={stop.get('roi')} -- stop rule (>= {LIVE_EV_FLOOR_STOP_MIN_SETTLED} settled, ROI < "
            f"{LIVE_EV_FLOOR_STOP_ROI:.0%}); live plans are Suggested-only until the key is removed",
            flush=True,
        )
        return None
    rows, counts = live_ev_floor_rows(shortlist.get("rows"))
    stop_summary = {k: stop.get(k) for k in ("settled", "roi", "tripped", "unknown") if k in stop}
    print(
        f"[portfolio_commit] LIVE_EV_FLOOR date={normalized} floor=0 rows={len(rows)} "
        f"counts={counts} stop={stop_summary}",
        flush=True,
    )
    return rows


def _small_edge_skip(venue: str | None) -> float | None:
    """The small-edge line when option C applies to this live plan, else None.

    Needs all three: the key set, compounding `on`, and a one-contract minimum
    (`one_contract` / `floor_one_contract`). With any missing, skipping the $1
    minimum would hand compounding rows it would size to fractions of a cent
    and refuse anyway -- or, compounding off, place them at the fixed bankroll.
    """
    if venue is None:
        return None
    from syndicate.features.shared.live_stake_band import small_edge_fraction
    from syndicate.features.shared.venue_capital import (
        MIN_STAKE_FLOOR_ONE_CONTRACT,
        MIN_STAKE_ONE_CONTRACT,
        compounding_config,
    )

    line = small_edge_fraction()
    if line is None:
        return None
    config = compounding_config()
    if config.get("mode") != "on":
        return None
    if config.get("min_stake") not in (MIN_STAKE_ONE_CONTRACT, MIN_STAKE_FLOOR_ONE_CONTRACT):
        return None
    return line


def default_bankroll_resolver(venue: str, settings: Any):
    """`position -> sizing_bankroll(...)` over ONE stamp read, for one venue.

    One read per plan, so every position of a plan is sized against the same
    reading. Kalshi shards come from the market's own `exchange_index`
    (`execution_guard._kalshi_shard_of`: public, cached per process, a failure
    not cached).
    """
    from syndicate.features.shared.execution_guard import _kalshi_shard_of
    from syndicate.features.shared.venue_capital import (
        _read_stamp,
        compounding_config,
        sizing_bankroll,
    )

    stamp = _read_stamp()
    config = compounding_config()
    fixed = float(getattr(settings, "bankroll_units", 0.0) or 0.0)

    def _resolve(position: Mapping[str, Any]) -> dict[str, Any]:
        ticker = position.get("venue_ticker")
        if isinstance(ticker, Mapping):
            ticker = ticker.get("slug")
        return sizing_bankroll(
            venue,
            fixed_bankroll=fixed,
            ticker=ticker,
            stamp=stamp,
            shard_of=_kalshi_shard_of,
            config=config,
        )

    return _resolve


def _apply_compounding_bankroll(
    plan: dict[str, Any],
    *,
    venue: str,
    settings: Any,
    refusals: dict[str, int],
    by_market: dict[str, dict[str, int]],
    by_sport: dict[str, dict[str, int]],
    resolver: Any = None,
) -> None:
    """Re-dollar each live position against the venue's capital. In place.

    `stake_fraction` -- what `commit_portfolio` decided, after every budget and
    the slate ceiling -- is kept; only the number it multiplies changes. Because
    every position's fraction already satisfies the slate ceiling as a share of
    ONE bankroll, re-dollaring each against a SMALLER one (a Kalshi shard) keeps
    each shard inside the same ceiling.

    `shadow` writes the compounding stake beside the real one and changes
    nothing that is placed. A position refused by compounding does not free a
    `max_positions` slot for another row -- the cut ran before this -- which is
    the conservative error and is stated here rather than discovered.
    """
    from syndicate.features.shared.venue_capital import (
        MIN_STAKE_FLOOR_ONE_CONTRACT,
        MIN_STAKE_ONE_CONTRACT,
        compounding_config,
        one_contract_dollars,
        one_contract_floor_dollars,
    )

    from syndicate.features.shared.live_stake_band import band_config

    config = compounding_config()
    mode = config["mode"]
    # THE BAND SETS THE MINIMUM when it is on (lane `live-stake-band`): every
    # compounded stake is under $1 on today's edges, so a minimum applied here
    # would refuse each bet before the band could size it. Unknown capital
    # still refuses below -- that is a fact about the account, not a minimum.
    #
    # PER POSITION, NOT PER PLAN [option C, user 2026-10-20]: with a small-edge
    # line set, the band leaves positions under it at their compounded stake
    # (`live_stake_band`), so for THOSE this step's own minimum must still run --
    # otherwise they go out at a fraction of a contract and the order builder
    # refuses them (measured in the 10:59 AM CT dry run: $0.20 / $0.19, floored=None).
    band = band_config()
    band_on = bool(band["on"])
    small_edge_line = band.get("small_edge_fraction") if band_on else None

    def _band_sizes(position: Mapping[str, Any]) -> bool:
        if not band_on:
            return False
        if small_edge_line is None:
            return True
        try:
            return float(position.get("stake_fraction") or 0.0) >= float(small_edge_line)
        except (TypeError, ValueError):
            return True

    one_contract_rule = config.get("min_stake") == MIN_STAKE_ONE_CONTRACT
    floor_rule = config.get("min_stake") == MIN_STAKE_FLOOR_ONE_CONTRACT
    floored = 0
    # The executor builds at the LIVE ask, up to its own slippage bound, so the
    # floor carries that bound (`one_contract_floor_dollars`).
    try:
        from pipeline.execute_portfolio import max_slippage_dollars

        slippage = float(max_slippage_dollars())
    except Exception:
        slippage = 0.03
    if mode not in {"shadow", "on"}:
        return

    fixed = float(getattr(settings, "bankroll_units", 0.0) or 0.0)
    min_stake = float(getattr(settings, "min_stake_units", 0.0) or 0.0)
    try:
        resolve = resolver or default_bankroll_resolver(venue, settings)
    except Exception as exc:
        resolve = None
        resolver_error = f"resolver_error:{type(exc).__name__}"
    else:
        resolver_error = None

    kept: list[dict[str, Any]] = []
    refused_keys: list[str] = []
    unknown_reasons: dict[str, int] = {}
    refused_reasons: dict[str, int] = {}
    staked_fixed = 0.0
    staked_compounded = 0.0

    def _refuse(reason: str, position: Mapping[str, Any]) -> None:
        refusals[reason] = refusals.get(reason, 0) + 1
        market = str(position.get("market") or "").strip().lower() or "unkeyed"
        sport = str(position.get("sport") or "").strip().lower() or "unkeyed"
        by_market.setdefault(reason, {})[market] = by_market.setdefault(reason, {}).get(market, 0) + 1
        by_sport.setdefault(reason, {})[sport] = by_sport.setdefault(reason, {}).get(sport, 0) + 1
        refused_keys.append(str(position.get("position_key") or ""))
        refused_reasons[reason] = refused_reasons.get(reason, 0) + 1

    for position in list(plan.get("positions") or []):
        if not isinstance(position, dict):
            continue
        fixed_dollars = float(position.get("stake_dollars") or 0.0)
        staked_fixed += fixed_dollars
        if resolve is None:
            verdict = {"known": False, "reason": resolver_error}
        else:
            try:
                verdict = dict(resolve(position) or {})
            except Exception as exc:
                verdict = {"known": False, "reason": f"resolver_error:{type(exc).__name__}"}

        fraction = float(position.get("stake_fraction") or 0.0)
        bankroll = float(verdict.get("bankroll") or 0.0) if verdict.get("known") else None
        compounded = round(fraction * bankroll, 2) if bankroll is not None else None
        contract = one_contract_dollars(position)
        stamp = {
            "mode": mode,
            "known": bool(verdict.get("known")),
            "reason": verdict.get("reason"),
            "bankroll": bankroll,
            "fixed_bankroll": fixed,
            "capital": verdict.get("capital") if verdict.get("known") else None,
            "shard": verdict.get("shard"),
            "shard_cash": verdict.get("shard_cash"),
            "stake_dollars_fixed": round(fixed_dollars, 2),
            "stake_dollars_compounded": compounded,
            "basis": verdict.get("basis"),
            "min_stake_rule": config.get("min_stake"),
            "one_contract_dollars": contract,
            "contracts_compounded": (
                int(compounded // contract) if compounded is not None and contract else None
            ),
        }
        position["compounding"] = stamp

        if not verdict.get("known"):
            reason = str(verdict.get("reason") or "unknown")
            unknown_reasons[reason] = unknown_reasons.get(reason, 0) + 1
            if mode == "on":
                _refuse(REFUSAL_COMPOUNDING_BANKROLL_UNKNOWN, position)
                continue
            kept.append(position)
            continue

        if mode == "on":
            band_sets_minimum = _band_sizes(position)
            floor_to_one_contract = floor_rule and not band_sets_minimum
            one_contract_minimum = one_contract_rule and not band_sets_minimum
            if floor_to_one_contract:
                floor = one_contract_floor_dollars(position, venue, slippage_dollars=slippage)
                if floor is None:
                    _refuse(REFUSAL_NO_CONTRACT_PRICE_COMPOUNDED, position)
                    continue
                stamp["floor_dollars"] = floor["dollars"]
                if compounded is None or compounded < floor["dollars"]:
                    # ROUNDED UP to one contract, fee included -- but only if
                    # the cash that funds it can: the order's own shard on
                    # Kalshi (the venue checks nothing else), the venue's
                    # capital elsewhere. Unknown funding refuses, never floors.
                    funding = verdict.get("shard_cash") if str(venue).lower() == "kalshi" else verdict.get("capital")
                    if funding is None or float(funding) < floor["dollars"]:
                        stamp["floor_refused_funding"] = funding
                        _refuse(REFUSAL_FLOOR_EXCEEDS_CASH, position)
                        continue
                    stamp["floored_from"] = compounded
                    stamp["floored_to_one_contract"] = True
                    compounded = floor["dollars"]
                    stamp["stake_dollars_compounded"] = compounded
                    stamp["contracts_compounded"] = 1
                    floored += 1
            elif one_contract_minimum:
                # The venue's own minimum replaces the fixed-dollar one: a $1
                # floor does not scale with the account, one contract does.
                if contract is None:
                    _refuse(REFUSAL_NO_CONTRACT_PRICE_COMPOUNDED, position)
                    continue
                if compounded is None or compounded < contract:
                    _refuse(REFUSAL_BELOW_ONE_CONTRACT_COMPOUNDED, position)
                    continue
            elif not band_sets_minimum and (compounded is None or compounded < min_stake):
                _refuse(REFUSAL_BELOW_MIN_STAKE_COMPOUNDED, position)
                continue
            scale = (compounded / fixed_dollars) if fixed_dollars else 0.0
            position["stake_dollars"] = compounded
            position["bankroll_dollars"] = bankroll
            attribution = position.get("attribution")
            if isinstance(attribution, dict):
                for key in ("stake_dollars_ev_only", "stake_dollars_sim_delta"):
                    if attribution.get(key) is not None:
                        attribution[key] = round(float(attribution[key]) * scale, 2)
        staked_compounded += float(compounded or 0.0)
        kept.append(position)

    plan["positions"] = kept
    totals = dict(plan.get("totals") or {})
    if mode == "on":
        totals["positions"] = len(kept)
        totals["staked_dollars"] = round(sum(float(p.get("stake_dollars") or 0.0) for p in kept), 2)
        sim_dollars = sum(
            float(((p.get("attribution") or {}) if isinstance(p.get("attribution"), dict) else {}).get("stake_dollars_sim_delta") or 0.0)
            for p in kept
        )
        totals["staked_dollars_sim_attributed"] = round(sim_dollars, 2)
        totals["sim_share_of_staked"] = (
            round(sim_dollars / totals["staked_dollars"], 4) if totals["staked_dollars"] else None
        )
    plan["totals"] = totals
    plan["compounding"] = {
        "mode": mode,
        "venue": venue,
        "config": {
            key: config[key]
            for key in ("fraction", "ceiling_mode", "ceiling_dollars", "basis", "min_stake", "max_age_seconds")
        },
        "fixed_bankroll": fixed,
        "positions_in": len(kept) + len(refused_keys),
        "positions_out": len(kept),
        "staked_dollars_fixed": round(staked_fixed, 2),
        "staked_dollars_compounded": round(staked_compounded, 2),
        "unknown_reasons": dict(sorted(unknown_reasons.items())),
        "refused_reasons": dict(sorted(refused_reasons.items())),
        "floored_to_one_contract": floored,
        "refused_keys": refused_keys,
    }


def _write_live_venue_plan(
    scoped: list[Mapping[str, Any]],
    *,
    normalized: str,
    venue: str,
    settings: Any,
    settled_sample_size_by_sport: Mapping[str, int] | None,
    paper2_plan: Mapping[str, Any],
    scope_refusals: Mapping[str, int],
    job_state: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Commit and persist the live plan, and print the line that verifies it."""
    path = live_portfolio_plan_path_for_venue(normalized, venue)
    try:
        live_plan = commit_live_venue_plan(
            scoped,
            selected_date=normalized,
            settings=settings,
            settled_sample_size_by_sport=settled_sample_size_by_sport,
            venue=venue,
        )
        live_plan["venue"] = venue
        live_plan["venue_scope_refusals"] = dict(scope_refusals or {})
        live_plan["job_state"] = dict(job_state or {})
        live_plan["paper2_generated_at"] = paper2_plan.get("generated_at")
        write_json_file(path, live_plan)
        if live_plan.get("live_ev_floor"):
            record_live_ev_floor_positions(live_plan, selected_date=normalized, venue=venue)
    except Exception as exc:
        print(
            f"[portfolio_commit] LIVE_PLAN_FAILED date={normalized} venue={venue} "
            f"error={type(exc).__name__}: {exc}",
            flush=True,
        )
        # FAIL CLOSED. Leaving the previous build's live plan in place would
        # have live place an OLDER plan than the comparison book just written,
        # with nothing saying so. An empty plan places nothing until the next
        # build, and the line above says why.
        try:
            write_json_file(
                path,
                {
                    "selected_date": normalized,
                    "venue": venue,
                    "plan_kind": PLAN_SOURCE_LIVE,
                    "generated_at": _utc_now_iso(),
                    "positions": [],
                    "totals": {"positions": 0, "staked_dollars": 0.0},
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
        except Exception as stub_exc:
            print(
                f"[portfolio_commit] LIVE_PLAN_STUB_FAILED date={normalized} venue={venue} "
                f"error={type(stub_exc).__name__}: {stub_exc}",
                flush=True,
            )
        return None

    positions = [p for p in (live_plan.get("positions") or []) if isinstance(p, Mapping)]
    totals = live_plan.get("totals") or {}
    live_keys = {p.get("position_key") for p in positions}
    compounding = live_plan.get("compounding") if isinstance(live_plan.get("compounding"), Mapping) else None
    compounding_refused = set((compounding or {}).get("refused_keys") or ())
    band = live_plan.get("stake_band") if isinstance(live_plan.get("stake_band"), Mapping) else None
    # Refused BY NAME by the band, so not missing -- same reason as compounding's.
    compounding_refused |= set((band or {}).get("refused_keys") or ())
    paper2_placeable = [
        p
        for p in (paper2_plan.get("positions") or [])
        if isinstance(p, Mapping) and placeable_refusal(p) is None
    ]
    print(
        f"[portfolio_commit] LIVE_PLAN_WRITTEN date={normalized} venue={venue} "
        f"rows_in={live_plan.get('rows_in')} placeable_in={live_plan.get('placeable_rows_in')} "
        f"positions={totals.get('positions')} staked=${totals.get('staked_dollars')} "
        f"scale={totals.get('slate_scale_factor')} "
        # COMPUTED FROM THE OUTPUT, not asserted from the construction: a
        # position that lost its contract on the way through `commit_portfolio`
        # reads here as N-1/N rather than hiding behind the filter above.
        f"placeable_committed={sum(1 for p in positions if placeable_refusal(p) is None)}"
        f"/{totals.get('positions')} "
        # THE SELF-CHECK. Every placeable position paper2 committed must also be
        # in the live plan: same rows, same gates, fewer rows competing for the
        # cap and the budget. Non-zero here is a regression, never noise.
        f"paper2_positions={(paper2_plan.get('totals') or {}).get('positions')} "
        f"paper2_placeable={len(paper2_placeable)} "
        # Minus what compounding refused BY NAME: those are accounted for in
        # `refusals`, and counting them here would make a working fail-closed
        # read as the regression this check exists to catch.
        f"paper2_placeable_missing={sum(1 for p in paper2_placeable if p.get('position_key') not in live_keys and p.get('position_key') not in compounding_refused)} "
        f"refusals={live_plan.get('refusals')}",
        flush=True,
    )
    if compounding:
        # The paper measurement, one line per venue per build: what the same
        # positions cost at the fixed bankroll and at the account's own.
        print(
            f"[portfolio_commit] COMPOUNDING_BANKROLL date={normalized} venue={venue} "
            f"mode={compounding.get('mode')} positions={compounding.get('positions_out')}"
            f"/{compounding.get('positions_in')} staked_fixed=${compounding.get('staked_dollars_fixed')} "
            f"staked_compounded=${compounding.get('staked_dollars_compounded')} "
            f"unknown={compounding.get('unknown_reasons')} "
            f"refused={compounding.get('refused_reasons')} "
            f"floored_to_one_contract={compounding.get('floored_to_one_contract')} "
            f"basis={(compounding.get('config') or {}).get('basis')} "
            f"min_stake={(compounding.get('config') or {}).get('min_stake')} "
            f"bankrolls={sorted({(p.get('compounding') or {}).get('bankroll') for p in positions if (p.get('compounding') or {}).get('bankroll') is not None})}",
            flush=True,
        )
    if band:
        # The verification line for lane `live-stake-band`: every placed stake
        # must sit in [min, max] unless trimmed to its funding cash.
        print(
            f"[portfolio_commit] STAKE_BAND date={normalized} venue={venue} on={band.get('on')} "
            f"invalid={band.get('invalid')} config={band.get('config')} "
            f"positions={band.get('positions_out')}/{band.get('positions_in')} "
            f"staked_before=${band.get('staked_dollars_before')} staked_after=${band.get('staked_dollars_after')} "
            f"trimmed_to_funding={band.get('trimmed_to_funding')} refused={band.get('refused')} "
            f"left_small={band.get('left_below_small_edge_fraction')} "
            f"favourite_cap={(band.get('favourite_cap') or {}).get('on')} favourite_capped={band.get('favourite_capped')} "
            f"stakes={[p.get('stake_dollars') for p in positions]}",
            flush=True,
        )
    return live_plan


# The venues `paper2` runs a book for. EXCHANGES AND PREDICTION MARKETS ONLY --
# the venue class that has a real order API and does not limit an account for
# winning. Traditional sportsbooks (draftkings, fanduel, betmgm, betrivers,
# fanatics, williamhill_us) are deliberately absent: no public betting API, and
# automated placement is against their terms. `pinnacle` is excluded too --
# its API exists only through partner/agent arrangements, which is a different
# kind of thing to arrange and not comparable on price alone.
#
# Measuring FOUR rather than one because Kalshi's coverage came in at 3.8% of
# the board (47 of 1,227, 2026-08-23T01:35Z) and a Stage D go/no-go taken on
# one venue's number would be a decision made on a fifth of the evidence
# sitting in `book_prices` already.
_DEFAULT_PAPER2_VENUES = ("kalshi", "novig", "prophetx", "polymarket")


def paper2_venues() -> tuple[str, ...]:
    """The venues `paper2` scopes to. Comma-separated; empty disables.

    Defaults ON rather than dark, and the reasoning differs from a normal new
    job: this places nothing by itself (the execution flag still gates that),
    writes small artifacts, and its ENTIRE value is a comparison that only
    accrues with elapsed time. A flag defaulting off would mean it silently
    collects nothing while looking installed -- `#284`'s "absent is not off"
    read in the direction that costs data rather than money.

    `SYNDICATE_PAPER2_VENUES` wins; `SYNDICATE_PAPER2_VENUE` (singular) is still
    read so an existing deployment's setting keeps working rather than silently
    reverting to the default list.
    """
    raw = os.environ.get("SYNDICATE_PAPER2_VENUES")
    if raw is None:
        raw = os.environ.get("SYNDICATE_PAPER2_VENUE")
    if raw is None:
        return _DEFAULT_PAPER2_VENUES
    seen: list[str] = []
    for token in str(raw).split(","):
        name = token.strip().lower()
        if name and name not in seen:
            seen.append(name)
    return tuple(seen)


def paper2_venue() -> str:
    """Back-compat shim: the FIRST configured venue, or empty when disabled."""
    venues = paper2_venues()
    return venues[0] if venues else ""


def read_portfolio_plan(selected_date: str | None) -> dict[str, Any] | None:
    normalized = str(selected_date or "").strip()
    if not normalized:
        return None
    payload = read_json_file(portfolio_plan_path(normalized))
    return payload if isinstance(payload, dict) else None


# The game identity a quote row needs and a venue match does not carry. Same
# three fields, same order, as `kalshi_odds_refresh._capture_kalshi_quotes`.
_QUOTE_IDENTITY_FIELDS = ("home_team", "away_team", "commence_time")


def _capture_polymarket_quotes(
    report: "Mapping[str, Any] | None",
    board_rows: "Sequence[Mapping[str, Any]] | None",
    selected_date: Any,
) -> None:
    """Record Polymarket's OWN prop prices into the quote log. The sibling of
    `kalshi_odds_refresh._capture_kalshi_quotes`.

    WHY IT IS HERE AND NOT BESIDE THE FETCH. The Polymarket JOIN runs inside
    `run_portfolio_commit`, and that runs from `intelligence_state`'s background
    loop -- `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP` is **true only
    on refresh-worker** (read 2026-09-01; live-odds-worker and web are both
    `false`). The sibling lane shipped its Kalshi capture to live-odds-worker
    because that is where the Kalshi FETCH runs, and the join did not run there,
    so the code never executed. Same trap, named so the next reader does not
    walk into it: **this capture only runs where the JOIN runs.**

    THE SHARD IS CHOSEN PER MATCH, from the board row's own sport. A quote
    written to the wrong sport's shard is worse than a missing one, because it
    is later read as another sport's price.

    NEVER RAISES. The quote log is instrumentation; committing is the product.
    """
    try:
        matches = report.get("matches") if isinstance(report, Mapping) else None
        if not matches:
            return
        from syndicate.features.shared.book_shortlist import (
            QUOTE_SOURCE_FIELD,
            QUOTE_SOURCE_VENUE_DIRECT,
        )
        from syndicate.features.shared.odds_book_quotes import (
            append_book_quotes,
            quote_rows_from_polymarket_matches,
        )

        # THE GAME'S IDENTITY, from the same board rows as the sport -- the
        # Kalshi capture has done this since 2026-09-10 and this sibling never
        # did. `quote_rows_from_polymarket_matches` names the event and nothing
        # else about it, so every Polymarket quote reached the shard with
        # `commence_time`, `home_team` and `away_team` all null. MEASURED
        # 2026-09-22 on web's MLB shard: 5,995 of 5,995 Polymarket prop quotes.
        # `book_grid` took the grid row's start time from the newest quote, so
        # whenever that was Polymarket's the row lost it -- 457 of 1,823 MLB
        # prop rows on the 15:11Z board -- and the submitter refused those rows
        # `commence_unknown`. First non-empty value per field, from ANY row of
        # the event, matching the Kalshi rule.
        sport_by_event: dict[str, str] = {}
        identity_by_event: dict[str, dict[str, str]] = {}
        for row in board_rows or ():
            if not isinstance(row, Mapping):
                continue
            event_id = str(row.get("event_id") or "").strip()
            sport = str(row.get("sport") or "").strip().lower()
            if event_id and sport:
                sport_by_event.setdefault(event_id, sport)
            if event_id:
                identity = identity_by_event.setdefault(event_id, {})
                for field in _QUOTE_IDENTITY_FIELDS:
                    value = str(row.get(field) or "").strip()
                    if value and field not in identity:
                        identity[field] = value

        by_sport: dict[str, list[dict[str, Any]]] = {}
        no_sport = 0
        identity_stamped = 0
        for match in matches:
            if not isinstance(match, Mapping):
                continue
            sport = sport_by_event.get(str(match.get("event_id") or "").strip())
            if not sport:
                no_sport += 1
                continue
            by_sport.setdefault(sport, []).append(dict(match))

        captured = 0
        appended_by_sport: dict[str, int] = {}
        game_line_rows = 0
        for sport, sport_matches in by_sport.items():
            # GAME LINES FOR SOCCER ONLY -- the sibling of the Kalshi capture's
            # opt-in, reading the SAME predicate so the two cannot drift.
            # Polymarket's soccer matches are h2h/totals/btts/corners, none of
            # which carry a player, so the props-only bound discarded every one.
            from syndicate.features.shared.odds_book_quotes import (
                sport_allows_game_line_capture,
            )

            rows = quote_rows_from_polymarket_matches(
                sport_matches,
                allow_game_lines=sport_allows_game_line_capture(sport),
            )
            if not rows:
                continue
            # Stamped on the QUOTE ROWS, not the matches: the row builder
            # copies a fixed field set that does not include these three, and
            # it lives in a file another lane holds (`book-quotes-splice-repair`).
            for quote_row in rows:
                identity = identity_by_event.get(str(quote_row.get("event_id") or "").strip()) or {}
                gained = False
                for field, value in identity.items():
                    if not str(quote_row.get(field) or "").strip():
                        quote_row[field] = value
                        gained = True
                identity_stamped += int(gained)
            result = append_book_quotes(
                sport=sport,
                date_str=str(selected_date or "").strip(),
                rows=rows,
                captured_at=_utc_now_stamp(),
                # Without this the grid discards these rows: `drop_from_grid`
                # refuses a direct-feed venue unless the row says it came from
                # the venue, and absent means dropped.
                extra={QUOTE_SOURCE_FIELD: QUOTE_SOURCE_VENUE_DIRECT},
            )
            _n = int((result or {}).get("appended") or 0)
            captured += _n
            if _n:
                appended_by_sport[sport] = appended_by_sport.get(sport, 0) + _n
            game_line_rows += sum(1 for r in rows if not r.get("player_name"))
        # ONE LINE, ALWAYS, INCLUDING THE ZEROES. `no_sport` and an empty
        # `by_sport` are different failures -- "the match carries no sport" and
        # "the join produced nothing" -- and a line printed only on success
        # cannot tell them apart.
        print(
            "[portfolio_commit] POLYMARKET_QUOTE_CAPTURE"
            # `sports=` lists sports with MATCHES, not sports with ROWS. Soccer
            # sat in that field contributing nothing for a whole day, which
            # reads as working capture -- `appended_by_sport` is what
            # discriminates.
            f" matches={len(matches)} sports={sorted(by_sport)}"
            f" appended={captured} appended_by_sport={appended_by_sport}"
            f" game_lines={game_line_rows} no_sport={no_sport}"
            f" identity_stamped={identity_stamped}",
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001 -- instrumentation must not fail the commit
        print(f"[portfolio_commit] POLYMARKET_QUOTE_CAPTURE_FAILED {type(exc).__name__}: {exc}", flush=True)


def _utc_now_stamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


class _VenueResolvers(tuple):
    """`(price_resolver, ticker_resolver)`, plus WHY it is empty when it is.

    A TUPLE SUBCLASS ON PURPOSE, so `price, ticker = _venue_price_resolver(...)`
    keeps working everywhere and every plain `return (None, None)` in this file
    stays exactly what it is today. `_venue_feed_status` reads the extra field
    through `getattr(..., "withheld_by", None)`, so the DEFAULT -- a bare tuple,
    an unconverted return path, a caller that never asks -- is `None`, which is
    the READER_FAILED branch. The alarm is what you get when nobody said
    otherwise; you have to positively assert a policy to escape it.

    `withheld_by` is the NAME OF THE ENV FLAG that suppressed the matches, and
    it is set only by the site that actually did the suppressing and watched the
    match list go empty because of it. It is not derived from the flag's value,
    the sport, or the date: a build whose join produced nothing at all sets it
    to None even with the flag off, because that build's zero is not the
    policy's doing and must keep reading as a defect.
    """

    # NO `__slots__`: a variable-length builtin (`tuple`) cannot take a
    # non-empty one -- `TypeError: nonempty __slots__ not supported for subtype
    # of 'tuple'` -- and the attribute is the whole point of the class.

    def __new__(cls, price, ticker, withheld_by: str | None = None):
        self = super().__new__(cls, (price, ticker))
        self.withheld_by = str(withheld_by).strip() if withheld_by else None
        return self


def _polymarket_price_resolver(selected_date: str | None):
    """`(price_resolver, ticker_resolver)` for Polymarket US, or `(None, None)`.

    Until this existed, `_venue_price_resolver` returned `(None, None)` for
    every venue but Kalshi, so the `paper:polymarket` book was priced from the
    AGGREGATOR -- a venue label on someone else's prices. Any
    `paper:polymarket` P&L recorded before this is not a Polymarket result.

    `(None, None)` on every failure path, never a partial resolver: falling back
    to the aggregator is the documented, understood behaviour, while a resolver
    built from half a slate would price some rows at the venue and some at the
    aggregator with no way to tell which from the outside.
    """
    try:
        from syndicate.features.shared.polymarket_board_join import (
            join_polymarket_to_board,
            load_polymarket_markets,
            polymarket_price_resolver,
            polymarket_ticker_resolver,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[portfolio_commit] POLYMARKET_RESOLVER_UNAVAILABLE {type(exc).__name__}: {exc}", flush=True)
        return (None, None)

    markets, fetched_at = load_polymarket_markets()
    if not markets:
        # The artifact is written by live-odds-worker's slate tick. Absent means
        # that has not run here yet -- named, so it is not read as "Polymarket
        # quotes nothing".
        print("[portfolio_commit] POLYMARKET_RESOLVER status=no_slate_artifact", flush=True)
        return (None, None)

    try:
        board_rows = _board_rows_for_join(selected_date)
    except Exception as exc:  # noqa: BLE001
        print(f"[portfolio_commit] POLYMARKET_RESOLVER_BOARD_FAILED {type(exc).__name__}: {exc}", flush=True)
        return (None, None)

    # TIMED `[2026-08-28]`. This join is INSIDE the `portfolio_commit` span the
    # board build now emits, and that span is a black box: `polymarket` appears
    # nowhere in `intelligence_state`, so Kalshi's refresh and join get their own
    # spans while Polymarket's equivalent work is invisible. This join indexes
    # ~8,973 markets against ~1,335 board rows, which makes it a credible
    # largest-single-item inside the ~305s of board compute that no named stage
    # accounts for -- and until now nothing could say so either way.
    #
    # ON THE EXISTING LINE rather than a new one: this print already reports what
    # the join DID (markets, indexed, matched, refusals). Cost belongs beside
    # outcome, or the two have to be joined by timestamp across two lines that a
    # concurrent build can interleave.
    #
    # `monotonic`, not `time.time`: `slate_age_s` below is wall-clock by
    # necessity (it is an age against a stored stamp) but a DURATION must not be
    # readable as negative because the clock stepped.
    _join_started = time.monotonic()
    joined = join_polymarket_to_board(markets, board_rows, selected_date=str(selected_date or ""))
    _join_elapsed_s = round(time.monotonic() - _join_started, 2)
    _capture_polymarket_quotes(joined, board_rows, selected_date)
    age = None if fetched_at is None else round(time.time() - float(fetched_at), 1)
    print(
        f"[portfolio_commit] POLYMARKET_BOARD_JOIN elapsed_s={_join_elapsed_s} "
        f"markets={joined.get('polymarket_markets')} "
        f"indexed={joined.get('indexed')} board_rows={joined.get('board_rows')} "
        f"matched={joined.get('matched')} slate_age_s={age} "
        f"refusals={joined.get('refusals')} "
        # The SHAPES behind the parse refusals, bounded to six. A count says
        # how many; only this says what the venue actually sent.
        f"shapes={joined.get('unreadable_shapes')}",
        flush=True,
    )
    # WHAT WE FETCH AND THROW AWAY, on its own line because it is the largest
    # single number in the refusals and has never been characterised. 6,838
    # `market_type_not_a_game_line` plus 1,064 segment markets are paid for on
    # every cycle and discarded. Counts are complete; the samples carry the
    # QUESTION, which is the only field that says what the bet actually is --
    # `SPORTS_MARKET_TYPE_PROP` turned out to include League of Legends map
    # winners, so the family cannot be named from its type alone.
    # BOARD ROWS THE VENUE COULD NOT BE PAIRED WITH. A `totals under 10.5` on
    # Minnesota Twins @ Athletics reached the placer with `venue_ticker=None`
    # on 2026-08-25T18:49:14Z because nothing was stamped here -- and the join
    # reported it only as `no_matching_polymarket_market: 54`. This prints what
    # the BOARD wanted beside what the VENUE offered for the same league, date
    # and market, so "not listed" and "listed under a name we do not know" stop
    # sharing a number.
    if joined.get("unmatched_counts"):
        print(
            "[portfolio_commit] POLYMARKET_UNMATCHED"
            f" counts={joined.get('unmatched_counts')}"
            f" samples={joined.get('unmatched_samples')}"
            # The COMPLETE prop no-match classification -- class/family over
            # the matching no_match count on this same line IS the rate the
            # bounded samples cannot give (rung_miss vs near_token vs
            # player_not_listed vs fixture_miss).
            f" prop_classes={joined.get('prop_unmatched_classes')}"
            # WHICH COMPONENT of the key disagreed. `no_candidates` alone
            # cannot distinguish a league mismatch from a date or a market one,
            # and BTTS is currently unexplained for exactly that reason.
            f" key_misses={joined.get('key_miss_samples')}"
            # The venue's OWN soccer prop vocabulary. `btts` was found from a
            # slug token; corners has not been found at all, and its current
            # route reads a `question` field that is never populated.
            f" soccer_prop_shapes={joined.get('prop_modifier_census')}"
            # Board rows rescued by the slate/fixture date split. See the
            # forward-horizon block in the join.
            f" forward_date_widened={joined.get('forward_date_widened')}"
            # WHERE THE LINE CAME FROM. `|row_field` non-zero proves the slate's
            # own `line` field is populated and the fallback fires; `|none` with
            # a slug sample names a family that carries no number anywhere.
            f" line_source={joined.get('line_source')}"
            f" line_gaps={joined.get('line_gap_samples')}"
            # Outcome names beside the side we wanted, for the matched markets
            # whose side could not be placed.
            f" side_gaps={joined.get('side_gap_samples')}"
            # P(over) must not rise with the line on one fixture. The one check
            # that sees soccer totals, where the fair-value gate is all
            # `too_close`.
            f" ladder={joined.get('ladder_counts')}"
            f" ladder_bad={joined.get('ladder_samples')}",
            flush=True,
        )
    # WHICH COMPETITIONS THE BOARD CAN REACH, AND WHICH IT CANNOT. Printed
    # unconditionally when the unreachable list is non-empty, because "soccer is
    # not executing" was answerable for two days only by reading the join's
    # source: the proven-token set decides whether a competition is filed under
    # `soccer` at all, and nothing emitted it. The unreachable entry carries the
    # club codes that would settle it -- see `join_polymarket_to_board`.
    # THE ORIENTATION RATE, DIAGNOSTIC ONLY. Rows that refused on fixture
    # pairing but would pair with the slug's two sides swapped. Printed per
    # league|market because MLB and NFL pair correctly today and are therefore
    # the control: soccer high with those near zero says the slug order differs
    # by sport; soccer high WITH them high says the orientation reading is
    # wrong and the cause is elsewhere. No flip is applied anywhere.
    # UNCONDITIONAL, AND THAT IS THE POINT. This was gated on
    # `if joined.get("orientation_flip_counts")`, so a build where the flip
    # rescued NOTHING anywhere printed no line at all -- indistinguishable from
    # the code not being deployed. That is the single most interesting result
    # (orientation is not the cause) wearing the costume of an inert deploy,
    # and this counter's whole first run was going to be judged on whether a
    # line appeared. `would_match_if_flipped={}` with a non-empty `tried=` is a
    # RESULT; no line at all is an ambiguity.
    #
    # `tried=` is the denominator and must be read FIRST. `{'mlb|h2h': 0}` out
    # of `tried={'mlb|h2h': 47}` is a clean control; the same zero out of
    # `tried={}` is an untested branch. Both print as an absent rescue key.
    print(
        "[portfolio_commit] POLYMARKET_ORIENTATION"
        f" would_match_if_flipped={joined.get('orientation_flip_counts')}"
        f" tried={joined.get('orientation_flip_attempts')}"
        # THE ELIGIBILITY SPLIT, and `listed` is the denominator that makes
        # `would_match_if_flipped` a RATE. `flipped/tried` is not one:
        # a row whose fixture the venue never listed sits in `tried` and can
        # never reach the numerator. Read `listed` first, then
        # flipped/listed. `not_listed` is coverage and no join change
        # recovers it; `unreadable` is the honest bucket where a club token
        # would not canonicalise on one side or the other, so eligibility is
        # UNKNOWN -- never fold it into `not_listed`.
        # READ THIS FIRST. False means the classifier contradicted itself --
        # more rows flip-matched than it called listed, which is impossible
        # since a flip-match proves listing. Every number on this line is
        # suspect when it is False.
        f" invariant_ok={joined.get('orientation_invariant_ok')}"
        f" listed={joined.get('orientation_fixture_listed')}"
        # HOW the listing was established. `flipped / listed` is TAUTOLOGICAL
        # when every listing came from the flip itself -- two production
        # readings returned listed and flipped identical (5/5, then 24/24),
        # which is what that failure looks like. `by_canonical` is the
        # independent evidence and is the denominator to divide by; a
        # `by_canonical` of 0 means the rate above measures nothing.
        f" listed_by_canonical={joined.get('orientation_listed_by_canonical')}"
        f" listed_by_flip_only={joined.get('orientation_listed_by_flip_only')}"
        f" not_listed={joined.get('orientation_fixture_not_listed')}"
        f" unreadable={joined.get('orientation_fixture_unreadable')}"
        f" samples={joined.get('orientation_flip_samples')}",
        flush=True,
    )
    # `#595` step 2. Prints even when empty: "no matched row was lopsided enough
    # to test" and "the code did not run" must not look the same, which is the
    # gating mistake this lane already made once with POLYMARKET_ORIENTATION.
    print(
        "[portfolio_commit] POLYMARKET_PRICE_ALIGNMENT"
        f" counts={joined.get('price_alignment')}"
        f" inverted_samples={joined.get('price_alignment_samples')}",
        flush=True,
    )
    if joined.get("unproven_league_tokens"):
        print(
            "[portfolio_commit] POLYMARKET_LEAGUE_REACH"
            f" soccer_tokens_proven={joined.get('soccer_tokens_proven')}"
            f" unreachable={joined.get('unproven_league_tokens')}",
            flush=True,
        )
    if joined.get("out_of_scope_counts"):
        print(
            "[portfolio_commit] POLYMARKET_OUT_OF_SCOPE"
            f" counts={joined.get('out_of_scope_counts')}"
            f" samples={joined.get('out_of_scope_samples')}",
            flush=True,
        )
    matches = joined.get("matches") or []
    # ------------------------------------------------------------------
    # PLAYER-PROP MATCHES FEED THE QUOTE LOG, NOT THE ORDER PATH -- yet.
    # ------------------------------------------------------------------
    #
    # The join admits MLB player props as of 2026-09-01 (lane
    # `polymarket-prop-quote-capture`) so `_capture_polymarket_quotes` above
    # can record the venue's own prop prices. The RESOLVERS below are a
    # different consumer: whatever they index becomes priceable and
    # ticker-stamped for the paper AND LIVE books, and `execute_portfolio`
    # places real venue orders off exactly that. Widening the money path was
    # not this change's decision to make, so prop matches are withheld here
    # behind an explicit switch, OFF by default.
    #
    # Before arming it, check the two standing constraints in
    # `live-prob-producer-reader-gap`'s lane block (a live prop edge was
    # shipped and BACKED OUT once already), and the resolver-key asymmetry:
    # a prop match carries the CANONICAL market name while `_resolver_key`
    # reads a board row's market RAW -- identical for today's shortlist rows
    # (`batter_hits` et al.), but verify before trusting a resolve.
    #
    # PRINTED ALWAYS, ZEROES INCLUDED: `withheld=0` on a slate with prop
    # matches means the switch is armed, and a line printed only when
    # withholding could not say so.
    prop_matches = [m for m in matches if str(m.get("player_name") or "").strip()]
    props_armed = str(
        os.environ.get("SYNDICATE_POLYMARKET_PROP_RESOLVERS") or ""
    ).strip().lower() in {"1", "on", "true", "yes"}
    if prop_matches and not props_armed:
        matches = [m for m in matches if not str(m.get("player_name") or "").strip()]
    print(
        "[portfolio_commit] POLYMARKET_PROP_RESOLVERS"
        f" armed={props_armed} prop_matches={len(prop_matches)}"
        f" withheld={0 if props_armed else len(prop_matches)}",
        flush=True,
    )
    if not matches:
        # WHICH ZERO THIS IS, carried out rather than re-derived. If withholding
        # is what emptied the list, the plan line says `policy_withheld:` and
        # names the flag; if the join produced nothing in the first place, this
        # stays `None` and the venue keeps stamping READER_FAILED, because that
        # zero is a defect no matter what the flag is set to.
        return _VenueResolvers(
            None,
            None,
            withheld_by=(
                "SYNDICATE_POLYMARKET_PROP_RESOLVERS"
                if (prop_matches and not props_armed)
                else None
            ),
        )
    return polymarket_price_resolver(matches), polymarket_ticker_resolver(matches)


def _board_rows_for_join(selected_date: str | None) -> list[dict]:
    """The same shortlist rows the commit is about to price.

    Read here rather than threaded through, so the join is built against the
    board actually being committed. A join made against a different read would
    pair tonight's rows with a pairing computed from another board -- the
    stale-pairing mistake `clv_join`'s arrow-of-time check exists to catch.
    """
    from pipeline.intelligence_state import read_layer2_shortlist

    shortlist = read_layer2_shortlist(str(selected_date or ""))
    rows = (shortlist or {}).get("rows") if isinstance(shortlist, dict) else None
    return [r for r in (rows or []) if isinstance(r, dict)]



# WHY A VENUE HAS NO DIRECT FEED. Keyed by venue, and ABSENT means "this venue is
# supposed to have one" -- so a venue that should be priced and is not falls
# through to `reader_failed`, which is the alarm rather than a shrug.
#
# Each reason is a MEASURED capability gap, not an intention:
#   novig     the public CSV tier is anonymised at game/player/team level, so
#             `reportTicker` names a CATEGORY and can never price a named bet
#             (measured 2026-08-24). The credentialed NBX REST tier is
#             implemented and needs founder-gated credentials that are absent.
#   prophetx  no fan-in adapter is registered at all, the API token is
#             partner-issued with no self-serve signup, and the production base
#             URL is unconfirmed -- the client defaults to SANDBOX.
_VENUE_FEED_GAP = {
    "novig": "capability_gap:public_csv_anonymised;needs_NOVIG_CLIENT_ID",
    "prophetx": "capability_gap:no_fanin_adapter;partner_token;sandbox_base_url",
}

#: Venues that DO have a direct feed. One of these reading `no_feed` is a defect,
#: not a gap, and the stamp says so in capitals so it cannot be skimmed past.
_VENUES_WITH_FEEDS = ("kalshi", "polymarket")


def _venue_feed_status(
    venue: str, resolver: object, withheld_by: str | None = None
) -> str:
    """One token explaining `venue_priced`, for the plan line.

    THE POINT IS THE THIRD CASE. `venue_feed` and `capability_gap` are both
    fine; `READER_FAILED` is a venue we can price, silently pricing from the
    aggregator instead -- exactly the Kalshi failure of 2026-08-25, which cost
    weeks because its symptom was a zero that looked like Novig's zero.

    THE FOURTH CASE IS THE THIRD ONE'S TWIN, and it was reading as the third
    for as long as both existed. `SYNDICATE_KALSHI_SOCCER_RESOLVERS` and
    `SYNDICATE_POLYMARKET_PROP_RESOLVERS` are DELIBERATE gates, off by default,
    that strip their matches out of the order path; when they strip the last
    one the builder returns `(None, None)` -- the same value a broken reader
    returns. Measured 2026-09-09 (lane `kalshi-join-match-rate`): every
    near-zero Kalshi match tick observed that day was a tomorrow-date build
    whose matches are 100% soccer, and every one of them stamped
    `READER_FAILED` on a system doing exactly what it was told. So:

        venue_feed       priced from the venue's own book
        capability_gap   nothing to do; the venue cannot be priced and never could
        policy_withheld  someone CHOSE this; the flag named in the token undoes it
        READER_FAILED    a venue we CAN price is not being priced -- a live defect

    `READER_FAILED` IS NOT BROADENED OR SOFTENED BY THE NEW CASE, and must not
    be. It is in capitals so it cannot be skimmed past, and the whole cost of
    2026-08-25 was an alarm that read like an ordinary zero. The fourth token
    is a SEPARATE branch reached only when a caller positively asserts which
    flag did the withholding; `withheld_by=None` -- the default, and what every
    plain `(None, None)` in this file produces -- leaves this function's
    behaviour byte-for-byte what it was.

    `withheld_by` is a FLAG NAME, not a boolean, because a reader who has to
    grep for the switch is a reader who does not flip it.
    """
    name = str(venue or "").strip().lower()
    if resolver is not None:
        return "venue_feed"
    flag = str(withheld_by).strip() if withheld_by else ""
    if flag:
        return f"policy_withheld:{flag}"
    if name in _VENUE_FEED_GAP:
        return _VENUE_FEED_GAP[name]
    if name in _VENUES_WITH_FEEDS:
        return "READER_FAILED:has_a_feed_but_resolver_returned_none"
    return "no_feed:unregistered_venue"


def _venue_price_resolver(venue: str, selected_date: str | None = None):
    """`(price_resolver, ticker_resolver)` for a venue, or `(None, None)`.

    BOTH ARE BUILT FROM ONE SET OF MATCHES. Building them separately would let
    the price come from one pairing and the contract id from another -- an order
    placed on a ticker at a price that was never quoted for it, which is the
    single most expensive shape of mismatch available in this file.

    Price rows from the VENUE's own feed, or `(None, None)` to fall back to
    OddsAPI.

    Kalshi and Polymarket US have direct feeds. A venue with none keeps behaving
    exactly as before rather than erroring, and the difference surfaces as
    `price_source` on the rows instead of as a special case in the caller.

    THE RESULT MAY BE A `_VenueResolvers`, which unpacks as the same two-tuple
    and additionally carries `withheld_by` when a POLICY GATE
    (`SYNDICATE_KALSHI_SOCCER_RESOLVERS`, `SYNDICATE_POLYMARKET_PROP_RESOLVERS`)
    is what emptied the match list. Read it with `getattr(..., "withheld_by",
    None)` and hand it to `_venue_feed_status`: every other path here returns a
    bare tuple, so an unconverted or unread path degrades to the ALARM rather
    than to a shrug.

    NOVIG DELIBERATELY HAS NONE, and that is a capability gap rather than an
    omission: its public CSV mirror is anonymized at the game/player/team level
    (measured 2026-08-24), so `reportTicker` names a CATEGORY and can never
    price a named bet. The credentialed REST tier could.

    The join is rebuilt from the freshest fetched markets on every call. Carrying
    a join made against an older board would pair tonight's rows with a pairing
    computed from a different board -- the stale-pairing mistake `clv_join`'s
    arrow-of-time check exists to catch, in a new costume.
    """
    normalized_venue = str(venue or "").strip().lower()
    if normalized_venue == "polymarket":
        return _polymarket_price_resolver(selected_date)
    if normalized_venue != "kalshi":
        return (None, None)
    try:
        payload = read_json_file(reports_root() / "intelligence" / "kalshi_markets.json")
        # THROUGH THE MERGE HELPER, never `payload["markets"]`. That key is no
        # longer persisted -- the markets live under `series[<ticker>]["markets"]`
        # since the artifact was split to fit the store's 8MB ceiling.
        #
        # THIS READER FAILED WORSE THAN THE OTHER TWO, because it did not
        # error. `.get("markets") or []` became `[]`, which returns
        # `(None, None)` -- the value that means "this venue has no direct
        # feed", indistinguishable from Novig, which genuinely has none.
        # Measured 2026-08-25 3:55:49 PM Central:
        #
        #   PAPER2_PLAN_WRITTEN venue=kalshi rows_in=86 positions=0
        #     venue_priced=0 sim_view_on=84/86
        #
        # ...while the fan-in was simultaneously producing 2,344 Kalshi quotes
        # and winning 1,852 selections. Kalshi silently priced from the
        # aggregator instead of its own book, so no Kalshi position was ever
        # committed and `ORDER_PATH venue=kalshi` read `no_positions`.
        from pipeline.kalshi_odds_refresh import markets_from_state

        markets = markets_from_state(payload)
        if not markets:
            return (None, None)
        return _resolvers_from_markets(markets, selected_date)
    except Exception as exc:
        # Named, and returns None so the venue silently reverts to the
        # aggregator rather than losing its book entirely.
        print(f"[portfolio_commit] KALSHI_RESOLVER_FAILED venue={venue} error={exc}", flush=True)
        return (None, None)


def _resolvers_from_markets(markets, selected_date: str | None = None):
    """Fetched Kalshi markets -> `(price_resolver, ticker_resolver)`.

    THROUGH THE BOARD JOIN, which this used to skip -- and skipping it made
    every resolver it returned inert.

    `_match_key` indexes on `board_event_id` and returns None without one, so a
    match carrying no board event is NEVER INDEXED. This function built its
    match dicts by hand from `classify_market` alone -- market, player, line,
    side, price, ticker -- and a Kalshi market does not know which board row it
    belongs to. So every key was None, the index was empty, and `resolve()`
    returned None for every row it was ever asked about.

    Measured 2026-08-25 4:40:11 PM Central, after three separate artifact-reader
    fixes had already landed:

        PAPER2_PLAN_WRITTEN venue=kalshi     rows_in=86  venue_priced=0
        PAPER2_PLAN_WRITTEN venue=polymarket rows_in=89  venue_priced=30

    ...while the fan-in was pricing 2,344 Kalshi quotes off the same artifact
    on the same service. Two matchers, one venue, and only one of them said
    anything. Kalshi silently took the AGGREGATOR's price on all 86 rows --
    `venue_not_quoting` never fired, because a price was always found.

    `_match_key`'s own docstring names this: "Adding the game to `_match_key`
    moved the ticker resolver and left this behind." It also predicted the
    silence -- "its board join currently supplies only player props, whose
    `player_name` happens to identify a game" -- describing the join's matches,
    not these hand-built ones, which never had an event id under any market.

    `join_kalshi_to_board` stamps `board_event_id` off the row it paired with,
    which is the only place that fact exists. So this now mirrors
    `_polymarket_price_resolver` exactly: read the board being committed, join,
    and build both resolvers from ONE match list -- which is also what keeps a
    price and a contract id from coming out of two different pairings.
    """
    from syndicate.features.shared.kalshi_board_join import (
        _row_key as _kalshi_row_key,
        join_kalshi_to_board,
        kalshi_price_resolver,
        kalshi_ticker_resolver,
    )

    try:
        board_rows = _board_rows_for_join(selected_date)
    except Exception as exc:  # noqa: BLE001
        print(
            f"[portfolio_commit] KALSHI_RESOLVER_BOARD_FAILED {type(exc).__name__}: {exc}",
            flush=True,
        )
        return (None, None)

    joined = join_kalshi_to_board(
        markets, board_rows, selected_date=str(selected_date or "")
    )
    # THE DENOMINATOR FOR `alt_main_collisions`, AND IT IS NOT `board_rows`.
    # See the twin in `kalshi_odds_refresh.join_to_board` for the full argument:
    # the collision rate is per COLLAPSED KEY, and the first production reading
    # of that counter had to be filed with a caveat because `2 / 1100 rows` and
    # the replay's `~1 per 78 keys` are not the same ratio. `_row_key` is the
    # bet identity the collapse keys on, so this is the same number, not an
    # approximation of it.
    _collapsed_bet_keys = len(
        {k for k in (_kalshi_row_key(r) for r in board_rows) if k is not None}
    )
    matches = joined.get("matches") or []
    # `reasons`, NOT `refusals`. This line read `joined.get('refusals')` and
    # `join_kalshi_to_board` has never returned that key -- it returns the
    # breakdown under `reasons`. So every build printed `refusals=None`, for as
    # long as the line has existed, while the join computed a complete
    # per-reason count and dropped it on the floor.
    #
    # MEASURED 2026-08-28 on refresh-worker: three consecutive builds printed
    # `matched=186 refusals=None`, `matched=0 refusals=None`, `matched=0
    # refusals=None`. 1,140 refused rows on the first of those and not one word
    # about why -- which is exactly the question "why is soccer never executed
    # by Kalshi" needed answered, and the reason it could not be answered from
    # production at all. Polymarket's equivalent join has printed its refusals
    # by name the whole time, which is why its story was readable and this one
    # was not.
    #
    # THE MISS IS NOW SELF-REPORTING. A `.get()` on a key the callee does not
    # return is indistinguishable from a callee that returned nothing, and that
    # is the whole defect -- so when the key is absent this says WHICH keys
    # exist rather than printing a confident `None` a second time.
    reasons = joined.get("reasons")
    if reasons is None:
        reasons = f"<no 'reasons' key; join returned {sorted(joined)}>"
    print(
        f"[portfolio_commit] KALSHI_BOARD_JOIN markets={joined.get('kalshi_markets')}"
        f" board_rows={len(board_rows)} matched={len(matches)}"
        # THE DOUBLEHEADER VERIFICATION, printed even when zero. The
        # commence-time split shipped unverified on 2026-09-04 because the only
        # doubleheader contracts that day were on a series with no sport
        # mapping; `> 0` on any later slate settles it from the logs alone.
        f" doubleheader_resolved={joined.get('doubleheader_resolved')}"
        # THE SAME THREE COUNTERS THE ODDS-SIDE EMITTER PRINTS, and they matter
        # MORE here: this is the join whose output becomes an ORDER, so a
        # duplicate bet or a wrong-series pairing costs money on this path and
        # only coverage on the other.
        #
        # WHICH SERIES A SEGMENT ROW MET, both directions. Kalshi lists
        # `KXMLBF5TOTAL-...-5` and `KXMLBTOTAL-...-5` for the SAME game at the
        # SAME strike, and `_row_market()` strips the segment on purpose so both
        # key as (event,'totals',4.5). `_segments_agree` separates them --
        # unprinted, "which contract priced this row" was an inference.
        f" segment_matched_series={joined.get('segment_matched_series')}"
        f" segment_refused_series={joined.get('segment_refused_series')}"
        # ALT/MAIN COLLAPSE RATE. `_row_market()` also strips `_alt`, so a
        # main-line row and an alternate row for one bet key identically and
        # `_collapse_duplicate_bets` picks one. Replay measured ~1 per 78
        # collapsed keys -- a ZERO here is worth a second look, not a
        # celebration. It shipped RETURNED BUT PRINTED NOWHERE (`21aac548`, live
        # in `58302f07`), so the rate this tie-break decides was unmeasurable.
        f" alt_main_collisions={joined.get('alt_main_collisions')}"
        # ...and its denominator beside it. `collisions / collapsed_bet_keys` is
        # one ratio; `collisions / board_rows` is a different, smaller one, and
        # quoting either against the replay's ~1/78 without saying which is the
        # mistake this field exists to prevent.
        f" collapsed_bet_keys={_collapsed_bet_keys}"
        # Named refusals last: `reasons` is a dict repr and anything after it is
        # harder to read and to parse. The odds-side emitter learned this the
        # expensive way -- two sessions appended to it within minutes and the
        # merged line stranded four fields behind the dict and printed
        # `alt_main_collisions` twice.
        f" reasons={reasons}",
        flush=True,
    )
    # THE GRAMMAR WORK LIST, on its own line and only when non-empty. A title
    # the catalogue cannot read is refused as `unreadable_title`, and the count
    # alone cannot say WHICH families are lost -- measured 2026-08-25, eight
    # soccer series refused 413 markets while not one soccer title was legible
    # in any log. `unreadable_by_series` is complete rather than sampled, so an
    # ABSENT family and a bounded sample that simply did not reach it stop
    # sharing a number. Mirrors `POLYMARKET_UNMATCHED`, which is the reason the
    # Polymarket side of this question was answerable and this one was not.
    if joined.get("unreadable_by_series") or joined.get("unmatched_events"):
        print(
            "[portfolio_commit] KALSHI_UNMATCHED"
            f" unreadable_by_series={joined.get('unreadable_by_series')}"
            f" unreadable_titles={joined.get('unreadable_titles')}"
            f" board_market_vocabulary={joined.get('board_market_vocabulary')}"
            f" unmatched_events={joined.get('unmatched_events')}",
            flush=True,
        )
    # ------------------------------------------------------------------
    # SOCCER MATCHES FEED THE QUOTE LOG, NOT THE ORDER PATH -- yet.
    # ------------------------------------------------------------------
    #
    # `kalshi_board_join` gained a SOCCER-ONLY forward-date widening
    # (2026-09-01, lane `kalshi-soccer-forward-date`) so Kalshi's ~918 soccer
    # markets stop refusing `market_is_for_another_date` and their prices reach
    # `book_quotes`. That capture runs off `kalshi_odds_refresh`'s OWN join and
    # is unaffected by this gate.
    #
    # THESE RESOLVERS ARE A DIFFERENT CONSUMER: whatever they index becomes
    # priceable and ticker-stamped for the paper AND LIVE books, and
    # `execute_portfolio` places real venue orders off exactly that.
    #
    # WHY THE GATE EXISTS, and it is a MEASUREMENT that overturned my own
    # prediction rather than a precaution. I expected `no_model_edge_pct` to
    # keep soccer out of positions on its own. **It does not:** `/api/portfolio
    # /paper` shows **4 soccer positions in the 7 days to 2026-09-01**
    # (08-26/28/29/30), soccer was NOT in `DEFAULT_EXCLUDED_FAMILIES`
    # (`mlb:player_prop` only; removed 2026-09-16), `SYNDICATE_EXECUTION_ENABLED=1` and soccer is in
    # `SYNDICATE_ACTIVE_SPORTS`. So widening the join without this would have
    # added 918 markets of a sport whose model is recorded as NOT beating the
    # market (`soccer-model-dispersion`: worse than market in 8 of 9 leagues) to
    # a live order path, as a side effect of a coverage fix.
    #
    # Coverage and profitability are different questions. This keeps them apart
    # until someone decides the second one on evidence.
    #
    # PRINTED ALWAYS, ZEROES INCLUDED: `withheld=0` on a slate with soccer
    # matches means the switch is armed, and a line printed only when
    # withholding could not say so.
    # THROUGH `sport_for_series`, THE JOIN'S OWN MAPPER, and off `series` --
    # the field a match actually carries. **A match has no `sport` key**:
    # verified against both `matches.append` blocks, which write
    # ticker/series/market/player_name/line/board_side/kalshi_*/board_event_id
    # and no sport. A gate keyed on `m.get("sport")` would have read None for
    # every row, withheld nothing, and printed `withheld=0` -- indistinguishable
    # from an armed switch. Caught before shipping; recorded because that is the
    # inert-guard shape this repo keeps paying for.
    from syndicate.features.shared.kalshi_catalogue import sport_for_series

    soccer_idx = {
        i for i, m in enumerate(matches)
        if sport_for_series((m or {}).get("series")) == "soccer"
    }
    soccer_armed = str(
        os.environ.get("SYNDICATE_KALSHI_SOCCER_RESOLVERS") or ""
    ).strip().lower() in {"1", "on", "true", "yes"}
    soccer_matches = soccer_idx
    if soccer_idx and not soccer_armed:
        matches = [m for i, m in enumerate(matches) if i not in soccer_idx]
    print(
        "[portfolio_commit] KALSHI_SOCCER_RESOLVERS"
        f" armed={soccer_armed} soccer_matches={len(soccer_matches)}"
        f" withheld={0 if soccer_armed else len(soccer_matches)}",
        flush=True,
    )
    if not matches:
        # Named, and `(None, None)` so the venue reverts to the aggregator
        # rather than losing its book -- but the line above says it happened,
        # which is what this whole failure lacked.
        #
        # AND WHICH ZERO IT IS, carried out to the plan line. `soccer_idx and
        # not soccer_armed` is the ONLY thing that earns `policy_withheld`: it
        # means withholding is what took the last match. A join that matched
        # nothing at all leaves this `None` and keeps stamping READER_FAILED,
        # which is correct -- the flag's value says nothing about whether the
        # reader worked, and reading the flag alone would reclassify exactly
        # the 2026-08-25 defect as policy.
        return _VenueResolvers(
            None,
            None,
            withheld_by=(
                "SYNDICATE_KALSHI_SOCCER_RESOLVERS"
                if (soccer_idx and not soccer_armed)
                else None
            ),
        )
    return kalshi_price_resolver(matches), kalshi_ticker_resolver(matches)


def _execution_enabled() -> bool:
    """Imported inside the call: `execute_portfolio` imports this module."""
    from pipeline.execute_portfolio import execution_enabled

    return execution_enabled()


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")



def _settled_sample_size_by_sport() -> dict[str, int]:
    """Per-sport SETTLED counts, for the S6 sample-credibility ramp.

    **THIS EXISTS BECAUSE THE HOOK BELOW WAS NEVER WIRED, AND ITS OWN COMMENT
    SAID WHEN IT SHOULD BE.** `commit_portfolio` shrinks every stake by
    `_sample_credibility(settled_sample_size)`, which ramps 0.25 -> 1.0 at 50
    settled bets (`bankroll_manager.py:158,187`). No caller ever passed the map,
    so the argument defaulted to `None` and EVERY market sized at the 0.25
    floor. Combined with the fixed quarter-Kelly multiplier that is

        staked_fraction = full_kelly * 0.25 * 0.25   = 1/16 Kelly

    The hook's comment read "correct while `settled_count` is 0 platform-wide".
    Measured 2026-09-04, that premise had expired: settlement carries **1,594
    settled orders** (book 662, kalshi 474, polymarket 224, prophetx 150, novig
    84), and the dominant sport has **616 settled at +5.76% ROI** -- credibility
    1.00, four times what it was being sized at. The whole board wanted $19.64
    of a $1,000 bankroll.

    *(Those two figures are kept as written because they are the reading that
    motivated the fix, but label them: 1,594 is every book including the
    venue-scoped shadow copies, and MLB's 616 is the PAPER book alone. The
    portfolio book over the same ledger is 979 settled rows / **783 distinct
    decisions**, MLB 616 -> 865 rows -> 684 decisions. See the correction below
    -- none of those moves MLB off credibility 1.00, which is exactly why the
    error survived a first reading: it was invisible in the sport that was
    looked at.)*

    **DERIVED HERE RATHER THAN PASSED BY THE CALLER, deliberately.** There is
    exactly one production caller (`intelligence_state.py`) and it did not pass
    it; making the fix depend on a caller remembering is how it was lost the
    first time. A default of `None` now means "work it out", not "size
    everything at the floor".

    -----------------------------------------------------------------------
    IT COUNTS DECISIONS, NOT ORDER ROWS, AND THAT IS A CORRECTION [2026-09-04]
    -----------------------------------------------------------------------

    This first shipped reading `settlement_summary()["by_sport"]["settled"]`,
    which is a count of settled ORDER ROWS. Two settlement numbers then
    disagreed about NFL in production on 2026-09-04 -- `settlement_all_time.
    by_sport` said `orders=1, settled=0` while this line printed `nfl: 18` --
    and running both down produced two separate facts:

      1. THE PRODUCERS ARE BOTH RIGHT. `settlement_all_time` is rendered on
         `/portfolio/paper`, whose banner says "no money moves", so its payload
         is filtered to `mode != live` before the summary ever sees it. It is
         the PAPER book. This function reads the whole ledger, paper AND live,
         which is the right population for "what do we know about our edge" --
         the live book is 315 of the 979 settled rows and all 18 of the NFL.

      2. THE UNIT WAS WRONG HERE. A row count is not a sample size. The same
         bet placed at Kalshi and at Polymarket is two rows and ONE trial; the
         game resolves once. Measured over the production ledger the same day,
         NFL's 18 settled rows are **12 distinct decisions** -- six pairs, and
         all six pairs settled identically, as they must.

    So this delegates to `paper_settlement.settled_decisions_by_sport`, which
    owns the definition and the dedupe, rather than deriving a second one here.
    The measured effect on sizing is stated where it belongs, in that
    function's docstring: **NFL credibility 0.360 -> 0.250, the floor.**

    Returns `{}` on any failure, which reverts to the old behaviour rather than
    breaking the commit. The reason is printed, because a silent revert here is
    indistinguishable from the bug.
    """
    try:
        from syndicate.features.shared.paper_settlement import (
            settled_decisions_by_sport,
        )

        return settled_decisions_by_sport()  # whole ledger -> ALL TIME
    except Exception as exc:  # noqa: BLE001
        print(f"[portfolio_commit] SETTLED_SAMPLE_UNAVAILABLE error={exc}", flush=True)
        return {}


def suggested_rows(rows: list) -> tuple[list, dict[str, int]]:
    """The shortlist rows the paper book may stake: those the board flagged `suggested`.

    `[user decision 2026-10-13, "Yes, one definition"]`, lane `layer2-suggested-opps`.
    The board stamps a per-LINE flag (`layer2_board._stamp_suggested`: market EV >= +2%
    net of venue fee, two-sided fair, plausible fresh quote, one side per line) and the
    paper book stakes exactly that set, so the graded set IS the shown set. Applied here,
    on the production read of the shortlist, and not inside the pure
    `commit_portfolio` sizer: every sizing gate, refusal name and test of that function
    is unchanged.

    A row with NO flag (built before it existed) is counted `flag_absent` and NOT
    staked -- unknown must not take the permissive branch.
    """
    kept: list = []
    gate = {"rows_in": 0, "suggested": 0, "not_suggested": 0, "flag_absent": 0}
    for row in rows or ():
        gate["rows_in"] += 1
        if not isinstance(row, Mapping) or "suggested" not in row:
            gate["flag_absent"] += 1
        elif row.get("suggested") is True:
            gate["suggested"] += 1
            kept.append(row)
        else:
            gate["not_suggested"] += 1
    return kept, gate


def run_portfolio_commit(
    selected_date: str,
    *,
    settled_sample_size_by_sport: Mapping[str, int] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Build and persist today's plan. Returns a status payload, never raises.

    `force` bypasses only the enablement flag, never the input checks -- a
    forced run on an absent shortlist still reports `no_shortlist` rather than
    writing an empty plan, because an empty plan and no plan are different
    facts and the reader needs to tell them apart.
    """
    normalized = str(selected_date or "").strip()
    if not normalized:
        return {"status": "skipped", "reason": "no_date"}
    if not (force or portfolio_commit_enabled()):
        return {"status": "skipped", "reason": "disabled", "date": normalized}

    from pipeline.intelligence_state import read_layer2_shortlist

    shortlist = read_layer2_shortlist(normalized)
    if not isinstance(shortlist, dict):
        print(f"[portfolio_commit] NO_SHORTLIST date={normalized}", flush=True)
        return {"status": "skipped", "reason": "no_shortlist", "date": normalized}

    rows = shortlist.get("rows")
    if not isinstance(rows, list):
        return {"status": "skipped", "reason": "shortlist_has_no_rows_key", "date": normalized}

    # SUGGESTED ONLY -- see `suggested_rows`. A shortlist built entirely before the
    # flag existed leaves the previous plan standing instead of writing an empty one.
    rows, suggested_gate = suggested_rows(rows)
    print(
        "[portfolio_commit] SUGGESTED_GATE date=%s rows_in=%d suggested=%d not_suggested=%d flag_absent=%d"
        % (normalized, suggested_gate["rows_in"], suggested_gate["suggested"],
           suggested_gate["not_suggested"], suggested_gate["flag_absent"]),
        flush=True,
    )
    if suggested_gate["rows_in"] and suggested_gate["flag_absent"] == suggested_gate["rows_in"]:
        return {"status": "skipped", "reason": "shortlist_predates_suggested_flag", "date": normalized,
                "suggested_gate": suggested_gate}

    # THE GATE. Pure computation, no I/O, so it runs before every plan write.
    #
    # Harder than the reference implementation's `--warn-only`
    # (`run_mlb_daily_sim_job.py:506`) on purpose: the failure this catches does
    # not look like a failure. An unfed sizer writes a plan full of $0 positions
    # and a reader cannot tell it from a slate with no edges. Refusing to write
    # leaves the previous plan standing and an absence to explain, which is the
    # recoverable direction.
    try:
        import sys
        from pathlib import Path as _Path

        sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "scripts"))
        from portfolio_commit_input_checklist import run_checklist

        checklist_ok, checklist_lines = run_checklist()
    except Exception as exc:
        print(f"[portfolio_commit] CHECKLIST_ERROR date={normalized} error={exc}", flush=True)
        return {"status": "error", "reason": f"checklist_error: {exc}", "date": normalized}
    if not checklist_ok:
        # Carry the failing lines, not just a verdict -- a check whose failure
        # message does not carry the evidence for the failure is one nobody can
        # act on (`learnings.md` 2026-08-16, FORBIDDEN).
        failures = [line for line in checklist_lines if line.startswith("FAIL")]
        for line in failures:
            print(f"[portfolio_commit] CHECKLIST_FAIL {line}", flush=True)
        return {
            "status": "error",
            "reason": "input_checklist_failed",
            "date": normalized,
            "failures": failures,
        }

    # RESOLVED ONCE. Read twice, this would be two answers whenever the stored
    # settings change mid-run -- and the log line below would then describe a
    # bankroll the plan was not sized with.
    settings = resolve_settings()

    # S6 HOOK, NOW WIRED (2026-09-04). The comment that stood here said this was
    # "correct while `settled_count` is 0 platform-wide" and that "when
    # settlement starts producing records this is where the real per-sport
    # sample enters, and stakes rise on evidence rather than on a constant being
    # edited". Settlement has been producing records for weeks; the caveat came
    # due and nothing noticed, so every stake sized at 1/16 Kelly instead of 1/4.
    if settled_sample_size_by_sport is None:
        settled_sample_size_by_sport = _settled_sample_size_by_sport()
    # OBSERVABLE, because a silent derivation is indistinguishable from the bug
    # it replaces. `credibility` is what the sizer will actually apply.
    print(
        "[portfolio_commit] SETTLED_SAMPLE date=%s samples=%s credibility=%s"
        % (
            normalized,
            dict(sorted((settled_sample_size_by_sport or {}).items())),
            {
                sport: round(min(1.0, max(0.25, n / 50.0)), 3)
                for sport, n in sorted((settled_sample_size_by_sport or {}).items())
            },
        ),
        flush=True,
    )

    plan = commit_portfolio(
        rows,
        selected_date=normalized,
        settings=settings,
        settled_sample_size_by_sport=settled_sample_size_by_sport,
    )

    # Run the CLV join BEFORE the write, so its summary lands in the artifact the
    # web service reads. Web must not compute -- `/portfolio/paper` would
    # otherwise have to load ~3k opening records per request to show a match
    # rate, which is exactly the recompute-in-a-request-handler the architecture
    # forbids. The worker joins once; web reads the answer.
    #
    # `rows` is deliberately DROPPED from what gets stored: it duplicates every
    # position and would roughly double an artifact that has an 8MB keyvalue
    # refusal ceiling. The counters are what anybody reads.
    # WHERE THE JOBS ACTUALLY RUN, stamped by the process that runs them.
    # `/portfolio/paper` read these flags from its OWN environment and reported
    # "COMMIT JOB off / EXECUTION JOB off" on a page full of committed positions
    # and filled orders -- true of the web service, useless to a reader, and
    # exactly backwards as a status line. The flags are worker-side facts, so
    # the worker records them.
    plan["suggested_gate"] = suggested_gate
    plan["job_state"] = {
        "commit_enabled": True,
        "execution_enabled": _execution_enabled(),
        "execution_mode": execution_mode(),
        "recorded_by": "refresh-worker",
        "recorded_at": _utc_now_iso(),
    }

    # LIVE MARKS -- every order for this date re-priced against the board that
    # was just built. Covers orphans too: a bet whose position left the plan is
    # still a bet, and is usually the one you most want to look at.
    try:
        from syndicate.features.shared.execution_ledger import _load as _load_ledger

        todays_orders = [
            order
            for order in (_load_ledger().get("orders") or [])
            if order.get("selected_date") == normalized
        ]
        marks = mark_orders_to_board(todays_orders, rows)
        print(marks_report_line(marks), flush=True)
        plan["live_marks"] = marks
    except Exception as exc:
        print(f"[portfolio_commit] LIVE_MARKS_FAILED date={normalized} error={exc}", flush=True)

    # LIVE BET STATUS -- where each placed bet stands against the GAME, not
    # against the line. `position_marks` answers "has the market moved toward
    # us"; this answers "is it winning". Different questions, and the second is
    # the one a person watching a slate actually wants.
    #
    # Resolvers are per sport and only MLB has one today, so every other sport's
    # orders come back with a named reason rather than a blank -- which is the
    # honest rendering of "not built yet" and is visible on the page as such.
    try:
        from syndicate.features.shared.bet_status import (
            bet_status_report_line,
            statuses_for_orders,
        )
        from syndicate.features.shared.paper_settlement import _default_resolver

        # ITS OWN IMPORT. This block used to call `_load_ledger_for_clv()`,
        # which is bound by a `from ... import ... as` TWENTY LINES BELOW, in
        # the ORDER_CLV block. Python sees an assignment anywhere in the
        # function and treats the name as local for the whole of it, so this
        # read raised `UnboundLocalError` on every single cycle -- caught by
        # this block's own `except` and printed as BET_STATUS_FAILED.
        #
        # So live bet status NEVER ONCE WORKED from the day it was written, and
        # it failed in the shape that is hardest to notice: a feature that looks
        # installed, a log line nobody was grepping for, and a page column that
        # renders an honest-looking blank. Measured 2026-08-23T17:12:31Z.
        from syndicate.features.shared.execution_ledger import _load as _load_ledger

        status_orders = [
            order
            for order in (_load_ledger().get("orders") or [])
            if order.get("selected_date") == normalized
        ]
        if status_orders:
            # THE SAME DISPATCHER SETTLEMENT USES. Two copies of "which resolver
            # for which sport" is two places to add WNBA and one place to forget
            # -- and the live column and the settled record disagreeing about
            # what is resolvable would be worse than either being wrong alone.
            statuses = statuses_for_orders(status_orders, resolver=_default_resolver(normalized))
            print(bet_status_report_line(statuses), flush=True)
            plan["bet_status"] = statuses
    except Exception as exc:
        print(f"[portfolio_commit] BET_STATUS_FAILED date={normalized} error={exc}", flush=True)

    # STAGE C'S GATE INPUT: what our placed orders got against the CLOSE.
    # Distinct from the join below, which is orders -> OPENING. A close only
    # exists once a market has stopped moving, so most of the day this resolves
    # nothing for today and everything for yesterday -- which is why it runs
    # over the ledger rather than over today's positions, and why an unresolved
    # row is named rather than dropped.
    try:
        from syndicate.features.shared.execution_ledger import _load as _load_ledger_for_clv

        dated_orders = [
            order
            for order in (_load_ledger_for_clv().get("orders") or [])
            if order.get("selected_date") == normalized
        ]
        if dated_orders:
            order_clv = clv_for_orders(dated_orders, date=normalized)
            print(order_clv_report_line(order_clv), flush=True)
            # `rows` dropped from the artifact for the same reason as the join
            # below: it duplicates every order against an 8MB ceiling. The
            # per-market aggregates are what a reader needs, and they carry `n`.
            plan["order_clv"] = {
                key: value for key, value in order_clv.items() if key != "rows"
            }
    except Exception as exc:
        print(f"[portfolio_commit] ORDER_CLV_FAILED date={normalized} error={exc}", flush=True)

    clv_join = None
    try:
        report = join_positions_to_openings(plan.get("positions") or [], date=normalized)
        print(join_report_line(report), flush=True)
        for example in report.get("disagreement_examples") or []:
            # A count says the derivation is wrong; an example says which field.
            print(
                f"[portfolio_commit] CLV_KEY_DISAGREEMENT position={example.get('position_key')} "
                f"stamped={example.get('stamped')} derived={example.get('derived')}",
                flush=True,
            )
        clv_join = {key: value for key, value in report.items() if key != "rows"}
        plan["clv_join"] = clv_join
    except Exception as exc:
        # A DIAGNOSTIC must never cost a slate. The plan is complete either way.
        print(f"[portfolio_commit] CLV_JOIN_FAILED date={normalized} error={exc}", flush=True)

    try:
        write_json_file(portfolio_plan_path(normalized), plan)
    except Exception as exc:
        print(f"[portfolio_commit] PLAN_WRITE_FAILED date={normalized} error={exc}", flush=True)
        return {"status": "error", "reason": f"write_failed: {exc}", "date": normalized}

    totals = plan.get("totals") or {}

    # WHERE THE BANKROLL CAME FROM, not just what it is.
    #
    # `resolve_settings` is stored > env > default per field, and the three are
    # fixed in DIFFERENT PLACES: stored is the settings form, env is the Render
    # dashboard, default is this repo. A line that prints `bankroll=$250.0`
    # without the source sends a reader to change the wrong one -- and the two
    # do not override symmetrically, so setting the env var while a stored
    # value exists changes nothing at all and looks like it worked.
    #
    # Measured 2026-08-26 00:35:49Z: `bankroll=$250.0` against a stated policy
    # of $1000, with no way to tell from any log which of the three won. Same
    # defect as `RECONCILE_COUNT_IMPLAUSIBLE` printing one branch's numbers
    # while another decided -- a value stated without its provenance.
    bankroll_source = str((settings.sources or {}).get("bankroll_units") or "?")

    # THE TOP MARKET UNDER EACH REFUSAL, because "98 rows had no model edge"
    # cannot answer "why are no PROP positions being taken" and that is the
    # question the counts get asked. Trimmed to the leader per reason: the full
    # breakdown is in the artifact, and a log line that printed every market
    # would be read by nobody.
    by_market = plan.get("refusals_by_market") or {}
    leaders = {
        reason: f"{next(iter(markets))}:{next(iter(markets.values()))}"
        for reason, markets in by_market.items()
        if markets
    }
    # THE SPORT SPLIT OF `no_model_edge_pct` SPECIFICALLY, in full rather than
    # trimmed to a leader. That one refusal was 93.9% of in-scope rows across 4
    # days and 4 venues, and the board's own projection join reported MLB at 89%
    # and NFL at 76% coverage on the same day -- readings that cannot both
    # describe the same sport. The leader alone cannot settle it; the whole
    # split can, and there are only a handful of sports.
    no_view_by_sport = (plan.get("refusals_by_sport") or {}).get("no_model_edge_pct") or {}

    # print, not logger.info -- logger.info never reaches Render's collector.
    print(
        f"[portfolio_commit] PLAN_WRITTEN date={normalized} "
        f"rows_in={plan.get('rows_in')} sized={plan.get('sized')} "
        f"positions={totals.get('positions')} staked=${totals.get('staked_dollars')} "
        f"bankroll=${plan.get('bankroll_units')} bankroll_source={bankroll_source} "
        f"scale={totals.get('slate_scale_factor')} "
        f"refusals={plan.get('refusals')} top_market_per_refusal={leaders} "
        f"no_model_edge_by_sport={no_view_by_sport}",
        flush=True,
    )
    # ---- paper2: the same pipeline, restricted to one venue's prices --------
    #
    # Answers the question Stage D's plan says to answer with numbers rather
    # than in advance: the legally automatable venues trade mostly
    # moneyline/spread/total, while this board's edge is in props. If the
    # venue-scoped book has no edge, no placer is worth writing.
    #
    # Runs AFTER the main plan is on disk, and wrapped, so the comparison can
    # never cost the portfolio it is being compared against.
    venue_plans: dict[str, Any] = {}
    # THE PAPER LADDER (lane paper-alongside-live): one paper-only plan per
    # LADDER_VENUES entry, built below beside that venue's paper2 book.
    ladder_plans: dict[str, Any] = {}
    main_totals = plan.get("totals") or {}
    # THE LIVE PLANS' ROWS: Suggested-only unless the 0% net floor is on (see
    # `live_ev_floor_rows`). paper2 below keeps the Suggested rows either way.
    live_floor_rows = _live_ev_floor_population(shortlist, normalized)
    for venue in paper2_venues():
        # Each venue in its OWN try: one venue's failure must not cost the
        # others' measurements, and the whole point is comparing across them.
        try:
            # THE VENUE'S OWN PRICES, where we have them. Only Kalshi has a
            # direct feed today; every other venue falls back to the aggregator,
            # and `price_source` on each scoped row records which was used.
            venue_resolvers = _venue_price_resolver(venue, normalized)
            venue_price_resolver, venue_ticker_resolver = venue_resolvers
            # `getattr`, not an attribute read: every other return path in
            # `_venue_price_resolver` is a plain `(None, None)` and must keep
            # stamping READER_FAILED. Absent signal -> alarm, never policy.
            feed_status = _venue_feed_status(
                venue,
                venue_price_resolver,
                withheld_by=getattr(venue_resolvers, "withheld_by", None),
            )
            scoped, scope_refusals = scope_rows_to_venue(
                rows,
                venue,
                price_resolver=venue_price_resolver,
                ticker_resolver=venue_ticker_resolver,
            )
            print(
                venue_scope_report_line(venue, len(rows), len(scoped), scope_refusals),
                flush=True,
            )
            # ONE read per venue, shared by that venue's paper2 book and its
            # live book, so the two are never sized under different settings.
            venue_settings = resolve_settings()
            venue_plan = commit_portfolio(
                scoped,
                selected_date=normalized,
                settings=venue_settings,
                settled_sample_size_by_sport=settled_sample_size_by_sport,
                # A row this venue cannot PLACE must not hold one of its
                # `max_positions` slots. See the cut in `commit_portfolio`.
                prefer_placeable=True,
            )
            venue_plan["venue"] = venue
            venue_plan["venue_scope_refusals"] = scope_refusals
            venue_plan["job_state"] = dict(plan.get("job_state") or {})
            write_json_file(portfolio_plan_path_for_venue(normalized, venue), venue_plan)
            venue_totals = venue_plan.get("totals") or {}
            venue_refusals = venue_plan.get("refusals") or {}
            print(
                f"[portfolio_commit] PAPER2_PLAN_WRITTEN date={normalized} venue={venue} "
                f"rows_in={len(scoped)} positions={venue_totals.get('positions')} "
                f"staked=${venue_totals.get('staked_dollars')} "
                # THE NUMBER THAT DECIDES STAGE D, on the line rather than
                # inferred: how many of the venue's own quoted rows the model
                # has any view on at all. Kalshi measured 12 of 47.
                # Counted on the rows (`sim_coverage`), not inferred from the refusal: EV-only
                # staking sizes rows with no sim edge (2026-09-16). Same rule as the paper page.
                f"sim_view_on={(venue_plan.get('sim_coverage') or {}).get('rows_with_sim_edge', len(scoped) - int(venue_refusals.get('no_model_edge_pct', 0) or 0))}"
                f"/{len(scoped)} "
                # How many rows were priced from the VENUE rather than the
                # aggregator -- the difference between a real coverage number
                # and OddsAPI's view of one.
                f"venue_priced={sum(1 for r in scoped if r.get('price_source') == 'venue_feed')} "
                # ...AND WHY, because a zero here has opposite causes and they
                # call for opposite work. `capability_gap` is nothing to do;
                # `policy_withheld:<FLAG>` is a gate someone chose, and the
                # token names the switch that undoes it; `READER_FAILED` is a
                # venue that HAS a feed pricing off the aggregator instead,
                # which is what Kalshi did silently for weeks while the fan-in
                # produced 2,344 quotes for it.
                f"feed={feed_status} "
                # HOW MANY PLACEABLE ROWS THE POSITION CAP COST, which is the
                # number that says whether `max_positions` is the binding
                # constraint on this venue actually trading. A cut that reports
                # only a total cannot distinguish "we ran out of slots for bets
                # we could make" from "we ran out of slots for bets we could
                # not".
                f"placeable_committed={sum(1 for p in (venue_plan.get('positions') or []) if p.get('price_source') == 'venue_feed')}"
                f"/{venue_totals.get('positions')} "
                # Side by side on ONE line, because the comparison IS the
                # deliverable and reading it off two lines invites pairing the
                # wrong two runs.
                f"vs_unrestricted_positions={main_totals.get('positions')} "
                f"vs_unrestricted_staked=${main_totals.get('staked_dollars')} "
                f"refusals={venue_refusals} "
                # Same split, on the plan that the 93.9% was measured from.
                f"no_model_edge_by_sport={(venue_plan.get('refusals_by_sport') or {}).get('no_model_edge_pct') or {}}",
                flush=True,
            )
            venue_plans[venue] = venue_plan
            # THE BOOK LIVE PLACES, from the same scoped rows and the same
            # settings, and only once paper2 is on disk. In its own guard: it
            # must never cost the comparison book it is derived from, nor the
            # next venue's measurements.
            try:
                live_scoped, live_scope_refusals = scoped, scope_refusals
                if live_floor_rows is not None:
                    live_scoped, live_scope_refusals = scope_rows_to_venue(
                        live_floor_rows,
                        venue,
                        price_resolver=venue_price_resolver,
                        ticker_resolver=venue_ticker_resolver,
                    )
                _write_live_venue_plan(
                    live_scoped,
                    normalized=normalized,
                    venue=venue,
                    settings=venue_settings,
                    settled_sample_size_by_sport=settled_sample_size_by_sport,
                    paper2_plan=venue_plan,
                    scope_refusals=live_scope_refusals,
                    job_state=plan.get("job_state"),
                )
            except Exception as exc:
                print(
                    f"[portfolio_commit] LIVE_PLAN_FAILED date={normalized} venue={venue} "
                    f"error={type(exc).__name__}: {exc}",
                    flush=True,
                )
            # THE PAPER LADDER, PAPER ONLY  [2026-10-20, user decision relayed by
            # session b87af0fc: "yes - but we should reconsider the floors"; lane
            # paper-alongside-live]. AFTER the live plan and in its own guard, so it
            # can never change or cost the live book or paper2. It prices the WHOLE
            # shortlist's floor-refused rows with this venue's own resolvers and
            # keeps what paper2 did not stake. See `paper_ladder`.
            try:
                from syndicate.features.shared import paper_ladder

                if venue in paper_ladder.LADDER_VENUES and paper_ladder.ladder_enabled():
                    eligible = paper_ladder.eligible_rows(shortlist.get("rows") or [])
                    ladder_scoped, _ladder_scope_refusals = scope_rows_to_venue(
                        eligible,
                        venue,
                        price_resolver=venue_price_resolver,
                        ticker_resolver=venue_ticker_resolver,
                    )
                    ladder_plan = paper_ladder.build_ladder_plan(
                        ladder_scoped,
                        venue=venue,
                        selected_date=normalized,
                        staked_position_keys=frozenset(
                            str(p.get("position_key") or "")
                            for p in (venue_plan.get("positions") or [])
                            if isinstance(p, Mapping)
                        ),
                    )
                    write_json_file(portfolio_plan_path_for_venue(normalized, f"{venue}_ladder"), ladder_plan)
                    print(paper_ladder.ladder_report_line(ladder_plan, eligible=len(eligible)), flush=True)
                    ladder_plans[venue] = ladder_plan
            except Exception as exc:
                print(
                    f"[portfolio_commit] LADDER_PLAN_FAILED date={normalized} venue={venue} "
                    f"error={type(exc).__name__}: {exc}",
                    flush=True,
                )
        except Exception as exc:
            print(
                f"[portfolio_commit] PAPER2_FAILED date={normalized} venue={venue} error={exc}",
                flush=True,
            )

    return {
        "status": "ok",
        "date": normalized,
        "plan": plan,
        "clv_join": clv_join,
        "venue_plans": venue_plans,
        "ladder_plans": ladder_plans,
        "venues": sorted(venue_plans),
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Commit a portfolio from the Layer 2 shortlist.")
    parser.add_argument("--date", required=True, help="slate date, YYYY-MM-DD")
    parser.add_argument("--force", action="store_true", help="ignore the enablement flag")
    args = parser.parse_args()
    result = run_portfolio_commit(args.date, force=args.force)
    print(result.get("status"), result.get("reason") or "")
    return 0 if result.get("status") in {"ok", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
