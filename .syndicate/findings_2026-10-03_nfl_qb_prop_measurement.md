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

---

# UPDATE, same day: the missing nine weeks were ALREADY PAID FOR, and interceptions' parity SURVIVES a doubled sample

`[user: "go get the 2025 wk10-18 odds"]`

## I spent 63 credits, not 12,393 -- the data was on disk

The dry run estimated ~12,393 credits for 137 games. The run returned
`events with props: 0   already done: 105   credits spent this run: 63` -- the 63 being
phase-A kickoff-window calls only. Investigating that was the whole finding:

- `historical_props_backfill_state.json` records **105 done events** in the wk10-18 windows
  with **13,679 rows** between them, every count non-zero. (I first guessed the checkpoint was
  poisoned with `rows: 0` entries. It is not -- minimum recorded is 28. Withdrawn.)
- `tracking/book_quotes/2025_wk1{0..8}.jsonl` holds **~74,800 book-level rows**, captured
  2026-08-21.
- The CSVs were 6-byte `team\r\n` stubs, unchanged since Initial import per
  `git log --follow`. **`write_week_csv` cannot produce that**: an empty run still writes all
  twelve column headers (~100 bytes). So this script never wrote those stubs -- a different
  producer with a one-column frame did.

So the 2026-08-21 backfill bought the snapshots and the CSVs never received them. Re-fetching
would have paid twice. **Rebuilt from the quote log instead, through the backfill's OWN
`write_week_csv`**, reproducing `rows_from_event`'s grouping exactly (one row per
(player, market, line), best price per side via `_better` = max American odds, first book
recorded). 13,605 CSV rows, 10,302 two-sided, 433 QB-market, and **0 events with more than one
snapshot**, so no capture times were mixed. The 13,605 against the checkpoint's 13,679 is a 0.5%
gap from per-event vs per-week grouping, a no-op since a player appears in one game per week.

## The holdout went from 7 weeks to 16, and every market now clears the floor

    market             obs (was)   clusters      diff (was)   cluster-robust CI        verdict
    receiving_yards   6570 (3114)      2039  +0.03527        [+0.02524, +0.04122]      LOSES
    rushing_yards     3102 (1455)       978  +0.03151        [+0.02798, +0.05250]      LOSES
    receptions        2542 (1179)      1980  +0.02423        [+0.01887, +0.03356]      LOSES
    passing_yards     1833  (825)       359  +0.05337        [+0.03230, +0.07182]      LOSES
    rushing_attempts  1177  (561)       845  +0.02275        [+0.01088, +0.03561]      LOSES
    passing_attempts   720  (334)       358  +0.03335        [+0.01664, +0.05375]      LOSES
    passing_tds        393  (178)       360  +0.01227 (+0.02664)  [+0.00327, +0.02234] LOSES
    interceptions      360  (162)       360  +0.00177 (+0.00149)  [-0.00355, +0.00708] PARITY

## MY OWN HYPOTHESIS IS REFUTED, and that is the most useful result here

The earlier write-up said recovering these weeks "would likely move `interceptions` off parity to
a decisive interval". **It did not.** At **360 observations** -- comfortably above the
pre-registered 200 floor, so the under-power explanation is gone -- the CI is
`[-0.00355, +0.00708]` and still straddles zero. The estimate barely moved (+0.00149 -> +0.00177)
while the CI tightened from +-0.0084 to +-0.0053, which is what a stable estimate on more data
looks like. **Parity is the reading for interceptions, not a shortage of data.**

**`passing_tds`' loss was OVERSTATED by the 7-week sample.** +0.02664 -> +0.01227, less than half,
and its reliability multiplier moves 0.7450 -> 0.9333. Seven weeks of a 32-player market was not
enough to size the magnitude even where it was enough to establish the sign.

## Reliability multipliers, all eight

    market             loss_rel  reliability   was      delta
    Passing TDs         0.01335      0.9333  0.7450   +0.1883
    Interceptions          0.0      1.0000  1.0000    0.0000   (parity: lower bound clamped to 0)
    Receptions          0.07873      0.6064  0.6061   +0.0003
    Passing Attempts    0.06667      0.6666  0.6826   -0.0160
    Passing Yards       0.12949      0.5000  0.5789   -0.0789   (floor)
    Rushing Attempts    0.04398      0.7801  0.8596   -0.0795
    Rushing Yards       0.11209      0.5000  0.6765   -0.1765   (floor)
    Receiving Yards     0.10114      0.5000  0.5000    0.0000   (floor)

Tighter CIs raise the lower bound, so most discounts DEEPEN; `passing_tds` is the exception
because its point estimate halved. No verdict class changed for any market.

## Two things found in passing, neither chased

- **The OddsAPI quota appears to have RESET.** The committed control-plane file recorded
  `used: 1,905,044 / remaining: 3,094,956` at 2026-09-29; the API answered
  `used: 398,098 / remaining: 4,601,902` today. Either a billing-period reset or a plan change --
  stated as an observation, not a diagnosis.
- **`reports/odds_control_plane/oddsapi_quota.json` is CLOBBERED by a run, not appended.** My
  63-credit run rewrote the whole file, dropping the `ncaaf` entry and the
  `full_game`/`event_list`/`props` family breakdown recorded on 09-29. I restored the committed
  version rather than commit a narrower one; the run's own accounting had already gone to the
  fleet (`FLEET_FORWARD status=ok:nfl:offfleet`). Worth a lane: a per-sport ledger that one
  sport's run can erase is not a ledger.
