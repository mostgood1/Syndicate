# The measured-joint parlay pricer, scored on OUTCOMES

`#621` Phase 5 / commit `169e328e`, flag `SYNDICATE_PARLAY_MEASURED_JOINT`.
Lane `segments-joint-v1`. Measured 2026-09-09, local run, worktree
`session/joint-pricer-scoring` at `origin/main` `4740f2c9`.

## VERDICT: **CONFIRMED — but narrowly, and NOT for the mechanism the commit is named for.**

The shipped arm (`sec2_85`) beats every baseline on **both** metrics pooled,
with bootstrap CIs over GAMES that exclude zero — including the check the
previous attempt failed, plain independence. So the difference has become a
scored improvement.

But the decomposition says the improvement is **the cap raise on same-player
pairs**, not the n-leg covariance estimator:

| what | log-loss effect, pooled | verdict |
|---|---|---|
| the estimator at equal cap (`sec2_25` vs `raw25`) | **+0.000003** [−0.000166, +0.000180] | **NULL** |
| the cap raise on the new estimator (`sec2_85` vs `sec2_25`) | −0.000652 [−0.000897, −0.000381] | BETTER |
| the cap raise on the RAW coefficient (`raw85` vs `raw25`) | −0.000570 [−0.000811, −0.000305] | BETTER |
| the cap raise on the FLAG-SUM (`heur85` vs `heur25`) | **+0.017148** [+0.012912, +0.021579] | **WORSE** |

The second-order expansion is statistically indistinguishable from the plain
Fréchet weight at the same cap. What the flag actually buys is permission to
move further, and that permission is only safe because the coefficient is
measured — granting the same licence to the flag-sum is a **26x larger
regression in the opposite direction**.

**RECOMMENDATION: ENABLE `SYNDICATE_PARLAY_MEASURED_JOINT`** — on the evidence
below, with the claim re-stated and one monitor attached (§8). The incremental
effect over today's code is real, positive on both metrics, and null rather than
negative in every segment where it is not positive.

---

## 1. Runtime and cost

| | |
|---|---|
| backfill | `scripts/backfill_mlb_sim_joint.py`, 13 dates 2026-06-29..07-11, **177 games, 0 failed** |
| wall clock | **47 m 47 s** (17:18:30 → 18:06:17 CDT) |
| compute | **~2.7 CPU-hours** (shard sums 2295 + 2142 + 2201 + 2419 s + ~800 s) |
| shape | 5 disjoint date shards × 1 worker, 1000 sims, seed 4242 |
| peak memory | ~1.2 GB per process, ~6 GB of 31.6 GB; 12 logical CPUs |
| output | 11 MB, 177 files under `reports/joint_backfill/` (untracked) |
| external cost | **zero.** No StatsAPI, no OddsAPI, no `/api/ops/artifacts/export` |
| scoring | ~3 min, 2000 game-bootstrap resamples × 12 comparisons × 2 metrics × 7 splits |

**It did not compete with production.** The backfill reads git-tracked
`roster_objs` and runs `_sim_many` in-process on this machine; it touches no
Render service, so no in-flight MLB sim was at risk. This is a statement about
a LOCAL run, and therefore evidence about the CODE, never about the deployment.

**Two self-inflicted costs, recorded so the next run avoids them.** A serial
run would have taken ~94 min; sharding cut it to 48. `Start-Process
-NoNewWindow` children were reaped when the PowerShell tool call returned (5
shards died with empty logs, ~6 min lost), and piping a shard through
`Select-Object -First 15` closed its stdout and killed it at 14 of 16 games.
The backfill's skip-if-exists resumability absorbed both — it is load-bearing,
not decoration.

## 2. The population actually scored

- **151 games** carrying at least one gradeable pair (of 177 backfilled), 13 dates.
- **162,491 two-leg** and **44,940 three-leg** tickets.
- Positives: 2-leg **14.14%** (22,977), 3-leg **5.74%** (2,578).
- Skipped: `no_graded_row` 1,064, `not_lineup` 1,507. **No `undefined_corr`,
  `no_label` or `degenerate_marginal` skips at all.**
- 3-leg tickets are a seeded random sample of <=300 per game (`rng` seed 1717),
  not the full C(n,3).
- Outcomes come from `daily_top_props` (graded in-file), which is selected **by
  model edge**. This answers "does it help on the props we would bet", not "on
  all board pairs".
- Marginals are the sim's own `*_dist` over the graded line — **not**
  production's `model_probability`. Every arm shares them, so the dependence
  comparison is fair; the absolute log-loss levels are not production's.
