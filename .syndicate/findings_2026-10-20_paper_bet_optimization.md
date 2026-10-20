# Paper bet optimization: no selection rule beats taking every bet, and at $5-$10 the paper venue book goes broke

Lane `paper-bet-optimization`, session 6200a74b, 2026-10-20. The user asked: "once enabled start to figure out bet
optimization using the paper data we have". READ-ONLY on the fleet. Times are Central.

**Pre-registration.** `## Pre-registration` below was written at 9:27 AM CT, before any outcome in this study was
computed; the analysis first ran at 9:39 AM CT. It was not committed separately before the run. Its scratchpad copy
carries the earlier mtime. The rules and the falsifier were not changed after the run.

## Answer

- **Verdict, by the pre-registered rule: NO-GO on every selection rule.**
  - Population: the venue paper books live trades, `paper:kalshi` + `paper:polymarket`.
  - Out of sample, taking every bet returns **−12.0% ± 5.1 flat ROI** (807 bets, 183 events, dates 10-05..10-18).
  - No floor, ceiling, per-cell floor or sim-agreement filter beats it. Higher EV floors do WORSE:
    `ev_net >= 1` −18.3% ± 6.7, `>= 2` −18.0% ± 10.8.
- **Sizing: bigger bets lose faster, because the bets lose.** Replayed in submit order from a $465 bankroll over all
  917 settled venue bets:

| sizer | end bankroll | staked | P&L | ROI | max drawdown |
|---|---|---|---|---|---|
| flat $1 | $347.91 | $917 | −$117.09 | −12.8% | 26.8% |
| **band $5-$10 (live now)** | **$0** | $2,878 | −$465.03 | −16.2% | **100%** |
| quarter Kelly | $281.05 | $1,252 | −$183.95 | −14.7% | 40.9% |
| flat $5 | $0 | $2,849 | −$465.15 | −16.3% | 100% |

- **Under the CURRENT live regime it is undetermined, not shown to win.** The paper book has staked only Suggested
  rows since 2ecf7c2e (10-13 11:35 CT). Bets submitted from 10-13 return **−6.0% ± 7.0** (120 bets, 49 events);
  pregame only −0.2% ± 10.4 (79). That rules out neither a small edge nor the full −12%.
- **The data stopped growing when the fleet went live.** The newest paper order was submitted on 10-19 at
  10:55 AM CT. With `SYNDICATE_EXECUTION_MODE=live`, no paper book records new orders, so the evidence that would
  settle the current regime is not being collected. The engine is not learning from anything after that.

## Data (substrate: the local fleet, read-only)

- **Source.** `execution_ledger.full_history_orders()`, dumped under refresh-worker's environ at nice 19. 10,414 rows
  at 9:31 AM CT, fleet `e491c260`. The same count was read on 10-19 at 1:50 PM CT, consistent with no paper order
  since 10:55 AM CT that day.
- **Population.** Settled won/lost orders with `ev_pct`, deduped to one per `(venue, opening_key)`, earliest submit.
  - Primary: 917 bets, 226 events, 17 selected dates (10-02..10-18). paper:kalshi 586, paper:polymarket 331.
  - Secondary: paper:prophetx / paper:novig / unrestricted paper, 5,072 bets, 427 events, 18 dates.
  - In-play: 213 primary bets.
- **Returns** are per $1, net of the venue fee. The ledger's `pnl_dollars` is already net where a fee was recorded
  (checked row by row). 241 primary rows with no recorded fee get the venue's taker fee from
  `venue_fees.taker_fee_per_contract`.
- **Derived fields.**
  - `ev_net` = EV after that fee, from `p_fair = (1 + ev_pct/100) / decimal`.
  - Full Kelly uses the fee-inclusive win and loss returns.
- **Errors.** Every ± is one event-clustered standard error. The out-of-sample window is dates[3:], so the per-cell
  floor (S3) always has 3 or more training dates.
- **Reproduce.** `py -3 scripts/paper_bet_optimization.py <ledger.json> <repo root>`. The dump script is
  `dump_ledger.py` in this session's scratchpad; the same can be had from `ev_overstatement_decomp.py dump`.

## Segments (descriptive only, all dates; not selection rules, and not tested out of sample)

| segment | primary flat ROI | secondary flat ROI |
|---|---|---|
| paper:kalshi / paper:polymarket | −15.3% ± 5.5 (586) / −8.3% ± 6.5 (331) | |
| ncaaf | −6.3% ± 6.4 (392) | +0.4% ± 3.8 (3,007) |
| mlb | −23.2% ± 8.5 (361, **25 events**) | −10.3% ± 8.3 (533) |
| nfl | −4.9% ± 9.5 (92) | −5.1% ± 4.3 (670) |
| props / totals / spreads / h2h | −14.9 / −13.2 / −15.8 / **−2.3** | −5.8 / −3.2 / −0.8 / −3.4 |
| favourites (implied >= .5) / dogs | **−3.7% ± 5.5** / −17.4% ± 6.0 | −0.4% ± 3.4 / −4.3% ± 3.3 |
| `ev_net` 0-2 / 2-4 | −11.9% ± 5.1 (786) / −18.4% ± 9.5 (129) | −4.0 / −2.5 |
| pregame / in-play | −13.0% ± 5.2 / −11.9% ± 8.3 | −3.8 / −1.0 |

