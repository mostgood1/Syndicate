# H2 — season-metric agreement term in the Layer 2 score: pre-registered backtest

Lane `intelligence-evidence-coverage`, session 13ac7622. Run 2026-10-07 ~13:05–13:45 CDT by a background agent, read-only, Idle priority. Nothing edited, committed, pushed or deployed by the run. Raw output: `C:\tmp\l2score_season\h2_output.txt` (numbers below checked line-for-line against it).

## Hypothesis (pre-registered in the lane block before any number, unchanged)

H2: adding a season-metric AGREEMENT term to the Layer 2 board score improves fee-net CLV of the top 25 per date x sport slate.

- Game sides only (h2h / spread): `term = z(pick primary metric) − z(opponent)`; NBA/WNBA net rating, NHL xG share, NFL offense+defense EPA, NCAAF SP+ margin.
- Variant = `sc + clip(w·term, ±1.5)`. **Primary w = 0.5**; 0.25 / 1.0 sensitivity only.
- Top 25 per slate, ≤ 3 picks/game, paired variant − live fee-net CLV (pp), 95% CI by 2,000 bootstrap resamples over GAMES (seed 20261007).
- MET if CI > 0 with ≥ 50 games; NOT MET if CI < 0; else INCONCLUSIVE. Prior: NULL.

## Code and data

- Pinned SHA `7d01834eee01dcf63fc43fef3ab662583bb953f6`; snapshot `git archive ... scripts syndicate pipeline requirements.txt` -> `C:\tmp\l2score_season\snap` (+ NCAAF team registry, `.env`).
- Population: replicates `C:\tmp\l2score\v2\v2_clv_contrast.py` — `clv_openings` joined to pregame same-book closes from `/api/ops/clv/report`; `sc = blended_score` at fee-net EV, movement 0; fee-net CLV = `100·(imp(close) − (imp(open) + fee))`. The recorder `pull` rows carry no closes or team names, so could not be used.
- Pull: `py -3 C:\tmp\l2score_season\fetch.py 2026-09-21 2026-10-06 nba,wnba,nhl,nfl,ncaaf` (reuses `C:\tmp\l2score\oos`; Render-era days exist only in that cache). Analysis: `py -3 C:\tmp\l2score_season\h2_season_term.py`.
- Window: slate (= sighting) date 09-22..10-06.

## Point-in-time — what could decide

1. **NCAAF.** The fleet's `sp_ratings_2026.json` was re-fetched **2026-10-07T17:58:46Z, during this run**, overwriting the copy it held (no backup). **Correction to the run's own report:** that overwritten copy DID carry `fetched_at 2026-09-30T23:40:12Z` — read directly from the file ~17:3xZ the same day and in the refresh-worker's `[sp_ratings] ... source=cache` lines; the run attributed that stamp only to `sp_ratings_inseason_blend_2026.json` week 4, which also carries it. So the pre-registered table existed and was lost to an in-place refresh. **Substitute used:** the git-mirror copy fetched 2026-09-05T21:43Z — point-in-time valid for every slate, but stale. This substitutes an INPUT, not the rule; recorded as such. Also reported: the 10-07 fetch [LEAKY] and the in-season blend by `generated_at` [deviation].
2. **NFL.** No week-3 ratings file anywhere -> week-3 slates excluded (7 slates, 16 games, 19,403 rows). The wk4 file is stamped 10-05T04:27Z but its 30 team ratings are byte-identical to `removed/2026-10-01/smartsim2_ratings_2026_wk5.json` (10-01T15:29Z), so its content predates week 4 and was used. KC/CAR exist only in the later build.
3. **WNBA.** Newest asof strictly before the slate: 09-22..09-27 use git-mirror asof_0830 (18–21 games/team); 09-30..10-04 fleet asof files with 11–15 games/team. Playoff games.
4. NBA and NHL: preseason throughout -> do not decide. MLB, soccer: out of scope (no team table in the design).

## Funnel

