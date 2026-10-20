# Paper ladder: Kalshi/Polymarket paper books below today's floor, so the floors can be reconsidered on evidence

Lane `paper-alongside-live`, session f8387262, 2026-10-20. Times in Central.

**Decision.** The user, relayed by session b87af0fc, answered "Let Kalshi/Polymarket paper books record a wider selection, paper only?" with **"yes - but we should reconsider the floors"**. Live selection, placement, caps, compounding and the $5-$10 band stay unchanged.

**Pre-registration.** This file was written at 1:44 PM CT (18:44Z), before any ladder row existed. The code that writes the rows had not reached the fleet. The rules below must not change after the first ladder row is read. A change needs a new dated section that says why, and it applies only to rows submitted after it.

## Why

- Since 11:18 AM CT the venue paper books (`paper:kalshi`, `paper:polymarket`) have recorded again beside live (1006cb75).
- Their plans had **0 positions in all 5 builds** to 1:23 PM CT. Kalshi showed 5/5 at 0 and Polymarket 5/5 at 0, refused as `below_min_ev_pct`, `_net_of_fee` and `zero_kelly_stake`.
- Those are the same gates the live plan uses. The current floors therefore produce no evidence about themselves: nothing below them is ever recorded.

## What is recorded (code: `syndicate/features/shared/paper_ladder.py`)

- **The book.** A separate paper book per venue: `paper:kalshi:ladder` and `paper:polymarket:ladder`.
  - `mode = paper`, flat **$1** stake (`stake_basis = flat_1`).
  - Off switch: `SYNDICATE_PAPER_LADDER=off`.
- **Eligible rows.** Shortlist rows are eligible when the board flagged them Suggested, or refused them **only** for `ev_below_min` / `ev_net_of_fee_below_min`.
  - Every non-EV Suggested gate stays: opportunity lane, implausible book, fair method / one-sided fair, stale quote, single-book fair.
  - So do the in-play market-fair refusal, valid sizing inputs, and one side per line (the better net EV).
- **Pricing.** Rows are priced at the venue by the same resolvers, in the same build, as the venue's paper2 and live plans.
- **The complement.** The book holds exactly what that build's paper2 plan did **not** stake, plus no bet the `paper:<venue>` book already holds for the slate.
- **Bands.** Each row is tagged by net-of-fee EV at the venue price:
  - `ge2`: >= 2%
  - `1to2`: [1, 2)
  - `0to1`: [0, 1)
  - `m1to0`: [-1, 0)
  - Below -1% is not recorded.
- **Tags on every ladder row:** `ev_band`, `ev_net_pct`, `ladder_reason` (`suggested_not_staked` | `below_suggested_floor`), `stake_basis`, `price_source`, `selection = ladder`, `season_phase`, `paper_alongside_live`.

## Never live (tested in tests/test_paper_ladder.py)

- **Plans unchanged.** With the ladder on or off, the live plan, the paper2 plan and the unrestricted plan are identical.
- **Paper only.** `run_execution(book="ladder")` is refused in live mode (`ladder_is_paper_only`). With `SYNDICATE_PAPER_ALONGSIDE_LIVE=off` the inline refusal stands. No submitter is built and no venue is read.
- **No double count against live.** Live rows are `mode=live` under the bare venue name, and every live cap / held-position / unreconciled read filters `mode=live`.
- **The tuner path.** Rows below the current floor may reach live selection **only** through the min_ev tuner's bounded, shadow-first path, and only after that lane pre-registers how it reads them.
  - Requested of that lane at 1:30 PM CT: exclude `:ladder` venues by default (`ladder_not_pre_registered`), with an explicit opt-in.
  - Until it lands, its nightly shadow pass can include ladder rows by substring. That is shadow only: `SYNDICATE_MIN_EV_TUNER` is not `apply`.

## How the existing pre-registered readers see it

- **Forward test (16888bb6, `scripts/paper_bet_optimization.py --forward`).**
  - Unchanged. It selects venues by EXACT name (`paper:kalshi`, `paper:polymarket`, `kalshi`, `polymarket`; secondary `paper:prophetx`, `paper:novig`, `paper`), and no ladder venue is in any list (tested).
  - Its H1-H3 populations are what they were. The ladder adds no row to them.
- **Paper bet optimization study.** Same exact-name selection. Unaffected.
- **min_ev tuner.** See above. It must exclude ladder rows until its lane's own pre-registration.

## Readout and decision rule (`scripts/paper_ladder_readout.py`)

- **Population.**
  - Settled (won/lost) paper rows in `paper:<venue>` (band `venue_book`) and `paper:<venue>:ladder` (by `ev_band`), submitted from 2026-10-20T16:18:24Z.
  - One row per (venue, position_key, selected_date): the venue book wins over the ladder.
- **Per venue x band.**
  - Flat ROI per $1 net of the recorded fee, with an event-clustered SE.
  - Mean same-book CLV (`closing_mark.clv_pct` with `close_book_scope = same_book`).
  - The coverage line: settled bets, dates, events.
- **Rule**, applied per venue and per band below the floor (`1to2`, `0to1`, `m1to0`):
  - **CANDIDATE** to lower that venue's floor to the band's lower edge, only if:
    - >= **100 events**, and
    - flat ROI > 0 and >= **2 SE** above 0, and
    - mean same-book CLV > 0.
  - **AGAINST** if ROI is >= 2 SE below 0.
  - Otherwise **NO CHANGE**, keep collecting.
  - For `venue_book` and `ge2`: ROI >= 2 SE below 0 reads **AGAINST THE CURRENT FLOOR**, cross-checked with the forward test's H3.
- **Multiplicity.** There are 6 below-floor tests (2 venues x 3 bands) per readout. At 2 SE one-sided, about 2.3% each, so about 13% chance of one false ROI candidate per readout. That is why CLV must agree and 100 events are required.
- **Sport x market x season-phase cells** (`--cells`) are DESCRIPTIVE ONLY. No cell-level rule is pre-registered.
- **Cadence.**
  - Weekly beside the forward test, Mondays 9 AM CT from 2026-10-26.
  - A CANDIDATE is a recommendation to the USER, never an automatic change.
  - Any floor change goes through the user, or through the tuner's bounded path.
- **Expected volume.** Unknown until the first builds. Report rows per band per day in the first readout before anything else.
