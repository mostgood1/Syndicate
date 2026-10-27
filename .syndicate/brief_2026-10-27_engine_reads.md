# Engine reads from E3, E4 and E5 — briefs to the sim owners `[2026-10-27, lane syndicate-decision-engine]`

**User, verbatim (2026-10-27, session "Syndicate AI decision engine"):**
"Yes, adopt E3 and E4's recommendations: Phase 5 drops the derived-line taker and sim-based combos (Kalshi's mid
prices derived lines; measured SGP correlation prices combos, sim only for soccer scorelines). Route the engine reads
to the sim owners and open a lane for a forward Kalshi combo capture."

**Why this file exists:** cross-session messages to sessions in another permission mode are held and then expire
undelivered (6 of 6 on 2026-10-26; `learnings.md` 2026-10-26). This file is the durable copy. If you own one of the
lanes below, the section with your lane's name is addressed to you.

**What these are.** Three offline tests (E3 derived-market surface, E4 combo correlation, E5 venue news lag) killed
their venue-edge hypotheses. Each also measured where a sim is WRONG. Those measurements are engine work: correctness,
not a strategy. Nothing here puts a sim into EV, price or stake. D3 keeps the sim's mean weight at 0 until it earns
weight per cell.

Sources:
- E3: `.syndicate/findings_2026-10-26_e3_derived_surface.md`, todo `#741`, script `scripts/e3_derived_surface.py`.
- E4: `.syndicate/findings_2026-10-26_e4_combo_correlation.md`, todo `#740`, script `scripts/e4_combo_correlation.py`.
- E5: `.syndicate/findings_2026-10-26_e5_venue_news_lag.md`, todo `#739`.

Standing constraints on every item:
- Each fix is its own item, default-off, with a reachability test (`off != on`) before any correctness test
  (`docs/ai_context/model_engine_standard.md`).
- Adding a MECHANISM to a calibrated engine means re-fitting the rates that were absorbing it.
- Every line stays its own decision; nothing here switches a market, family or sport on or off.
- Do not disturb the dated reads: `#704` keep/revert 11-02, the football NFL v2 2026 validation 11-03, the NBA minutes
  readings 10-28 (`nba-sim-minutes-723-readings`).
- The E3 and E4 scripts are the re-test harness. Re-run them with the same constants after a fix.

---

## `basketball-player-distribution` and `basketball-scenario-calibration` (session e0a3e383); FYI `nba-sim-minutes-history-path`

1. **NBA within-player P / R / A are INDEPENDENT in the smart-sim** (E4). This is the largest item.
   - Post hoc, over 846 player-games with >= 15 sim minutes: the sim's `Var(PRA) / [Var(P) + Var(R) + Var(A)]` has
     median **0.997** (p10-p90 0.90-1.11). Real boxes read **1.196**.
   - Backed out of the ladders: PTS x REB sim +0.014 vs realised +0.27 [+0.16, +0.38] (copula +0.236); PA x REB
     +0.021 vs +0.33; PTS x RA -0.016 vs +0.28.
   - Likely mechanism: minutes are an INPUT held constant across draws (S10 in
     `findings_2026-10-06_basketball_scenario_calibration.md`). Minutes are the common driver of a player's points,
     boards and assists, so holding them fixed leaves the three independent.
   - Fix to test: minutes drawn per draw, or a per-draw usage/pace shock. This matches
     `basketball-player-distribution`'s own hypothesis (near-deterministic minutes), and its Phase 1 (`0050a741`,
     10-27) independently found minutes the dominant defect in the player distributions. E4's covariance read is a
     second symptom of the same cause, so one minutes fix should move both.
   - Re-test: `scripts/e4_combo_correlation.py`, `off != on` on the SP-disjoint cell, then `D_bc` against the copula.
   - Knock-on: the SGP pool's `p_sim` gate for PR/PA/RA uses a Normal that assumes independent parts. It is wrong in
     the same direction.
2. **NBA margins are 8-27% too wide** (E3). The sim's per-game sd over the residual sigma about a near-close line:
   full game **1.27**, halves 1.15-1.17. Quarter totals 1.06-1.14.
   - It costs the sim on segments: arm (b) minus arm (a) +0.0073 nats [+0.0014, +0.0128] on segment spreads and
     +0.0047 [+0.0008, +0.0088] on segment totals.
   - The sim is anchored to the market mean (weight 0.95), so the excess variance is in the possession and efficiency
     noise.
   - Caveat: NBA history lines are near-close, not closes. That inflates the reference sigma (14.0 vs ~12), so the
     true excess may be larger.
3. **Draw count:** 67 of 92 NBA games stored n = 100 draws. That is too coarse to price a ladder. The 500-draw files
   did not survive E4's funnel.
