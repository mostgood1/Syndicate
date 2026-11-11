# NHL live re-sim: a fitted end-game (empty-net) on the margin histogram (todo #773, lane nhl-live-endgame-calibration)

2026-11-11, replays 20:24-20:35Z and 20:40-20:50Z (2:24-2:50 PM CST). Session 87074b1f. READ-ONLY on production. User: "Engine fix first" (after the grade `findings_2026-11-11_nhl_live_puckline_grade.md` said DO NOT PRICE).

**Result: the decisive failure is closed.** With a one-goal lead late in the third, the live histogram gave the leader 0.09-0.26 to win by 2+, and it happened 0.37-0.46 of the time. Out of sample with the fitted end-game, those states sit within +-0.035 (n = 57-63 each, binomial sd ~0.065).

**Recommendation: LOAD for the display** (live-odds-worker, the producer). It fixes the number the board shows in exactly the states people watch. **Pricing stays closed.** It needs the v6 recorder's market comparison and a sample free of the season-rate leakage.

**Not loaded, not pushed:** the code is uncommitted in the session worktree (backup `C:\tmp\nhlrec\code_backup\`), waiting on the user's push/load decision.

## The mechanism (`syndicate/features/nhl/live_resim.py`)

- **What it does.** A sim that finishes REGULATION with a one-goal margin gets one more goal for the leader, with probability `p_eff = p * min(1, s / ramp)`. Here `s` is the regulation time that margin had left when it was set: the time of the sim's LAST regulation goal, read from its own goal events, or the cutoff's own time when no goal came after it.
- **Why `s`.** A lead that became one with 20 s left has almost no empty-net chance; the trailer cannot pull the goalie in time.
- **What it never touches.** OT/SO sims (they end by one). Overtime states (no regulation left).
- **How it is applied.** Post-sim, with its own RNG. The engine's draws are untouched, so `off` reproduces today's histogram seed for seed.
- **Off switch:** `SYNDICATE_NHL_LIVE_ENDGAME_CALIBRATION=off`.
- **The pregame numbers are NOT copied.** `NHL_GAME_MARKET_CALIBRATION` (`empty_net_p` 0.3006, `tie_weight` 0.7539) was fit on a plain per-period Poisson sim with no end-game logic. The live path runs the event engine, which already has a last-3-minute heuristic (`engine.py:1580`).
  - `tie_weight` would make the live path worse: it already gives the trailer slightly too many ties (P2 10:00 lead 1: model 0.326 vs 0.261).
  - So `p` is fit on this engine.
- **MARGIN ONLY, not the total (model_engine_standard 4.4).** The live total mean is already HIGH early, and the extra goals would push it +0.11 further.

  | cutoff | model total - actual, off | with the goals |
  |---|---|---|
  | P1 20:00 | +0.814 | +0.931 |
  | P2 10:00 | +0.335 | +0.452 |
  | P3 05:00 | -0.197 | -0.083 |

  This is the event engine's scoring rate, the issue the pregame path's `regulation_scale` corrects. The total's level is set there, so it needs its own fit. Lead recorded.
- **Publication.** The lane publishes `liveEndgame: {empty_net_p, ramp_seconds, empty_net_goals, calibration}` at lane level, so a production reading can tell on from off. No pricer reads it.

## Population and provenance

- **Harness:** `scripts/backtest_nhl_live_puckline.py`, extended:
  - `--endgame off` replay;
  - the raw splits `regulation_margin_dist` / `overtime_margin_dist` / `regulation_one_goal_seconds` on every row;
  - an in-expectation apply of any (p, ramp);
  - the `--fit-endgame` walk-forward;
  - the lead-state table.
- **Run:** on the fleet host at nice 19, 3 processes, with the WORKTREE's producer. Hashes are in `C:\tmp\nhlrec\replay3_code_hashes.txt`: `live_resim.py` blob `a02c8660b7fa`, harness `10c78ce59c48`.
  - The shipped file differs from that blob only by the fitted constant and margin-only totals. Neither changes an `--endgame off` replay.
  - Inputs: production's `build_slate_features(date, root=~/syndicate-prod/data/nhl_source)`, 200 sims.
- **Sample:** 284 completed REGULAR-season games on 41 dates (2026-10-01..11-10), 0 dropped, 0 refused.
  - 8 cutoffs: P1 20:00, P2 20:00, P2 10:00, P3 20:00, P3 10:00, P3 05:00, P3 03:00, P3 01:30. The last two are new; they identify the ramp.
  - 2,272 rows in all.
- **PROVENANCE: LEAKY,** as in the grade. The season rate files are rewritten daily and kept dated nowhere.
  - `p` is fit on rates that already contain each game, so it measures what this engine misses given its best-informed inputs.
  - In production, with less-informed rates, the right p could differ somewhat. The walk-forward range (below) is the honest spread.
- **Objective:** Brier of the board's own number (Agresti-Coull P(home margin > line)) on both +-1.5 lines.
  - The Brier is quadratic in p, so p is closed-form for each ramp.
  - Ramp grid: 0-240 s.

## Fit

- **Full sample (shipped):** `empty_net_p` **0.38**, `ramp_seconds` **90**. Brier 0.11845 -> 0.11197.
- **Walk-forward** (each date fit only on the dates before it; first 14 dates warm-up; 27 out-of-sample dates): p 0.35-0.55, ramp 90-120 s.
- **The first version** had a ramp on the cutoff clock instead of the margin's own time. It fit p 0.35 with ramp 0, and it overshot two-goal leads more (P3 01:30 lead 2: -0.207 vs -0.186). Its numbers are in `C:\tmp\nhlrec\replay2\report.txt`.

## Out of sample: 185 games on 27 dates, 1,480 rows, off vs on

| | off | on |
|---|---|---|
| +-1.5 worst powered bucket | 0.1-0.2 n=278 **+0.084** | 0.6-0.7 n=232 **+0.073** |
| its 95% game-bootstrap interval | [0.060, 0.186] | [0.053, 0.158] |
| +-1.5 Brier | 0.11609 | **0.11303** |
| model - skill-free baseline, 95% | [-0.0077, -0.0006] | [-0.0141, -0.0001] |
| width realised/model, P3 05:00 / 03:00 / 01:30 | 1.19 / 1.27 / 1.23 | 1.09 / 1.15 / 1.12 |

- **On - off Brier**, bootstrapped over games: **-0.0031 [-0.0095, +0.0031]** out of sample, and **-0.0065 [-0.0114, -0.0015]** in sample at the full fit. Pooled, the out-of-sample gain is within noise; the state table is where it is decisive.
- **Alt +-2.5:** unchanged by construction, since a one-to-two move never crosses 2.5. Worst bucket 0.135, interval [0.106, 0.313]. It still fails to beat the baseline and stays unpriceable.

**P(the LEADER wins by 2+), out of sample, oriented to the leader:**

| cutoff | lead | n | off | on | observed |
|---|---|---|---|---|---|
| P3 10:00 | 1 | 63 | 0.261 | 0.425 | 0.460 |
| P3 05:00 | 1 | 57 | 0.184 | **0.423** | **0.421** |
| P3 03:00 | 1 | 61 | 0.138 | 0.422 | 0.393 |
| P3 01:30 | 1 | 59 | 0.093 | 0.354 | 0.373 |
| P3 20:00 | 1 | 52 | 0.320 | 0.428 | 0.308 (in sample: 0.418 vs 0.414) |
| P3 05:00 | 2 | 37 | 0.759 | 0.821 | 0.757 |
| P3 03:00 | 2 | 34 | 0.826 | 0.869 | 0.765 |
| P3 01:30 | 2 | 24 | 0.875 | 0.894 | 0.708 |

- **Trailer ties-or-wins** is unchanged by the mechanism (it only moves +-1 to +-2) and was already about right late.

## What remains, and is not fixed here

1. **Two-goal leads late are held too often**, by off and on alike.
   - With "on" at P3 01:30: 0.894 vs 0.708 (n=24, z -2.0). In sample: P3 03:00 0.868 vs 0.804, P3 01:30 0.908 vs 0.795.
   - The engine under-produces the trailer's 6-on-5 goals when down two. The end-game adds about 0.02-0.06 to that miss.
   - A second mechanism (trailer goalie-pull scoring) would be its own fit.
2. **Mid-game score effects:** at P2 10:00 the trailer's comeback is still over-predicted (-0.061 / -0.079 out of sample), as the grade found.
3. **The live TOTAL is biased high early** (+0.81 goals at puck drop). Lead.
4. **Pricing:** still closed. It needs the v6 recorder's live market comparison, which runs on tonight's slate, and a sample without season-rate leakage.

## Load (the user's decision)

- **The producer runs on live-odds-worker.** Loading means:
  1. push to main;
  2. ff the fleet to that exact SHA;
  3. take the live-odds-worker claim, drain, and run a preflight against origin/main;
  4. a claimed TERM.

  Nothing on web or refresh-worker changes. The join, ledger and board read the published histogram.
- **Verify:** on a live NHL game, the served snapshot's NHL lanes carry `liveEndgame.calibration = "on"`, `empty_net_p 0.38`, `ramp_seconds 90`.
  - A late one-goal state shows the leader's -1.5 near 0.40 rather than 0.18.
  - The v6 ledger records `display_prob` beside `market_fair_prob_over` for those rows.
- **Revert:** env `SYNDICATE_NHL_LIVE_ENDGAME_CALIBRATION=off` (`LIVE_ODDS_WORKER__` scope, a drained down/up), or revert the commit, ff, and a claimed live-odds-worker TERM.

## Reproduce

```
wsl -- bash /mnt/c/tmp/nhlrec/replay3.sh          # replay (end-game off, splits stored) + --fit-endgame
py -3 C:\tmp\nhlrec\endgame_extra.py <worktree> C:\tmp\nhlrec\replay3   # on-off bootstrap, totals, lead-state sd
```

Tests: `tests/test_nhl_live_endgame_calibration.py` (15).
- Reachability through `build_live_lens_snapshot` (`off != on`, `liveEndgame` names which).
- `off` equals the raw splits summed.
- Only regulation-end +-1 sims move.
- The resumed-period clock and the ramp.
- The harness's apply equals the producer's at p = 1.
- The closed-form fit recovers a known p.
- Walk-forward trains only on earlier dates.

4 of 4 mutations caught: OT sims eligible, ramp ignored, the resumed period on a 1200 s clock, the calibration never read. Neighbouring NHL, join and ledger suites: 179 passed.
