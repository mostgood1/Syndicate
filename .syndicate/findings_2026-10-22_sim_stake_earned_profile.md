# Findings: sim-stake-earned-profile (2026-10-22)

Lane `sim-stake-earned-profile`, session bde77672. Harness: `scripts/fit_staked_probability_cells.py`
(it reuses `scripts/fit_staked_probability.py`'s row derivation, split, Brier and beta grid by import;
that file and `staked_probability_profile.py` are unedited, since they belong to lane
`sim-stake-unfitted-market-only`).

Question: can the sim EARN stake in any cell, instead of getting none (#704, live since
2026-10-19 22:43:52Z) or full weight (pre-#704)?

Substrate: fleet execution ledger, read-only, refresh-worker state env (keyvalue backend,
`SYNDICATE_REPORTS_ROOT=/home/amyn/syndicate-prod/data/reports`), via
`execution_ledger.full_history_orders()`, at nice 19. The fleet's HEAD is `36eb357b9`. The harness ran from this
worktree's checkout against that ledger.

## s0. Coverage (printed BEFORE any outcome was scored; no outcome read)

`coverage` at 2026-10-22 ~17:2xZ: 9,178 ledger orders. 4,852 are the venue-comparison book, dropped
because each re-prices a portfolio decision and would count one outcome several times. Of the rest,
1,242 have no model edge (the market-fair book, which says nothing about beta), 169 are unsettled,
28 are pushes and 2 have a model probability out of range. **Usable: 2,885 settled portfolio rows
on 414 events, selected dates 2026-10-02..2026-10-21.** The settled ledger is all paper. The
portfolio book has no live venue order.

At the asked grain, **venue x sport x market x segment x season_phase, there are 305 cells.** The
venue is the order's `book`, where the bet was priced. Largest cells (rows / events / dates):

| cell | rows | events | dates |
|---|---:|---:|---:|
| prophetx / ncaaf / spreads / full / regular | 504 | 120 | 20 |
| prophetx / ncaaf / totals / full / regular | 202 | 68 | 16 |
| novig / ncaaf / spreads / full / regular | 147 | 75 | 18 |
| novig / ncaaf / h2h / full / regular | 124 | 61 | 18 |
| prophetx / ncaaf / h2h / full / regular | 70 | 43 | 15 |
| draftkings / nhl / sog / full / regular | 48 | 36 | 12 |
| (299 more) | <= 47 each | | |

By sport x phase: ncaaf regular 1,448; nfl regular 431; mlb postseason 344; nhl regular 266;
wnba postseason 203; soccer regular 189; nhl preseason 4. No unknown-phase row survived.
By venue: prophetx 821, novig 363, betmgm 258, kalshi 256, draftkings 235, fanduel 227, betrivers 210,
bovada 134, fanatics 104, betonlineag 96, polymarket 93, pinnacle 50, williamhill_us 38.

**Arithmetic, before fitting:** the floor is 200 HELD-OUT rows at a 70/30 chronological cut, so a cell
needs about 667 rows. **No cell at the asked grain has that many.** The largest has 504, which is about
150 held out. With venues pooled (phases still apart), only ncaaf / spreads / full / regular (757) clears
it. The answer to "which cells earn beta > 0" is therefore fixed by the data volume before any outcome is
scored: **none can be written today.** The fit below runs anyway, so that the per-cell numbers exist and
the next fit has a baseline.

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
