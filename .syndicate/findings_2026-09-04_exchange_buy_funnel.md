# Why Kalshi and Polymarket place almost nothing — 2026-09-04, lane `mlb-rate-refit`

Measured end-to-end on production, 2026-09-04 ~14:0xZ. **Capital is not the
constraint and the engines are not the constraint.** Both were my prior and both
were wrong.

## The funnel, measured

    /api/portfolio/paper       943 board rows -> 3 positions -> $14.88
    refusals   market_family_excluded 554 | no_model_edge_pct 190
               below_min_ev_pct 187 | zero_kelly_stake 5 | below_min_stake 4

    PAPER2_PLAN_WRITTEN (13:59-14:01Z)
      venue       rows_in  positions  staked  sim_view_on  venue_priced  placeable
      kalshi          770          1   $4.76      550/770           521        0/1
      polymarket      514          3   $5.38      313/514           311        3/3
      novig           420          1   $6.58       62/420             0        0/1
      prophetx        462          1   $3.86       48/462             0        0/1

      vs_unrestricted_positions=4   vs_unrestricted_staked=$19.64

## What is NOT wrong

- **CAPITAL.** Live spend today: **$5.62 of a $150.01 day cap.** The cap has
  never bound. Adding money changes nothing.
- **THE ODDS/SIM ENGINES.** Kalshi priced **521 of 770** rows off its OWN book,
  Polymarket **311 of 514**. I hypothesised the venue plans were carrying
  sportsbook prices into exchange orders; `venue_priced` disproves it. novig and
  prophetx read 0 because novig has no direct feed BY DESIGN (its public CSV is
  anonymised) — a known capability gap, not a defect.
- **LIVE WIRING.** `SYNDICATE_EXECUTION_MODE=live` + `LIVE_ARMED=1` +
  `VENUE=kalshi,polymarket` on **live-odds-worker only** (the refresh-worker path
  is structurally paper-only). Real signed POSTs to both exchanges. Kalshi
  filled a real $5.62 order today.

**A correction worth keeping:** the web endpoint reports
`execution_mode: 'paper'`, and that is WEB'S OWN DEFAULT — web does not run
execution. Reading it as "live ordering is off" is a false negative, and it is
the `which service runs the code` trap in a new costume.

## What IS wrong, by leverage

### 1. EVERY STAKE IS 1/16 KELLY, NOT 1/4. A caveat that came due.

`bankroll_manager.py:210`

    staked_fraction = full_kelly_fraction * multiplier * credibility
                                            # 0.25       # 0.25, FLOORED

`credibility = _sample_credibility(settled_sample_size)` ramps 0.25 -> 1.0 at
**50 settled bets** (`_SAMPLE_SIZE_FOR_FULL_CREDIBILITY`). It is pinned at the
floor because **no caller anywhere passes `settled_sample_size_by_sport`** — the
argument exists on `run_portfolio_commit` (`pipeline/portfolio_commit.py:762`)
and on `commit_portfolio`, and a repo-wide grep for a caller supplying it returns
nothing.

The code says why, and the reason has EXPIRED:

    # S6 HOOK. Layer 2 rows carry no `historical_profile`, so this is empty
    # today and every market therefore sizes at `_MIN_SAMPLE_CREDIBILITY`
    # (0.25) -- which is correct while `settled_count` is 0 platform-wide.

`settled_count` is no longer 0. Settlement has **1,594 settled orders**
(book 662, kalshi 474, polymarket 224, prophetx 150, novig 84), and by sport the
dominant one has **616 settled at +5.76% ROI** -> credibility **1.00**.

**Effect: 4x every stake, on evidence rather than on a constant being edited —
which is exactly what the comment said should happen.** Today's book $19.64 ->
~$78. This is a `documented caveat is a scheduled defect` instance.

### 2. Kalshi builds orders it can never place

Six-plus per day, all TOTALS-family; `h2h` is fine (that is the $5.62 fill):

    rejected kalshi ticker=None mlb    totals     over 8.5  stake=8.40  no_venue_ticker
    rejected kalshi ticker=None soccer totals     under 2.5 stake=4.46  no_venue_ticker
    rejected kalshi ticker=None mlb    totals_alt over 5.5  stake=2.31  no_venue_ticker  (x3)

~$20/day of intended stake that cannot reach the venue. `KALSHI_BOARD_JOIN`
(13:59Z) matched 563 of 15,891 markets against 2,447 board rows; the unmatched
reasons include `recognised_but_no_board_market` 1,348,
`unreadable_title` 533 and `stat_not_in_market_vocabulary` 272. **Not yet
root-caused to the totals family specifically** — the price resolver and ticker
resolver are documented as built from ONE match set, so a priced-but-tickerless
position should be impossible and is worth understanding before it is patched.

### 3. `market_family_excluded` — 489 of Kalshi's 770 rows (63%)

The `mlb:player_prop` exclusion (`SYNDICATE_PORTFOLIO_EXCLUDED_FAMILIES`,
default `"mlb:player_prop"`), held shut by `#624` step 6's unmet ROI gate. The
single biggest filter on the board, and DELIBERATE.

### 4. Execution-stage losses on Polymarket, both defensible

- `pregame_price_too_high` x2 — **a HOLD, not a refusal.** The rule is
  two-dimensional: pregame+near-even HOLDS (no book on that side yet),
  pregame+cheap PLACES, live PLACES anything. The log says "it places once
  live"; both games were ~10h out. **I first reported this as "excludes every
  favourite" — that was wrong, and reading the code corrected it.**
- `_SlippageExceeded` x1 — planned 0.4545 (American +120) vs Polymarket ask
  0.555, drift +0.1005 against `SYNDICATE_EXECUTION_MAX_SLIPPAGE_DOLLARS=0.03`.
  A 3c tolerance is structurally tight for exchange trading, where the
  venue-vs-book price DIFFERENCE is the edge being captured. **A policy
  decision, not a defect.**

## The asks

| setting | now | proposed |
|---|---|---|
| `SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_ALL_VENUES` | 150.01 | 250 (user's stated 25% of a $1,000 bankroll) |
| `SYNDICATE_EXECUTION_MAX_SLIPPAGE_DOLLARS` | 0.03 | user decision |
| credibility wiring | floored 0.25 | wire the map (4x stakes) |

**Sequencing caution, stated before anything is changed:** wiring credibility is
a 4x real-money change on live venues. Do it FIRST and let the EXISTING $150 cap
bound the blast radius; do not raise the cap and the stakes in the same move, or
neither can be attributed if the result is bad.
