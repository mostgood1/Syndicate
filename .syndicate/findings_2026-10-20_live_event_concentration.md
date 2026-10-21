# Live per-game concentration: measured, mechanism, rule proposal (2026-10-20)

Lane `live-event-concentration`, session 8ac736cb, a side session of 332cb014 (live execution monitor). Todo `#711`.
**Design only. No code, no env change, no deploy.** Read-only reads on the WSL fleet at `nice 19`, under
refresh-worker's `/proc` environ, fleet HEAD `3567ff3bb`, 2026-10-21 00:40-00:52Z (7:40-7:52 PM CDT 10-20).
Probe scripts are in this session's scratchpad (`conc_probe2.py`, `conc_probe3.py`, `p4.py`) and in `/tmp/conc_8ac7/` on the fleet.

## Answer first

1. **Stacking is structural, not a one-night accident.** On the live Kalshi book, 62.5% of the stake sits in games
   with more than one position ($45.65 of $73.03). On paper:kalshi, the closest paper book to live, it is 54.5% over
   19 slates. In both books it comes mostly from **several lines on ONE outcome axis** (alt-spread ladders, adjacent
   totals, both sides of adjacent spreads), not from unrelated markets on the same game.
2. **A per-game budget already exists and the live sizing chain erases it.** `commit_portfolio` runs
   `apply_exposure_budgets` (`bankroll_manager.py:364`): a 5% per-game cap plus 0.5^i decay per extra leg, both on
   `stake_fraction`. Live stake fractions are about 0.002, so the 5% cap can never bind. The stake band then
   re-dollars every leg above the small-edge line from **FULL Kelly** (`live_stake_band.full_kelly_of`), which is
   read before the decay. Two legs on one game both land at $5-10. The 10-20 19:45 CDT Kalshi plan: `exposure.adjusted_groups=1` of 7.
3. **The stacking happens ACROSS executor passes, so a plan-only rule cannot fix it.** OKC@SAS margin legs were
   placed at 21:35Z (OKC +20.5, $10 @ -1329), 00:13Z (SAS +17.5, $10 @ -809; OKC +16.5) and 00:36Z (OKC -3.5). Each
   plan held at most one or two of them. The current plan sizes SAS +17.5 at $0.93, but the ledger holds it at $10.
   Each build sees a fresh line and so a new `position_key`, and D1 (`already_held_other_slate`) matches the key
   only. **The authoritative check has to be in the executor, against the held book.**
4. **Recommended rule (section 3):** (R1) one position per game AXIS, keeping the best net EV, enforced against held
   live orders; (R2) a per-game dollar cap on the venue, held book included (proposed $15 = 1.5 x band max). **No
   count cap.** The paper evidence for a count cap is mixed, and the dollar cap already bounds the risk.
5. **R1's paper evidence leans the right way but is not proven.** On 4 of 5 paper books the rows R1 would drop
   returned worse than the rows it keeps. No event-clustered 95% CI excludes zero. Argue this rule on risk
   (concentration and paying the fee twice on near-hedges), not on ROI.

## 1. Measured

**Population.** The execution ledger (live doc of 3,000 rows plus archive, 10,730 rows), `selected_date`
2026-10-02..10-20, status != `rejected`. One ledger row is one position on its slate. "Slate-event" means
(`selected_date`, `event_id`).
**Coverage:** paper books have 19 slates (paper:polymarket 18; ladders exist only on 10-20). **Live has two slates
in the window (10-19, 10-20) and 36 positions.** Every other live row predates October. On live, only 1 position is
graded, so live ROI is unreadable.

**Axis** (the outcome a leg rides on, `axis()` in `conc_probe2.py`):
- `margin|segment`: spreads, alt spreads, h2h and 3-way h2h of one game;
- `total|segment`: totals and alt totals;
- `teamtotal|side|segment`;
- `prop|stat|player|segment`.
Different players and different stats are different axes.

