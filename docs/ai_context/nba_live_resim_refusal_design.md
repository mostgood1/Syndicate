# NBA live re-sim — refusal design (P3, lane `nba-native-live-resim`)

Written 2026-10-09, BEFORE the module exists, because P1 (`basketball-native-engine`) and P2
(`basketball-native-live-state`) had not landed. Plan: `docs/ai_context/basketball_live_native_plan.md`.
Template: `syndicate/features/nhl/live_resim.py`. Consumer: `syndicate/features/shared/live_gameline_join.py`.

The rule is the NHL one: **refuse rather than degrade.** Every path that cannot produce a live number
from a resumed native sim returns a named refusal. A refusal publishes a lane stamped `pregame_only`, which
`LIVE_LENS_SOURCES_BY_SPORT["nba"]` must NOT accept. A refused game is never priced off its pregame number
(`#414`), and it is never priced off the vendored tick either. There is no fallback chain.

## 1. Module shape (to build once P1 + P2 land)

`syndicate/features/nba/live_resim.py`, mirroring NHL:

| function | input | output |
|---|---|---|
| `live_state_for_game(raw)` | P2 `LiveGameState` (or the raw feed row) | `NbaResumeState` or `NbaResimRefusal` |
| `resim_live_game(inputs, state, *, sims, base_seed, deadline)` | the SAME pregame inputs object the pregame sim used, plus the resume state | result dict or `NbaResimRefusal` |
| `build_game_lens(state, result)` | one game | exactly one lane, honestly stamped |
| `build_live_lens_snapshot(date)` | slate | the shared `gameLens` snapshot, with `refusalsByReason` |

- `NbaResimRefusal(reason: str, detail: str = "")` is frozen, and `reason` is a STABLE token from the
  table below. A new failure mode gets a new token, never a reused one.
- `build_live_lens_snapshot` calls `refuse_if_compute_in_request_path("nba_live_resim_snapshot")`. It runs
  on live-odds-worker's live-lens tick and never in a request handler.
- Team names on the refusal lane come from the SAME helper as the success lane, as in NHL's
  `team_names_from_score_row`. A refusal the board cannot key is invisible.

## 2. Refusal tokens

