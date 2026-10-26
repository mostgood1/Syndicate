# min_ev tuner — backtest on the fleet's production ledger (2026-10-19)

Lane `min-ev-tuner-shadow`. Session b98807bc.

## Data — what this rests on

Read 2026-10-19 ~18:16Z from the fleet: `execution_ledger.full_history_orders()` run inside WSL against
the refresh-worker's keyvalue state (`redis://127.0.0.1:6379/0`, reports root
`/home/amyn/syndicate-prod/data/reports`), checkout `~/Syndicate` at `71631544`. 10,414 rows (live doc +
`execution_ledger_archive/orders_2026-10.jsonl`), all `status=filled`; 9,150 graded.

| venue | mode | rows | settled | settled with ev_pct | settled with any CLV | dates |
|---|---|---|---|---|---|---|
| kalshi | live | 421 | 420 | **0** | 0 | 08-06..09-27 (32) |
| polymarket | live | 132 | 132 | **0** | 0 | 08-25..09-27 (23) |
| paper:kalshi | paper | 928 | 769 | 769 | 398 | 10-02..10-18 (17) |
| paper:polymarket | paper | 453 | 407 | 407 | 184 | 10-02..10-18 (17) |
| paper (all books) | paper | 4,789 | 4,045 | 4,045 | 3,000 | 10-02..10-18 (17) |
| paper:novig / :prophetx | paper | 3,691 | 3,377 | 3,377 | 3,003 | 10-02..10-18 |

- The 552 live rows are the 2026-10-02 `venue_rebuild` (one row per settled market, no plan fields):
  results with no `ev_pct`, so **no EV cut line decided them and they are not evidence about one**. The
  tuner skips them as `no_ev_pct`. The first real live order (10-19 16:59Z) is not settled yet.
- **So the tuner's evidence today is paper venue orders only: 1,176 settled rows over 17 dates.**
  Same code as live up to the submit, priced at the venue's own quote; fills assume the quoted price.
- Same-book CLV coverage on those rows, by venue x sport: kalshi ncaaf 182/359, kalshi mlb **49/266**,
  polymarket ncaaf 119/245, kalshi nfl 81/109, polymarket mlb **1/95**, polymarket nfl 1/30. MLB props on
  both venues are close to unclosable: those cells cannot move until that changes.

## Finding 1 — ROI does not rise with EV here either (learnings 2026-09-29 STANDING, third measurement)

ROI and same-book CLV by EV band, event-clustered t (`cell_evidence`):

| population | [2,3) | [3,4) | [4,5) | [5,7) |
|---|---|---|---|---|
| all paper books, ROI % (t) | +0.4 (0.07) | +2.1 (0.35) | −8.3 (−1.33) | −9.8 (−1.12) |
| all paper books, CLV % (t) | +1.24 (7.3) | +1.39 (8.6) | +1.73 (8.1) | +1.56 (6.0) |
| kalshi venue, ROI % | −4.9 | +13.1 | −5.9 | −10.3 |
| polymarket venue, ROI % | −25.3 | −13.2 | −18.1 | +8.3 |

No single band's ROI is significant; the ordering is the read. CLV is positive and highly significant in every band.
CLV runs flat with EV (1.2–1.7), so the extra claimed EV above ~4% is not showing up at the close either.
**Engine read:** claimed EV above ~4% is overstated relative to both the close and the result, which is
an overconfidence signature in the EV the board stamps, not a threshold problem.

**Design consequence (shipped):** the tuner does NOT decide on the whole cell. A cell lost by its 5%-EV
rows would otherwise raise the cut and remove its 2%-EV rows, the better ones. It decides on the
**marginal band** `[cut, cut + 1.0)`, the rows a one-step move actually stops (or starts) taking. Pinned by
`test_a_cell_lost_by_its_high_ev_rows_does_not_raise_the_cut`, mutation-checked (deciding on the whole cell
fails it).

## Finding 2 — at today's volume the tuner proposes nothing, and that is the honest output

Walk-forward replay (`scripts/min_ev_tuner_readout.py replay`): 18 nights (night D sees orders graded
before D 12:00Z), state carried forward. **0 moves.** Final: 60 cells, all `hold / insufficient_events`.
The largest marginal band holds 17 events (polymarket ncaaf h2h) against a 40-event minimum.

