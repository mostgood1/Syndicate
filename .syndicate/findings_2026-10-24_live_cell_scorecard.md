# Findings: live-cell-scorecard (2026-10-24)

Lane `live-cell-scorecard`, session d57baa09 (side session of the portfolio endpoint a21617bf).
Harness: `scripts/live_cell_scorecard.py` (tests: `tests/test_live_cell_scorecard.py`, 9 pass).
Question: where does Kalshi / Polymarket US trading have real edge? Concentrate there and stop
funding cells that have none. Measured, never assumed. **No live behaviour was changed.**

## s0. Substrate and coverage

**Substrate: the fleet execution ledger, read-only.** It was read through
`execution_ledger.full_history_orders()` at nice 19 with the fleet venv
(`/home/amyn/.venvs/syndicate/bin/python`) and the refresh-worker state env (keyvalue
`redis://127.0.0.1:6379/0`). `read_json_file_result(...)[1] is True` was asserted before the
count was trusted. Read at **2026-10-24T22:02:27Z**: 15,136 orders, newest submit 21:45:03Z,
fleet HEAD `5f32d9c4f`.

**Reconciliation.** The scorecard reproduces the coordinator's 10-24 headline from
`/api/portfolio/live` to the cent:

| slice | coordinator | scorecard |
|---|---|---|
| Kalshi pregame, before 10-20 | 421 / $2,262.84 / -$361.07 | 421 / $2,262.84 / -$361.07 |
| Kalshi pregame, since 10-20 | 127 / $407.45 / -$54.22 | 127 / $407.45 / -$54.22 |
| Kalshi in-game | 31 / $12.67 / -$2.75 | 31 / $12.67 / -$2.75 |
| Polymarket pregame | 148 / $618.13 / -$178.40 | 148 / $618.13 / -$178.40 |

Settled rows, after drops:

| book:venue | settled | dates | window | in-game |
|---|---|---|---|---|
| live:kalshi | 579 | 38 | 08-06..10-24 | 31 |
| live:polymarket | 148 | 27 | 08-25..10-23 | 0 |
| paper:kalshi | 609 | 22 | 10-02..10-24 | 112 |
| paper:polymarket | 335 | 20 | 10-02..10-24 | 108 |
| ladder:kalshi | 673 | **5** | 10-20..10-24 | 138 |
| ladder:polymarket | 259 | **5** | 10-20..10-24 | 110 |

Drops: 261 paper and 107 ladder duplicate positions (the first submit is kept); 250 paper,
1,593 ladder and 36 live unsettled; 6 live not filled.

**Coverage caveats.**

- **The window is short.** Since 10-20 the paper:kalshi alongside-live book has only **15**
  settled rows; the 10-20+ evidence is mostly the ladder, which covers 5 dates.
- **Paper settlement is stuck.** 928 paper/ladder rows on games that commenced before
  10-23 06Z are still unsettled. Most are NBA: ladder `spreads_alt` 188, `player_threes` 64,
  `totals_alt` 59, other props ~130. Paper NBA is therefore under-counted and may be biased.
  Live is not affected, because the venue settles it. **This is a lead; no lane owns it.**
- **The 552 live rows before 10-19 are `venue_rebuild` rows** with no `market`, `event_id`,
  `ev_pct` or `commence_time`. Family and sport are parsed from the Kalshi series ticker or
  the Polymarket slug, and the game from its date+teams token. Their phase is pregame by
  construction, because in-game entries started 10-23.

**Phase rule.**

- A live row is `in_game` when it came from the in-game entry path: no `ev_pct` and not a
  rebuild. The first was 10-23T23:38Z. This reproduces the coordinator's 31.
- Four pregame-plan orders that filled 7 min after a 23:00Z kickoff on 10-20 carry ev, so
  they stay pregame.
- A paper row is `in_game` when it was submitted at or after `commence_time`.

## s1. Headline: no cell has demonstrated edge, live or paper

Flat ROI is net of fees, per bet. CI90 is a game-clustered bootstrap (2,000 reps, seeded).
**EDGE** or **LOSES** needs the CI90 to exclude 0 on at least 5 bets and at least 10 games.