**State (from P2's `LiveGameState`):**

| token | when | note |
|---|---|---|
| `game_not_started` | status pre | |
| `game_final` | status post | lane `closed: true` |
| `game_state_unrecognised` | any status not explicitly live | UNKNOWN IS NOT LIVE (standing rule) |
| `no_game_id` / `no_score` / `no_period` / `no_clock` | field missing | never default a clock to 12:00 |
| `live_state_stale` | `as_of` older than the tick's staleness bound | P2 owns `as_of`; this reads it, never wall-clock-of-tick |
| `pbp_score_mismatch` | pbp running score != scoreboard score | the backtest excludes the same case (`pbp_linescore_mismatch`) |
| `period_out_of_range` | period > 4 and P1 cannot resume OT | becomes resumable only if P1's resume test covers OT |

**Inputs:**

| token | when |
|---|---|
| `no_pregame_inputs` | the pregame inputs (team model, roster, minutes) for this game are absent on disk |
| `team_not_in_rotation_history` | the stints-interval mechanism is ON and P2's history has no row for the team |
| `mechanism_input_missing:<name>` | ANY enabled mechanism whose input is absent. A switched-on mechanism with a missing input never runs as if switched off: unknown must not default permissive, and the model-engine standard's 26 unfed fields were exactly this |

**Engine:**

| token | when |
|---|---|
| `engine_resume_rejected` | P1's resume API rejects the state (its validation, its detail) |
| `budget_exhausted` | the tick deadline passed before this game's N sims finished. **The budget is a refusal, not fewer sims**: the NHL precedent and `PRICEABLE_SIGMA` both assume `simsRun` is the real count |
| `sims_below_floor` | fewer than the configured minimum sims completed |

**Publishing:**

| token | when |
|---|---|
| `props_over_size_budget` | the props block would push the snapshot past its size budget (§4). Game lines still publish; only props refuse |

## 3. What the success lane carries, and what it does not

The success lane carries:
- `source: "live_resim"`, `modelHomeWinProb`, `simsRun`, `liveStateAsOf`.
- `projection.homeMargin` / `projection.total` (means, display).
- `projection.totalRunsDist` / `projection.marginDist`: full-game histograms, home-positive margin frame.
  These are what `price_distribution_market` reads.
- Quarter and half markets as their own distributions under the same keys the join's segment path reads.
  If the join has no segment path for nba yet, they ship display-only and say so, as NHL's totals did.

The success lane does NOT carry:
- **The pregame probability, ever.** Not on refusal, not as a "prior" field a downstream `or` can pick up.
- **Distributions for a market whose estimator has not been graded by the checkpoint harness.** The precedent
  is `#499`, where WNBA totals became priceable only after a measured backtest. A market that has not cleared
  §5 is display-only.

## 4. Size budget (keyvalue 8 MB cap; lesson 2026-10-08, 9.6 MB of per-player rows)

- Histograms are integer-keyed counts, trimmed to their nonzero support. Measure the per-game game-line
  block (expected a few KB); the ship check records the measured value.
- **Props live outside the game-lens snapshot** in their own artifact, keyed by game, carrying only
  players with a posted live line. They are never per-player-for-every-player.
- Before writing, the producer serializes and measures. Over 6 MB means props are dropped with
  `props_over_size_budget`. Game lines are never dropped for size. The write path must never be the
  thing that discovers the cap (`KEYVALUE_WRITE_REJECTED` = 0 is a verification item).
- Check `_keyvalue_backed` for the path before choosing it (P2's note).

## 5. Ship gate (graded by `scripts/basketball_live_checkpoint_backtest.py`)

**Checkpoints:** end Q1, end Q2, end Q3, 5:00 Q4.

**Populations:** preseason, regular, postseason. They are never pooled, and n is reported per cell.

**Projectors:**
- the native resumed sim;
- `vendored_replay`, the vendored tick's closed-form formulas on as-of production SmartSim draws;
- `pregame_rate`, the market-prior baseline;
- `espn_wp`, a reference for ML only.

**Gate (regular season):** for full-game total MAE, margin MAE and ML Brier at every checkpoint, the paired
game-resampled 95% CI of (native − vendored_replay) lies below 0.

**Postseason:** the CI must not lie above 0. Postseason n is small, so "not worse" is the honest bar there.

**Native vs `pregame_rate`:** reported beside the gate, never hidden. A sim that loses to "current score +
pregame line pro rata" has no business pricing live.

**Distributions (`totalRunsDist`, `marginDist`):**
- the central 50% and 80% intervals cover the final at their nominal rate ± 3 pp at each checkpoint
  (regular season);
- otherwise the market is display-only.

**Live close:**
- when the live-close file exists, report the line's own error and the model's side-of-line hit rate on the
  same games;
- this is reported, not gated, until n ≥ 300 per checkpoint.

## 6. Mechanisms: each is reachable, then re-fit

Each mechanism is a default-off switch. Each has a reachability test showing `off != on` on a resumed state
where it must bite. Each is then judged against its measured target in
`.syndicate/findings_2026-10-09_nba_live_situation_targets.md`. Mechanisms are measured ALONE, then
TOGETHER, then with the absorbing rates re-fit. Two mechanisms together measured a NEGATIVE interaction in
4 of 4 markets, so "each helps alone" is not evidence for the stack.

| mechanism | target it must hit (findings file) | absorbing rate to re-fit |
|---|---|---|
| score-effect reversion | rest-of-game margin on margin-now slope per checkpoint; H2-on-H1 | team efficiency multipliers (`eff_mult`, events.py:1163) |
| asymmetric garbage time | leader vs trailer starters on floor and pace by Q4 margin bucket | minutes distribution / bench weights |
| end-game fouling + clock management | trailer fouls/min, FTA/min and pts/min in the last 2:00 by trailing margin | FT rate, possessions per game |
| foul trouble | starters' on-floor share after 2 PF in Q1, 3 in Q2, 4 in Q3, 5 in Q4 vs control | minutes targets |
| bench rotation intervals | starters-on-floor curve by game minute, close vs blowout | per-player minutes |

## 7. Cut-over order

1. Native lane published alongside the vendored tick, with nba NOT yet in `_LIVE_GAMELINE_SPORTS`.
2. Fleet reading: the served lens reads `live_resim`; `refusalsByReason` is sane; `KEYVALUE_WRITE_REJECTED`
   is 0 for the key over a slate.
3. §5 gate passes, then nba goes into `_LIVE_GAMELINE_SPORTS` and `LIVE_LENS_SOURCES_BY_SPORT["nba"] =
   ("live_resim",)`.
4. Delete `from vendor.nba_betting_repo.app import _live_lens_tick_payload` (`nba/live_lens.py`) and the
   live-props path that reads `live_lens_projections_*.jsonl`, in the same change. Then
   `git grep vendor syndicate/features/nba` returns no runtime import.
