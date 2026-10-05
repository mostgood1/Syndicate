# Soccer xG-league totals bias — is the goals-level over-projection real?

Lane `soccer-xg-totals-bias` (session 43e4d5fe), opened 2026-10-05. Hypothesis and falsifiers were
pre-registered in the lane block BEFORE any of the numbers below were computed.

Origin: the 2025-26 h2h-calibration backtest (findings `2026-10-02_soccer_lines_props_backtest.md`, result
2026-10-05): five xG-rated leagues, n 1,391, model mean total 2.95 vs actual 2.77; mean P(over 2.5) 0.590 vs
0.540.

## Step 1 — 2026-27 served, and 2025-26 season halves (2026-10-05)

**Data.** 2026-27: served PRE-KICKOFF builds only (latest build generated before kickoff), from the Render-era
export in the audit cache (`C:/tmp/soccer-lpb/cache/prod/recs`, pulled 10-02 — the fleet keeps only upcoming
dates' recommendation files, so nothing after Render's suspension is retained). Outcomes: audit cache
`outcomes.json`. TRUE close: football-data `AvgC>2.5` / `AvgC<2.5`, de-vigged. 2025-26: the harness dumps
(`h2h_2526_all9.jsonl`, leak-free as-of, production ratings).

Coverage (pre-kickoff rec → completed outcome → close joined):

| league | recs | outcome | close |
|---|---|---|---|
| epl | 20 | 20 | 20 |
| la_liga | 38 | 36 | 29 |
| bundesliga | 19 | 18 | 14 |
| serie_a | 20 | 20 | 20 |
| ligue_1 | 19 | 18 | 16 |
| championship / eredivisie / primeira / belgian (control) | 41 / 23 / 22 / 23 | 40 / 22 / 20 / 22 | 36 / 21 / 18 / 22 |

**2026-27, xG five, n 112 (2026-08-15..09-20):** model 2.94, actual **3.11**, bias **−0.163 [−0.511, +0.171]**;
P(over 2.5) model 0.572, observed 0.616, close 0.563. Pre-0907 −0.211 (n 56), post-0907 −0.115 (n 56).
Per league (n ≈ 18–36, every CI spans 0): epl **+0.639** [−0.25, +1.44]; la_liga −0.348; bundesliga −0.363;
serie_a −0.220; ligue_1 −0.421. Control (goals-rated four, n 104): bias −0.128 [−0.384, +0.154].

**2025-26 season halves, xG five:** Aug–Dec +0.230 [+0.093, +0.375] (n 539); Jan–May +0.148 [+0.037, +0.258]
(n 852). No sign reversal. Every league positive in both halves; largest and most persistent is EPL
(+0.298, +0.370). Control (goals-rated four): −0.047, −0.040, both no diff.

## Verdict against the pre-registration

- **Clause (1), "present in 2026-27 too": NOT SUPPORTED.** The pooled point estimate has the OPPOSITE sign
  (−0.163). The literal falsifier ("within ±0.05 of actual") does not fire, because the bias has turned
  negative rather than vanished. That is still a failure of the hypothesis, not support for it. The 2026-27
  CI (±0.34) is too wide to exclude +0.18 either, so this is **underpowered rather than refuted**: n 112 over
  five weeks.
- **Clause (2), stable across the season: SUPPORTED within 2025-26** (+0.23 then +0.15, same sign).
- **Clause (3), a 2025-26-fitted correction:** not yet tested, but step 1 already predicts its sign. The model's
  mean total is essentially CONSTANT across seasons (2.95 in 2025-26, 2.94 in 2026-27) while the actual level
  moved (2.77 → 3.11). A per-league multiplier fitted on 2025-26 (~×0.94) would move 2026-27 projections
  further from actual on the evidence so far.

**Reading.** The pattern is a model that does not track a season's scoring level, rather than a fixed
offset: flat projected totals against a moving actual. The control group shows the same (2025-26 ≈ 0 and
2026-27 −0.13). EPL is the one league with the same sign in all three readings (+0.30, +0.37, +0.64 on n 20)
and is the only per-league candidate for a level fix.

## Owed / next

- Power: a CI half-width of ~0.18 on 2026-27 needs roughly n ≈ 350 xG-league matches (total-goals SD ≈ 1.7).
  **The served history after 2026-09-20 is not retained anywhere this check can read:** the fleet prunes past
  `recommendations_*.json`. Growing n needs either retention of pre-kickoff builds or the harness run over
  2026-27 (leak-free as-of, same method as 2025-26).
- If a correction is pursued, test a season-adaptive level (as-of league scoring rate) against the static
  multiplier. The hypothesis as registered predicts the static one; step 1 points to the adaptive one.
- `league_profiles.py` is claimed by lane `soccer-corners-model-rebuild`.

Reproduce: `py -3 C:/tmp/soccer-lpb/totals_bias_2627.py` (output `C:/tmp/soccer-lpb/totals_bias_2627.out`).

## Step 2 — H-STALE: 2026-27 harness, production ratings (A) vs + current-season rows (B) (2026-10-05)

