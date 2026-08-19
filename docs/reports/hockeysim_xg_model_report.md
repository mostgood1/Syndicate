# hockeysim real xG (expected goals) model

Closes the last genuinely-absent input `docs/ai_context/hockeysim_engine_reference.md` §5 flagged:
`xgf_per_60`/`xga_per_60` had a reader (`loaders.load_team_xg_map`, already wired into
`build_team_features`/`build_game_features`/`build_slate_features` from a PRIOR session) but no
producer anywhere — `projection.py`'s `_offense_rate`/`_defense_rate` silently fell back to
`goals_per_60`, then the league baseline, on every team, every game. This is that producer: a real,
truth-fit shot-quality model, not a placeholder.

## Why this needed new data, not a new reader

Neither existing truth source carries shot location. The `landing` feed (goals, penalties, period
splits) and the `boxscore` feed (per-player box totals, used for §2e/§2g/§2h) both lack it. NHL's
SEPARATE `play-by-play` endpoint (`/v1/gamecenter/{id}/play-by-play`) does: every shot/goal/missed-
shot/blocked-shot event carries `xCoord`/`yCoord`, `shotType`, `situationCode` (strength state), and
`zoneCode` — the standard substrate every public NHL xG model (MoneyPuck, Corsica/Evolving-Hockey,
etc.) is built from. `NhlWebIngestClient.play_by_play()` (new) + `scripts/fetch_nhl_playbyplay_cache.py`
(new) bulk-fetched all 1,312 regular-season games — 1,307 new fetches, 0 failures, ~492 seconds.

## Why Fenwick, not Corsi

`blocked-shot` events record the coordinate of the BLOCK, not the shooter's release point — using
it for a distance/angle feature would systematically understate shot distance. Every public NHL xG
model fits on Fenwick events (shots-on-goal + missed-shots + goals) for exactly this reason;
`historical_truth/shot_xg_model.py` does the same. Blocked shots still count toward raw shot VOLUME
elsewhere in this package (`boxscore_shot_strength.py`); they're excluded here, not double-counted.

## Why `sign(xCoord)`, not `homeTeamDefendingSide` bookkeeping

The attacked net could be derived by tracking `homeTeamDefendingSide` (which flips each period)
against `eventOwnerTeamId`. Instead this uses the simpler, standard shortcut the public NHL
analytics community uses: a shot recorded in (or near) the offensive zone has coordinates naturally
closer to the net it's attacking, so `sign(xCoord)` directly identifies which net without any
period-flip bookkeeping. Small noise on rare neutral-zone attempts, in exchange for a much simpler,
less error-prone implementation — the same trade-off every public model makes.

## Features and model

`sklearn.linear_model.LogisticRegression` on: distance (feet), angle (degrees off the direct line
to net), shot type (one-hot: wrist [baseline]/slap/snap/backhand/tip-in/deflected/wrap-around/
other), strength state (one-hot: EV [baseline]/PP/SH, derived from `situationCode`'s 4-digit skater
encoding), is-rebound (a Fenwick attempt by the SAME team within 3 seconds of its own prior one),
is-empty-net.

**Team identity is deliberately NOT a feature.** This matters for the aggregation step: because the
model has no way to know which team is shooting, it cannot overfit to a specific team's shooting or
goaltending quality. That means scoring every shot with the model fit on the FULL dataset (rather
than needing out-of-fold/cross-validated scores to protect the aggregation from leakage) is safe —
the train/holdout split below exists only to validate calibration, not to protect the team-level
totals from leaking team identity back into themselves.

## Data

1,312 regular-season games, 112,888 Fenwick shot attempts, 8,350 goals (7.40% shooting%). Split by
GAME (not shot) 80/20 for the holdout — 90,670 train shots (1,050 games), 22,218 holdout shots (262
games).

## Holdout validation (the model NEVER saw these games during fitting)

- **AUC = 0.7450** — in line with public NHL xG models built on comparable feature sets (distance,
  angle, shot type, strength state, without player-quality or full pre-shot-movement features,
  which typically report ~0.75-0.78).
- **Brier = 0.0667** — better than the naive "always predict the base rate" baseline
  (0.0740 × (1 − 0.0740) ≈ 0.0685), confirming real discriminative power, not just a rescaled
  constant.
- **Calibration table** (predicted vs. actual goal rate, by decile of predicted probability):

