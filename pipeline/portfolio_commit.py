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
            f" samples={joined.get('unmatched_samples')}",
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
        f" listed={joined.get('orientation_fixture_listed')}"
        f" not_listed={joined.get('orientation_fixture_not_listed')}"
        f" unreadable={joined.get('orientation_fixture_unreadable')}"
        f" samples={joined.get('orientation_flip_samples')}",
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
    if not matches:
        # Named, and `(None, None)` so the venue reverts to the aggregator
        # rather than losing its book -- but the line above says it happened,
        # which is what this whole failure lacked.
        return (None, None)
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

    # RESOLVED ONCE. Read twice, this would be two answers whenever the stored
    # settings change mid-run -- and the log line below would then describe a
    # bankroll the plan was not sized with.
    settings = resolve_settings()

    plan = commit_portfolio(
        rows,
        selected_date=normalized,
        settings=settings,
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

    # print, not logger.info -- logger.info never reaches Render's collector.
    print(
        f"[portfolio_commit] PLAN_WRITTEN date={normalized} "
        f"rows_in={plan.get('rows_in')} sized={plan.get('sized')} "
        f"positions={totals.get('positions')} staked=${totals.get('staked_dollars')} "
        f"bankroll=${plan.get('bankroll_units')} bankroll_source={bankroll_source} "
        f"scale={totals.get('slate_scale_factor')} "
        f"refusals={plan.get('refusals')} top_market_per_refusal={leaders}",
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
                f"sim_view_on={len(scoped) - int(venue_refusals.get('no_model_edge_pct', 0) or 0)}"
                f"/{len(scoped)} "
                # How many rows were priced from the VENUE rather than the
                # aggregator -- the difference between a real coverage number
                # and OddsAPI's view of one.
                f"venue_priced={sum(1 for r in scoped if r.get('price_source') == 'venue_feed')} "
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
