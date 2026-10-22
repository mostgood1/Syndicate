# Findings: sim-stake-earned-profile (2026-10-22)

Lane `sim-stake-earned-profile`, session bde77672. Harness: `scripts/fit_staked_probability_cells.py`
(it reuses `scripts/fit_staked_probability.py`'s row derivation, split, Brier and beta grid by import;
that file and `staked_probability_profile.py` are unedited, since they belong to lane
`sim-stake-unfitted-market-only`).

Question: can the sim EARN stake in any cell, instead of getting none (#704, live since
2026-10-19 22:43:52Z) or full weight (pre-#704)?

Substrate: the fleet execution ledger, read-only, through `execution_ledger.full_history_orders()`
at nice 19. The env was the refresh-worker state env: keyvalue backend,
`SYNDICATE_REFRESH_STATE_URL=redis://127.0.0.1:6379/0`,
`SYNDICATE_REPORTS_ROOT=/home/amyn/syndicate-prod/data/reports`, `PYTHONPATH=~/Syndicate`.
**The interpreter was the fleet's `/home/amyn/.venvs/syndicate/bin/python`, not the system `python3`
(s0).** The fleet's HEAD was `36eb357b9`, and the harness ran from this worktree's checkout against that
ledger. Read at 2026-10-22T16:46:29Z.

## s0. Coverage (printed BEFORE any outcome was scored; no outcome read)

**SUBSTRATE CORRECTION.** The first coverage pass in the pre-registration commit `a61332bf` read **only
the disk archive**. I had run the harness with the WSL system `python3`, which has no `redis` module. The
keyvalue read of the live ledger document failed (`read_json_file_result` -> ok=False, RuntimeError),
and `read_json_file` swallowed that failure as an EMPTY document (`#658`). The result was 9,178 orders
with 0 from the 3,000-row live document, no live venue order, and an apparent "order collapse" after
10-18 that was really missing data. With the fleet's interpreter, `/home/amyn/.venvs/syndicate/bin/python`,
the read returns ok=True, 3,000 live-document rows, and **12,175 orders** in all: 11,500 paper, 675 live,
newest submitted 2026-10-22T16:15:20Z. That matches lane `fitter-contract-price-units`'s 12,111 from
earlier today. Every number below is from the corrected read. The archive-only fit gave the same verdicts
(0 written cells, the same diagnostic cells), and **the s1 criteria were not touched.**

Of 12,175 orders, 6,222 are the venue-comparison book, dropped because each re-prices a portfolio
decision and would count one outcome several times. Further drops: 1,243 with no model edge (the
market-fair book, which says nothing about beta), 1,169 unsettled, 420 with no `ev_pct` (all live), 131
with no price (all live), 29 pushes, and 2 with a model probability out of range. **Usable: 2,959 settled
portfolio rows on 427 events, selected dates 2026-10-02..2026-10-21.** Of those, 2,885 are paper and
**74 are live**. The live trading book has 626 settled orders, but 551 of them carry no `ev_pct` or no
price, so the sim weight cannot be fitted on the live book at all (s6).

At the asked grain, **venue x sport x market x segment x season_phase, there are 321 cells.** The venue
is the order's `book`, where the bet was priced. Largest cells:

| cell | rows | events | dates | window |
|---|---:|---:|---:|---|
| prophetx / ncaaf / spreads / full / regular | 504 | 120 | 20 | 10-02..10-21 |
| prophetx / ncaaf / totals / full / regular | 202 | 68 | 16 | 10-02..10-21 |
| novig / ncaaf / spreads / full / regular | 147 | 75 | 18 | 10-02..10-21 |
| novig / ncaaf / h2h / full / regular | 124 | 61 | 18 | 10-02..10-19 |
| prophetx / ncaaf / h2h / full / regular | 70 | 43 | 15 | 10-02..10-17 |
| draftkings / nhl / sog / full / regular | 48 | 36 | 12 | 10-06..10-20 |
| (315 more) | <= 47 each | | | |

- **By sport x phase:** ncaaf regular 1,452; nfl regular 431; mlb postseason 344; nhl regular 267;
  wnba postseason 214; soccer regular 189; nba regular 58; nhl preseason 4. **Unknown phase: 0 rows.**
- **By venue:** prophetx 821, novig 363, kalshi 325, betmgm 258, draftkings 235, fanduel 227,
  betrivers 210, bovada 134, fanatics 104, polymarket 98, betonlineag 96, pinnacle 50, williamhill_us 38.
- **Venue-pooled (diagnostic grain):** ncaaf spreads regular 759 rows / 139 events; ncaaf h2h 344;
  ncaaf totals 293; nfl receptions 175; nhl sog 108; soccer h2h 105.

**Arithmetic, before fitting:** the floor is 200 HELD-OUT rows at a 70/30 chronological cut, so a cell
needs about 667 rows. **No cell at the asked grain has that many**; the largest has 504. With venues
pooled (phases still apart), only ncaaf / spreads / full / regular clears it. So data volume, not outcomes,
fixes the answer to "which cells earn beta > 0": **none can be written today.** The fit below runs
anyway, so that the per-cell numbers exist and the next fit has a baseline.

## s1. PRE-REGISTRATION (written and committed BEFORE `fit` was run)

1. **Cell** = `<venue>|<sport>|<market>|<segment>|<phase>`. The venue is the order's `book`, and the phase
   is `season_phase.season_phase(sport, selected_date)`. Phases are never pooled. An unknown phase is
   its own cell, and the harness reports it and NEVER writes it.
2. **Rows** = portfolio-book settled orders (won or lost) with a model edge. They are derived exactly
   as the sizer derives them: `fair` comes from `ev_pct` and `requested_price` (unit-aware), and
   `model = fair + model_edge_pct/100`. No market or family is excluded.
3. **Split** = chronological, cut at the date boundary at or after the 70th-percentile row, and computed
   per cell.
4. **Floors** = n_test >= 200 rows (the base harness constant, unchanged) AND n_test >= 30 events.
5. **Fit** = beta on the grid 0.00..1.00, step 0.05, chosen to minimise the train Brier. The smallest beta
   wins a tie.
6. **Gates.**
   - **WRITE beta > 0** only if the held-out `Brier(beta0) - Brier(fit) > 0` AND that delta's
     event-bootstrap 95% CI has its lower bound > 0. The bootstrap uses 1,000 draws over held-out
     events, with seed 20261022.
   - A point win whose CI includes 0 is `refused_point_win_ci_includes_zero` and is NOT written.
   - **WRITE market_only** if the train fit picks beta 0 AND the held-out `Brier(beta0) < Brier(beta1)`.
     This is the base harness's rule, unchanged.
   - Every other cell is not written.
   - Below the floors, cells with n_test >= 50 rows and >= 10 events are reported as DIAGNOSTIC: beta,
     the CIs and the deltas. They are never written, and no decision rests on them.
7. **beta CI** = 250 refits of the grid on train events resampled with replacement, giving the 2.5/97.5
   percentiles.
8. **A venue-pooled diagnostic** (`--grain pooled_venue`, phases still apart) is reported for context
   only. It can never be written, because the asked grain carries the venue.
9. **Hypothesis H-EARN** (expected NOT to hold): at least one cell passes the beta > 0 write gate.
   The prior is that the pooled sim weight on 4,876 orders was w = -0.27 [-0.78, +0.18]
   (`findings_2026-10-19_ev_overstatement_decomp.md`).
10. **Nothing is published.** The profile reader keys `<sport>|<market>|<segment>` (`portfolio_commit.py`
    ~776), so a 5-part candidate key is INERT until the reader learns venue and phase. Making it read
    them needs loans of `staked_probability_profile.py` (lane `sim-stake-unfitted-market-only`) and of
    the `portfolio_commit` seam, plus the user's decision.

## s2. RESULT at the asked grain -- NOTHING EARNS STAKE, AND NOTHING IS WRITTEN

`fit` on the corrected read, 2026-10-22T16:46:29Z, 1,000 bootstrap draws:

| verdict | cells |
|---|---:|
| `refused_n_test_below_floor` (n_test < 200) | 195 |
| `refused_no_chronological_split` (all rows on one date, or the cut lands on the first date) | 126 |
| `write` (beta > 0) | **0** |
| `market_only` | **0** |

The largest held-out set at the asked grain is 189 rows. **H-EARN is not tested, not falsified.** No cell
had the volume to be judged. The candidate profile is EMPTY:
`reports/staked_probability/candidate_profile_2026-10-22.json` has `cells: {}` and version
`staked_probability_cells_v1@2026-10-22T16:46:29Z`.

### Diagnostic cells (below the floor; reported, never written; no decision rests on them)

Delta = `Brier(beta0) - Brier(x)` on held-out rows; **positive means x beats the market alone**.
CIs are event-bootstrap 95%. Train ends 10-12 or 10-13 and test starts the next day in every row.

| cell | train rows / events | test rows / events | beta (95% CI) | Brier beta0 | Brier beta1 (raw sim) | delta beta1 (95% CI) |
|---|---|---|---|---:|---:|---|
| prophetx / ncaaf / spreads / regular | 315 / 97 | 189 / 45 | 0.00 [0.00, 1.00] | 0.25146 | 0.26225 | -0.0108 [-0.0328, +0.0123] |
| prophetx / ncaaf / totals / regular | 134 / 50 | 68 / 28 | 0.00 [0.00, 1.00] | 0.24864 | 0.24522 | +0.0034 [-0.0260, +0.0314] |

Venue-pooled (phases apart; **can never be written**, because the asked grain carries the venue):

| cell | train rows / events | test rows / events | beta (95% CI) | Brier beta0 | Brier beta1 | delta beta1 (95% CI) | verdict |
|---|---|---|---|---:|---:|---|---|
| * / ncaaf / spreads / regular | 508 / 113 | **251 / 53** | 0.00 [0.00, 0.65] | 0.24983 | 0.25306 | -0.0032 [-0.0236, +0.0164] | market_only (would-be) |
| * / ncaaf / h2h / regular | 225 / 74 | 119 / 41 | 0.00 [0.00, 1.00] | 0.22174 | 0.23765 | -0.0159 [-0.0387, +0.0039] | below floor |
| * / ncaaf / totals / regular | 192 / 63 | 101 / 35 | 0.00 [0.00, 1.00] | 0.24589 | 0.25477 | -0.0089 [-0.0387, +0.0169] | below floor |
| * / nfl / receptions / regular | 80 / 26 | 95 / 26 | 0.00 [0.00, 1.00] | 0.23959 | 0.23996 | -0.0004 [-0.0228, +0.0220] | below floor |
| * / nhl / assists / regular | 20 / 16 | 56 / 21 | 0.00 [0.00, 0.00] | 0.19948 | 0.20622 | -0.0067 [-0.0233, +0.0093] | below floor |

The pattern across all 7 measurable cells:

- **Every train fit picked beta 0.** The sim never earned weight in-sample.
- On the held-out rows the raw sim lost to the market in **6 of 7** cells, as point estimates.
- **No CI excludes 0 in either direction.** These cells cannot tell "the sim is mute" from "the sim
  slightly hurts".
- The beta CIs are mostly [0, 1]: at this volume, beta is **unidentified**, not measured to be 0.

This agrees with the 10-19 pooled w = -0.27 [-0.78, +0.18] and adds the per-cell, per-phase,
out-of-sample view. The only cell volume can support today, venue-pooled ncaaf spreads, says
market-only. Its beta upper bound of 0.65 rules out the old full-weight sizing (beta ~1) there.

## s3. SHADOW -- the expected stake change if the candidate were published: $0.00, by construction

- The candidate has **no cells**, so every row resolves exactly as it does today.
  - Under the live mode (`SYNDICATE_STAKED_PROBABILITY_UNFITTED=market`, since 2026-10-19 22:43:52Z),
    unfitted means the market fair.
  - Under `raw` or `market_only_cells`, an empty profile is the raw sim, also as today.
- **No cell would get beta > 0, so no row's stake changes.**
- Even a non-empty 5-part candidate would change nothing today: the reader keys
  `<sport>|<market>|<segment>` (s5). `tests/test_fit_staked_probability_cells.py::test_five_part_candidate_key_is_inert_to_todays_reader`
  pins this.
- No fleet plan was re-sized, because the delta is identically zero. That is arithmetic, not a measurement.
- **Nothing to publish, and no deploy was made.**

## s4. When can a cell first be judged

- **The asked grain.** prophetx / ncaaf / spreads / regular needs about 160 more settled rows to reach
  200 held out. 81 model-edge orders in that cell were already placed and still unsettled at the read.
  - Its settled flow by selected date was 32-38 a day on 10-14..10-17, then 3, 3, 2, 1 on 10-18..10-21.
    The drop is partly settlement lag (the NCAAF games are on the weekend) and partly the new paper
    selection: from 10-20, portfolio paper orders are tagged `selection=suggested_only` (227 of 294 on
    10-21).
  - **First refit worth running: after the 10-31 NCAAF slate settles, about 2026-11-01.** Run `coverage`
    first, and fit only if a cell shows >= 667 rows.
  - Even then it is ONE cell. The other 320 cells will not reach the floor this NCAAF regular season
    (it ends 12-12) at the current paper volume.
- **Venue-pooled.** ncaaf spreads regular already clears the floor, and ncaaf h2h and totals need about
  2-3x their rows.
- **The design question this raises (the user's).** At the per-venue grain, the paper ledger is too
  thin to ever earn stake for most cells. Two ways out:
  - fit at sport x market x segment x phase with venues pooled (closer to the reader's key, which
    lacks phase today);
  - or accept that the sim stays at beta 0 everywhere except where one venue dominates the volume.
  This harness supports both grains. Only the asked grain is written.

## s5. The reader cannot see venue or phase today

- `portfolio_commit.sizing_inputs_with_provenance` (~776) calls
  `profile.staked_basis(sport, market, segment)`, an EXACT 3-part key.
- A cell fitted per venue and phase can only take effect once two things change, each with a loan and the
  user's decision:
  - `staked_probability_profile.lookup` must accept the 5-part key. It belongs to lane
    `sim-stake-unfitted-market-only`, which is OPEN, so this needs a loan.
  - The `portfolio_commit` seam must pass `book` and the season phase.
- **Phase can never be pooled at application either.** Writing a 3-part cell from a regular-season fit
  would apply it to the postseason.
- So the reader change is the prerequisite for ANY phase-correct profile, not just for this lane's.

## s6. Side finding -- the live book carries no `ev_pct` on most orders

- 626 settled live orders. **420 have no `ev_pct` and 131 have no price**, and only 74 are usable for
  any fit that derives `fair` from `ev_pct`.
- So the live money book, the one the user's principle cares about most, is nearly invisible to the
  staked-probability fit, and to any other fitter using the sizer's derivation.
- The 74 usable live rows are mostly kalshi nba spreads_alt (29) and nba player props.
- Not investigated here; recorded as a lead.
- **RESOLVED 2026-10-22 (`e0f22300`, `findings_2026-10-22_live_order_ev_pct_gap.md`, todo #728 closed):**
  no live write path drops `ev_pct`. All 552 unusable settled live rows come from the 2026-10-02 venue rebuild
  of the Render-era book, which carries `ev_pct` null by design and cannot be recovered. All 125 live orders
  placed on the fleet carry `ev_pct` and a price. So the live book is fittable from 10-02 on, and it is
  simply young.

## s7. Tooling defect found on the way

The WSL system `python3` has no `redis`. With `SYNDICATE_REFRESH_STATE_BACKEND=keyvalue` it reads the
execution ledger's live document as EMPTY, with no error, and `full_history_orders()` returns the archive
alone. A fit, census or CLV read run that way **looks complete and is missing the newest 3,000 orders
and every live order.**

**Rule:** run fleet reads with `/home/amyn/.venvs/syndicate/bin/python`, and assert
`read_json_file_result(_ledger_path())[1] is True` before trusting a count. Recorded in `learnings.md`.
