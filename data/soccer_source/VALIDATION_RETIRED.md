# Retired soccer backtest results — do not cite

**Audit §7 ranked fix #6, retired 2026-08-14.**

The 13 files listed below were produced with **lookahead leakage** and their
numbers are not evidence of anything. They are kept rather than deleted so the
retraction is auditable, and so a re-run can be compared against them.

## What was wrong

`compute_team_ratings` had no notion of time, and
`backtest_soccer_live_lens.run_backtest` called it **once per league** off the
full loaded season, then applied the result to **every match inside that
season**:

```python
ratings = _load_team_ratings(league)   # computed ONCE, whole season
for event in completed:                # applied to every match IN it
```

So a March match was scored using ratings built partly from May results. The
model was shown the answer. Every accuracy, calibration and edge number in
these files inherits that.

**This is a measurement defect, not a model defect.** It says nothing about
whether the soccer model is good — only that these particular numbers cannot
tell you.

## Affected — leaky, do not cite

    belgian_pro_league/validation/starter_backtest_100matches.csv
    bundesliga/validation/starter_backtest_full_season.csv
    epl/validation/live_lens_backtest_30min_cutoff.csv
    epl/validation/live_lens_backtest_60min_cutoff.csv
    epl/validation/starter_backtest_60matches.csv
    epl/validation/starter_backtest_full_season.csv
    eredivisie/validation/starter_backtest_100matches.csv
    eredivisie/validation/starter_backtest_100matches_true_per90.csv
    la_liga/validation/starter_backtest_full_season.csv
    ligue_1/validation/starter_backtest_full_season.csv
    mls/validation/starter_backtest_60matches.csv
    mls/validation/starter_backtest_full_season.csv
    serie_a/validation/starter_backtest_full_season.csv

## NOT affected — these remain usable

    championship/validation/h2h_2026-07-20.csv
    epl/validation/anchor_2026-07-19.csv
    epl/validation/anchor_weight07_2026-07-19.csv
    epl/validation/h2h_2026-07-19.csv
    epl/validation/red_card_before_after_samples.csv
    mls/validation/props_model_vs_market_2026-07-19.csv
    mls/validation/props_model_vs_market_top_minutes_2026-07-19.csv

These come from `validate_soccer_vs_market`'s **forward-looking** modes, which
simulate UPCOMING fixtures against the market. They never applied a rating to a
match that had already contributed to it. Blanket-condemning the whole directory
would have been the easy call and would have thrown away good evidence.

## What changed

`compute_team_ratings(rows, *, as_of, window=None)` — `as_of` is now
**required**, and rows dated on or after it are excluded (strictly before, by
calendar day). Required rather than defaulted because the three call sites are
not the same case:

- `backtest_soccer_live_lens` — evaluates past matches, now derives ratings
  **per match** as of that match's own date (memoised per day).
- `validate_soccer_vs_market` — forward-looking; passes the fixture date.
- `build_soccer_artifacts` — **production**, builds for future matches;
  behaviour unchanged, since every history row already predates the target date.

Pinned by `tests/test_soccer_team_ratings_as_of.py`, including a test that
fails if the ratings call is ever hoisted back out of the match loop — a
correct `compute_team_ratings` still leaks if the caller hoists it, which is
exactly what happened here.

## To re-run

`scripts/backtest_soccer_live_lens.py` needs network access (it calls
`fetch_completed_events` / `fetch_match_summary`). It was **not** re-run when
these were retired, so there is currently **no** leak-free soccer backtest
number for any league. That gap is real and should be stated as "unmeasured"
rather than filled from the files above.
