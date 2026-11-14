# NHL live score effects: weakening them does not help the priced moneyline (todo #773, lane nhl-live-score-effects)

2026-11-14, replays 23:00-23:34Z (5:00-5:34 PM CST). Session 87074b1f. READ-ONLY on production; nothing priced, published, pushed as code or loaded. User: "Yes, fix it" (the mid-game comeback bias the re-grade left over). Pass/fail pre-registered on main before any replay (`80f291530`).

**Verdict: FAIL on the pre-registration (criteria 3, 4 and 5). Nothing ships.**

- **What worked:** a live-only scale on the engine's dynamic score effects, fit walk-forward, picks scale 0 (no score effects) on 25 of 30 out-of-sample dates, and it closes the mid-game margin gap.
- **What failed:** the PRICED moneyline gains nothing out of sample. The early margin gets too wide, and the puck line and the total come out slightly worse.
- **The 11-11 diagnosis is falsified for its headline cell.** At P2 10:00 with a two-goal lead, the model gives the trailer 0.173 with the score effects and still 0.152 with none at all. The observed rate is 0.092.
- **The bias itself is not established out of sample.** Today's engine's mid-game gap has a game-bootstrap interval that includes 0.

## What was run

- **Code:** production's NHL code (fleet HEAD `8553a38cc`; its `syndicate/features/nhl` and harness equal `origin/main`'s), plus one knob:
  - `SimConfig.score_effect_scale` multiplies `_score_effect_delta`, the trailer's shot-rate push.
  - It is passed only by `live_resim` (`NHL_LIVE_SCORE_EFFECTS`, switch `SYNDICATE_NHL_LIVE_SCORE_EFFECTS`) and replayed by `--score-effect-scale`.
  - At 1.0 it is today's engine seed for seed (tested). The last-minutes empty-net block is not scaled.
  - The code was run from a WSL copy of the worktree (md5 `live_resim` `0b2f2585c1ca`, `engine` `c073f633b089`, harness `a6f17b7bf1d7`).
- **Data:** a FROZEN copy of the fleet's `nhl_source`, 2,783 files, equal to the live root file for file at the 22:22:46Z rates (`team_rates` md5 `3919120c477e`).
  - The live root's rates were rewritten at 21:12:35Z and again at 22:22:46Z today, so the live root cannot hold one version through a run.
  - All three arms read the same version at start and at end.
- **Arms:** scale 0, 0.5 and 1.0 (1.0 = today).
  - Each ran under live-odds-worker's environ at nice 19, PYTHONHASHSEED=0, 200 sims, with seeds fixed per game x cutoff, `--endgame production`.
  - Every other NHL live switch was at production's default.
  - 303 games / 44 dates (10-01..11-13), 2,424 states per arm, 0 refused.
- **Re-fits:** the end-game p and the total keep were re-fit per arm, because they absorb late play. The end-game's full-sample p is 0.32 / 0.36 / 0.40 at scale 0 / 0.5 / 1.0 (ramp 90 s throughout).
- **PROVENANCE: LEAKY**, as before: the rates contain every graded game.

## The pre-registered test

| criterion | result | |
|---|---|---|
| (1) walk-forward picks 1.0 on a majority of the 30 OOS dates (10-15..11-13) -> FAIL | 0.0 on 25, 0.5 on 1, 1.0 on 4 | **PASS** |
| (2) OOS pooled mid-game (P2 20:00 / P2 10:00 / P3 20:00): margin gap within +-0.10 goals, P(trailer wins) gap within +-0.02, leads 1 and 2 | chosen +0.022 / +0.035 goals, -0.015 / -0.016 | **PASS** (point estimates) |
| (3) OOS paired moneyline Brier and log loss, chosen - today, 95% upper < +0.0005; no cutoff wholly above 0 | Brier +0.00010 [-0.00097, +0.00122], log loss +0.00219 [-0.00223, +0.00817]; no cutoff wholly worse | **FAIL** |
| (4) full sample at scale 0, end-game 0.32 / 90: the re-grade's four criteria, and paired +-1.5 Brier vs production today upper < +0.001 | all four pass; paired +0.00066 [-0.00038, +0.00178] | **FAIL** |
| (5) total CRPS at a re-fit keep (0.86 / 420 s) vs production today (0.85 / 240 s), upper < +0.003 | +0.0008 [-0.0026, +0.0042] | **FAIL** |

