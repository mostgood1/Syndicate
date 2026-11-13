# NFL quarter/half model probabilities — graded against the market and the box

`[2026-11-13, lane nfl-segment-skill, session 386d4115; todo #752; user "Yes, start #752"]`

## What #752 actually needed (corrects the todo)

#752 said NFL segment lines had "no sim view" and NFL full-game spreads/h2h carried "no cover
probability". Both were already built:

- **Segment pricing.** `nfl_segment_projections.py` (`ace49609b`, 2026-10-08) prices h1/h2/q1-q4
  totals/spreads/h2h off the sim's own histograms (`smartsim2_segment_distributions_<s>_wk<w>.json`).
  - Served 2026-11-13 21:5xZ: all 46 TNF segment rows carried a sim view, `source nfl_smartsim2_segment`.
    The probability was withheld only because the game was final.
  - Sunday's segment rows were not yet captured, because the pregame tier pulls only within 6 h
    of kickoff.
- **Full-game cover probability.** It was already computed: `nfl/cards.py:2385`, plus the
  `margin_dist` repricing in the module above.

What was never done is the verification that lane `nfl-segment-model` set: "a held-out check
that the segment probabilities are calibrated **before they rank anything**". They ranked anyway,
at full weight, under a self-contradicting label:

- The producer stamped `model_skill: {"state": "unmeasured", ...}`.
- `projection_skill.normalize_existing_note` keeps ANY non-empty producer note and adds
  `status: "measured"`.
- The served rows therefore read `status: measured` with text saying "no measured market skill
  yet". There was no `established_loss_rel`, so `skill_reliability` returned 1.0, and
  `measured_market_skill` was never consulted.

## Method — pre-registered in `lanes.md` (`39fe2d752`) before any outcome was read

Grader: `scripts/nfl_segment_skill.py`.

- **Population:** NFL games that have all three of:
  - a pregame segment quote, `captured_at < commence_time`, in the fleet's
    `nfl_source/tracking/book_quotes/<date>.jsonl.gz`. Segment capture has been on by default since
    `a126ae951`, 10-22.
  - a regular-season sidecar block for the matchup.
  - a final ESPN linescore.
- **Market:** each book's LAST pregame two-sided pair, de-vigged proportionally.
  - The consensus line is the line most books quote; a tie goes to the line nearer the median.
  - The market probability is the mean of the de-vigged books at that line.
- **Model:** production's own `probability_above` over the sidecar histogram.
  - Home/over side, with the line in the away frame (home covers strictly past it).
  - h2h is segment margin > 0.
  - h2 = q3 + q4 + OT, as `segment_actuals` grades it.
  - Pushes are dropped.
- **Unit:** one observation per game x segment x market.
- **Families:** totals, spreads and h2h, each pooled over the 6 segments.
- **Test:** dBrier = Brier(model) − Brier(market), with a 95% CI from a game-clustered bootstrap
  (2,000 reps, seed 752).
- **Verdict:** beats if the CI's upper bound is < 0; loses if its lower bound is > 0; parity
  otherwise.
- **As-of:** the sidecar for week W is built from plays of weeks < W
  (`generate_smartsim2_nfl_projections.team_rating`, `before_week`). A file regenerated after
  kickoff therefore carries nothing from its own week.

## Population actually graded

- 790 quoted segment markets; 746 lines graded; 44 pushes dropped; 0 other refusals.
- **44 games:** NFL 2026 weeks 7-10, kickoffs 10-23 00:15Z .. 11-13 01:15Z.
- Spot-checked against the ESPN box, 5 of 5 correct. Example: MIA–DET Q1 3-3 against the away
  -1.5 line, so home covers.

## Result vs the market

| family | lines | games | Brier model | Brier market | dBrier [95% CI] | verdict |
|---|---|---|---|---|---|---|
| totals | 262 | 44 | 0.2548 | 0.2483 | +0.0065 [−0.0132, +0.0264] | parity (underpowered) |
| spreads | 263 | 44 | 0.2586 | 0.2497 | +0.0089 [−0.0016, +0.0200] | parity (underpowered) |
| h2h | 221 | 44 | 0.2329 | 0.2206 | **+0.0123 [+0.0017, +0.0237]** | **loses to market** |
| all | 746 | 44 | | | +0.0091 [−0.0009, +0.0196] | parity |

**No information beyond the line.** I fitted a logistic regression of the outcome on
logit(market) + logit(model). The model's weight beside the market:

| family | model weight | model calibration slope | market calibration slope |
|---|---|---|---|
| totals | +0.14 | +0.22 | +1.68 |
| spreads | −0.72 | −0.27 | +0.78 |
| h2h | −0.57 | +1.48 | +2.09 |

Every one of the 18 segment-alone CIs spans 0. The point estimates favour the market in 14 of 18.
The figures are in `measured_market_skill._NFL_SEGMENT_ALONE`.