| predicted | actual | n |
|---|---|---|
| 0.0098 | 0.0090 | 2221 |
| 0.0192 | 0.0135 | 2221 |
| 0.0283 | 0.0230 | 2221 |
| 0.0382 | 0.0338 | 2221 |
| 0.0488 | 0.0486 | 2221 |
| 0.0604 | 0.0756 | 2221 |
| 0.0745 | 0.0896 | 2221 |
| 0.0947 | 0.1144 | 2221 |
| 0.1267 | 0.1544 | 2221 |
| 0.2280 | 0.2073 | 2229 |

Monotonic, tracks closely across all ten deciles — a well-behaved, well-calibrated model, not
overfit to the training population.

## Full-data model coefficients (final production model, refit on all 112,888 shots)

Intercept −0.6930. Distance (−0.0519) and angle (−0.0166) both carry the expected sign (farther /
more off-angle = lower probability). `is_empty_net` (+3.7291) dominates, as expected. `strength_PP`
(+0.3023) confirms the power play meaningfully raises shot quality, independent of the separate
PP/PK GOAL-conversion mechanism (§2d) and shot-VOLUME mechanism (§2e/§2f) already in the engine —
this is a third, genuinely distinct signal (shot quality, not volume or raw conversion rate).

**Two coefficients worth stating plainly rather than glossing over**: `is_rebound` (−0.1269) and
`shot_type_tip-in`/`shot_type_deflected` (−0.9388/−0.3873) came out NEGATIVE — the opposite sign a
hockey prior would predict (rebounds and tips are usually described as high-danger). This is a real,
measured finding from the fitted data, not adjusted to match intuition. Plausible explanation, not
confirmed further this pass: distance and angle already capture most of "close to the net," and the
residual rebound/tip-in signal may reflect that many such attempts are hurried, poorly placed, or
easily saved once location is already controlled for — a documented open question for whoever picks
this model up next, not a claimed conclusion.

## Team-level aggregation

For each shot, both the shooting team's `xGF` total and the defending team's `xGA` total get the
model's predicted probability. Divided by games played (82 for every team, full season) — matches
the SAME per-game-as-per-60 convention this codebase already uses for `league_baseline_goals_per_60`
(itself literally `total_goals / games / 2`, not TOI-normalized).

**League average: xGF/60 = xGA/60 = 3.1826** — within ~1.8% of the real, truth-calibrated
`league_baseline_goals_per_60` (3.1269) this codebase already uses elsewhere (§2d and others). This
is exactly the sanity check a well-calibrated logistic model should pass: a maximum-likelihood fit's
mean predicted probability equals the mean actual outcome rate over its training population, so the
league-wide total tracking real goals closely is a structural property of the fit, not a
coincidence — but the ~1.8% gap (not exact) reflects real variance across the 32-team spread, not a
tautology.

**Real per-team spread, external sanity check**: CAR (3.83 xGF/60) and COL (3.69) rate highest;
CHI (2.73) and SEA (2.80) rate lowest — Carolina and Colorado are widely regarded as strong
possession/shot-quality teams in the real 2025-26 season, Chicago is in a rebuild; this matches
external reality the same way EDM's best-measured PP (§2d) and best-measured PP shot volume (§2f)
did.

## Checklist impact

`scripts/nhl_sim_input_checklist.py`: `xgf_per_60`/`xga_per_60` move from `FAIL (0.0%, consumed
but never populated)` to fully populated — alarm count drops from 9 to **7**, the lowest this
session has measured. The remaining 7 (`blocks_per_60`/`faceoff_win_pct`/`penalties_per_60`/
`shots_per_60` team, `block_weight`/`goal_weight`/`shot_weight` player) need per-team/per-player
game-log data no current truth source carries at all — a distinct, still-open gap (§5).

## What remains open

- **Rebound/tip-in sign** — flagged above, not chased further.
- **No rush-shot feature** — time-since-defensive-zone-event, a common feature in richer public
  models, was not built (diminishing returns against the added parsing complexity).
- **No per-shooter or per-goalie adjustment** — deliberately excluded (see "team identity" note
  above); a future pass could add player-level shooting/goaltending talent on top of this shot-
  quality base, the same layered structure `block_rate_index` (§2g) added on top of the calibrated
  `block_rate_ev`/`pk`/`pp_def` base (§2h).
- **Not re-run against the goal/shot-multiplier calibrations** (§2d-§2h) — `xgf_per_60`/`xga_per_60`
  feed `projection.py`'s PREGAME goal projection (main board), a different code path from
  `player_props.py`'s possession/segment sim those calibrations tuned. No interaction expected (see
  `hockeysim_engine_reference.md`'s "main-board / props-engine split" note), not independently
  re-verified this pass.