- Only `batter|<pid>|{hits,home_runs,total_bases,rbi}` labels are scored.
  `strikeouts` and all **8 team segment dimensions** in the joint are never
  exercised.

## 3. THE BASELINE IS AMBIGUOUS, AND THE COMMIT SCORED THE WRONG HALF

`pipeline/layer2_shortlist.py:665` calls
`correlation_wiring.install_measured_correlation(selected_date)`
**UNCONDITIONALLY** — not behind `SYNDICATE_PARLAY_MEASURED_JOINT`. That
registers a process-wide resolver, and
`intelligence_parlay_runtime._parlay_correlation_profile` reads it through
`_compute_correlation` **regardless of the flag**. So for any pair the resolver
can measure, today's flag-off `average_correlation` is the **measured Spearman**,
not the categorical flag-sum.

`scripts/measure_measured_joint_parlay.py:172` clears the resolver in its OFF
arm (`register_measured_correlation_resolver(None)`) while its docstring claims
that arm is "the byte-for-byte today path". **For measured pairs it is not.**
The commit's headline −0.0239 is therefore measured against a baseline
production may not run.

I scored **both**, and kept them separate:

- **`heur25`** — categorical flag-sum as a Fréchet weight, cap 0.25. The
  pre-wiring path, and the commit's OFF arm.
- **`raw25`** — measured Spearman as a Fréchet weight, cap 0.25. Today's path
  *if* the parlay-building process has the resolver installed.

**Which one production runs is UNVERIFIED.** The resolver registry is
per-process; `layer2_shortlist` writes an artifact that a different process
reads back to build parlays, and I did not measure which process holds the
registration. That is a production reading, not a local one, and this lane did
not take it. It matters because it decides how much of the gain is already live.

## 4. Scoring table — pooled

n = 207,431 tickets over **151 games**, positives 25,555 (12.32%).
Bootstrap: 2000 resamples **over GAMES** (pairs within a game are correlated;
a pair-level CI would be far too narrow). Negative = better.

| arm | log-loss | Brier |
|---|---|---|
| `indep` independence | 0.33487 | 0.09891 |
| `heur25` flag-sum, cap 0.25 | 0.33755 | 0.10001 |
| `heur85` flag-sum, cap 0.85 | 0.35478 | 0.10564 |
| `raw25` measured raw, cap 0.25 | 0.33346 | 0.09877 |
| `raw85` measured raw, cap 0.85 | 0.33290 | 0.09862 |
| `conv25` converted, cap 0.25 | 0.33355 | 0.09873 |
| `sec2_25` **shipped estimator**, cap 0.25 | 0.33346 | 0.09875 |
| `sec2_85` **shipped, as flagged** | **0.33281** | **0.09859** |

| comparison | log-loss [95% CI] | Brier [95% CI] |
|---|---|---|
| `sec2_85` vs `raw25` | −0.000648 [−0.000816, −0.000474] SIG | −0.000186 [−0.000245, −0.000123] SIG |
| `sec2_85` vs `heur25` | −0.004663 [−0.007753, −0.001680] SIG | −0.001400 [−0.002121, −0.000671] SIG |
| `sec2_85` vs `indep` | −0.002086 [−0.003321, −0.000850] SIG | −0.000331 [−0.000634, −0.000015] SIG |
| `raw25` vs `heur25` | −0.004015 [−0.007205, −0.000990] SIG | −0.001214 [−0.001996, −0.000463] SIG |
| `sec2_25` vs `raw25` | +0.000003 [−0.000166, +0.000180] null | −0.000019 [−0.000049, +0.000010] null |

SIG = CI excludes zero.

**Read this row pair carefully.** Of the −0.004663 the flag appears to win
against `heur25`, **−0.004015 is delivered by the resolver wiring that is
already unconditional in the code.** The flag's own incremental contribution is
the `vs raw25` row: **−0.000648 log-loss**.

**It beats independence.** The 2026-09-05 precedent recorded in
`threshold_correlation.py:16-20` had the joint beating the heuristic by −0.027
and **losing to independence** (+0.007 pooled, +0.101 same-player). Applying the
threshold conversion in the covariance role reverses that: −0.002086 and
−0.000331, both CIs excluding zero. That is the substantive thing Phase 5 fixed.

## 5. The four splits