4. **Not persisted:** a team-total histogram; a (margin, total) joint (so side x total, the only 2-leg combo type in
   Kalshi's NBA single-game series, cannot be priced); any cross-player or player x team joint.
5. **Availability correctness** (E5): DTD / Questionable players stay at FULL weight (78 of 88 on 10-16). An intraday
   OUT reaches the sim only at the next `raw/injuries.csv` refresh, not at the collector's 10-minute event.
6. **Where the sim's shape helped:** WNBA segment totals, -0.0219 [-0.058, -0.001] on 11 games, where the parametric
   history is thin. Small sample; keep it in mind for the WNBA off-season.

## `football-scenario-calibration` (session 20aa7f5b); FYI `nfl-game-day-injuries`

1. **NCAAF and NFL totals are 7-16% too narrow** (E3). The sim's per-game sd over the history sigma: NCAAF totals
   **0.84-0.87** (full, h1, q1, q2); NFL totals 0.88-0.93 except q1 / q3. Margins are fine (NCAAF 0.90-1.01, NFL
   0.94-1.09).
   - The cost sits where a narrow distribution misprices most, at 0.5-1.5 sd from the mean: NCAAF full totals +15.0
     vs +6.7 x10⁻³ nats for the parametric arm, segments +15.9 vs +8.4.
   - Check the scoring-rate dispersion. A fixed-seed 300-draw run also understates tails.
2. **The stored histograms are noisy.** The unsmoothed sim pmf is worse than the smoothed one on NFL segment totals
   (+0.0099 [+0.0039, +0.0165]) and NCAAF segment totals (+0.0075 [+0.0017, +0.0141]).
3. **Not persisted:** a team-total histogram; a (margin, total) joint. NFL and NCAAF player props do not come from the
   sim.
4. **Availability correctness** (E5): the NFL prop model reads no status (`injury_adjustment.py` OFF since
   `36cd8a5c`); an injury change triggers an odds sweep, not a re-sim. NCAAF reads nothing (ESPN's CFB injury feed is
   dead).
5. Leakage check, for your own replays: football sims written after kickoff do no better against Kalshi's mid
   (NCAAF post-kickoff +0.0037 vs pre-t_d +0.0153).

## `nhl-game-any-line-pricing` (UNOWNED; opened 2026-10-08 for pickup)

1. **NHL stores no distribution** (E3 and E4). Only period means and one probability are stored. Per-sim player
   samples are discarded (`player_props.py:133-150`), and no goals table or SD is saved. So neither E3 nor E4 could
   grade NHL shape or correlation at all.
   - This is this lane's own goal: a goals distribution hockeysim publishes. E3 adds a reason to store per-game draws
     or period goal pmfs, and E4 a reason to keep a player joint.
2. **Availability correctness** (E5): Day-To-Day players stay dressed. Whether a lineup rebuild runs after a scratch
   posted at about T-25 is UNVERIFIED.
3. Lead, not engine work: E3 found the Poisson period-spread surface beats Kalshi's mid on log loss in the preseason
   (fails Bonferroni) and leans that way in the regular season (-3.7 [-7.7, +0.1], 140 games). The forward re-read is
   owed after 30 more regular-season days (`#741` (b)).

## MLB (no owner lane; the season is over, so this waits for the 2027 pre-season)

1. **`sim.joint` understates same-batter HR pairs** (E4): HR x RBI sim +0.56 vs copula +0.95 and realised >= 0.95;
   HR x TB +0.48 vs realised +0.80; HR x hits +0.31 vs +0.63. That is why the copula beats the sim on nested pairs
   (+0.0052 [+0.0009, +0.0095]).
   - Cause: `2·sin(pi·rho_S/6)` maps a Spearman of COUNTS, and ties in a zero-inflated count attenuate it.
   - Fix: publish the per-draw indicator correlation, or the 2x2 at the traded line. `threshold_correlation.py`
     already notes the conversion is an approximation.
2. **Opposing batters:** sim +0.014 vs realised -0.04 [-0.10, +0.03]. On hits x hits the sim is WORSE than
   independence (+0.0012 [+0.0003, +0.0022]). With market-anchored marginals the shared run environment is already in
   the price, so the residual cross-team rho should be ~0.
3. **Add `team|full|margin` and `team|full|total` labels to `sim.joint`.** One column each. They make player x winner
   and player x total testable without assumptions (batter x own-team win is a LEAD at -0.012 nats).
4. **Pitchers are not in the joint**, so pitcher Ks x anything is unreachable. Only 50 joint samples are stored, so
   team totals cannot be priced.
5. Lead, not engine work: MLB F5 spreads, one EV band at +19% on 33 contracts / 20 games, log loss fails. Next read is
   the 2027 season.

## Soccer (no owner named)

- **No engine change.** The scoreline table's dependence is calibrated: BTTS x over +0.76 vs +0.75 realised
  [+0.63, +0.85]; BTTS x draw +0.435 vs +0.43; draw x over -0.27 vs -0.24 (289 matches). It is the one sim the
  decision engine will use for combo correlation (result / total / BTTS).
- Availability (E5): no injury feed; the confirmed XI arrives about a minute before kickoff.

## Every sport

- **Persist a (margin, total) joint.** No sport does today. Basketball's `score.dist` and football's smartsim2 keep
  margin and total separately; MLB keeps 50 score samples. Without it, winner/spread x total combos cannot be priced
  from any sim artifact.

---

**Re-test path.** After a fix lands, re-run the matching script with the same constants and record the reading in the
owner lane and the todo item (`#740` (d) for E4, `#741` (b) for E3). The forward Kalshi combo capture
(`kalshi-combo-capture`, `#742`) makes E4's venue test runnable after a month; the NBA minutes fix makes it re-runnable
sooner.