**Hypothesis** ("loses, as the full-game numbers do"):
- **Supported for h2h.** It is the only family whose CI clears 0.
- **Not falsified for totals or spreads.** The CIs span 0 with the point estimates against the
  model, so these are parity verdicts on 44 games, not evidence of skill.

## Engine read (smartsim2, per-quarter scoring)

**Sample:** 89 games, every 2026 sidecar from weeks 4 to 10 that has a final box.

| segment | sim mean total | actual | bias [95% CI] |
|---|---|---|---|
| full | 43.6 | 46.0 | −2.4 [−5.2, +0.3] |
| h1 | 20.9 | 22.4 | −1.5 [−3.2, +0.2] |
| h2 | 22.8 | 23.7 | −0.9 [−3.0, +1.1] |
| q2 | 12.2 | 13.4 | −1.2 [−2.7, +0.1] |
| q3 | 10.2 | 9.7 | +0.5 [−0.7, +1.7] |

**The sim misplaces scoring between quarters.** Quarter share of all points:

| quarter | sim (89 games) | league 2022-25 (1,087 games, nflverse pbp, 95% CI) | 2026 actual (137 games) |
|---|---|---|---|
| q1 | 0.199 | 0.194 [0.187, 0.201] | 0.192 |
| q2 | **0.279** | **0.313 [0.305, 0.320]** | 0.292 |
| q3 | **0.234** | **0.205 [0.198, 0.212]** | 0.215 |
| q4 | 0.285 | 0.282 [0.274, 0.290] | 0.289 |

- **The halves come out the wrong way round.** The sim puts more points in H2 than in H1
  (22.8 vs 20.9); the league did the opposite in 2022-25 (22.7 vs 22.1).
- **Likely mechanism, already identified upstream:** `CalibrationProfile.halftime_kickoff` is
  OFF in production.
  - Lane `football-scenario-calibration`, H1 (2026-10-06): the team holding the ball at the half
    KEEPS it at the same spot. The sim's second half starts at the 34.6, against a real 25.8.
  - So the drive that real football ends at halftime continues, and scores, in Q3.
  - Q2 also lacks the real end-of-half surge.
  - That lane holds the switch until its joint re-fit passes.
- **For that lane:** this is the segment-market cost of the delay. h1/h2/q2/q3 pricing inherits
  a structural shift of about 3 share points.

**PIT of totals** (share of games in the outer 20%; 0.20 would be calibrated): full 0.29, h1
0.24, q2 0.27, q4 0.28, q1 0.135. The full-game and late-quarter distributions are too narrow
or off-centre. This agrees with the full-game backtest's overconfidence (`state_football.md`
`[nfl-model-accuracy-backtest]`).

## What changes (code)

- **`measured_market_skill.py`:** 18 entries, `("nfl", totals|spreads|h2h, h1..q4, pregame)`.
  - Each carries its family's pooled measurement, as pre-registered.
  - The segment's own figure rides in `segment_alone`, descriptive only.
  - Live rows get no pregame note.
- **`nfl_segment_projections.py`:** the producer no longer stamps a note.
  - `attach_projection_skill` runs after it and reads the registry.
  - A full-game spread repriced here keeps the full-game module's own note.
- **Effect on rank:**
  - h2h segment rows: `established_loss_rel` 0.00757, so `skill_reliability` is 0.962, a small
    demotion.
  - totals and spreads: `established_loss_rel` 0.0, so 1.0 and an unchanged rank.
  - All three now carry an honest verdict.
- Nothing is withheld. The user's rule is that every line is its own decision (2026-10-05).

## Owed / follow-ups

- Load on web; then a served reading that NFL segment rows carry `basis measured_market_skill`
  with the family verdict.
- Re-grade as weeks accumulate. 44 games cannot separate totals or spreads from parity; at
  roughly 14 games a week, doubling the sample takes about 3 more weeks.
- **NCAAF segment rows probably carry the same contradictory label** (not graded here).
  - `ncaaf/segment_projections._skill_note` stamps `{"state": "measured_loss", ...}`, which is
    normalised to `status: measured` with no `established_loss_rel`, so it ranks at 1.0.
  - Lane `college-segment-grade` (`50d20adcd`) is grading college segment lines right now and is
    the natural owner.

## Reproduce

Data copied read-only from the fleet to `C:\tmp\nfl_seg\` (not in git):
- `quotes\` — the date files 10-22..11-13;
- `sidecars\`;
- `linescores.json` (ESPN cache);
- `result.json` and `result.obs.json`.

```
py -3 scripts/nfl_segment_skill.py --sidecars C:\tmp\nfl_seg\sidecars --quotes C:\tmp\nfl_seg\quotes --linescores C:\tmp\nfl_seg\linescores.json --out C:\tmp\nfl_seg\result.json
```

League quarter shares: `C:\tmp\nfl_seg\qshare.py`, run in WSL over
`nfl_source/tracking/nflverse/pbp/pbp_<season>.csv`.