| book | positions / stake | slate-events (>1 pos) | stake in >1-pos games | same-axis stacks: rows, stake share | stacks holding BOTH sides |
|---|---|---|---|---|---|
| **live kalshi** (10-19..10-20) | 34 / $73.03 | 18 (4) | **62.5%** | 8 rows, **44.7%** | 2 |
| live polymarket (10-20) | 2 / $0.98 | 2 (0) | 0% | 0 | 0 |
| paper:kalshi | 930 / $10,709.61 | 476 (140) | 54.5% | 219 rows, 22.1% | 19 |
| paper:polymarket | 453 / $6,566.74 | 289 (67) | 45.3% | 85 rows, 17.9% | 13 |
| paper:novig | 1,488 / $10,349.79 | 719 (378) | 69.9% | 791 rows, 51.6% | 142 |
| paper:prophetx | 2,232 / $16,280.87 | 807 (559) | 83.8% | 1,601 rows, 67.5% | 242 |
| paper (unrestricted; 785 rows are the same bet at another book) | 4,821 / $41,602.52 | 1,437 (895) | 88.7% | 2,680 rows, 59.2% | 401 |

**The four live multi-position games (10-20, Kalshi):**
- **OKC@SAS, 13 positions, $32.17.**
  - Margin axis, 4 legs: OKC +20.5 $10 @ -1329 (ev 0.90%, resting); SAS +17.5 $9.79 @ -809 (ev 1.71%); OKC +16.5 $0.89 @ -809; OKC -3.5 $0.41 @ +144 (ev 4.75%).
  - OKC +20.5 and SAS +17.5 are opposite teams getting points. At most one of them can lose: $20 at risk to win about $2.
  - Plus 8 props on different players (axes) and 1 total.
- **MTSU@FIU:** under 44.5 $5.17 + under 45.5 $0.48. Same axis, same direction.
- **Missouri St@Delaware:** DEL -3.5 $5.50 + MoSt +2.5 $0.41. Opposite sides of adjacent lines; both lose only on DEL by exactly 3.
- **PHI@NYK:** 3 props on 3 players, all different axes. The 6 spread lines in the plan log were refused after kickoff and never reached the ledger.

**Held book across slates (live):** no live event is held on more than one slate in the window. The cross-slate
case D1 covers has not happened live yet. Today's stacking is all within one slate, across passes.

**By sport (paper:kalshi):** MLB 96% of stake in multi-position games (prop-heavy), NCAAF 44%, NFL 54%, NBA 82%,
soccer 0%.

## 2. Counterfactual rules on the ledger (ordered by `ev_pct`; realised = graded rows only)

| book | R1 axis dedupe drops | R1 kept ROI | R1 dropped ROI | dropped - kept, 95% CI (event-clustered, 2,000 draws) | R2 count<=3 drops (dropped ROI) |
|---|---|---|---|---|---|
| live kalshi | 5/34 pos, **$21.57 (29.5%)** | n=1 | n=0 | - | 10/34, $24.64 |
| paper:kalshi | 124/930, $1,440.93 (13.5%) | -2.3% | -21.0% | -18.8pp [-46.3, +6.8] | 250, $1,737.72 (**+8.5%**) |
| paper:polymarket | 51/453, $770.67 (11.7%) | -12.6% | -30.4% | -17.8pp [-50.6, +16.3] | 61, $786.14 (-8.4%) |
| paper:novig | 461/1,488, $3,315.65 (32.0%) | -6.5% | -13.1% | -6.6pp [-22.2, +9.5] | 206, $1,149.89 (-22.2%) |
| paper:prophetx | 1,011/2,232, $6,924.96 (42.5%) | -6.5% | -3.1% | +3.4pp [-9.9, +15.9] | 517, $2,742.69 (+2.1%) |
| paper | 1,760/4,821, $16,871.25 (40.6%) | -0.2% | -7.1% | -7.0pp [-19.5, +5.0] | 1,892, $16,542.20 (-4.2%) |

- **R1 (keep the best net EV per axis)** points the right way on 4 of 5 books. On live 10-20 it drops exactly the
  two max-band heavy favourites (OKC +20.5 and SAS +17.5 at 0.9-1.7% EV). It keeps OKC -3.5 at 4.75%. The legs at
  max are those with the THINNEST edge, because the band reads full Kelly, and full Kelly is large at short prices.
  This is the hindsight version (the best leg over the whole day). The executor only knows what is already held,
  so it keeps the FIRST leg; see T5 for that replay ($11.98 refused, not $21.57).