Whole-cell decision (before the marginal-band change), for comparison: also 0 moves, and still 0 at
z=1.5 / min 25 events. NCAAF cells there showed ROI −6..−15% (not significant) with CLV +1.4..+2.2
(t 4.3–5.0), which held as `only_clv_significant`.

Rough time to first possible move: one cell's marginal band gains about 1–2 events a day at current paper
volume, so expect **weeks, not days**. The one-week shadow readout will most likely show holds. What it
CAN show is that the job runs nightly, persists, and accumulates evidence correctly.

## Parameters as shipped (all env-overridable, bounded, refuse-not-clamp)

step 0.5, floor 1.0, ceiling 6.0, band 1.0, trailing 150 events, min 40 events, min 30 CLV events, cooldown
20 new events, z 2.0, CLV scope `same_book`, evidence modes `live,paper`, run hour 12Z. Mode
`SYNDICATE_MIN_EV_TUNER` = off / shadow (default; absent and unrecognised resolve here) / apply.

## Not done (decision owed by the user)

- **Apply wiring.** `effective_min_ev_pct` exists and is tested but nothing calls it. The cut lines are in
  `portfolio_commit.py:1102-1108` (claimed by lane `published-negative-ev`) and
  `polymarket_us_orders.py:1251`. Wiring them needs that lane's loan plus the user's apply decision.
- **Cell granularity.** If weeks are too slow, pooling `market` into its family (game_line / game_total /
  player_prop) inside venue x sport x phase roughly triples events per cell. It is still a threshold and
  never an exclusion. This is a user choice: the brief named market-level cells.


## CORRECTION 2026-10-19 19:4xZ -- production's cut line is 0.0, not 2.0, and the band was anchored wrong

**What I assumed:** that the base cut was `DEFAULT_MIN_EV_PCT = 2.0`. Both the brief and the ledger survey said so, and both
were wrong for the fleet. **What production read:** the first nightly line on the fleet, `2026-10-19T19:25:36.467Z [min_ev_tuner]
MIN_EV_TUNER mode=shadow ... base=0.0`. refresh-worker carries `SYNDICATE_PORTFOLIO_MIN_EV_PCT=0`, the user decision of
2026-09-16 (`state.md`, beside the family-exclusion removal). There is no stored settings key on the fleet's Redis, so the env wins.

**Consequence for the design:** anchored at the configured 0.0, the marginal band `[0, 1)` held 0-5 events in every cell. Rows
reach the ledger at EV >= ~2 because other gates bind first (fair noise, net of fee, the shortlist). So the tuner could NEVER move:
holds by construction, not by evidence. Also, the shipped floor of 1.0 sat above the base, so a first raise to 0.5 would have
been refused as out of bounds.

**Fixed (commit below):**
- The band is anchored at the cell's EFFECTIVE cut: max(configured cut, 5th-percentile EV taken).
- A raise steps from that cut.
- A lower is proposed only when the configured cut is the binding gate (`cut_not_binding` otherwise).
- The floor defaults to 0.0.

Mutation-checked: anchoring back at the configured cut fails 2 tests.

**Replay at base 0.0 with the fix:** still 0 moves over 18 nights, but now for evidence reasons. Two NCAAF cells have 45-46 events in
their band and hold only on CLV sample (18 and 28 of 30): kalshi ncaaf spreads band [3.79, 4.79) ROI -12.6% (t -0.64), CLV +1.97
(t 4.2); polymarket ncaaf totals band [3.34, 4.34) ROI -5.3% (t -0.28), CLV +1.65 (t 4.5). Both would hold as `only_clv_significant`
once the CLV sample fills. So the earlier "weeks, not days" estimate was too pessimistic for those two cells, and still right for
the rest.


## UPDATE 2026-10-19 ~20:3xZ: the cut is now graded in FLAT UNITS (per bet), not dollars

`findings_2026-10-19_ev_overstatement_decomp.md` (lane ev-overstatement-decomp) found that from 10-05, 58-69% of every EV band's
DOLLARS are sim-added stake. The sizer stakes the raw sim at full weight with no fitted profile, while the sim's fitted weight on
these orders is w = -0.27 [-0.78, +0.18]. So a dollar ROI grades the sim's SIZING, not the cut line. Built here on that
suggestion: `roi_pct` / `roi_t`, the numbers `decide` reads, are flat units by default (`SYNDICATE_MIN_EV_TUNER_ROI_BASIS`
= flat | dollars; absent/unrecognised = flat). Dollar ROI and EV-only dollar ROI (net of `sim_share_of_stake`) are kept as readout.
Tests: 24; the reachability test (dollars raises, flat does not, on a cell lost only by sim-added stake) fails if the default is
mutated to `dollars`.

