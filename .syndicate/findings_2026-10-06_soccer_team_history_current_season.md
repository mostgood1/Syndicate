# Soccer current-season team history — how to rate few-match (promoted) teams

Lane `soccer-team-history-current-season` (session 43e4d5fe). Arms, primary metric and decision rule were
pre-registered in the lane block (`28bceaf6`, 2026-10-06) before any number was computed.

## Why this was needed

Production team ratings for 2026-27 held no 2026-27 match (findings 2026-10-05 soccer_xg_totals_bias). The
refresh step that fixes that (`refresh_odds_sources._soccer_current_history_step`, `fa6c3506`, OFF unless
`SYNDICATE_SOCCER_CURRENT_HISTORY=1`) changes one case nothing had measured: a promoted club a few matches in
stops getting `PROMOTED_TEAM_RATING` (−0.18/−0.18) and is rated from those few rows, because
`compute_team_ratings` (`loaders.py:395-419`) applies no shrinkage.

## Data

Scratch harness copy (`C:/tmp/soccer-lpb/rrF`), leak-free per-day as-of, 300 sims, TRUE close (football-data
`AvgC*`, both seasons in one file per league). Ratings include current-season rows (2026-27 fetched 10-05/10-06:
`teams_2026.csv` for the xG five, `matches_2026.csv` for the goals four; both sources stop at 2026-09-20).
Absent teams filled exactly as production's `_fill_promoted`. Scored: matches where either side has 1–19 rated
rows as of the day (sides with 0 rows get the default in every arm and cannot discriminate).

| family | n |
|---|---|
| matches selected (count, no sim) | 461 (2025-26 364, 2026-27 97) |
| scored, all three arms, paired | 461 |
| with TRUE close | 461 |

## Result (paired per match, 2,000-rep bootstrap)

| set | n | RAW | DEFAULT | BLEND | close | RAW−DEFAULT | BLEND−DEFAULT |
|---|---|---|---|---|---|---|---|
| **ALL (primary)** | 461 | 0.6436 | **0.6269** | 0.6283 | 0.6066 | **+0.0166 [+0.0015, +0.0321]** | +0.0014 [−0.0091, +0.0109] |
| 2025-26 | 364 | 0.6450 | 0.6286 | 0.6310 | 0.6061 | +0.0164 [+0.0024, +0.0306] | +0.0024 [−0.0088, +0.0125] |
| 2026-27 | 97 | 0.6380 | 0.6205 | 0.6181 | 0.6084 | +0.0175 [−0.0338, +0.0671] | −0.0024 [−0.0306, +0.0242] |
| xG five | 274 | 0.6467 | 0.6248 | 0.6301 | 0.5964 | +0.0219 [+0.0035, +0.0407] | +0.0054 [−0.0068, +0.0173] |
| goals four | 187 | 0.6390 | 0.6301 | 0.6256 | 0.6215 | +0.0089 [−0.0171, +0.0342] | −0.0045 [−0.0231, +0.0132] |

(1X2 Brier; lower is better.) O/U 2.5: no arm differs anywhere (ALL: RAW−DEFAULT −0.0006, BLEND−DEFAULT −0.0016,
both CIs span 0). RAW−BLEND +0.0153 [+0.0043, +0.0281].

**DECISION (pre-registered rule): ship DEFAULT** — neither RAW nor BLEND beats it with a CI wholly below 0. The
expectation "few-match raw ratings are noise" is CONFIRMED for RAW (worse than both alternatives with CIs
excluding 0); BLEND and DEFAULT are indistinguishable, so the simpler one ships.

**Consequence:** turning `SYNDICATE_SOCCER_CURRENT_HISTORY` on WITHOUT the DEFAULT gate would make 1X2 worse on
promoted teams' matches by about +0.017 Brier. The flag must not be enabled until production gives a team with
< 10 rated rows `PROMOTED_TEAM_RATING`. That gate belongs beside `_fill_promoted` in
`scripts/build_soccer_artifacts.py` (claimed by lane `soccer-corners-model-rebuild` — needs a user-approved
cross-lane write).

Reproduce: `py -3 C:/tmp/soccer-lpb/score_few.py` (output `score_few_final.out`); arms via
`SOCCER_BT_FEW_MODE={raw,default,blend} SOCCER_BT_ONLY_FEW=1` on the patched harness in `C:/tmp/soccer-lpb/rrF`.