- **R2 (a count cap by EV rank)** is mixed: the dropped rows won +8.5% on paper:kalshi and +2.1% on prophetx. A
  count cap mostly cuts props on different players, which are not one bet. **Not recommended.**
- The paper populations are paper2's venue-scoped books, so they are the live candidate set. They did not run
  under live's band, compounding, small-edge line, or 0% floor, so their dollar shares are not live's.

## 3. Rule proposal

### 3.1 The rule

- **R1: one position per game axis per venue.** The axis key is a pure function of the DecisionRecord key
  (`event_id | market | segment | player | line | side` -> `event_id | axis(market) | segment | player`).
  - Inside one plan: keep the leg with the highest `ev_pct_net_of_fee` and refuse the others as
    `same_axis_lower_ev`. This is the same criterion Suggested uses for one side per line
    (`layer2_board._stamp_suggested`, :3740), so the rule extends that one instead of adding a new idea.
  - Against the held book: if a LIVE order on the same venue and axis may be held (`_blocks_a_new_attempt`:
    filled / submitted / failed), a new leg is refused as `axis_held_live`. The executor cannot unwind the held
    leg, so the first one in stands. This generalises D1: the same `position_key` implies the same axis.
- **R2: a per-game dollar cap per venue.** Let `held(E)` be the stake of live orders on event E that may be held
  (same predicate, open positions only, any slate) and `cap` = `SYNDICATE_LIVE_EVENT_MAX_DOLLARS` (proposed $15).
  - The order is placed at `min(band stake, cap - held(E))`.
  - If that room cannot buy one contract at the order price, the leg is refused as `event_exposure_cap`.
  - Legs are taken in plan order (net EV desc), so the best leg on a game is sized first.
  - The cap is on dollars AT RISK, which on these venues equals the stake. Heavy favourites therefore use up the
    room fastest, and that is intended.
- **What it is not:** no sport, market or family exclusion, and no count cap. A game with one leg is never
  touched. Every line is still judged on its own EV; it only competes with lines that ride on the same outcome of
  the same game (`learnings.md`, "every line is its own decision").

### 3.2 Where it runs (both places, one module)

- New module `syndicate/features/shared/event_concentration.py` holds:
  - `axis_key(row)`;
  - `dedupe_plan(positions)` (R1 within a plan);
  - `held_exposure(venue, event_id)` and `held_axes(venue, event_id)` (the ledger read, beside `held_position_for`
    in `execution_ledger.py`);
  - `concentration_verdict(request, held)`.
- **Plan pass, provisional:** `pipeline/portfolio_commit.commit_live_venue_plan`, after `apply_live_stake_band`.
  It runs R1 over the plan, and R2 over the plan plus a held read at commit time.
  - Refusals land in the plan's `refusals` tables, so `sum(refusals) + positions == rows_in` holds.
  - This keeps the plan honest about what will be placed. It is stale by up to one build.
- **Executor pass, authoritative:** `pipeline/execute_portfolio._run_execution`, after
  `REFUSED_HELD_OTHER_SLATE` (D1) and BEFORE `TRIMMED_TO_ORDER_CAP`.
  - It runs R1 against held axes and R2 against `held(E)`, plus the orders this loop already placed (counted
    locally, as `used` is for `spent_today`).
  - Log lines `REFUSED_SAME_AXIS_HELD` / `TRIMMED_TO_EVENT_CAP` / `REFUSED_EVENT_CAP`, all named. Nothing is written
    for a refusal (the D1 contract).
  - The executor is the only layer that sees the passes accumulate (finding 3).
- **Flag:** `SYNDICATE_LIVE_EVENT_CONCENTRATION=off|shadow|on`.
  - Absent = off = today's behaviour.
  - `shadow` logs `CONCENTRATION_SHADOW` verdicts and changes nothing.
  - Unknown values map to off; anything else would be permissive-by-default in reverse, so say it in the code.
  - Paper books are unchanged: live venue plans only.
- **Claims a build needs:**
  - `pipeline/portfolio_commit.py` `commit_live_venue_plan` (lane `compounding-bankroll` holds the compounding step;
    the band call site was returned to it);
  - `pipeline/execute_portfolio.py` `_run_execution` (lane `future-dated-live-orders-scope` holds D1; the
    insertion point sits right after it);
  - `execution_ledger.py` for the held read (`future-dated-live-orders-scope` holds `held_position_for`).
  - Ask both by message before building.