**Engine read** (`feedback_sim_improvement_is_the_secret_sauce`):
- **The venue books lose 3-4x the sportsbook-priced books** (−12% vs −2..−3%) on the same strategy. At the venue the
  edge after fee is 0-2% (786 of 917 bets), so the claimed EV is mostly inside the fee and the noise of the fair.
- **Underdogs carry the loss** in both populations. That is consistent with a favourite-longshot bias the fair does
  not absorb: the fair overrates longshots.
- **MLB props are the worst cell**, on 25 events only.
- **None of these was pre-registered as a rule**, so none is recommended as one. They are hypotheses for the next
  study, and they need data the fleet is no longer collecting.

## Recommendations

1. **Decide the band now, on the user's own threshold.**
   - **Risk of keeping it:** on the paper evidence the band loses about $0.30-$1.60 per bet, and up to 10x faster
     than sub-$1 stakes.
   - **Today's exposure:** about 0-2 live bets a day. The worst plausible day is capped by balance caps at ~25% of
     Kalshi capital, about $122.
   - **Revert:** remove the `REFRESH_WORKER__SYNDICATE_LIVE_STAKE_BAND` line and do a full down/up, or a code revert
     plus one refresh-worker TERM.
2. **Restart paper collection alongside live (highest value).** Book the paper venue books in live mode too, so every
   live-plan candidate keeps being graded at $0 cost. Without it, the current regime (−6% ± 7) cannot be resolved,
   and no optimizer, tuner or band can learn.
3. **Then re-run this study on the current regime only**, pre-registered with the segment hypotheses above:
   favourites vs dogs, h2h vs props, MLB props. At ~25 bets a day on both venues, ±3 points takes about 3 weeks.

## Pre-registration (as written at 9:27 AM CT, unchanged)

- **Population:** settled paper:kalshi + paper:polymarket orders, one per `(venue, opening_key)`. Secondary books are
  reported apart.
- **Coverage:** printed first.
- **Selection rules:** S0 all; S1 `ev_net` floor 0/1/2/3/4; S2 floor 0 or 2 with ceiling 6 or 8; S3 floor per
  sport x family, fit on training dates; S4 `sim_view != disagrees`. S5 (books quoting) was dropped: the ledger row
  does not carry it.
- **Sizing:** Z0 flat $1, Z1 band, Z2 quarter Kelly on $465, Z3 flat $5.
- **Validation:** walk-forward by date, with event-clustered SEs.
- **Decision:** a rule is recommended only if its out-of-sample flat ROI beats S0 by >= 2 SE AND is positive.
  Otherwise selection is NO-GO, and sizing is compared on log growth and flagged as noise-dominated.

## Forward test (pre-registered 2026-10-20 ~1:15 PM CT, BEFORE any forward row was read)

- **Why:** the first pass found the current regime (Suggested-only, from 10-13) undetermined. Paper books record
  again under live since `1006cb75` (lane `paper-alongside-live`, refresh-worker restarted 16:18:24Z). The
  forward window is bets submitted at or after **2026-10-20T16:18:24Z**.
- **Instrument:** `py -3 scripts/paper_bet_optimization.py <ledger.json> <repo> --forward 2026-10-20T16:18:24`.
  The code is fixed now; the decision rules are printed by the script itself.
- **Population:**
  - **Primary (H3):** venue books plus live orders, `paper:kalshi`, `paper:polymarket`, `kalshi`, `polymarket`.
    Settled, with `ev_pct`, one per `(venue, opening_key)`.
  - **Other books:** reported apart.
- **Hypotheses (from the first pass's segments, untested there):**
  - **H1:** in-play minus pregame flat ROI < 0. First pass: venue −16.8 ± 19.4, other books −6.2 ± 7.1.
  - **H2:** underdog minus favourite < 0. First pass, all dates: venue −13.7; current regime −3.8 ± 16.1.
  - **H3:** venue+live flat ROI vs 0. This decides the band.
- **Decision rules:**
  - **Fewer than 300 venue+live bets:** INSUFFICIENT, no decision.
  - **H3 ROI + 2 SE < 0:** recommend the user turn the $5-$10 band OFF.
  - **H3 ROI − 2 SE > 0:** band supported; widen only per cell.
  - **Otherwise:** no change.
  - **H1, per population:** if each side has 100+ bets and in-play is 2+ SE worse than pregame, propose a per-cell
    in-play EV floor through the min_ev tuner. Never a ban (learnings 2026-09-16).
  - **H2:** reported, not acted on alone.
- **Readings:** weekly on Mondays at 9:00 AM CT (scheduled task `paper-bet-optimization-forward`). Each reading
  appends to `.syndicate/log/<date>.md`. At ~25 venue bets a day, 300 arrives in about 2 weeks.
- **Exploratory, current regime from 10-13** (NOT part of the test; run before this section was written):
  - Venue books −6.0% ± 7.0 (120): pregame −0.2 ± 10.4, in-play −17.0 ± 16.4.
  - Other books +0.9% ± 4.0 (1,466): pregame +3.5 ± 5.5, in-play −2.8 ± 4.4.