| sport | rows | with fee-net CLV | game sides | both teams resolved | games | slates |
|---|---|---|---|---|---|---|
| NBA | 2,266 | 2,266 | 1,085 | 1,085 | 12 | 4 |
| WNBA | 19,847 | 19,808 | 5,814 | 5,814 | 22 | 8 |
| NHL | 10,047 | 10,047 | 548 | 548 | 91 | 12 |
| NFL | 42,209 | 42,184 | 1,407 | 592 (wk4 only) | 32 (16 PIT) | 13 (6 PIT) |
| NCAAF | 32,258 | 32,201 | 11,459 | 10,747 (93.8%) | 131 | 11 |

NCAAF unresolved = FCS opponents (not in FBS SP+); those rows keep `sc`. The first join pass silently mis-matched Texas A&M->Texas, NC Central->North Carolina, Houston Baptist->Houston, Texas Southern->Texas and missed UMass, San José St, Southern Miss, App St — fixed; all pairs in `C:\tmp\l2score_season\ncaaf_names.txt`.

**Reachability (w = 0.5):** 57/434 top-25 picks differ on 19 of 25 deciding slates — not inert. The ±1.5 cap clips ≤ 0.5% of terms (NHL 3.1%).

## Results, w = 0.5 (variant − live, fee-net CLV pp)

| stratum | diff [95% CI] | games | slates | picks differ | verdict |
|---|---|---|---|---|---|
| WNBA | −0.179 [−0.443, +0.058] | 22 | 8 | 11/66 | INCONCLUSIVE |
| NFL wk4 | +0.003 [−0.028, +0.039] | 16 | 6 | 5/128 | INCONCLUSIVE |
| NCAAF SP+ 09-05 | −0.018 [−0.213, +0.209] | 102 | 11 | 41/240 | INCONCLUSIVE |
| **OVERALL deciding** | **−0.036 [−0.171, +0.088]** | 140 | 25 | 57/434 | **INCONCLUSIVE** |
| NCAAF ≥ 10-01 | −0.024 [−0.377, +0.342] | 40 | 4 | 11/78 | subset |
| NCAAF 10-07 fetch [LEAKY] | −0.028 [−0.267, +0.185] | 102 | 11 | 48/240 | no verdict |
| NCAAF blend [deviation] | −0.055 [−0.432, +0.377] | 40 | 4 | 16/78 | no verdict |
| NBA [preseason] | −2.130 [−5.372, +0.848] | 12 | 4 | 9/34 | does not decide |
| NHL [preseason] | +0.183 [−0.056, +0.495] | 89 | 12 | 39/229 | does not decide |
| Overall incl. preseason | −0.066 [−0.277, +0.133] | 241 | 41 | 105/697 | — |

## Sensitivity (no verdict drawn)

| stratum | w = 0.25 | w = 1.0 |
|---|---|---|
| WNBA | −0.084 [−0.278, +0.111] | −0.984 [−2.181, −0.105] |
| NFL | −0.006 [−0.068, +0.038] | +0.010 [−0.041, +0.096] |
| NCAAF | −0.025 [−0.133, +0.079] | −0.146 [−0.512, +0.223] |
| OVERALL deciding | −0.028 [−0.102, +0.042] | −0.227 [−0.524, +0.027] |

More weight is worse, not better.

## Verdict

**INCONCLUSIVE for WNBA, NFL, NCAAF and overall.** MET was unreachable for WNBA and NFL (< 50 games). The overall interval excludes any gain above +0.09 pp, consistent with the NULL prior and with `[sim-weight-clv-decomposition]` / `[ncaaf-payload-vs-market]`: the market already prices team strength. **No score change is recommended.** Season metrics stay in the explanation layer only (`ced2618f`).

## What would make it decidable

- **Keep dated copies of rating tables.** The refreshers overwrite in place; that destroyed the 09-30 SP+ copy (mid-run) and any NFL wk3 file.
- NCAAF needs ~4x the games (half-width ~0.21 pp at 102 games) to resolve a 0.1 pp effect — ~6 more Saturdays with point-in-time tables.
- WNBA: undecidable this season (partial asof tables to 10-06; playoffs cannot supply 50 games).
- NBA/NHL: regular-season slates with current-season tables refreshed point-in-time.
