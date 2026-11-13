# Does the NBA pregame market anchor reach the live re-sim? (todo #780 lead; lane nba-live-anchor-trace)

- **User** 2026-11-13 "Trace it now".
- **Hypothesis and prediction,** committed before tracing (`5c7ffb272`): the anchor is applied where the live resume
  does not read it.
- **Verdict:** H is **FALSIFIED**, and the prediction was wrong in both parts.
  - The anchor DOES reach the live resume.
  - The live number at tip is no farther from the market than the served pregame number.
- **Where the agreement is lost:** inside the engine. It follows its anchored target only loosely, and that departure
  is noise.

## The trace (file:line)

1. **The anchor is pre-sim.** `shared/basketball_props_smart_sim.py:1218`: `_apply_market_anchor_local` moves the team
   means (`home_mu`, `away_mu`) toward the market spread at `margin_w` (0.95 on all 171 games) and the total at
   `total_w` (0.7). It records `model_margin_raw` -> `anchored_margin` in `market_anchor`.
2. **Those means build the quarter targets** (`_simulate_quarters_local`, `qsum.quarters`). The orchestrator sums them
   into `target_home_points` / `target_away_points` (`basketball_engine/orchestrator/smart_sim.py:1568`).
3. **The engine call's kwargs are persisted on the first call of each game:**
   - `basketball_props_smart_sim.py:3164` -> `_persist_engine_inputs_once_local` -> `nba/live_resim.persist_engine_inputs`.
   - The persisted keys `_INPUT_KEYS` (`nba/live_resim.py:108`) include `target_home_points`, `target_away_points` and
     `quarters`.
4. **The live resume loads exactly those kwargs** (`nba/live_resim.load_engine_inputs`), so it runs on the anchored
   target.
5. **Where it is lost.** `basketball_engine/engine.py:1114-1175`: the engine steers each team's efficiency toward
   target points per possession. It clips the multiplier to +-15%, or solves exactly under
   `EXACT_TARGET_CALIBRATION`. Then pace, rebounding, fouls, the end game and the lineups play out, and the output
   margin lands where it lands.

## The fleet reading (read-only)

**171 NBA pregame SmartSim artifacts, 10-21..11-12** (`C:\tmp\livegrade\load780\anchor_follow.py`), margins in
points, home frame:

| quantity | mean | sd | mean \|.\| |
|---|---|---|---|
| raw model - market | -1.64 | 7.32 | 6.28 |
| **anchored TARGET - market** | -0.08 | 0.37 | **0.31** |
| **engine OUTPUT - market** | -0.34 | 3.18 | **2.43** |
| engine output - its target | -0.25 | 3.10 | 2.38 |

Examples of the engine missing its own target:

| target margin | engine margin | market margin |
|---|---|---|
| +7.3 | -1.4 | +7.5 |
| +8.0 | +1.1 | +8.5 |
| -1.3 | +1.1 | -1.5 |

**Is the departure information?** 170 of those games against ESPN finals
(`C:\tmp\livegrade\load780\engine_vs_final.py`), bootstrap 95%:

| regressor | slope of (final - market) on it |
|---|---|
| engine margin - market | **-0.26 [-0.89, +0.40]**: noise |
| raw model margin - market | **-0.25 [-0.52, -0.01]**: points the wrong way |

Margin MSE against the final: market 206.8, anchored target 208.3, **engine output 222.3** (7.5% worse).

**At tip, the same 65 games** (the first live h2h state with <= 12 points scored, joined to its own pregame artifact):

| | mean \|. - market\| | games >= 10 pp off the market |
|---|---|---|
| pregame sim P(home) | 7.95 pp | 24 of 65 |
| live re-sim P(home) at tip | 9.52 pp | 24 of 65 |

The live number at tip differs from its own pregame number by 7.55 pp mean absolute. That covers a few minutes of play
and 200-sim noise (~3.5 pp sd at 0.5).

## What it means

- **The live moneyline's early disagreement with the market** (`.syndicate/findings_2026-11-13_live_moneyline_gap.md`)
  is the pregame engine's own departure from its anchored target, carried into the game.
  - The anchor works: the target is within 0.3 points of the market.
  - The engine adds about 3 points (sd) of margin that predicts nothing.
  - The raw model's view, before the anchor, is worse than nothing against the market.
- **The college re-sims avoid this** with a post-sim margin anchor: `ncaab/live_resim._anchor_segments` shifts the
  histogram by the pregame gap times the share still to play (`marginAnchored`).
- **The candidate fix (not built):** the same for NBA.
  - Shift the live re-sim's margin histogram by (anchored target - the engine's pregame margin mean) x the share of
    regulation still to play.
  - Both numbers are already in the pregame artifact: `market_anchor.anchored_margin` and `score.margin_mean`.
- **The fix is a mechanism** under `docs/ai_context/model_engine_standard.md`:
  - a reachability test (off != on);
  - a re-check of the live totals / spreads scales, which were fitted on today's un-anchored margins and may absorb
    part of the same error (the spreads k in particular);
  - a walk-forward grade of the moneyline and spreads against finals before anything loads.
- **The pregame board** already weights the NBA sim's game lines 0 / 0.05 in Layer 2 (`#721`), so this mostly
  matters live, where the join uses the re-sim 100%.

## Nothing was changed in production

Read-only scripts in `C:\tmp\livegrade\load780\` (`anchor_follow.py`, `engine_vs_final.py`, `find_smartsim.sh`).
