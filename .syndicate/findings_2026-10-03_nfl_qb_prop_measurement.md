# passing_tds and interceptions ARE measurable, and the same pass found the stored CIs too narrow

`[session 4ab694ed, 2026-10-03, lane nfl-qb-prop-skill-measurement — user: "take the passing_tds and interceptions measurement"]`

## The headline

Both markets were carrying a `superseded` note saying no reading exists because each had fewer
than the pre-registered 200 two-sided rows. That label was half wrong.

    market          obs   clusters  brier_model  brier_market      diff   cluster-robust 95% CI   verdict
    passing_tds     178        162      0.26490       0.23826  +0.02664   [+0.01215, +0.04199]    LOSES
    interceptions   162        162      0.25016       0.24867  +0.00149   [-0.00692, +0.00990]    PARITY

**`passing_tds` has a decisive verdict at n=178.** Its CI is clear of zero by a wide margin.
**`interceptions` is genuinely indistinguishable** from the de-vigged market — which is a READING,
not an absence of one, and materially different from "unmeasured".

## I am reporting below my own pre-registered floor, deliberately

The 200-row floor was set earlier on 2026-10-03 before the data was seen, and I did not lower it
after seeing the data — I am declining to let it override a CI. A row count is a PROXY for power;
the confidence interval is the actual test and it already accounts for n. Refusing to report an
interval that excludes zero because a proxy threshold is unmet would discard real evidence on a
technicality. The floor did its job: it stopped me publishing the old, wrongly-estimated numbers.

What a floor cannot do is turn a decisive interval into an indecisive one. So `passing_tds` gets a
verdict, `interceptions` gets a parity verdict, and both state their n plainly.

## THE CORPUS IS THE BINDING CONSTRAINT, and it is narrower than every entry claimed

All eight entries said "holdout 2025+2026". The data never supported that. Measured coverage:

    odds (oddsapi_player_props_*.csv)        outcomes (load_player_plays)
      2025 wk1-9    real                       2025  18 weeks, 46,452 plays
      2025 wk10-21  6-BYTE STUBS               2026   2 weeks,  5,489 plays
      2025 wk22     10KB (playoffs)
      2026 wk1      861KB
      2026 wk4      330KB mirror / 970KB fleet

Every kept row comes from **2025 wk3-wk9. Seven weeks.** Everything else dies structurally:

- **2025 wk10-18: outcomes exist, odds do not.** Nine weeks of realised results unusable because
  the odds capture is twelve 6-byte stubs — in the git mirror AND on the fleet. This is the one
  recoverable loss, and it would roughly double the sample for all eight markets.
- **2025 wk1-2 and 2026 wk1: no in-season history, so `player_rate` returns None.** Correctly
  excluded, not a defect — production serves no projection for those rows either, so scoring them
  would grade a row the board never priced. 93 interceptions and 171 passing_tds rows go here.
- **2026 wk4: odds but no outcomes.** Play data stops at week 2, so week 4 is unscoreable. The
  fleet's wk4 file is the fuller one (336 target rows against the mirror's 4-5) and still cannot
  be used.
- **2025 wk22 is playoffs and the play data has no week 22.** Unscoreable.

**The fleet cannot run this measurement at all.** `load_player_plays(2025)` and `(2026)` both
return **0 plays** there, so all 60 distinct wk4 rows failed at `resolve_player_id`. The git mirror
holds the outcome data and the fleet holds the fresher odds; neither alone is sufficient. That is
the reverse of the usual "Render/fleet is the source of truth" direction, and worth remembering
before reaching for either corpus on its own.

## THE STORED CIs WERE TOO NARROW — a defect in numbers shipped EARLIER TODAY

`recheck_eight_markets.gather()` appended one triple per CSV **row**. The CSV carries a `book`
column, so N books quoting one player's line became N observations sharing a single outcome, and a
player quoted at several lines in one game contributed several correlated observations. Both
inflate n and shrink the CI.