| book | venue | phase | n | games | staked | pnl | ROI $ | ROI flat | CI90 flat | CLV same-book (n) |
|---|---|---|---|---|---|---|---|---|---|---|
| live | kalshi | pregame | 548 | 300 | 2,670 | -415 | -15.6% | **-11.8%** | [-20, -4] LOSES | +0.28 (70) |
| live | polymarket | pregame | 148 | 124 | 618 | -178 | -28.9% | **-18.2%** | [-34, -2] LOSES | +1.99 (7) |
| live | kalshi | in_game | 31 | 17 | 13 | -3 | -21.7% | -26.1% | [-59, +10] | - |
| paper | kalshi | pregame | 497 | 174 | 4,385 | +1 | +0.0% | -13.8% | [-24, -3] LOSES | +0.87 (391) |
| paper | polymarket | pregame | 227 | 118 | 2,332 | -288 | -12.3% | -9.3% | [-22, +3] | +3.35 (165) |
| paper | kalshi | in_game | 112 | 74 | 2,479 | -390 | -15.7% | -21.5% | [-35, -6] LOSES | +2.94 (31) |
| ladder | kalshi | pregame | 535 | 87 | 535 | +0 | 0.0% | 0.0% | [-6, +6] | +0.73 (285) |
| ladder | polymarket | pregame | 149 | 70 | 149 | -30 | -20.4% | -20.4% | [-31, -10] LOSES | +0.65 (89) |

Since 10-20, live Kalshi pregame is **-17.1% flat [-30, -6]** (127 bets, 41 games).

**Fees are not the problem.** Kalshi fees are 2.8% of stake all-time (2.0% since 10-20).
Before fees, Kalshi is still **-12.8%** and Polymarket **-28.6%**. The loss is in WHICH bets
get placed.

**The 40-75c price band did not rescue live.** Since 10-20, live Kalshi 40-55c is -23.9%
[-40, -8] LOSES (60 bets) and 55-75c is -15.3% [-34, +4] (55 bets). All-time, live Kalshi
55-75c is -22.3% [-37, -5] LOSES on 79 bets / 47 games.

**Price buckets, all-time.**

- **Under 40c loses everywhere it is measured:** paper:kalshi -42% [-63, -19], live
  Polymarket -53% [-79, -22].
- 75c+ loses on paper:kalshi: -14% [-27, -3].
- **55-75c is the only bucket with a non-negative point estimate in any book:** paper:kalshi
  +3.5% [-11, +17], paper:polymarket +9.8% [-11, +29], ladder:kalshi +1.7%. No CI excludes 0.

**The EV ranking is not picking winners.** The Kalshi ladder (below-floor EV bands, $1 flat)
breaks even (0.0% [-6, +6] on 535 bets). The above-floor bets that went live lost -11.8%.
Only 5 dates sit under the ladder, so read this as consistent with "claimed EV carries no
information at venue prices", not as proof of it.

**Positive CLV did not turn into profit.** Same-book CLV is positive on every book with
n > 50 (+0.3 to +3.4%), while ROI is negative. Either the CLV mark measures something other
than the realised edge, or the edge it shows is smaller than the noise plus fee. CLV is not
a sufficient gate on its own.

## s2. Cells (sport x family, all-time; the full cell table is in the report output)

**LOSES (CI90 upper < 0):**

| cell | flat ROI | CI90 | bets / games |
|---|---|---|---|
| live Kalshi NBA props | -34.8% | [-63, -13] | 35 / 13 |
| live Kalshi NCAAF h2h | -64% | [-102, -26] | 6 bets; thin by games |
| live Kalshi MVE parlays | -105% | — | 7 bets |
| live Polymarket soccer h2h | -55% | — | 12 bets |
| paper:kalshi MLB props | -26% | [-43, -11] | 213 bets |
| paper:kalshi NCAAF totals | -21.5% | [-42, -2] | — |

**Best point estimates, none of them proven:**

| cell | flat ROI | CI90 | bets / games | paper and ladder twins |
|---|---|---|---|---|
| live Kalshi NCAAF spreads | +19.0% | [-9, +45] | 36 / 33 | paper:kalshi -3.9%; ladder +3.0% |
| live Kalshi NBA spreads | -3.4% (+5.3% $) | [-25, +18] | 51 / 24 | ladder -0.4% |
| live Kalshi NCAAF totals | -2.3% | [-26, +22] | 56 / 49 | paper:kalshi **-21.5% LOSES** |