**Data.** Both arms: `scripts/backtest_soccer_h2h_calibration.py` (post `bc438e3e`), leak-free per-day as-of,
300 sims, `--since 2026-07-01`, TRUE close from football-data 2026-27 `AvgC*` (downloaded 10-05; 250/250 rows
carry it). Fixtures: `fetch_soccer_history_local.py --kind matches --seasons 2026` (250 matches,
2026-08-15..09-20; football-data and Understat both stop at 09-20). Arm A ratings: `teams_2024/2025.csv` (what
the fleet has). Arm B: + `teams_2026.csv` (Understat, 500 team-rows to 09-20). Scratch snapshots
`C:/tmp/soccer-lpb/rr27{A,B}` only; the fleet and repo `data/` untouched.

**Result, paired n 183:** 1X2 Brier vs actual **B−A −0.0063 [−0.0156, +0.0024]** (B better in 4 of 5 leagues,
Serie A −0.0180 [−0.0369, +0.0003] the largest; La Liga +0.0029). Mean total: A 2.93, B 2.94, actual 3.08 →
**bias A −0.145, B −0.138 (B−A shift +0.007 goals)**. vs TRUE close: 1X2 A +0.0198 [−0.004, +0.044], B +0.0135
[−0.009, +0.036]; O/U 2.5 Brier A +0.0098, B +0.0112.
Without wrong-club rows (below), paired n 172: B−A −0.0056 [−0.0145, +0.0038]; bias A −0.131, B −0.125.

**Verdict against the pre-registration: MIXED, by the letter** — the 1X2 CI includes 0 (not SUPPORTED), and
|bias B| < |bias A| by 0.007 (so not FALSIFIED). **In substance, H-STALE does not explain the totals bias at
all:** refreshing ratings moved the mean total by +0.007 against a bias of −0.145 (2026-27) / +0.18 (2025-26).
The 1X2 direction favours fresh ratings but is underpowered at n 183.

**Why ratings cannot move the total — the cause, file:line.** `compute_team_ratings`
(`syndicate/features/soccer/features/loaders.py:390-414`) divides every team's xG by the window's league mean
and never exports that mean: attack/defense ratings are RELATIVE. The league's scoring LEVEL reaches the sim
only through the fixed per-league constants in
`syndicate/features/soccer/sim_engine/soccersim/league_profiles.py` (conversion bases, shot frequency, etc.).
So the model's mean total is a per-league constant that does not track a season (2.95 in 2025-26, 2.94 in
2026-27, while actual moved 2.77 → 3.08), and stale vs fresh ratings is irrelevant to it. This also explains
the goals-rated control group showing the same flat pattern. **Next test (not run): an as-of league scoring
level fed into the sim (e.g. a goal-rate multiplier = as-of league goals per match / profile's implied mean),
vs the static profile, on both seasons.** `league_profiles.py` is claimed by lane `soccer-corners-model-rebuild`.

**Stale ratings remain a real input gap (separate from the totals bias):** `refresh_odds_sources._soccer_history_step`
fetches team history only when files are MISSING and only for COMPLETED seasons, so 2026-27 production ratings
contain no 2026-27 match (fleet `team_history/teams_2025.csv` ends 2026-05-24; no `matches_2026.csv`, read
10-05). Effect on 1X2 so far: −0.0063 Brier, CI spans 0.

## Defect found on the way — name resolution maps clubs onto the WRONG club

`match_team_name` (`syndicate/features/soccer/features/team_names.py`) fuzzy-matches when no exact name exists.
Measured 2026-10-05:
- **PRODUCTION (fleet, ESPN names vs production ratings): ESPN "Le Mans" → Understat "Lens".** Le Mans is
  promoted and absent from Understat history, so instead of `PROMOTED_TEAM_RATING` (−0.18/−0.18) it is priced
  with Lens's rating (attack +0.1999, defense +0.0865, 45 matches): one of the stronger sides in place of a
  promoted one, in every Le Mans match this season. Every other ESPN name in the five leagues resolves
  correctly or to None (promoted, as intended).
- **HARNESS ONLY (football-data names):** "Ath Madrid" → Real Madrid; "Paris SG" → Paris FC; "Le Mans" → Lens.
  Affected rows: 48 of 1,391 (2025-26 xG five), 10+4 of 187 (2026-27). Excluding them changes no conclusion:
  2025-26 xG five 1X2 vs close +0.0124 [+0.0052, +0.0192] (was +0.0130), O/U +0.0023 (was +0.0036, both no
  diff); all nine 1X2 +0.0195, O/U +0.0039 [+0.0010, +0.0067] (both still lose).
- No lane claims `team_names.py`. A fix changes served prices, so it is a user decision.

Reproduce: `C:/tmp/soccer-lpb/score_stale.py` (`STALE_P=C:/tmp/soccer-lpb/x_h2h27_{}.jsonl` for the
wrong-club-excluded set), `C:/tmp/soccer-lpb/le_mans.py`, `C:/tmp/soccer-lpb/espn_names.sh` (fleet).
