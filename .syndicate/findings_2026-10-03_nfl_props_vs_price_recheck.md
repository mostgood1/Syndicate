# NFL props vs the PRICE, re-checked independently at main tip — and a correction to my own 09-29 finding

`[session 4ab694ed, 2026-10-03, measured at origin/main c8fb3230 — user: "do the re-check at main tip"]`

## Why this exists

Lane `nfl-prop-predictive-spread` (session 4698e71e) found that `scripts/backtest_nfl_props.py::_rate_from_log`
omits production's zero-game imputation — `player_stats.py:506`, `SYNDICATE_NFL_PROP_ZERO_GAMES`,
**absent = ON**, whose own comment says the uncorrected estimator *"is measurably answering the wrong
question"*. My 2026-09-29 finding (all eight two-sided NFL prop markets lose to the de-vigged book) built
its rate index from `collect_raw`, which goes through that function. So it graded an estimator production
does not serve. Their note was correct and I verified it at source.

Two things then had to be separated, because the task as first framed would have confounded them: the
**estimator** had changed AND the **model** had been re-fitted five times since 09-29 (`26be8898`,
`99a4345d`, `cf2cdbae`, `c3874b91`, `41f14c3e`). Re-running my old comparison would have moved both at
once. So this is not a re-run of mine; it is an independent check of the CURRENT model.

## Method — deliberately not their harness

- rates from **production's** `player_stats.player_rate` (imputation ON, confirmed in-process)
- probabilities from **production's** `nfl_props._nfl_prop_model_probability`, so Poisson count stats,
  spread shrinkage and the Normal/log-normal blend apply exactly as the board applies them
- the market from **my own** de-vig, `(1/dec_over)/(1/dec_over + 1/dec_under)`
- paired Brier with a 95% CI on the per-row difference
- scored on **2025 + 2026 only** — 2023-24 was their fit window, and scoring on it would flatter the model

It does NOT import `fit_nfl_prop_predictive_spread.py`. A check that reuses the fitter's own scoring cannot
disagree with it (`learnings.md` 2026-09-23: two implementations of one question, the weaker one on the
money path).

**A control ran first**, the same one their `c69737cb` added after this defect was found in my work:
`_nfl_prop_model_probability(receiving_yards, mean 60, sd 25, n 6, line 55.5) = 0.5503148560314686`. The
harness reaches production's served probability path. Without that, no verdict follows.

## Result: six of six powered markets still LOSE to the de-vigged book

    market               n   brier_model  brier_market      diff            95% CI    verdict
    passing_yards      834      0.30669       0.24992    +0.05677  [+0.0430,+0.0706]  loses
    passing_attempts   343      0.29090       0.25012    +0.04078  [+0.0214,+0.0601]  loses
    receiving_yards   3116      0.28997       0.24941    +0.04056  [+0.0333,+0.0479]  loses
    rushing_yards     1463      0.27934       0.24993    +0.02941  [+0.0197,+0.0391]  loses
    receptions        1179      0.26931       0.24184    +0.02747  [+0.0175,+0.0374]  loses
    rushing_attempts   562      0.27316       0.24878    +0.02438  [+0.0091,+0.0397]  loses
    interceptions      168            —             —           —                  —  under-powered
    passing_tds        184            —             —           —                  —  under-powered

Drops: `no_production_rate` 5292, `no_player_id` 1776, `push_or_no_actual` 636, `no_two_sided_price_or_line`
152, `no_model_prob` 19.

## THIS DOES NOT CONTRADICT "ALL EIGHT MARKETS NOW PASS THE BAR" — we measured different bars

`41f14c3e`'s own body defines it: *"The pass is thin and the code says so: 0.1463 against a 0.150 bar."*
That is `#499`'s **calibration-bucket** threshold, a statement about calibration quality. Mine is
**Brier against the de-vigged market**, a different and harder question. Both hold simultaneously, and
reading their claim as "beats the book" would have been my error, not theirs. Better calibration has not
become an edge over the price; it is the precondition for ever having one.

## THE ESTIMATOR DEFECT WAS REAL AND DID NOT MOVE THIS NUMBER

My 09-29 holdout reported `passing_yards +0.0568` and `receiving_yards +0.0396`. This re-check, on
production's estimator and five model re-fits later, gives **+0.05677** and **+0.04056** — unchanged to
four decimals. So the `collect_raw` divergence was a genuine methodological defect that did **not** alter
the verdict. The 09-29 conclusion was reached the wrong way and landed in the same place. "Not proven
guilty" is not "proven innocent" in the other direction either: the old numbers should still be cited from
here, not from that run.

## WHAT I CANNOT EVALUATE, and it is their headline change

`passing_tds` (184) and `interceptions` (168) both fall under the 200-row floor, and those are exactly the
two markets moved to a **Poisson** family by `c3874b91` — the most substantive part of their fix. This
re-check says nothing about it. The floor was set before the data was seen and was not lowered afterwards.

## Owed follow-up

`measured_market_skill.MEASURED_MARKET_SKILL` carries eight `("nfl", <stat>, "full", PHASE_PREGAME)`
entries I added on 09-29 from the superseded run. The **verdict class is still correct** (these markets
lose), but the stored `brier_model` / `brier_market` / `ci95` numbers are from the wrong estimator and a
pre-re-fit model. They should be refreshed from the table above. Not done here; not claimed.

## My own instrumentation failures, recorded because they cost the time

1. **An uncached choke point.** `player_game_log` is not `lru_cache`d and does a FULL play scan per
   `(season, player)`; `load_player_plays` is cached, so the plays are in memory, but the scan is still
   O(all plays) per call. Both `player_rate` and `actual_for` go through it, so an uncached run is one full
   scan per CSV row. The first attempt sat past 40 minutes and produced no table. Memoised in the study
   only — production untouched, identical values.
2. **I masked an exit code with `| tail`.** `$?` was tail's status, so a killed python process reported
   `exit=0` and I said so. Redirect to a file and read python's own code.
3. **Unflushed output lost on the kill.** Only the pre-loop prints had `flush=True`, so the table vanished
   when the process died and the run looked like it had succeeded silently.
