---
name: daily-accuracy
description: Read back the daily model-scorecard cron's published artifact and report what the models are actually measured on -- per sport, per market, per segment, pregame and live -- plus what is ungradable and what changed overnight. Use when asked how the models are doing, whether the daily accuracy/backtest job ran, what beat or lost to the market, whether a sport is being graded, or to check the bucket overlay and the weekly backtests.
---

# Daily accuracy

Paths below are relative to the repo root; this file's own path is
`.claude/skills/daily-accuracy/SKILL.md`.

## What already exists (read this before building anything)

**A daily job already does the work.** The Render cron `model-scorecard`
(`crn-dam0ao942hec73cge0rg`, schedule `30 11 * * *`, branch `main`) runs
`scripts/publish_model_scorecard.py` from a fresh clone, grades the Layer 2
**priced** population (`opportunity_population_ledger` — never the published
subset), and publishes a dated scorecard plus a validated-bucket overlay. On
Mondays it also runs `scripts/run_weekly_backtests.py`.

Its output is served read-only by `syndicate/blueprints/model_scorecard.py`:

| route | what it returns |
|---|---|
| `GET /api/model-scorecard` | the latest scorecard |
| `GET /api/model-scorecard/<YYYY-MM-DD>` | one dated scorecard |
| `GET /api/model-scorecard/overlay` | the bucket overlay + whether this process's scorer is using it |
| `GET /model-scorecard` | the human-readable markdown for the latest slate |

All four need `X-Admin-Token`.

**So do not write a second grader.** A second number for the same question,
computed by different code on a different substrate, produces an argument nobody
can settle. This skill is a READER.

## Running it

```bash
ADMIN_TOKEN=... python .claude/skills/daily-accuracy/driver.py
```

Stdlib only, no repo imports — it runs from a bare checkout, against production
by default (`--base-url`, or `SYNDICATE_BASE_URL`). Useful flags:
`--json` for the machine-readable summary, `--compare-to YYYY-MM-DD` to diff
verdicts against a specific earlier slate, `--no-compare`, `--max-age-hours`.

Exit codes, so it can gate a scheduled task rather than only inform a human:
`0` fresh and no regression · `2` artifact **stale** · `3` a sport that was
graded is graded no longer · `4` unreadable · `5` no token.

## What the report says, and why each line is there

**Freshness is judged on the artifact's `generated_at`, never a scheduler
field.** `lastRunAt` is a *dispatch* timestamp. On this platform a scheduled job
has been observed dispatching on time while its child did not run for 9h13m — so
a job can look perfectly healthy having produced nothing. Judge by the artifact.

**Windows can be shorter than their label.** Measured 2026-09-20: `7d` and `28d`
held identical cells (263 each) because the population recorder only started
2026-09-14. A `28d` heading over 6 days of data is a claim the data does not
support. The driver flags this two independent ways — recorder age versus the
label, and "are these cells identical to a shorter window's" — because either
test alone is foolable.

**Ungraded rows are reported as a RATE, never a count.** A count has no
denominator: soccer's 2,887 `player_not_in_box` is unreadable until you know it
sits against 14,319 graded rows (11.5%). Sorted worst-rate-first.

**An absent sport and an off-season sport are distinguished.** Both are simply
missing from the payload, and they mean opposite things:

- *NO SETTLER, in season* — a real gap; nothing can grade that sport.
- *off-season (settler ready)* — deliberate. NBA and NCAAB are excluded from the
  daily read while out of season (`publish_model_scorecard.py`, `DEFAULT_SPORTS`)
  because each board date would spend a not-found read on them. A **cost
  decision, not a defect** — do not "fix" it by re-adding them mid-summer.
- *SETTLER REGISTERED, ZERO ROWS, in season* — a defect. This is what NHL read on
  2026-09-20.

The season windows in `driver.py` (`SEASON_WINDOWS`) exist **only to label**;
they never change what is graded.

## Reading a verdict honestly

A cell is `sport | market | segment | phase`, scored as
`brier(model) − brier(market)` on the side, **per game**, with a bootstrap CI
over games and Benjamini–Hochberg FDR at q=0.10. Negative means the model beat
the market.

- **`insufficient` means no sample, not no edge.** It was 222 of 263 cells
  (84.4%) on 2026-09-20. Quoting "only 1 cell beats the market" without that
  denominator is the single easiest way to misread this artifact.
- **Check `lodo_stable`.** A verdict that leave-one-date-out does not survive is
  one good night, not a finding.
- **The unit is the game**, so `n=78g/6d` is 78 games over 6 dates — and 6 dates
  is not a season. Early verdicts move a lot; the driver prints overnight verdict
  changes for exactly that reason.

## The optimization half

Bucket promotion is **already automatic and bounded**: the weekly search
validates buckets, the overlay carries them with an `expires_at`, and
`measured_bucket_skill` reads it at score time on web and refresh-worker, behind
an env kill switch. The driver prints `switch_enabled`, validity, bucket count
and time-to-expiry, and says so loudly when the overlay has expired and the
scorer has fallen back to the static table.

`weekly_backtests` is absent from the artifact on six days out of seven — that
is `weekly_due` gating on `weekday() == 0` (Monday, Central), not a failure.

## When something is wrong

Work backwards along the pipeline and find the first stage that is zero, rather
than starting at the report:

```
board build -> opportunity_population_ledger (priced rows)
            -> settler (population_outcomes*, per sport)
            -> graded rows -> cells -> verdict -> overlay
```

The scorecard's own `run` and `state` blocks carry the early stages
(`board_dates`, `grading`, `graded_games`, `pending_games`), so a sport with
board parts but no graded rows is a settler problem, and a sport with no board
parts is upstream of grading entirely.

**Do not diagnose any of this from `data/` in the local checkout** — it is a
lossy cold-start mirror with per-family date gaps, never evidence about what
production computed.