### 3.3 Fit with the one-engine DecisionRecord (`#709`)

- `axis_key` derives from the record key, so it is a field of the record (`identity.axis`), not a parallel identity.
- The concentration step is one more sizing layer that writes into `size`:
  `concentration: {axis, held_event_dollars, verdict: kept|same_axis_lower_ev|axis_held_live|trimmed_event_cap|event_cap, room}`.
  This is migration step 4 ("every layer records its effect").
- R1 inside a plan is a `verdict` the worker can compute.
- The held-book half needs the ledger at order time, so it stays in the executor in every design. Record that as
  the one per-destination verdict the worker cannot own.

## 4. Interactions

- **Stake band ($5-10 on FULL Kelly):**
  - The band undoes `apply_exposure_budgets`' decay (finding 2), and R2 is the replacement for that decay on live.
  - The full-Kelly read is also why heavy favourites sit at max: OKC +20.5 at -1329 had `full_kelly` near the 0.05
    `kelly_at_max` on a 0.9% edge. R1 removes those when a better-EV leg exists on the axis.
  - **The heavy-favourite cap `df57cbbd` is built and OFF on the fleet** (`SYNDICATE_LIVE_BAND_FAVOURITE_CAP`
    absent, read 00:45Z). With it on, OKC +20.5 at -1329 would have been refused (< -1000) and SAS +17.5 at -809
    capped at $5. **That is a separate one-key user decision and the cheaper first step.** The audit's
    "band should read applied Kelly" (`#709` step 4) would also shrink these legs; R2 bounds the game either way.
  - The R2 cap is set relative to the band: $15 = one max leg plus one minimum leg. If the band changes, the cap
    should be re-read, so state it in `SYNDICATE_LIVE_EVENT_MAX_DOLLARS`, not as a multiplier hidden in code.
- **Small-edge line (0.001):** 12 of 14 positions in the 10-20 Kalshi plan were left at one contract
  ($0.44-0.93). These rarely move R2, but they DO occupy axes under R1. A one-contract leg held first blocks a
  later band-size leg on the same axis (`axis_held_live`). Alternative: R1-held only counts legs >= the band
  minimum. **User decision; recommend counting every held leg** (a contract on the axis is exposure on the axis).
- **Compounding (`on`, `floor_one_contract`) and balance caps (`on`):**
  - R2 is a dollar ceiling inside the existing ones: order cap 5% of capital, day cap 25%. Order of application:
    band -> R2 room -> order-cap trim -> `check_order`.
  - Proposal: `cap = min(SYNDICATE_LIVE_EVENT_MAX_DOLLARS, 10% x venue capital)` once capital is known.
    Unknown capital -> the dollar figure alone (it is a ceiling and only shrinks stakes).
  - With compounding able to grow capital past the $1,000 ceiling (`#702`), the fraction keeps the cap honest.
- **0% live EV floor (ee87954d):**
  - The floor adds `ev_only_extra` rows, more rungs on the axes Suggested already covers. R1 makes them compete
    with the Suggested rung on net EV, so a floor row survives only as the axis's best price. The floor still
    widens which axes can be bet; it no longer adds a second leg to a held one.
  - **Its stop rule (ROI < -5% after 100 settled 0-2% rows) gets a smaller, cleaner population.** Say so in the
    floor's lane before enabling, because it slows the stop rule's 100-bet clock.
- **D1 (`already_held_other_slate`):** unchanged and checked first. R1-held is its superset for live, so D1's
  refusal count should not change once R1 is on. That is a no-op check for the deploy reading.
- **D3 / after-kickoff block / kalshi-exit-path:** `held(E)` counts resting (`submitted`) orders, which D3 cancels
  at kickoff. An exited position (`kalshi-exit-path`) should free its room. Read the exit rows in `held_exposure`
  or the cap will be over-counted after an exit. Owned by `kalshi-exit-path`; ask.

## 5. Reachability test design (before any correctness test)

- **T0, off != on (plan):** the OKC@SAS fixture (4 margin legs, 8 props on distinct players, 1 total).
  - Flag off -> 13 positions.
  - Flag on -> 10: the 3 lower-EV margin legs refused `same_axis_lower_ev`, OKC -3.5 kept, every prop kept.
  - `sum(refusals) + positions == rows_in` holds in both.