Replay at base 0.0, flat basis: still 0 moves (sample-limited, as before). The basis matters where it should:
polymarket ncaaf totals band [3.34, 4.34), 46 events: **flat +9.6%, EV-only dollars +11.6%, all dollars -5.3%**. The sim's
stake alone turned a winning band into a losing one in dollars.


## PRE-REGISTRATION 2026-10-20T18:33Z: how the tuner will read the EV-band paper LADDER (written BEFORE any ladder row settled)

Source: lane paper-alongside-live books Kalshi/Polymarket rows the CURRENT floor refuses, paper only, $1 flat. They land in the ledger as
`mode=paper`, `venue=paper:<kalshi|polymarket>:ladder`, carrying `ev_band` (ge2 | 1to2 | 0to1 | m1to0), `ev_net_pct` (net-of-fee EV),
`ladder_reason` and `ev_pct`. User decision relayed 2026-10-20: "yes - but we should reconsider the floors".

**Until a ladder reader is built, the tuner SKIPS every ladder row** (`ladder_not_pre_registered`), unconditionally and with no
opt-in flag. Untagged, ladder rows would drag each cell's effective cut down and land in the RAISE band.
Test: `test_ladder_rows_are_skipped_and_never_move_the_effective_cut`, mutation-checked.

**The rule the reader will implement, fixed now:**
1. **Knob.** A second per-cell setting: the NET-of-fee floor (`_min_ev_net_of_fee_pct`, default 0). It is the binding gate on the venues;
   the 2026-10-19 23:14Z live kalshi plan refused 9 of 12 rows `below_min_ev_pct_net_of_fee`. The gross `min_ev_pct` knob is unchanged.
   Bounds [-1.0, +3.0]; step 0.5; shadow first, applied only via `SYNDICATE_MIN_EV_TUNER=apply`.
2. **LOWER** a cell's net floor one step only when the ladder rows in the band IMMEDIATELY BELOW it (`ev_net_pct` in [floor-1, floor))
   have flat-unit ROI AND same-book CLV both with t >= +2.0, event-clustered, >= 40 events and >= 30 CLV events, and >= 20 new events since
   that cell last moved.
3. **RAISE** of the net floor is NOT pre-registered here. The ladder only holds rows BELOW the floor, and the main book does not store
   `ev_net_pct` on orders today. It is registered once the main book carries `ev_net_pct`, from the taken rows' marginal band, mirroring
   the gross rule.
4. **Dedupe.** A bet in both the ladder and the main book (same venue family + `position_key` + `selected_date`) counts ONCE, in the main
   book, since that book took it. A bet only in the ladder is below-floor evidence.
5. **Unchanged guarantees.** Cells are venue x sport x market x season_phase; phases are never pooled and unknown is never regular. No family
   or market exclusion: a floor moves within its bounds and every row is still judged on its own EV. The ladder's own `$1` stakes make
   flat units and dollars identical there.
6. **Not tuned on the ladder:** sizing, the gross cut, and anything outside Kalshi/Polymarket.


### PRE-REGISTRATION AMENDMENT 2026-10-20T18:54Z (still before any ladder row settled; agreed with lane paper-alongside-live, session local_9c1e71e0)
- **"Below the floor" is `ev_net_pct < floor`, NEVER "is a ladder row".** The ladder is the COMPLEMENT of the main paper book, so it also
  holds at-or-above-floor rows the main book did not stake (`ladder_reason=suggested_not_staked`: zero Kelly, position cap). Those are
  not lowering evidence. LOWER reads only ladder rows with `floor - 1 <= ev_net_pct < floor`.
- **Slice on `ev_net_pct`** (4 dp), not on the 1-point `ev_band` label: the tuner moves in 0.5 steps.
- **Dedupe** on venue family + `position_key` + `selected_date`, preferring the `paper:<venue>` (main-book) row, which is the same rule as
  `scripts/paper_ladder_readout.py`.