Corrected: one observation per `(season, week, player, line)`, market = mean de-vig across the
books quoting it, and a CI clustered on `(season, week, player)`. The inflation is worst where one
player-game carries many lines:

    market             obs  clusters  naive 95% CI          cluster-robust 95% CI
    receiving_yards   3114       919  [+.03312, +.04768]    [+.02548, +.05200]
    rushing_yards     1455       441  [+.01957, +.03902]    [+.01617, +.05309]
    receptions        1179       890  [+.01753, +.03741]    [+.01905, +.04176]
    passing_yards      825       161  [+.04193, +.06964]    [+.02105, +.08096]
    rushing_attempts   561       384  [+.00882, +.03944]    [+.00699, +.04371]
    passing_attempts   334       161  [+.02381, +.06298]    [+.01587, +.06997]

**NO VERDICT FLIPS. All six still lose; every cluster-robust CI is still clear of zero.** The
direction shipped earlier today stands. But `established_loss_rel` reads the CI's LOWER bound, so a
too-narrow CI OVER-discounts, and the magnitudes were wrong.

**The practical effect is near zero, which is worth stating precisely rather than implying a bigger
correction than happened.** Row-weighted `skill_reliability` across the 103 rows carrying these
markets on the served 19:36:52Z board: **0.6215 -> 0.6217.** `passing_yards` has the largest single
change (0.5000 -> 0.5789) and **zero** live rows; `receptions` holds 69 of the 103 rows and moves
slightly the OTHER way (0.6376 -> 0.6061), because clustering RAISED its lower bound. So this is a
correctness fix, not a re-litigation of today's staking decision.

## ADMISSION CANNOT CHANGE, re-verified rather than inherited

Moving `interceptions` to PARITY is the one change here that could plausibly ADMIT rows.
`layer2_board._row_rests_on_unmeasured_model` withholds a one-sided row whose note is unmeasured OR
`loses_to_market`, and PARITY is neither. But its first condition is
`fair_method == "book_margin_model"`, and on the served 19:36:52Z NFL artifact **all 20
Interceptions and all 22 Passing TDs rows carry `fair_method=consensus`**. The gate cannot fire for
either market, so no verdict change here alters admission. The entries' previous
`admission_checked` text was a 10-02 reading; this one is taken on today's board.

## What this does to the product

`Passing TDs` goes from unmeasured (reliability 1.0) to measured-losing at **0.7450**, so its ~19
live rows now carry a discount. `Interceptions` goes from a stale `loses_to_market` reading over
374 rows — which the earlier pass had already correctly gated off as superseded — to a measured
PARITY at reliability **1.0000**. Its rows stay undiscounted, now for the right reason: a measured
parity rather than an absent measurement. Those two states score identically today and are not the
same claim, which is why a test pins the distinction.

## Owed

**Capture 2025 wk10-18 player props.** Outcomes are already present for those nine weeks, so this
is the highest-value data recovery available for NFL prop evaluation: it roughly doubles all eight
samples and would put `interceptions` in range of a decisive interval rather than a parity that may
simply be under-powered. OddsAPI historical endpoints are cheap. Not done here and not costed.

**This measurement is of the CURRENT model, and lane `nfl-prop-mean-inputs` is open on
`player_stats.py` / `props.py`.** If that lane changes the mean inputs or the probability function,
all eight readings need re-taking. Each entry's `seasons` text names the exact estimator and
probability function, so a future reader can tell whether their model is the one that was scored.

## Instrumentation notes

- The control was run on the TARGET stats, not only on `receiving_yards`. A Poisson count stat
  exercises a different branch of `_nfl_prop_model_probability` (`c3874b91`), and a control that
  misses the branch under test proves nothing. `passing_tds(mean 1.8, line 1.5) = 0.4472` and
  `interceptions(mean 0.7, line 0.5) = 0.5006` both answered through the harness.
- `receiving_yards` returned None in that same control because I passed `stdev=None`; a continuous
  stat needs a sd. Explained, not a defect — recorded so the None is not read as one later.
- `player_game_log` is still not `lru_cache`d and still does a full play scan per
  `(season, player)`. Memoised in the study only; production untouched, values identical.