**The one EDGE cell:** live Polymarket NCAAF totals, +61% [+13, +102] on **10 bets / 7
games**. It falls under the 10-game minimum, and since 10-20 it reads -21% $ on 7 bets. **It
is noise.** About 100 cells are scored, so about 5 clear a one-sided 5% bar by chance alone.

**Conclusion: there is no cell to concentrate money in today.** The live book loses ~12-18%
per bet, net of fees, on 727 settled bets. That is significant on both venues, and it stays
negative after the price band and the per-venue net floors.

## s3. Does the optimizer's calibration shrink w* reach live sizing? **NO.**

**The chain, with file and line.**

1. `daily_optimizer.py` fits w* per cell `sport|market|segment|phase`. Fleet overlay read
   11:30Z 10-24: 25 `edge_shrink` entries, 0 `stake_scale`, 219 cells (167 insufficient, 27
   not_proven, 25 overconfident).
2. `optimizer_overlay.factor_for_row` (`optimizer_overlay.py:108`) multiplies into
   `portfolio_commit._sizing_skill_factor` (`portfolio_commit.py:330`).
3. That factor scales `_sizing_model_edge` (`:405-413`), and it becomes `raw_model` (`:766`).
4. **Then `STAKED_BASIS_MARKET` (#704, live since 10-19 22:43Z) replaces it: `model_probability
   = fair` (`:800-806`).** The shrunk model edge is computed and discarded.
5. `live_stake_band` reads `sizing.kelly_fraction` (`live_stake_band.py:170`), which is
   Kelly on that fair.

**Evidence on the fleet ledger.** Since 10-22, every one of the 62 live orders on the
`model_edge` basis carries `staked_probability_version = market_fair@staked_probability` or
`market_fair@unfitted`. The other 3 stamped rows are market-only (`market_fair` basis,
`unfitted`). w* reaches only the board RANK
(`layer2_board.py:995`), and through it the `max_positions` cut. In-game entries are
1 contract and are not sized at all.

**Should it be wired in? Not now.**

- Market mode is w = 0 everywhere. Wiring w* in can only ADD sim weight.
- **Every cell live actually trades has a w* CI that spans 0:**

  | cell | w* | CI95 |
  |---|---|---|
  | `ncaaf\|spreads\|full\|pregame` | 0.34 | [-0.65, 1.34] |
  | `ncaaf\|totals\|full\|pregame` | 0.16 | [-0.65, 0.99] |
  | `nba\|spreads_alt` | no fit | — |
  | `nba\|totals_alt` | -3.5 | [-16, +21] |

- The 17 cells with a CI95 lower bound above 0 are soccer props and NBA/MLB live props. Live
  places nothing in them (the in-game book is 1 contract).
- w* is fitted against the SPORTSBOOK consensus, while live trades at the venue price.

**What would earn wiring:** a traded cell whose w* lower bound is > 0 in the optimizer AND a
venue-priced forward record. The mechanism would then be `beta = w*_lo` in the
`STAKED_BASIS_BLEND` branch for that cell only.

**Lead (not proven to matter): under market mode, a model-backed row skips the fair-noise
penalty.** `_fair_noise_penalty_pct` returns 0 whenever `_sizing_model_edge` is not None
(`:388`), and market mode then stakes the raw `fair`. An otherwise identical market-only row
stakes `fair - 5/sqrt(books)`. So the mere presence of a sim view, whose measured w* is ~0 on
traded cells, enlarges the stake and widens admission.

- Live is 140 of 144 model-backed rows (10-02+), so nearly every live bet takes this path.
- On paper, model-backed rows average $14.22 a bet against $1.98 for market-only. This is
  confounded by the pre-#704 sim sizing.

## s3b. The live EV-floor stop, and attribution after the live filters `[added 2026-10-24 between 22:02Z and 22:37Z, coordinator request; an earlier "~23:20Z" stamp was an estimate, corrected]`

**How the stop works** (`pipeline/portfolio_commit.py:510-670`, read on origin/main `3798acef`).

- **Population.** Only the live positions the 0% floor ADMITTED: rows the Suggested flag
  refused for EV reasons alone (`live_ev_floor_rows`, `:526`). They are logged once each to
  `intelligence/live_ev_floor_positions.json` in keyvalue, capped at 5,000 entries, and
  joined to settled live orders on `(selected_date, position_key)`. **Suggested rows are not
  in it, and no realised-ROI rule gates them at all.**
- **Window.** Cumulative from the first floor position (10-20 21:29Z). There is no rolling
  window.
- **Threshold.** >= 100 settled AND dollar ROI < -5%. Cached 30 min. An unreadable ledger or
  log fails closed (Suggested-only).
- **Effect when tripped.** The live plans take Suggested rows only. It is not a stop on live
  trading.
- **Re-arm.** None. The log message says *"until the key is removed"*
  (`SYNDICATE_LIVE_EV_FLOOR`). Once tripped, no new floor positions are logged, so its ROI is
  frozen and it cannot un-trip by itself.

**Measured on the fleet** (keyvalue log read ok=True, 332 entries, 10-20 21:29Z..10-24 03:37Z;
refresh-worker log):

- Last untripped read: 03:46:10Z 10-24, settled 93, ROI -18.6%. That build's floor admitted
  2,175 EV-only extras against **133 Suggested** rows, so the floor WAS the live book.
- **First trip: 03:56:03Z 10-24, settled 103, ROI -19.2%.**
- My join reproduces the coordinator's figure: 125 settled, -$67.20 on $396.10 = **-17.0%**.

**What the trip handed live back to.** Suggested-only is the population live traded before the
floor existed. **Before 10-20, live Kalshi pregame was 421 bets, -$361.07, -16.0%**. The
config was different then (sub-$1 stakes, no band, no net floors), but it lost either way.
Since 10-20 the Suggested rows are 18 bets, -$1.11 on $59 (-2%, CI [-35, +24] on Kalshi),
which says nothing either way.

**By filter regime** (live pregame since 10-20, by submit time, env-backup timestamps):

| regime | bets | games | flat ROI | CI90 |
|---|---|---|---|---|
| floor 0, before the net floor (10-20 20:45Z) | 83 | 25 | -11.5% | [-28, +5] |
| + per-venue net floor (10-21 18:12Z) | 19 | 9 | -42.8% | [-70, -8] |
| + R1/R2 per-game (10-22 16:17Z / 23:24Z) | 35 | 20 | -11.5% | [-27, +3] |
| + 40-75c band (10-23 19:58Z) | **2** | 2 | both lost | — |
| stop tripped, Suggested only (10-24 03:56Z) | **1** | 1 | won | — |

**Under the full current filter stack there are 3 settled live pregame bets. Its record is
unmeasured.** No regime shows an improvement, and every regime has too few games to show one.

**The 40-75c band as a counterfactual over all live pregame since 10-20.** Inside the band,
Kalshi is **-20.3% [-32, -8]** on 90 bets; outside it is -9.6% [-33, +13] on 37 bets. On this
evidence the band selects nothing good on live. (On paper and the ladder, 55-75c was the only
non-negative bucket, see s1.)

**Cells after the band** (live pregame since 10-20, inside 40-75c):

| cell | flat ROI | CI90 | bets / games |
|---|---|---|---|
| Kalshi NBA props | **-38.3%** | **[-64, -15] LOSES** | 33 / 13 |
| Kalshi NBA spreads | +16.0% | [-11, +40] | 17 / 12 |
| Kalshi NCAAF spreads | -5.3% | [-48, +28] | 8 |
| Kalshi NCAAF totals | -11.8% | — | 6 |
| Polymarket NCAAF totals | +45% flat, -21% $ | — | 7 |

Everything else is under 10 games.

## s4. Proposed gate policy (for the USER, via the coordinator; nothing is changed by this lane)

**FOLDED INTO THE EXISTING STOP (coordinator, 10-24): no parallel gate.** The policy below is the
stop's own mechanism — same ledger join, same fail-closed read, same 30-min cache — changed in
three ways:

1. **Population.** EVERY live row (Suggested included) is keyed by cell
   (venue x sport x family x phase), not only the floor extras.
2. **Trip rule, per cell.** A cell trips at >= 40 settled bets / 15 games with CI90 upper < 0,
   OR a cumulative live loss >= $75, OR the stop's own global rule (>= 100 settled, ROI < -5%)
   over its whole population.
3. **Re-arm rule (missing today).** The forward paper record below, read off the paper twin,
   which keeps recording at the live price while a cell is tripped. It replaces "until the
   key is removed".

Option A below is that stop with every cell starting TRIPPED. B is it with three cells
starting armed. C is it with the trip rule only.

**The pre-registered rule, as first written:**

**Pre-registered rule.**

- **Gating cell:** venue x sport x family x phase. Price bucket is a filter, not a cell
  (pooling is needed for n).
- **Default state for every cell: PAPER.** The existing paper-alongside-live / ladder books
  record at the live price.
- **Promotion to LIVE** uses a FORWARD paper record only. The clock starts at the decision,
  so a cell gets no credit for the past: that would be selection on the same data this table
  was read from. The record needs:
  - >= 150 settled bets, >= 40 games and >= 14 days;
  - flat ROI net of fees with a game-clustered **95%** CI lower bound > 0 (95%, not 90%, for
    many cells and weekly looks);
  - same-book CLV mean > 0 where n_clv >= 50.
  - Maker cells follow their own pre-registration (CLV-blind).
- **Live size when promoted:** the band floor ($5) with a $50/day cell cap, under all the
  existing caps.
- **Demotion back to paper:** a live cell's own record at >= 40 bets / 15 games with CI90
  upper < 0, OR a cumulative live loss of >= $75 in that cell, whichever comes first. The
  weekly report evaluates it, and it is applied as a user decision until it is automated.

**Options.**

- **A (RECOMMENDED): all live entries, pregame and in-game, both venues, go paper-only now.**
  - Exits keep managing the held positions.
  - Cells earn live money back by the rule above. The maker shadow (36 counted orders; first
    look at 200) is the most plausible route to a GO.
  - Run-rate saved: ~ -$71 over 10-20..10-24 (Kalshi -54.22, Polymarket -14.10, in-game
    -2.75), about **-$100/week**.
  - **Why A even though the floor stop has already tripped:** the trip moved live back to the
    Suggested-only population, which lost -16.0% on 421 bets before 10-20 and is gated by no
    realised-ROI rule.
- **B: a live canary.** Keep only Kalshi pregame NBA spreads, NCAAF spreads and NCAAF totals
  live at the $5 floor, $25/day total; everything else goes paper.
  - It keeps the order, fill, cancel and settle paths exercised.
  - None of these cells is proven, they were picked from ~30, and paper does not confirm them
    (paper:kalshi NCAAF totals LOSES).
  - Expected cost at zero edge plus fee: ~3% of ~$150/week, so ~ -$5/week, with a wide spread.
- **C: cut only the LOSES cells.** That means Kalshi NBA props, Kalshi NCAAF h2h, under 40c
  everywhere, MVE parlays and Polymarket soccer h2h. Everything else stays live.
  - The remaining book is still -10% to -17% flat, so this cuts the bleed by perhaps a third.

## s4b. USER DECISION 2026-10-24 (relayed by the coordinator 332cb014): "Keep everything live"

Quoted from the coordinator's message: the user, *"shown your numbers and options A/B/C. Their
answer: 'Keep everything live' (no change; keep trading to gather live data)."* **No cell moves to
paper.** What this lane owes now:

- the weekly scorecard (W44 next), with a flag on any cell whose CI90 turns significantly negative
  or positive;
- watching the maker shadow alongside session maker-orders-study;
- the nightly job (s5);
- the two leads below.

## s4c. Leads

**L1. Under market mode, a model-backed row skips the fair-noise penalty.** s3 has the detail.
No change is proposed until a measurement shows that it costs money. The comparison owed is
model-backed rows staked at the raw fair, against the same rows at `fair - 5/sqrt(books)`, on
the live and paper books.

**L2. The unsettled paper rows DO bias the scorecard, for NBA only.** Measured 2026-10-24 23:5xZ
on the same ledger read.

| NBA paper orders, by commence date (UTC) | settled |
|---|---|
| 10-04..10-14 (preseason) | 0 of 50 |
| 10-20 | 0 of 19 |
| 10-21 | 0 of 144 |
| 10-22 | 0 of 249 |
| 10-23 | 117 of 204 |
| 10-24 | 194 of 255 |

- Grading starts with the 10-22 US-evening slate, when `bet_status_nba` gave
  `paper_settlement._default_resolver` an `nba` entry (notes: nba-portfolio-live-prop-status).
- No NBA `live_player_box_<date>` file exists on the fleet disk for 10-20..10-22, and no
  refresh-worker or live-odds-worker log line `NBA_LIVE_BOX_CAPTURED` exists either. **So
  those orders will not grade on their own.**
- Other sports: NCAAF paper is 13-21% stuck and soccer 20-54%; MLB, NFL and NCAAF totals are
  4-9%.
- **Consequence:** every paper and ladder NBA cell covers only games from 10-23 UTC. The first
  ~2.5 nights of the NBA season, when live NBA spreads/props were placed, have NO paper twin.
  Any paper-vs-live NBA comparison, and any future re-arm on an NBA paper record, rests on a
  shorter window than the live one.
- The scorecard prints the window per book (s0). It does not yet print the per-cell stuck
  count; that is the planned addition.
- **Fix, not this lane's:** backfill-grade the 10-20..10-22 NBA paper orders from final box
  scores. `paper_settlement` is shared, so this was brought back to the coordinator.

## s4d. THE PER-CELL LIVE GATE -- BUILT (user decision "Per-cell trip only (C)", relayed by the coordinator 2026-10-24)

The coordinator's message quoted the user's answer to the question "The tripped EV-floor stop is
stuck (no re-arm), keeping live at Suggested-only. What should it do?". The answer was **"Per-cell
trip only (C)"**, described as *"Replace the one global stop with per-cell trips: a cell pauses
only if its own record is significantly negative or loses $75; all else stays live. Adds the
missing re-arm."*

**Code.**

- `syndicate/features/shared/live_cell_gate.py`, NEW, holds the gate and its classifiers. The
  scorecard now imports them, so the two cannot disagree about which cell a bet is in.
- `pipeline/portfolio_commit.py` changes in two places, behind `SYNDICATE_LIVE_CELL_GATE=on`:
  1. `_live_ev_floor_population` no longer consults the global stop. It returns the floor
     population (Suggested + EV-only extras).
  2. The venue loop's live try runs `live_cell_gate.refresh()` (evaluate + persist, cached 30
     min) and then `filter_rows` on `live_scoped`, before `_write_live_venue_plan`. Refusals
     are counted with the scope refusals.
- Off (absent / anything but `on`): byte-identical, and the global stop still gates.

**Rules (as decided):**

- **Cell:** venue x sport x family x phase.
- **Trip:** >= 40 bets AND >= 15 games with a game-clustered CI90 on flat ROI wholly < 0, OR
  pnl since `armed_since` <= -$75.
- **Re-arm:** the paper twin since `tripped_at` (paper:<venue> + paper:<venue>:ladder,
  deduplicated by position) with >= 150 bets, >= 40 games and >= 14 days, and a CI95 lower
  bound on flat ROI net of fees > 0. Re-arming sets `armed_since` = now, so the old record
  cannot re-trip the cell.
- **Start:** every cell starts armed, evaluated on its WHOLE live record.
- **Fail closed:** a ledger or state read that is not ok gives `CELL_GATE_UNKNOWN`, and every
  row is refused for that build. A confirmed-absent state file means first run.
- **State:** `intelligence/live_cell_gate_state.json` in the refresh-state store.
- **Log lines:** `[live_cell_gate] CELL_TRIP` / `CELL_REARM` / `LIVE_CELL_GATE cells= tripped=` /
  `CELL_GATE_UNKNOWN`, and `[portfolio_commit] LIVE_CELL_GATE_APPLIED venue= kept= refused=`.

**Tests.** `tests/test_live_cell_gate.py` has 14:

- trip by CI, and trip by loss;
- the CI needs 40 bets and 15 games;
- re-arm only on the FORWARD twin, refused when too soon / pre-trip record / too few games /
  not positive;
- no re-trip after re-arm;
- fail closed on state and on the ledger;
- **reachability off != on, including the stuck-trip migration:** the global stop tripped,
  then off -> Suggested-only, on -> floor population;
- the hook is placed before the live plan is written.

Also run: `test_live_ev_floor.py`, `test_live_net_floor.py`, `test_portfolio_commit*.py` (59 +
81 pass) and the scorecard (13).

**What trips at once on today's ledger** (fleet ledger read 2026-10-24 22:37Z, 15,178 orders,
whole record, `evaluate(orders, None, now)`): **2 of 43 cells.**

| cell | bets | games | pnl | flat ROI | why |
|---|---|---|---|---|---|
| `kalshi\|mlb\|prop\|pregame` | 141 | 72 | -$177.90 | -12.0% | loss rule |
| `kalshi\|parlay\|parlay\|pregame` | 7 | 6 | -$92.47 | -105% | loss rule |

**Armed but close:**

| cell | bets | games | pnl | flat ROI | note |
|---|---|---|---|---|---|
| `kalshi\|nba\|prop\|pregame` | 35 | 13 | -$30.55 | -34.8% | under 40 bets; the scorecard's CI90 is [-63, -13] |
| `kalshi\|mlb\|total\|pregame` | 66 | 58 | -$60.36 | | -$14.64 from the loss trip |
| `polymarket\|mlb\|h2h\|pregame` | 33 | — | -$71.51 | | -$3.49 from it |
| `kalshi\|nba\|spread\|pregame` | 40 | 19 | +$9.50 | +7.0% | |
| `kalshi\|ncaaf\|spread\|pregame` | 33 | 32 | +$7.64 | | |

If cells started from a FRESH clock (`armed_since` = now), nothing would trip today. That is
not what was built: "start armed" was read as "judged on its own record".

**What the replacement does to volume.** The global stop's trip had cut live to Suggested rows.
Its last untripped build, 03:46Z 10-24, had **133 Suggested vs 2,175 EV-only extras**. Turning
the gate on brings the extras back under every existing cap (band, per-game R1/R2, per-venue
net floor, compounding, day caps).

**Not covered: in-game entries** (`inplay_entries_live.LiveEntryPlacer`, live-odds-worker).
In-game cells ARE evaluated and can trip, but nothing in that path asks the gate yet. That file
belongs to lane `in-game-trading`, whose session was sent the exact check:
`live_cell_gate.allows(cell_key("kalshi", sport, family, "in_game"))`, read-only and fail closed.

## s5. Running it

**NIGHTLY JOB (built 2026-10-24, NOT LIVE until the coordinator's restart).**

- `ScheduledJob("live-cell-scorecard", 13, 30, ("scripts/live_cell_scorecard.py", "nightly"))`
  in `scripts/local_production.py`. It runs with the refresh-worker env, like every job, and
  renices itself to 19.
- It writes `<SYNDICATE_REPORTS_ROOT>/intelligence/live_cell_scorecard/<date>.{json,md}`: three
  windows (all, since 10-20, last 7 days), plus flags for every headline, sport x family and
  full cell whose CI90 excludes 0, diffed against the previous night (`NEW_FLAG` / `CLEARED`).
- It prints `LIVE_CELL_SCORECARD date=... flags=N new=N cleared=N`. rc 2 means the live
  document did not read, and nothing was written.
- **Measured on the fleet ledger 2026-10-24** (worktree code, fleet venv and env, scratch output
  root): rc 0, 11.8 s wall, 188 MB max RSS, 15,177 orders, 31 flags.
- 2 of the 31 flags are EDGE: paper NCAAF h2h 55-75c on Kalshi (+27% [+2, +49], n 14) and on
  Polymarket (+31% [0, +57], n 12). With ~100 groups x 3 windows scored, about that many clear
  a one-sided 5% bar by chance. **A flag is a reason to look again, not a result.**

**On-demand dump, as before (WSL):**

**Fleet dump (WSL):**

```
cd ~/Syndicate && SYNDICATE_REFRESH_STATE_BACKEND=keyvalue SYNDICATE_REFRESH_STATE_URL=redis://127.0.0.1:6379/0 \
  SYNDICATE_REPORTS_ROOT=/home/amyn/syndicate-prod/data/reports SYNDICATE_DATA_ROOT=/home/amyn/syndicate-prod/data \
  PYTHONPATH=$HOME/Syndicate nice -n 19 /home/amyn/.venvs/syndicate/bin/python <checkout>/scripts/live_cell_scorecard.py \
  dump --out /mnt/c/tmp/lcs/ledger.json
```

**Report (anywhere):**

```
py -3 scripts/live_cell_scorecard.py report --ledger C:/tmp/lcs/ledger.json [--since 2026-10-20] --out-md ... --out-json ...
```

A nightly fleet job, a `ScheduledJob` in `scripts/local_production.py` beside
`kalshi-maker-shadow-eval`, is a fleet config change. It belongs to the coordinator and is
NOT done here. Outputs of this run: `C:/tmp/lcs/all.{md,json}` and `C:/tmp/lcs/s1020.{md,json}`,
with copies in the notes folder.
