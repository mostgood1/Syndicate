# Engine learner: the M2 shadow learner (Phase 1B, lane `engine-learner`)

Plan: `docs/ai_context/plan_one_engine_pregame_live.md` §2 ("One learner") and §3 (M2). Umbrella `#736`. The experts it
learns from: `docs/ai_context/engine_experts.md`.

**Shadow only.** Nothing on the board, in Suggested, in sizing or on any order path reads it. `engine_learner.py`
imports neither `engine_experts` nor anything that places or sizes a bet (`tests/test_engine_learner.py`
`test_module_is_shadow_only`).

## The model

```
logit p_decision = logit p_prior + sum over experts e of  w_e(cell) * delta_e
```

| piece | what it is |
|---|---|
| `p_prior` | the prior each opinion carries (live: the books' in-play fair, or Kalshi's mid once slice 5 lands; pregame: the record's prior). An OFFSET: with every weight 0, `p_decision` IS the prior. |
| `delta_e` | expert e's Δlogit on that line at that instant (`ExpertOpinion.delta_logit`). |
| cell | root → sport → family (totals / spreads / h2h / props) → market → segment → phase → clock bucket → **prior age** (≤60 s / 60–180 s / 180–900 s). |
| `w_e(cell)` | the sum of one parameter per node on the cell's path, each with prior N(0, τ²), τ = 0.5: hierarchical partial pooling, shrunk toward "the expert adds nothing". |
| fit | MAP (L-BFGS) of the weighted log loss + the Gaussian penalty. Each line weighs 1 / its ticks, so a line counts once whether it was opined on 3 times or 300. |
| uncertainty | the cluster-robust (sandwich) covariance over GAMES: a game's lines share one final score and its ticks repeat. |
| applied weight | a fitted weight is applied only where `w − 1.96·SE > 0` (plan: "applied only when its lower bound is above 0"). A negative weight is never applied. Elsewhere the expert contributes 0 and `p_decision` is the prior. |

**Why prior age is a level.** On the fleet's 11-09 opinions, ~10% of live opinions had a prior ≤ 60 s old; most were
60–900 s old, while the re-sim knows the current score. Against a stale prior the expert looks far better than it is
against the price you could actually trade. The first smoke run showed this: on 11-10, NCAAB spreads "beat the prior"
by −0.096 nats against a prior log loss of 0.690. So the age is part of the cell, the held-out report is broken out
by age, and the live gate reads the fresh stratum.

## Pipeline trace (slice 1)

| hop | file:function | reads | writes |
|---|---|---|---|
| 1. opinions | `scripts/engine_experts.py run --opinions` | the live evidence log, the game-line ledger, book quotes (fleet data root) | `opinions_<date>.jsonl`, OFF the data root (research output) |
| 2. truth | `scripts/engine_learner.py` `BasketballTruth` | `nba_source/data/processed/linescores_<date>.json` (completed games only, ESPN event id); `<league>_source/data/scoreboard/scoreboard_<date>.json` (FINAL only); team names from `live_evidence/<sport>/<date>.jsonl` | nothing |
| 3. examples | `engine_learner.build_examples` | opinions + truth | in memory: one example per (line, instant), with every expert's Δ |
| 4. fit | `engine_learner.fit` | training slates | in memory |
| 5. report | `scripts/engine_learner.py run` | test slates | stdout + `--json` |

Truth rules: totals OVER = total > line; spreads HOME = home − away > line (the live join's away frame, as
`college_segment_grade.outcome`); h2h HOME = home > away; equal = push, dropped. NBA segments by
`segment_actuals.segment_score_pair`; NBA full game = every period, overtime included; college h1 = period 1, h2 =
period 2 plus overtime. Orientation: the evidence log's home team against the score source's, by name or (NBA) by
code with ESPN's aliases; a spread or moneyline whose orientation cannot be told is refused, totals are not.

**Game identity.** `live_resim` keys its opinions by the ledger's event id; the truth and the clustering use
`inputs.evidence_event_id` (ESPN's), so a game's full-game and segment rows are one cluster (`engine_learner.game_id`).
A successful `live_resim` lookup implies the ledger's home is the evidence log's home (`EvidenceIndex` files a game
only under the evidence's own orientation).

## The gate (M2), and what slice 1 is not

The M2 gate (plan §3): held-out log loss of `p_decision` against the prior alone, per sport family, pregame and live
separately, CI below 0; also the number of cells with a lower bound above 0. It is registered on main before its
data, with the code frozen by blob.

Slice 1 grades live basketball game lines only (nba / ncaab / wncaab; totals, spreads, h2h; full game and segments).
Everything else is refused by name and counted (`pregame_not_in_slice1`, `props_not_in_slice1`,
`sport_not_in_slice1`). Owed in slice 2: the NBA prop outcome (lane `nba-live-prop-grade`'s grader), NHL / NFL / NCAAF
finals, the pregame close and outcome (`decision_policy_paper.collect_closes` / `grade_outcome`), and the +300 s
mark-out (Kalshi's stored mid, `kalshi_quote_history`, once slice 5 lands).

## Fleet dry run, 2026-11-16 (dev data, NOT the gate)

Opinions: main's experts runner (fleet checkout), slates 11-09..11-14, nba / ncaab / wncaab; nothing from F2's window
(lane `engine-live-prior`, from 2026-11-15T20:00Z) was read. Code sha256: `engine_learner.py` `0813df1aea94`,
`scripts/engine_learner.py` `3ead9157097a` (since then a docstring-only edit for the experts' shadow guard:
`engine_learner.py` `926a5e3307a3`). Train 11-09..11-12 (329,101 examples, 222 games); test 11-13..11-14
(166,874 examples, 161 games).

- **Truth coverage:** of the live basketball game-line instants, NBA totals 272,192 graded of 273,478 (the rest
  pushes), NBA spreads 45,953 / 46,101, NCAAB totals 95,200 / 95,269, NCAAB spreads 74,864 / 74,944, WNCAAB spreads
  1,178 / 1,208 (30 orientation unresolved). No group's prior log loss is above ln 2 + 0.06, so no side or frame reads
  backwards.
- **off != on:** OFF reads exactly 0 in every group; ON moves 90,587 of 166,874 held-out probabilities; 134 of 312
  (expert, leaf) cells applied.
- **Held-out Δ log loss (ON − prior; 95% CI by game):**

| group | all priors | prior ≤ 60 s | 60–180 s | 180–900 s |
|---|---|---|---|---|
| NBA totals (14 games) | −0.0239 [−0.039, −0.007] | +0.0019 [−0.010, +0.015] | +0.0020 [−0.008, +0.011] | −0.0527 [−0.077, −0.022] |
| NBA spreads | −0.0069 [−0.026, +0.010] | −0.0068 [−0.024, +0.003] | −0.0069 [−0.030, +0.015] | — |
| NCAAB totals (123 games) | −0.0560 [−0.069, −0.041] | **−0.0086 [−0.016, −0.001]** | −0.0096 [−0.020, −0.000] | −0.1212 [−0.146, −0.094] |
| NCAAB spreads (120 games) | −0.0553 [−0.067, −0.041] | +0.0018 [−0.004, +0.007] | −0.0086 [−0.015, −0.003] | −0.1226 [−0.146, −0.096] |
| WNCAAB spreads (19 games) | +0.0118 [−0.003, +0.031] | 0 (no weight applied) | +0.0250 [−0.009, +0.068] | — |

**Reading.** Almost all of the apparent gain is against STALE priors: the books' in-play fair lags the score the
re-sim already knows. Against a prior ≤ 60 s old, only NCAAB totals shows a gain whose CI excludes 0, and it is small
(about 1.3% of the prior's log loss). A stale book prior is not a price anyone can trade (Kalshi leads the books in
play), so the M2 live gate must read the fresh stratum, and slice 5's Kalshi prior matters for how much of the data
is fresh. This is two test nights and seen data: it shapes the registration, it is not a result.

## Running it (read-only)

```bash
# 1. opinions per slate (main's experts runner, on the fleet, nice 19)
nice -n 19 python scripts/engine_experts.py run --date 2026-11-12 --sports nba,ncaab,wncaab --opinions <dir>/opinions_2026-11-12.jsonl
# 2. the learner
nice -n 19 python scripts/engine_learner.py run --opinions-dir <dir> --dates 2026-11-09..2026-11-14 --test-from 2026-11-13 --json <dir>/learner.json
```