- **Naming is fixed** as `paper:<venue>:ladder` (289c0b69). Settlement buckets any `paper:*` as venue_comparison.
- **RAISE side:** lane paper-alongside-live will stamp `ev_net_pct` on scoped main-book `paper:<venue>` rows, from its tags path. Once those
  rows exist, RAISE of the net floor is registered as a mirror of the gross rule: taken rows' marginal band `[effective net cut, +1)`, flat
  ROI AND same-book CLV both t <= -2, same sample minimums.
- **Apply stays a user decision,** and the net floor is shared by paper2 AND the live plan.


## PRE-REGISTRATION 2026-10-22T16:27Z: PARTIAL POOLING across markets within venue x sport x season_phase (user-approved; written BEFORE any pooling code)

User, 2026-10-22: "Yes: let the tuner borrow strength across markets within venue x sport x phase (partial pooling), keeping a separate threshold
per cell. Pre-register it and run it in shadow first."

**Why:** about 50 live fills a day spread over 73 cells means most cells need weeks to reach 40 band events. Pooling shrinks each market cell
toward its family, so a cell with little data borrows strength and a cell with a lot keeps its own verdict.

**The rule, fixed now:**
1. **Family** = venue x sport x season_phase. Cells = venue x sport x market x season_phase, unchanged. Each cell keeps its OWN threshold, and
   no family-wide threshold exists. Phases are never pooled, and an unknown phase forms no family.
