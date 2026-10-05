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
