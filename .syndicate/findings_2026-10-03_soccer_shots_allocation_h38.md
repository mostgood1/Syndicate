# Soccer shots / SOT — the player's own-rate blend (H38)

Lane `soccer-shots-allocation-blend` (session 43e4d5fe). Written 2026-10-07, after the fact: the result was in the
lane block and `log/2026-10-03.md` only, while the lane's Verification promised a findings file. Every number below
is copied from a saved artifact named beside it; nothing is re-derived.

## The problem

Post-fix pre-kickoff builds (119 matches, 2026-09-17..09-30) under-projected regular starters' shots and
over-projected subs': starters model 0.858 vs actual 1.101 per appearance, subs 0.646 vs 0.566. The sim allocates a
team's shots to players by a share that does not use the player's own observed rate.

## Pre-registration (lane block, 2026-10-03 ~04:45Z, before any computation)

- **H38:** for appeared players on POST-FIX pre-kickoff builds with >= 3 prior appearances, the mean
  `m = L·model_if_playing + (1−L)·c`, where `c` = the player's own as-of per-appearance average shrunk to the league
  mean with 3 pseudo-apps, and `L` ∈ [0,1] is fitted per market (shots, SOT) by LEAVE-ONE-DATE-OUT maximum Poisson
  likelihood, lowers held-out Poisson NLL per row versus BOTH the model alone (L=1) and `c` alone (L=0).
- **Deciding, per market:** paired held-out Poisson NLL (blend − model) AND (blend − c), match-bootstrap 95% CIs,
  BOTH wholly below 0, or nothing ships for that market.
- Reported only: Brier at lines (shots 0.5/1.5/2.5, SOT 0.5/1.5), starter vs sub, L per fold, the all-versions pool.

## Data

Per-row dump from `scripts/soccer_season_audit/audit_props.py --asof --dump-rows` (`C:/tmp/soccer-lpb/asof_props_h38.json`);
scorer `C:/tmp/soccer-lpb/score_h38.py`; results `C:/tmp/soccer-lpb/h38_result.json` (league-mean shrink, as
registered) and `h38_result_ct.json` (team-mean shrink, the variant production uses).

| population | rows | matches | dates |
|---|---|---|---|
| post-fix (DECIDING) | 3,003 | 119 | 2026-09-17..09-30 |
| all versions (reported) | 4,559 | 223 | 2026-09-02..09-30 |

## Result — SUPPORTED for both markets

Post-fix, deciding (league-mean shrink, as registered):

| market | L (LODO folds) | NLL model / c / blend | blend − model | blend − c |
|---|---|---|---|---|
| shots | 0.48 (0.47–0.54) | 1.3813 / 1.2550 / 1.2274 | **−0.154 [−0.222, −0.097]** | **−0.028 [−0.039, −0.017]** |
| SOT | 0.66 (0.64–0.68) | 0.6943 / 0.6850 / 0.6562 | **−0.038 [−0.069, −0.014]** | **−0.029 [−0.038, −0.020]** |

Both CIs wholly below 0 in both markets. The all-versions pool agrees (shots −0.160 / −0.029, SOT −0.036 / −0.031,
all CIs below 0). **Team-mean shrink** (production's variant): shots −0.154 [−0.222, −0.097] / −0.028
[−0.039, −0.017], L 0.49; SOT −0.038 [−0.069, −0.014] / −0.029 [−0.038, −0.019], L 0.67 — the same result.
Shipped constants are the registered league-shrink fits (L_SHOTS 0.48, L_SOT 0.66).

Line Brier (post-fix, reported): shots 0.5 model 0.2102 → blend 0.2021, 1.5 0.1618 → 0.1532, 2.5 0.0854 → 0.0822;
SOT 0.5 0.1601 → 0.1575, 1.5 0.0505 → 0.0502 (blend − model CI spans 0 at SOT 1.5 only).

**Starter vs sub (post-fix, per appearance):**

| | n | actual | model | c | blend |
|---|---|---|---|---|---|
| shots, starter | 2,312 | 1.101 | 0.858 | 0.942 | 0.899 |
| shots, sub | 691 | 0.566 | 0.646 | 0.850 | 0.747 |
| SOT, starter | 2,312 | 0.361 | 0.294 | 0.327 | 0.305 |
| SOT, sub | 691 | 0.211 | 0.221 | 0.286 | 0.242 |

**The blend does not fix the starter level.** It moves starters from 0.858 toward 1.101 but stops at 0.899, and it
pushes subs further above their actual (0.646 → 0.747 vs 0.566). The NLL gain is real; the allocation error between
starters and subs is only partly addressed. Not reported: the team-shots vs player-share decomposition of the
starter gap the pre-registration listed — it is not in the saved result.

## Stage 2 — shipped and served (deploys.md)

- Built flag-OFF behind `SYNDICATE_SOCCER_PROP_OWN_RATE_BLEND` (absent = off) in `soccersim/player_props.py`, with a
  per-row `own_rate_blend` note and tests (`tests/test_soccer_own_rate_blend.py`). Flag-off/on builds 2026-10-03:
  225 of 346 outfield rows move in 7 leagues (lane block).
- **Flag ON** 2026-10-04 (the flip caused a 5 h 14 min outage; postmortem in learnings.md; restored 13:53:23Z).
- **Served (MET, deploys.md 2026-10-04 17:55Z):** 2,043 of 4,500 outfield rows carry `own_rate_blend` across 9
  leagues; 188/188 blended SOT rows on the served board serve the blended ladder.
- **Defect 1 (fixed, MET deploys.md 21:16Z):** rows with a zero model shot mean recorded a blend they could not
  serve; `f588daff` rebuilds the components. 21 rebuilt artifacts, 0 mismatches; 103 zero-model rows now blended.
- **MLS is not reached:** 0 of 850 rows — the ASA file carries no games/appearances, so no own rate exists.

## Related, not part of H38

- **H39 NOT SUPPORTED:** a per-player own SOT RATE (SOT per shot) instead of the team rate was worse, NLL +0.0080
  [+0.0008, +0.0150] (2,733 rows). Keep that field unfed.
- Goals: lane `soccer-goal-allocation` (session 5942cf5f) found the analogous error for goals (58.3 of 355 expected
  goals on players who never appear); its H40/H41 did not ship.

## Open

- The starter under-projection (blend 0.899 vs actual 1.101) — an unregistered follow-up; the goal-allocation finding
  (expected output on players who never appear) is the same mechanism and is the better lead.
- MLS own rates need a source with appearances.
