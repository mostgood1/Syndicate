# Scheduled task — `layer2-score-v2-promotion-decision-1006`

**One-time, 2026-10-06 10:00 CDT.** Closes todo `#679` step 5: after 14+ days of
recorder grading from 2026-09-22, decide **per sport** whether the shadow
`score_v2` should be promoted from a stamped field to the thing the Layer 2 board
actually ranks on.

Created by session `dc70079c` 2026-09-22, no lane. **Read-only: this task NEVER
deploys, never changes an env var, and does not promote anything.** Promotion is
a code change plus a user decision plus a deploy behind two locks; this task
produces the evidence and a recommendation, nothing else.

Sibling task: `layer2-fee-net-7-slate-reading-0929`
(`.syndicate/scheduled_task_layer2_fee_net_7_slate.md`), which grades the
*fee-net score* that is already live. That one is a verification. **This one is a
choice**, and the two must not be conflated.

## What `score_v2` is

From `456e264f` / `97f01a37`: `min(g, g x reliability)` where `g` is quarter-Kelly
log growth (bp) at the **fee-net** price, or the fee-net EV when nothing is
sizable. Kalshi `0.07 x m x P(1-P)` per series (unknown series charged the full
rate and flagged); Polymarket `0.015` per contract. **No sim term, no movement
term.** Stamped as `candidate["score_v2"]`; nothing ranks, admits or sizes on it.
Off switch `SYNDICATE_SCORE_V2=0`. Recorder fields `s2` / `n2` / `fb` / `bk`
(`053ddd9e`) exist from **2026-09-22T00:12:34Z** — that start date is why this
window begins on 09-22.

## The in-sample result this is testing out of sample

`findings_2026-09-21_layer2_score_outcomes.md` §6, dataset B, paired over 82
slates, fee-net CLV points, top-K per (date x sport), <= 3 rows per game:

| contrast | top 10 | top 25 |
|---|---|---|
| score_v2 (Kelly) − fee-net EV x reliability | -0.01 [-0.66, +0.69] | -0.18 [-0.50, +0.16] |

i.e. **statistically equal edge overall**. What differs is the SHAPE: score_v2's
top-10 break-even is **0.464 vs 0.378** (median price +114 vs +150) and
beat-the-close **61.7% vs 59.5%** — the higher hit rate the original request
asked for, at the same edge.

And it is **sport-dependent**, which is the whole reason this is a per-sport
decision rather than a switch:

| sport | score_v2 − fee-net x reliability, top 10 |
|---|---|
| soccer | **+3.00 [+1.75, +4.22]** |
| NCAAF | **-2.71 [-4.03, -1.47]** |
| others | not separated in sample |

## The decision rule — fix it before looking at any number

For each sport with enough data, compute the paired difference (ranking by `s2`
minus ranking by `sc`) in fee-net CLV, top-25 and top-10 per (date x sport)
slate, <= 3 rows per game, **bootstrapped over GAMES, never rows**.

- **PROMOTE (recommend)** — the top-25 interval excludes 0 on the positive side
  **and** the sign agrees with the in-sample estimate for that sport.
- **DO NOT PROMOTE** — interval spans 0, or the sign disagrees with in sample.
  Equal edge is not a reason to change the ranking; a shorter-price, higher-hit
  board is a preference, and it is the user's to state, not this task's to infer.
- **REJECT** — interval excludes 0 on the negative side. Say so plainly.

**Multiple-comparisons guard, and it is mandatory.** This tests ~6 sports
separately. At 95% you expect roughly one sport in three windows to clear the bar
by chance. So a sport qualifies for PROMOTE only if it **both** clears its own
interval **and** agrees in sign with the in-sample fit. A sport that is
significant this window but was the opposite sign in sample is a **coin flip that
landed**, and must be reported as such — not as a discovery.

**Report the number of slates and GAMES each per-sport verdict rests on.** A
verdict on 3 games is not a verdict. If a sport is underpowered, the answer is
"not decidable this window", which is a real and acceptable outcome.

## Seasonal composition of this window — read before interpreting any sport

09-22..10-05 is not a stationary fortnight:

- **MLB** — the regular season ends ~09-27; the back half of this window is
  postseason only. A postseason sample is a different population (short slates,
  sharper markets, heavy prop coverage). Do NOT pool it with the regular-season
  in-sample fit without saying so.
- **WNBA** — playoffs, likely concluding inside the window. Expect it to run out
  of games.
- **NHL** — preseason crossing into the regular season. Preseason lineups make
  props and totals unlike the rest of the sample.
- **NFL / NCAAF** — weeks 4-5 and 5-6, the only two sports with a clean, full,
  comparable sample across the whole window. **NCAAF is the sport the decision
  actually turns on**, because it is the one that went the wrong way in sample.
- **Soccer** — continuous, and the one with the large positive in-sample effect.

## How to run it — the traps

The instructions in `.syndicate/scheduled_task_layer2_fee_net_7_slate.md` under
"How to run it" apply verbatim. The three that will otherwise bite:

