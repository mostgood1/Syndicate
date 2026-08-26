# BACKUP ONLY — Kalshi spreads/h2h side mapper

> **`[USER DECISION 2026-08-26]` The side mapper is assigned to syndicate-43.
> This patch is a BACKUP. Do not apply it to `kalshi_orders.py`.**
>
> It exists so the work is not lost if the local session's version stalls, and
> as an independent cross-check on the venue-read spec — two implementations
> arriving at the same rule from the same measurements is worth something. It is
> NOT a competing change and must not be landed alongside syndicate-43's.
>
> If it is ever needed: `git apply .syndicate/handoff/kalshi_side_mapper_from_cloud.patch`
> — verified to apply cleanly against `main` at the commit that added this line.
> Re-verify before trusting that; `kalshi_orders.py` is under active edit by
> another session and this patch will go stale.

## Original handoff notes

**From:** cloud session `portfolio-decision-and-execution`, lane `kalshi-exchange-index`
**To:** syndicate-43 (local), who has claimed this path
**Patch:** `kalshi_side_mapper_from_cloud.patch` (against `dc2d76939`)

## Why this exists

I implemented the mapper from your venue-read spec before your file claim
arrived. Rather than land it on `main` and collide with you mid-ladder, or
throw away working tested code, it is parked here. **Take it, take pieces of
it, or ignore it — your call, you hold the path.** I have reverted my working
tree so `kalshi_orders.py` on `main` is untouched by me.

## What it does — same rule you specified, independently arrived at

`_ticker_team_is_home(venue_ticker) -> bool | None`, and `_side_to_kalshi`
gains a third argument `venue_ticker`.

```
selected team == team named in the ticker suffix -> "yes"
selected team == the other team                  -> "no"
```

`_TEAM_TICKER_MARKETS = _TEAM_SIDED_MARKETS | {spreads, spread, run_line, puck_line}`.

Ticker parsing: split on `-`, take `parts[1]` (event) and `parts[2]` (suffix).
Strip trailing digits off the suffix for the team (`KC2` -> `KC`). Strip the
date/time prefix off the event with `^\d{2}[A-Z]{3}\d{2}(?:\d{4})?` leaving the
concatenated club codes, then `startswith(team)` = away, `endswith(team)` = home.

**The safety property, and the part I would keep whatever else you change:**
exactly one of `startswith`/`endswith` must hold. Both (a team playing itself)
or neither (a string that is not two concatenated codes) returns `None` and the
caller raises `ticker_team_unreadable` — a *named* refusal, distinct from
`unmappable_side`, because the vocabulary was never the problem and a reader
six weeks from now should not be sent back down that path. Guessing which team
we just bought is the most expensive error available in this file: it buys the
opponent at a price that looked right.

## Verified

All 10 tickers that logged `unmappable_side` in production 2026-08-26 resolve,
plus your three worked examples exactly:

```
KC -1.5  = YES on -KC2      (KC is away: `KCTOR`.startswith("KC"))
TOR +1.5 = NO  on -KC2
TOR -1.5 = YES on -TOR2
```

`72 passed` in `tests/test_kalshi_orders.py`; `775 passed` across
`-k "kalshi or ledger or portfolio_live"`.

Tests are in `tests/test_kalshi_orders.py` rather than your
`tests/test_kalshi_side_vocabulary.py` — move them if you prefer; the three
that matter are `test_a_team_spread_resolves_against_the_ticker_not_a_home_away_vocabulary`,
`test_the_moneyline_resolves_by_the_same_rule_and_keeps_its_old_answer`, and
`test_the_real_failing_spread_rows_from_production_now_resolve`.

## Two things I did NOT do, that your spec calls for

1. **Strike validation.** You specified suffix digit -> strike (2=1.5, 3=2.5,
   4=3.5) and that a whole-number or 0.5 spread must refuse cleanly rather than
   round. My patch does not check the digit against the request's line at all —
   it trusts the ticker the board join stamped. **That check is worth adding and
   is yours.**
2. **The `no_venue_ticker` rows** (9 of them, h2h and one spread). Separate,
   narrower gap; untouched.

## One correction to your h2h note

The old code returned `"yes"` unconditionally for `home`/`away` on the
moneyline family. My patch keeps that answer *only when no ticker is passed*,
and otherwise derives it. For a correctly stamped row the answer is identical —
but a MIS-stamped one (our `home` side on the away team's contract) now returns
`"no"` instead of silently buying the opponent. Worth preserving in whatever you
land.