`sec2_85` vs `raw25` (the flag's incremental effect), and vs `indep`:

| split | n | games | pos | vs `raw25` log-loss | vs `raw25` Brier | vs `indep` log-loss |
|---|---|---|---|---|---|---|
| 2-leg ALL | 162,491 | 151 | 14.14% | −0.000799 [−0.001020, −0.000579] SIG | −0.000230 [−0.000304, −0.000152] SIG | −0.002163 [−0.003298, −0.000990] SIG |
| **2-leg SAME-player** | 8,205 | 149 | 22.10% | **−0.016431 [−0.022403, −0.010461] SIG** | **−0.004246 [−0.006114, −0.002387] SIG** | −0.041591 [−0.053195, −0.030404] SIG |
| 2-leg CROSS-player | 154,286 | 151 | 13.72% | +0.000039 [−0.000093, +0.000175] null | −0.000014 [−0.000045, +0.000017] null | −0.000054 [−0.000713, +0.000613] null |
| 3-leg ALL | 44,940 | 151 | 5.74% | −0.000103 [−0.000486, +0.000332] null | −0.000026 [−0.000085, +0.000031] null | −0.001808 [−0.003868, +0.000069] null |
| 3-leg has-same-player | 7,056 | 149 | 7.84% | −0.000593 [−0.002279, +0.001069] null | −0.000090 [−0.000453, +0.000250] null | −0.010733 [−0.018296, −0.003557] SIG |
| 3-leg all-cross-player | 37,884 | 151 | 5.35% | −0.000005 [−0.000328, +0.000340] null | −0.000011 [−0.000043, +0.000023] null | −0.000091 [−0.001229, +0.000980] null |

**The mechanism is entirely the 5% of pairs that are same-player.** Cross-player
pairs — 95% of the population, and where the commit's difference was most
negative (−0.0249) — show **no outcome effect at all**, on either metric,
against either `raw25` or independence. The −0.0249 price difference was real
and changed nothing measurable about calibration.

**Three-leg is UNMEASURED, not positive.** Every 3-leg `vs raw25` CI spans zero.
This is the segment the n-leg estimator was built for — the commit's own
motivating example is a 3-leg ticket whose mean describes none of its pairs —
and it is exactly where the result is null.

**n the observed variance would need**, to resolve these nulls at their own
point estimates (scaling games by (half-width / |effect|)^2):

| null cell | observed | games needed |
|---|---|---|
| 3-leg ALL, `sec2_85` vs `raw25`, log-loss | −0.000103 | **~2,360** (have 151) |
| 2-leg CROSS, `sec2_85` vs `raw25`, log-loss | +0.000039 | ~1,750 |
| 3-leg has-same-player, `sec2_85` vs `raw25`, log-loss | −0.000593 | ~1,190 |
| 3-leg ALL, `sec2_85` vs `indep`, log-loss | −0.001808 | ~179 |
| pooled, `sec2_25` vs `raw25`, log-loss | +0.000003 | ~438,000 |

That last row is the point: the estimator-vs-weight difference is not merely
unproven, it is **small enough that no feasible sample would establish it.**

## 6. The cap, checked separately

The cap moved 0.25 -> 0.85 (scaled by measured share via `_effective_max_shift`;
every pair here is measured, so the effective cap is the full 0.85). It binds on
**1,494 / 162,491 two-leg pairs (0.92%)** and **2 / 44,940 three-leg (0.004%)** —
reproducing the commit's 0.72%.

| cap raise applied to | pooled log-loss | 2-leg same-player | 2-leg cross-player | 3-leg ALL |
|---|---|---|---|---|
| flag-sum (`heur85` vs `heur25`) | **+0.017148 WORSE** | −0.019229 better | +0.015212 WORSE | +0.030454 WORSE |
| measured raw (`raw85` vs `raw25`) | −0.000570 better | −0.014864 better | −0.000000 inert | +0.000101 null |
| shipped estimator (`sec2_85` vs `sec2_25`) | −0.000652 better | −0.016265 better | −0.000000 inert | −0.000013 null |

Three things follow, and all three matter:

1. **The cap is the whole mechanism.** Its effect (−0.000652) is the entirety of
   `sec2_85`'s margin over `raw25` (−0.000648).
2. **The cap raise is safe only on a measured coefficient.** On the flag-sum it
   is a +0.0171 regression pooled and +0.0305 on 3-leg. Coupling the bound to
   measured share is therefore load-bearing, not hygiene — and since the cap IS
   the mechanism, a silent drop in measured share removes the benefit, it does
   not merely "make the estimator quieter".
3. **The cap is inert on cross-player pairs** (−0.000000; max |w| 0.4097 never
   reaches either bound), so the old 0.25 was never restraining them. The
   commit's justification for raising it is confirmed on outcomes.

**One negative that survives:** the threshold conversion used as a Fréchet
weight is **WORSE** on same-player pairs — `conv25` vs `raw25` log-loss
+0.001586 [+0.001045, +0.002192], Brier +0.000101 [+0.000071, +0.000133]. This
independently reproduces the earlier CONV result the commit cites. The
conversion only pays in the covariance role at a raised cap. The commit's
argument that the units belong there and not in the weight is upheld by
measurement rather than by reasoning alone.

## 7. Population limits — does a June-July result license a September claim?

**For the dependence structure: yes, and this was checked rather than assumed.**
The June |w| distribution reproduces the September run closely:

| \|w\|, 2-leg | June (this run, n=162,491) | September (commit, n=181,476) |
|---|---|---|
| all, p50 / p90 / p99 | 0.0409 / 0.1295 / 0.8271 | 0.0394 / 0.1234 / 0.7211 |
| all, share <= 0.25 | 94.96% | 95.75% |
| same-player p50 / share <= 0.25 | 0.6107 / 1.86% | 0.5930 / 1.85% |
| cross-player max | 0.4097 | 0.3647 |
| cap binds (\|w\| > 0.85) | 0.92% | 0.72% |

So the quantity the estimator consumes, and the rate at which the cap engages,
are the same in both windows. The cap-raise result is the transportable part.

**For the outcomes: NO, not without caveats.** Plainly:

- The joint producer deployed **2026-09-04T23:26Z**. There is **no June
  production joint.** These joints were manufactured by running *today's* sim
  code on June `roster_objs`. That holds the estimator constant, which is what
  the comparison needs, but it means **production never priced these games this
  way** and no artifact in production corresponds to any row here.
- The sim engine between July and September is **not** held constant, only the
  scoring code is. Any change to hitter distributions since 2026-07-11 moves the
  marginals, and the marginals enter `threshold_correlation` and the covariance
  term directly.
- June rosters are v4 artifacts; September has September call-ups, different
  lineups and a different league-wide run environment. The 26 lineup batters per
  game here vs **29** in the production joint (138 labels vs 153) is a visible
  instance of that drift.
- The population is **edge-selected** (`daily_top_props`), so this is
  conditional on the props the model already likes.
- Team segment dimensions and `strikeouts` are in the joint and are **not
  scored here at all.**

What this licenses: a claim about *the estimator and the cap*, on same-game
batter-prop pairs of the kind the board bets, on 151 games of real outcomes.
What it does not license: any claim that the September board's parlays are
better priced — that needs a settled-September reading, and
`props_actuals` carries 28 batter rows / 123 pairs / **0 positives** over the
four settled dates, which is why this backfill existed.

## 8. What to do

**Enable the flag**, and change what is claimed for it:

- The commit's title — "price off the MEASURED joint, not a pairwise average" —
  names the part that scored **NULL**. The part that scored is the cap. Say so,
  or the next session will extend the estimator expecting the estimator to be
  what works.
- **Monitor `pairs_measured / pairs_total`.** `_effective_max_shift` scales the
  cap by measured share, and the cap is the mechanism, so a coverage drop
  silently removes the benefit. Coverage here was 100% **by construction** (legs
  were built from the joint's own players and mapped markets) and says nothing
  about board coverage — same limitation the commit already flagged.
- **Do not claim a 3-leg improvement.** It is unmeasured at 151 games and would
  need ~2,360.
- A cheaper alternative exists and should be stated rather than hidden: since
  `raw85` ~= `sec2_85` everywhere, raising the cap on the **already-wired** raw
  measured coefficient captures essentially the whole gain without the
  second-order estimator. The flag bundles the two; the evidence separates them.
- **Resolve §3 before quoting any "vs today" number**: read which process holds
  the measured-correlation registration in production. Until then, −0.000648
  (vs `raw25`) and −0.004663 (vs `heur25`) bracket the flag's true incremental
  effect, and the commit's headline difference sits on the wrong end of that
  bracket.

## Reproduce

```powershell
py -3 scripts/session_worktree.py open --lane <slug> --with-data
py -3 scripts/backfill_mlb_sim_joint.py          # or shard by date; 48 min / 5 procs
py -3 scripts/score_joint_pair_pricing.py        # shipped: 2-leg, fixed cap
```

The shipped scorer covers neither the 2x2 cap design nor 3-leg tickets nor the
`raw25` baseline. The extended scorer used here (8 arms x 7 splits, per-game
bootstrap, |w| distribution) is scratch at `scratchpad/score_ext.py`, with
output `score_full.txt` / `score_full.json`.
**Folding it into `scripts/score_joint_pair_pricing.py` is the obvious follow-up
and was deliberately not done in this lane** — the brief was one findings file
and no production-pricing change.