- (3), (4) and (5) fail their NON-INFERIORITY bounds. None of them shows a harm beyond noise.
- What they show is that the change buys nothing on the number that is priced, and gives up a little on the displayed ones.
- No per-cutoff refusal fired, so the pre-registered A/A arm was not needed.

## What the arms show

- **The mid-game centre does move as the hypothesis predicted.** Out of sample on 204 games, the pooled mid-game remaining-margin gap (observed - model) goes:
  - from +0.199 [-0.082, +0.519] to +0.022 with a one-goal lead;
  - from +0.267 [-0.075, +0.596] to +0.035 with a two-goal lead.
- **But today's own gap is not distinguishable from zero.** Its intervals include 0, and so do the P(trailer wins) gaps: -0.035 [-0.106, +0.042] and -0.030 [-0.092, +0.037].
  - The 11-11 note "consistent with score effects that pull too hard toward a tie ... so it is real" pooled STATES. States are several per game, not independent. Bootstrapped by game, out of sample, the bias is about 1.2-1.4 SE.
- **The headline cell does not follow the score effects.** At P2 10:00 with a two-goal lead (n=65, 6 comebacks), P(trailer wins) is:

  | scale | model | observed |
  |---|---|---|
  | 1.0 | 0.173 | 0.092 |
  | 0.5 | 0.160 | 0.092 |
  | 0 (no score effects) | 0.152 | 0.092 |

  - With a one-goal lead it is 0.317 / 0.305 / 0.295 vs 0.256.
  - Removing the score effects entirely closes about a quarter of the gap there. The rest is sample noise or something else.
- **The score effects also hold the early WIDTH.** Width (actual RMSE over model sd; < 1 is a model too wide):

  | scale | P1 20:00 | P2 20:00 | P2 10:00 | P3 20:00 |
  |---|---|---|---|---|
  | 1.0 | 1.024 | 1.041 | 0.962 | 0.987 |
  | 0 | 0.906 | 0.955 | 0.887 | 0.942 |

  - Their pull toward a tie is mean reversion. Without it, leads persist and the early margin spreads 5-11% too wide. This is the 2026-11-11 learning (gate a width change on the distribution) showing up as predicted.
- **Leader extension goes the other way.** With the score effects off, P(leader by 2+) mid-game becomes over-predicted: P2 20:00 one-goal lead 0.470 vs 0.421 (it was 0.428).
- **Moneyline, full sample (in-sample for the scale):** Brier 0.13256 at scale 0 vs 0.13289 at 1.0 (-0.00033). Out of sample it is +0.00010. The walk-forward's preference for 0 is real on prior dates and does not carry to the next date.

## What this means

- **The live NHL engine's score effects stay as they are.** The dynamic delta is not mis-sized in a way the priced moneyline can see on 303 games.
- **The "mid-game comeback bias" is downgraded from a defect to an unestablished residual.** It is about 1.3 SE by game out of sample, and the strongest cell barely responds to the mechanism blamed for it.
- **No further engine work on it is warranted at this sample size.** The next NHL live gate is unchanged: production's displayed number against the market's de-vig from the v6 recorder, on the fixed engine (about 100 games, roughly 11-26).
  - The recorder grades the moneyline against the MARKET, which this replay cannot. If the market prices comebacks lower than the model at these states, that is where it will show.
- **The knob is not on main.** `score_effect_scale` (engine + runtime + `live_resim` switch + harness `--score-effect-scale` + tests) is kept on local branch `lane/nhl-live-score-effects-knob`, unpushed. At 1.0 it is a no-op, and production does not need it.

## Reproduce

```
wsl -- bash /mnt/c/tmp/nhlrec/se_prepare.sh          # code copy + frozen nhl_source (re-freezes at TODAY's rates)
wsl -- bash /mnt/c/tmp/nhlrec/se_run.sh 0.0 2        # and 0.5, 1.0
wsl -- bash /mnt/c/tmp/nhlrec/se_grade.sh            # -> C:\tmp\nhlrec\se\compare.txt
```

Outputs: `C:\tmp\nhlrec\se\s{0.0,0.5,1.0}\` (`rows.jsonl`, `report.txt`), `C:\tmp\nhlrec\se\compare.txt`. Diagnostic that motivated the lane: `C:\tmp\nhlrec\regrade\diag_comeback.py`.