2. **Inputs per cell:** its marginal band only (`[effective cut, +band)`, as today), aggregated to EVENTS. Per event: the flat return (the mean
   of its bets' pnl/stake) and the same-book CLV (the mean over its bets, recomputed from prices as of 7f6f7b1c).
3. **Estimator, separately for flat ROI and for CLV:** a random-effects (DerSimonian-Laird) normal model over the family's cells that have
   >= 2 events in their band.
   - Per cell: mean `m_c` and sampling variance `v_c` = s^2 / n. A cell with s^2 = 0 uses the family's pooled within-cell variance.
   - Between-cell variance `tau^2` = max(0, (Q - (k-1)) / (sum w - sum w^2 / sum w)) with fixed-effect weights w = 1 / v_c.
   - Family mean `M` = the random-effects weighted mean, weights 1 / (v_c + tau^2), with var(M) = 1 / sum(1 / (v_c + tau^2)).
   - Shrunk cell estimate `theta_c = B M + (1 - B) m_c` with `B = v_c / (v_c + tau^2)`, and var(theta_c) = (1 - B) v_c + B^2 var(M).
     If tau^2 = 0, theta_c = M and var = var(M).
   - z_c = theta_c / sqrt(var(theta_c)).
4. **Decision:** the same rule as unpooled, on the pooled z's. RAISE when z_ROI <= -2 and z_CLV <= -2; LOWER when both >= +2 and the configured cut
   binds. Step 0.5, bounds and cooldown unchanged.
5. **Minimums:**
   - cell band events >= 10 and family band events >= 40;
   - cell CLV events >= 8 and family CLV events >= 30;
   - a family with fewer than 2 qualifying cells does not pool (`pool_single_cell`) and falls back to the unpooled verdict.
6. **Mode `SYNDICATE_MIN_EV_TUNER_POOLING` = off | shadow | on.** Absent or unrecognised = **shadow**.
   - In shadow the pooled verdict is computed, stored per cell as `pooled`, and counted in the nightly line (`pooled_actions=`), but it does NOT
     change the cell's action or override.
   - `on` makes the pooled verdict drive the cell. Switching to `on` is a USER decision after the shadow readouts.
   - All of this is still under the tuner's own shadow/apply mode: nothing reaches a commit gate unless SYNDICATE_MIN_EV_TUNER=apply.
7. **Shadow read, reported, not a gate:** after 7 daily readouts with pooling in shadow, report pooled vs unpooled proposals per cell, and for
   each pooled RAISE the removed band's subsequent flat ROI and CLV with n.


## RESULT 2026-10-22T16:34Z: partial pooling, first replay on the production ledger (built to the 16:27Z pre-registration)

**Data.** Fleet ledger read-only 2026-10-22 16:33Z: 12,175 rows. The replay covers 21 nights (night D sees orders graded before D 12:00Z) at the fleet's
base 0.0. Tuned evidence: paper venue rows 10-02..10-21; live venue rows WITH `ev_pct` only since 10-19 (kalshi nba 56 / 2 dates, wnba 10 / 2,
ncaaf 4 / 1); ladder rows skipped (80). CLV is recomputed from prices (7f6f7b1c, todo #719).

**Outcome. Pooled and unpooled both propose 0 moves; pooling changes WHY.**
- More cells now reach a verdict. kalshi ncaaf h2h is judged on its family (73 band events), no longer held as `insufficient_events`.
- Shrinkage behaves as designed. polymarket ncaaf (83 family events): ROI shrink 0.34-0.53, CLV z 3.7-5.2. kalshi ncaaf: ROI tau^2 = 0, so every cell
  takes the family mean (-3.47%, z -0.46).
- **The binding reason is disagreement, not sample size.** Across both NCAAF families, pooled CLV is strongly positive (z 3.7-5.2) while pooled flat
  ROI is negative and not significant (z -0.1 to -1.9). The AND rule holds them as `only_clv_significant`. This is the same reading as
  the 10-19 backtest, now at family strength: we beat the close by about 1.5-2 points, and the results have not followed on these samples.
- polymarket ncaaf spreads is the closest to a pooled RAISE: pooled flat ROI -30.5% (z -1.88), but CLV +1.48 (z 3.74), so the CLV
  contradicts the raise.

**Status.** `SYNDICATE_MIN_EV_TUNER_POOLING` defaults to shadow, so the nightly line will carry `pooled_actions=` and each cell a `pooled` verdict;
nothing changes. Switching it on is the user's decision after the readouts.


## WEEK OF READOUTS 2026-10-20..2026-10-26 (7 of 7, lane min-ev-tuner-shadow, scheduled task `min-ev-tuner-daily-readout`)

- **Ran 7 of 7. 0 FAILED readouts.** Each nightly pass logged a `MIN_EV_TUNER` line between 12:00 and 12:05Z on its date, and `last_run_at` read back from keyvalue matched it every time. 0 `MIN_EV_TUNER_FAILED` / `_SAVE_FAILED` / `_HOOK_FAILED` lines all week. Mode was `shadow` at every read (no alarm). Base 0.0 throughout.
- **Proposed moves: 0 of 7 nights, unpooled AND pooled.** Cells grew 60 -> 68 -> 73 -> 74 -> 74 -> 74 -> 78, and every cell held every night.
- **Flat-unit grading (affc9a7b) was live for 7 of 7.** Readout 1's pass ran on d3878d69, which contains it. Partial pooling (shadow) was live for 4 of 7 (readouts 4-7, from 10-23).
- **Cells that reached a full unpooled verdict:** polymarket ncaaf totals (from 10-23) and kalshi ncaaf totals (from 10-25). Both hold `only_clv_significant`. kalshi ncaaf spreads ended at 27/30 CLV events and would read the same.
- **Closest to a decision: polymarket ncaaf spreads, pooled.** Pooled flat ROI -30.6%, z -1.94 on 10-25/10-26 (-1.87..-1.94 all week), is 0.06 from the RAISE threshold. Pooled CLV is +1.52 (z +4.15), so the AND rule holds it. The unpooled cell has only 20/40 band events and did not grow all week. Second: kalshi nfl receptions, flat +36.2% (t 1.93) but CLV -0.02 and 17/40 events, so it is nowhere near a LOWER, which also needs the configured cut to bind.
- **The binding reason all week is disagreement, not sample size.** In every NCAAF cell, same-book CLV is +1.3..+2.0 points (t 4-6), while flat ROI is -9..+11% and never significant. This is the 10-19 backtest's reading, unchanged after a week. On the AND rule no cell can RAISE while it beats the close this clearly.
- **Volume note:** the top NCAAF marginal bands gained about 0-7 events over the whole week. Most new settled volume was ladder rows (14 -> 2,986 skipped as `ladder_not_pre_registered`). The ladder reader that would use them for LOWER of the net floor is pre-registered and not built.
- **Decision owed by the user:** whether to APPLY (`SYNDICATE_MIN_EV_TUNER=apply`). On this week's evidence apply would change nothing, because there are 0 proposals. Apply is also inert until `effective_min_ev_pct` is wired, since it is called nowhere today. It needs wiring at `syndicate/features/shared/portfolio_commit.py:1102-1108` (owned by lane `published-negative-ev`, needs a loan) and at `polymarket_us_orders.py:1251`. Switching pooling from shadow to `on` is a separate user decision.