1. **The primary checkout is ~1,200 commits behind `origin/main`** and
   `scripts/score_ranking_backtest.py` / `score_ranking_analysis.py` do not exist
   in it. Work from a `git archive` snapshot of `origin/main`. Write the tar to a
   FILE — piping `git archive` through PowerShell corrupts it.
2. **Copy the NCAAF team registry into the snapshot**
   (`data/ncaaf_source/source_artifacts/data/processed/team_registry/*.csv`,
   git-tracked). `git archive` excludes `data/`, and without it every NCAAF row
   drops as `extra_team_unresolved` — 24,829 rows on the 09-14..09-21 run.
   **On this task that failure would silently delete the decisive sport.**
3. **The recorder file date is the SIGHTING date, not the kickoff date**, and it
   keeps only the FIRST sighting per identity per phase. Use the graded row's
   `date` field and start the pull before the window:

   ```powershell
   py -3 scripts/score_ranking_backtest.py pull --start 2026-09-18 --end 2026-10-05 `
       --out C:/tmp/l2score/graded_1006.jsonl --cache C:/tmp/l2score/cache
   ```

   `--cache C:/tmp/l2score/cache` reuses everything already pulled; only new dates
   go over the wire. `score_ranking_analysis.py` is a **library, not a CLI**.

4. **Rows without `s2` cannot be in the contrast.** Count them and say what share
   of the population carried `s2`; if coverage is partial, the contrast is on a
   subset and must be labelled as one.

## Two things the 2026-09-22 dry run found — fold these into the run

Measured by this task's tool pre-approval dry run, 2026-09-22 16:25-16:29 CDT,
which exercised every command shape in the section above against live data.

1. **`origin/main` MOVES UNDER YOU MID-RUN. Pin the SHA.** The dry run read
   `ebd17ee2` at its first step and `44e09175` a few minutes later — **89 commits
   landed on `main` that day** from parallel sessions. So: capture
   `git rev-parse origin/main` **once**, build the snapshot from that exact SHA
   (`git archive --format=tar -o <tar> <SHA> scripts syndicate pipeline ...`), and
   quote that SHA in the findings file. Never re-read `origin/main` later in the
   run and assume it is the tree you measured. Everything read for this reading —
   the briefs, the prior findings, the scripts — must come from the one pinned SHA.
2. **`rows=1` is NOT a size control on `/api/ops/clv/report`.** With `rows=1` the
   MLB request still returned **1,074,201 bytes**, and `/api/portfolio/paper?date=<d>`
   returned **2,281,659 bytes**. Budget for multi-megabyte responses per
   (date, sport) — this reading fans out over ~14 dates x ~6 sports — and write each to a file
   rather than holding several in memory.
3. **The NCAAF registry copy is confirmed load-bearing, not a precaution.** On the
   dry run's single-day window NCAAF contributed **2,334 of 16,505 records**.
   Skipping the copy does not error; it silently removes a sport.

## Read first

- `.syndicate/findings_2026-09-29_layer2_fee_net_out_of_sample.md` — the 7-slate
  reading, which carries a running `s2` vs `sc` tally. **If that file does not
  exist, the 09-29 task never ran: say so in the report and flag it, but do not
  let it block this reading.**
- `.syndicate/findings_2026-09-21_layer2_score_outcomes.md` §6 — the in-sample fit.
- `.syndicate/findings_2026-09-22_layer2_board_0921_reading.md` §6 — the first
  slate, where `s2` out-hit `sc` on n=35 (a lead, not a result).
- `.syndicate/state_layer2.md` `[layer2-score-outcomes]`.

## If the recommendation is PROMOTE for any sport

Do **not** implement it. Instead:

1. Write the recommendation, per sport, with its interval and game count.
2. Note that this is a **mechanism change to a calibrated ranking**, so
   `docs/ai_context/model_engine_standard.md` applies: the terms currently
   absorbing what `score_v2` would now express (the sim term, the movement term)
   may need re-fitting, and two mechanisms added together have produced a
   NEGATIVE interaction in this repo before.
3. Note that a per-sport promotion needs a **reachability test before correctness
   tests** (`off != on`) — four inert features in one session were caught by that
   and nothing else.
4. Leave the decision to the user. Promotion is a deploy behind two locks.

## Where the result goes

1. `.syndicate/findings_2026-10-06_score_v2_promotion_decision.md`.
2. Update the `[layer2-score-outcomes]` subject in `.syndicate/state_layer2.md`.
3. Close or update todo `#679` step 5 in `docs/ai_context/todo.md` with the verdict
   — if the answer is "not decidable this window", say what would make it
   decidable and when, rather than leaving the item open with no condition.
4. Append to `.syndicate/deploys.md` only if something was measured against a
   deployed change; a pure analysis belongs in the findings file.
5. Commit and push to `main` (ledger pushes need no approval, user 2026-09-03).
   Build the commit against `origin/main` with git plumbing — the primary tree's
   index is shared with every other session. Append-only files must show **0
   deletions** in `git diff --numstat`.