- **T1, executor held axis:** a ledger holding a LIVE `filled` OKC +20.5 on event E, and a plan with SAS +17.5 on E.
  - On -> `refused == {"axis_held_live": 1}`, submitter called 0 times, no ledger row written.
  - Off -> submitted.
  - Same fixture with the held row `rejected` -> submitted (the `_blocks_a_new_attempt` predicate, not "any row").
- **T2, event cap trim and refuse:** cap $15.
  - Held $10 on E plus a new $8 leg on a different axis -> placed at $5.00 (`TRIMMED_TO_EVENT_CAP`).
  - Held $14.60 plus a leg priced 0.47 -> refused `event_exposure_cap` (room $0.40 < one contract).
  - The second order in the same loop sees the first (local counter, not a re-read).
- **T3, independence (the every-line rule):** 20 events with one leg each, mixed sports and markets -> on == off,
  byte for byte. Property: no verdict ever refuses the only leg of an event.
- **T4, axis classifier gate (model-engine standard style):** every `market` string on the live and paper ledgers
  plus the Kalshi/Polymarket series maps must map to a non-`other` axis. The test exits non-zero on a new market
  that lands in `other`, so a new market can never be silently ungrouped.
- **T5, replay before deploy (chronological, as the executor would have seen it):** replay the 10-20 live Kalshi
  ledger in `submitted_at` order through `concentration_verdict`. Worked by hand from `p4.py`'s output:
  - **R1 (held-first):**
    - OKC +20.5 (21:35Z) is first on its axis and stands.
    - SAS +17.5 $9.79, OKC +16.5 $0.89 and OKC -3.5 $0.41 are refused.
    - MTSU under 45.5 $0.48 and MoSt +2.5 $0.41 are refused.
    - Total: 5 rows, $11.98.
  - **R2 at $15, OKC@SAS** (held legs count their FILLED stake, new orders their requested stake; pinned by `tests/test_event_concentration.py::test_T5_replay_of_the_10_20_book`):
    - Held reaches $12.34 filled by 21:42Z.
    - Keldon Johnson threes ($6.73 asked, 23:07Z) is trimmed to $2.66.
    - The next 4 one-contract legs ($2.25 filled) are refused.
    - OKC@SAS ends at $15.00, down from $32.17.
  - **Kalshi 10-20 total:** $73.03 -> $54.97.
  - **As built:** a game's FIRST leg is never capped by R2 (concentration needs a second leg; the order cap bounds the first).
  - **Held-first keeps the WORST-EV leg on OKC@SAS:** OKC +20.5 @ -1329 at 0.9% was placed first. The plan-level R1
    only picks the best leg among the legs in one build. This is the strongest argument for doing decision 4 (the
    favourite cap) first or with it.
  - The deploy's `--expect` is these counts. After the first live slate with the flag on, read
    `REFUSED_SAME_AXIS_HELD`, `TRIMMED_TO_EVENT_CAP` and `REFUSED_EVENT_CAP` counts from the live-odds-worker log.

## 6. Decisions owed (user)

1. Build R1 + R2 behind `SYNDICATE_LIVE_EVENT_CONCENTRATION` (shadow first), or R1 only.
2. R2 cap: $15 (recommended) / $10 (one max leg per game) / other, and whether to add the 10%-of-capital term.
3. Do held one-contract legs block an axis (recommended: yes)?
4. Separately and cheaper: turn on the heavy-favourite cap `SYNDICATE_LIVE_BAND_FAVOURITE_CAP=on` (built, `df57cbbd`).
   This needs a refresh-worker env change plus a restart: deploy locks, and the user's yes.

## 7. Corrections to the brief

- In the ledger, the OKC@SAS $10 @ -1329 leg is **OKC +20.5** (`spreads_alt away 20.5`), not SAS +20.5. The $10 @
  -809 leg is SAS +17.5. They are opposite teams, so the pair is a middle, not a ladder.
- The PHI@NYK six-spread stack was refused after kickoff and never reached the ledger. The live PHI@NYK positions
  are 3 props on 3 players: different axes, untouched by R1.
