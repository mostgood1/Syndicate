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


def read_portfolio_plan_for_venue(
    selected_date: str | None, venue: str
) -> dict[str, Any] | None:
    normalized = str(selected_date or "").strip()
    if not normalized:
        return None
    payload = read_json_file(portfolio_plan_path_for_venue(normalized, venue))
    return payload if isinstance(payload, dict) else None


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

    joined = join_polymarket_to_board(markets, board_rows, selected_date=str(selected_date or ""))
    age = None if fetched_at is None else round(time.time() - float(fetched_at), 1)
    print(
        f"[portfolio_commit] POLYMARKET_BOARD_JOIN markets={joined.get('polymarket_markets')} "
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
    if joined.get("out_of_scope_counts"):
        print(
            "[portfolio_commit] POLYMARKET_OUT_OF_SCOPE"
            f" counts={joined.get('out_of_scope_counts')}"
            f" samples={joined.get('out_of_scope_samples')}",
            flush=True,
        )
    matches = joined.get("matches") or []
    if not matches:
        return (None, None)
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
        markets = (payload or {}).get("markets") or []
        if not markets:
            return (None, None)
        return _resolvers_from_markets(markets)
    except Exception as exc:
        # Named, and returns None so the venue silently reverts to the
        # aggregator rather than losing its book entirely.
        print(f"[portfolio_commit] KALSHI_RESOLVER_FAILED venue={venue} error={exc}", flush=True)
        return (None, None)


def _resolvers_from_markets(markets):
    """Fetched Kalshi markets -> `(price_resolver, ticker_resolver)`.

    Classified by the CATALOGUE, so every sport it knows is priced here without
    this function naming any of them. One match list feeds both resolvers.
    """
    from syndicate.features.shared.kalshi_board_join import (
        kalshi_price_resolver,
        kalshi_ticker_resolver,
    )
    from syndicate.features.shared.kalshi_catalogue import classify_market

    matches = []
    for market in markets:
        verdict = classify_market(market)
        # Unmapped series, unreadable titles and game lines with no event
        # mapping are all skipped here rather than guessed -- the catalogue
        # already refuses each of them by its own name, and `report_catalogue_gaps`
        # is where those numbers are meant to be read.
        if verdict.get("status") != "ok" or verdict.get("needs_event_identity"):
            continue
        # Each side takes its OWN quote: yes and no are separately priced and
        # the gap between them is the spread.
        for side, price_key in (("over", "yes_american"), ("under", "no_american")):
            price = market.get(price_key)
            if price is None:
                continue
            matches.append(
                {
                    "market": verdict["market"],
                    "player_name": verdict["subject"],
                    "line": verdict["line"],
                    "board_side": side,
                    "kalshi_american": price,
                    # Carried so the ticker resolver keys off the SAME match.
                    "ticker": verdict.get("ticker"),
                }
            )
    return kalshi_price_resolver(matches), kalshi_ticker_resolver(matches)


def _execution_enabled() -> bool:
    """Imported inside the call: `execute_portfolio` imports this module."""
    from pipeline.execute_portfolio import execution_enabled

    return execution_enabled()


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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

    plan = commit_portfolio(
        rows,
        selected_date=normalized,
        settings=resolve_settings(),
        # S6 HOOK. Layer 2 rows carry no `historical_profile`, so this is empty
        # today and every market therefore sizes at `_MIN_SAMPLE_CREDIBILITY`
        # (0.25) -- which is correct while `settled_count` is 0 platform-wide.
        # When settlement starts producing records this is where the real
        # per-sport sample enters, and stakes rise on evidence rather than on a
        # constant being edited.
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
    # print, not logger.info -- logger.info never reaches Render's collector.
    print(
        f"[portfolio_commit] PLAN_WRITTEN date={normalized} "
        f"rows_in={plan.get('rows_in')} sized={plan.get('sized')} "
        f"positions={totals.get('positions')} staked=${totals.get('staked_dollars')} "
        f"bankroll=${plan.get('bankroll_units')} scale={totals.get('slate_scale_factor')} "
        f"refusals={plan.get('refusals')}",
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
    main_totals = plan.get("totals") or {}
    for venue in paper2_venues():
        # Each venue in its OWN try: one venue's failure must not cost the
        # others' measurements, and the whole point is comparing across them.
        try:
            # THE VENUE'S OWN PRICES, where we have them. Only Kalshi has a
            # direct feed today; every other venue falls back to the aggregator,
            # and `price_source` on each scoped row records which was used.
            venue_price_resolver, venue_ticker_resolver = _venue_price_resolver(venue, normalized)
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
            venue_plan = commit_portfolio(
                scoped,
                selected_date=normalized,
                settings=resolve_settings(),
                settled_sample_size_by_sport=settled_sample_size_by_sport,
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
                f"sim_view_on={len(scoped) - int(venue_refusals.get('no_model_edge_pct', 0) or 0)}"
                f"/{len(scoped)} "
                # How many rows were priced from the VENUE rather than the
                # aggregator -- the difference between a real coverage number
                # and OddsAPI's view of one.
                f"venue_priced={sum(1 for r in scoped if r.get('price_source') == 'venue_feed')} "
                # Side by side on ONE line, because the comparison IS the
                # deliverable and reading it off two lines invites pairing the
                # wrong two runs.
                f"vs_unrestricted_positions={main_totals.get('positions')} "
                f"vs_unrestricted_staked=${main_totals.get('staked_dollars')} "
                f"refusals={venue_refusals}",
                flush=True,
            )
            venue_plans[venue] = venue_plan
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
