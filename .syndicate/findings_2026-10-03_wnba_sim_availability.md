# FINDINGS — WNBA SmartSim minutes: the sim simulated players who were not playing (fix #2)

**Lane** `wnba-sim-availability`, session `39b666bb`. **Date** 2026-10-03. **No deploy; flag default OFF.**
Follows `findings_2026-10-02_wnba_lines_props_backtest.md` §7 fix #2. Substrate: as-of re-runs of fleet code
`9a7f0d2f` + this lane's hook (scratch copies; evidence about the CODE), ESPN box scores, OddsAPI historical book.

## 0. Headline

1. **The minutes shortfall was availability, not the allocation function.** Of every 200 team minutes the sim handed
   **42.6 to players who did not play**: 29.05 to players absent from the box score (inactive/injured, 2.28 per
   team-game) and 13.55 to listed DNPs (662 team-games). Players who played got 157.4 → the −2.96 min/player bias.
   The 10-01 bench-first allocation fix (`b983a735`) was already in this code; it re-divides a pool that was wrong.
2. **Rule:** a player who did not appear (MIN > 0) in the team's last game is left out of that team's pool. Selected
   on May–July by net non-player minutes removed (27.0 vs 25.2 for "last 2"), confirmed on Aug–Sep (32.9 vs 31.1) and
   the playoffs.
3. **Held out, through the real engine at 500 sims (115 games, paired):** played-player minutes bias **−3.15 →
   +0.15**, MAE **−0.90 [−1.07, −0.73]**; points bias **−1.50 → +0.03**; book-line Brier improves on every market
   but threes (points −0.022 [−0.034, −0.011], PRA −0.044 [−0.057, −0.032]).
4. **Coverage GAINS, not loses**: the pool is capped (~11/team), so removing non-players let **369 players who did
   play** into it (mean 11.5 min); 83 real player-games were dropped (returning after one missed game). Net **+286**
   projected real player-games over 124 games.
5. **Still not at the player's own average or the book.** Points dMAE vs own average +0.31 → **+0.20 [+0.11, +0.29]**;
   PRA +0.52 → **+0.13 [−0.000, +0.28]** (no longer distinguishable); book-line Brier 0.280 vs book 0.249.

## 1. Rule selection (`scripts/fit_wnba_sim_availability.py`)

Per team-game, non-player sim minutes REMOVED vs real-player sim minutes wrongly removed:

| rule | train (414 tg) removed / wrong | test Aug–Sep (230 tg) removed / wrong | real players wrongly dropped (test) |
|---|---|---|---|
| missed last 1 | 32.4 / 5.4 | **38.9 / 6.1** | 79 (they played 19.5 min) |
| missed last 2 | 27.8 / 2.7 | 34.2 / 3.0 | 40 |
| missed last 3 | 24.6 / 1.5 | 30.7 / 2.2 | 27 |
| never played for team (≥3 team games) | 14.8 / 0.2 | 12.4 / 0.05 | 1 |

## 2. Engine re-run (held out), paired by (game, player, market) — `--compare`

| market | n | bias base → variant | d MAE [95% CI] | book n | d Brier at book line [95% CI] | Brier variant / book |
|---|---|---|---|---|---|---|
| minutes | 1,708 | −3.146 → +0.152 | **−0.899 [−1.068, −0.730]** | | | |
| points | 1,708 | −1.497 → +0.034 | −0.077 [−0.169, +0.015] | 1,112 | **−0.0223 [−0.0341, −0.0111]** | 0.280 / 0.249 |
| rebounds | 1,708 | −0.553 → −0.162 | **−0.053 [−0.080, −0.028]** | 957 | **−0.0171** | 0.276 / 0.245 |
| assists | 1,708 | −0.568 → −0.288 | **−0.034 [−0.052, −0.014]** | 726 | **−0.0152** | 0.280 / 0.248 |
| threes | 1,708 | −0.037 → +0.085 | +0.029 [+0.017, +0.041] | 737 | +0.0021 [−0.0049, +0.0091] | 0.256 / 0.243 |
| PRA | 1,708 | −2.618 → −0.416 | **−0.357 [−0.472, −0.244]** | 825 | **−0.0436 [−0.0572, −0.0316]** | 0.298 / 0.249 |
| PR | 1,708 | −2.050 → −0.128 | **−0.210 [−0.313, −0.108]** | 885 | **−0.0303** | 0.293 / 0.250 |
| PA | 1,708 | −2.065 → −0.254 | **−0.211 [−0.315, −0.104]** | 727 | **−0.0283** | 0.287 / 0.250 |
| RA | 1,708 | −1.121 → −0.450 | **−0.114 [−0.151, −0.078]** | 631 | **−0.0288** | 0.275 / 0.249 |

Playoffs (9 games, 146 rows): same direction — minutes −0.83 [−1.30, −0.33], points MAE −0.28 [−0.47, −0.08], PRA
Brier −0.030 [−0.048, −0.014]; rebounds/threes flat. Threes gets slightly worse on the mean (more minutes → more
attempts, bias flips to +0.09): a rate question for fix #3, not an availability one.

## 3. The change

- NEW `syndicate/features/shared/wnba_sim_availability.py`: reads `boxscores_history.csv` (WNBA processed root; only
  games strictly before the slate), and ADDS to the sim's existing excluded map every player with team history who
  did not play in the team's last K games (K = 1; `SYNDICATE_WNBA_SIM_AVAILABILITY_MISSED_GAMES`, bounded 1..5). Never
  overrides a `playing_today` flag; never removes an injury/league-status exclusion. Missing/unreadable history →
  adds nothing, logs `SIM_AVAILABILITY skipped reason=...`. Never raises. WNBA only; OFF unless
  `SYNDICATE_WNBA_SIM_AVAILABILITY` is set.
- ONE call in `basketball_props_smart_sim._smart_sim_run_date_local`, right after the excluded map is built.
- Input is production's own daily `boxscores_history.csv` -- already on the disk the sim reads; no new artifact.
- Reachability: the re-run logged `SIM_AVAILABILITY applied ... added=188-193` per date; pools 22.0 → 20.0 players per
  game; the paired table above is the off != on test through the real engine. Tests: `test_wnba_sim_availability.py`
  (6), `test_fit_wnba_sim_availability.py` (1), plus existing SmartSim tests.

## 4. NOT done, needs a user decision

Enable: set `SYNDICATE_WNBA_SIM_AVAILABILITY=1` on the worker(s) running the WNBA props SmartSim and fast-forward the
fleet. Then fix #1's widths must be RE-FIT on availability-on ladders (the mean moved; mechanism vs estimator, standard
§4.4) before fix #1 is considered. Going forward production also fetches injuries daily, which this rule complements.

## 5. What is left (fix #3 territory)

With minutes right, the points mean is still +0.20 worse than the player's own average and every prop market is still
behind the book at its line. The per-minute RATE is now the error: signal slope 0.16–0.27 (backtest §3c). Threes
moved the wrong way on the mean. Fix #3 (shrink the sim's per-minute rates toward the player's own as-of rate) is next.
