# College live half lines, RE-GRADE on nights 11-13 .. 12-06 — PRE-REGISTRATION (todo #763 + #736)

Written 2026-11-16 ~6:30 PM CST, before any outcome in the window below is read. User, 2026-11-16: "do the NCAAB
segment re-grade too", after the NFL (#752), NCAAF (#805) and NBA (#818) segment grades were registered. Run date:
**Tuesday 2026-12-08, 1:00 PM CST**, by a scheduled task.

## What is being re-graded

The registered grade of lane `college-segment-grade` (`.syndicate/findings_2026-11-13_college_segment_grade.md`,
registered `50d20adcd`, grader `scripts/college_segment_grade.py`, blob **`dbcdcce69a22`**).
- **What it scores:** every OPINED row of the live segment expert (`live_segment/1`) on NCAAB h1/h2 x totals/spreads:
  the engine's live probability beside the books' de-vigged median at the same instant, by the newest book quote's
  age.
- **Its rule:** eight primary tests, (h1, h2) x (totals, spreads) x quote age <= 30 s and <= 120 s. A test PASSES
  with >= 30 games AND the family-wise (Bonferroni over 8) interval's upper bound below 0.
- **Its result** on 162 games, nights 11-09 .. 11-12: all eight `no_edge`, so `#763`'s college live segment pricing
  stays OFF. At <= 120 s the engine sits within ~0.01 Brier of the books (95% half-widths 0.008-0.014). Against
  quotes 5-15 min old it wins big, the game having outrun the quote (#780's pattern on halves).
- **Why re-grade:** four nights cannot rule out an edge smaller than ~0.01 Brier. 24 more nights, at roughly
  40-50 graded games a night, should shrink the half-widths by more than half.

## Population

Exactly the registered grade's, with one change: **`PREREG["dates"]` = every ESPN NCAAB scoreboard date 2026-11-13
.. 2026-12-06 (24 dates).**
- The span is therefore 11-12 .. 12-07: one enumeration over every evidence file and quote shard in it.
- Everything else in `PREREG` is unchanged: expert version, segments, markets, ceilings, age buckets, min_games 30,
  alpha 0.05, n_tests 8, 20,000 bootstrap draws, **seed 763**, edge_pp 0.05.
- Read 2026-11-17 00:3xZ (fleet, read-only, no score):
  - `live_evidence/ncaab/` holds 11-09 .. 11-16 (4-8 MB a night, 39 MB in all). `artifact_retention` has no rule
    for it.
  - Scoreboards are present for 11-08 .. 11-16.
  - The fleet checkout (`69bd95177`) carries the registered grader blob.

**Conditions:**
- **(a) Every date's evidence file and scoreboard exists at run time.** A missing date is excluded BY NAME and
  reported. It is never back-filled from a mirror.
- **(b) Same estimator over the window.**
  - `#816`'s college total calibration loaded 2026-11-17 00:04:20Z, mid-window. It is scoped to college FULL-GAME
    totals; at run time, `tests/test_college_total_calibration.py::test_only_college_full_game_totals_are_calibrated`
    must pass on the run's checkout.
  - List every fleet load in the window (`.syndicate/deploys.md`) whose commits touch:
    - `syndicate/features/shared/engine_experts.py` (`live_segment_expert` / `live_segment_opinions`);
    - the segment path of `syndicate/features/shared/live_gameline_join.py`;
    - `syndicate/features/college_basketball/total_prob_calibration.py`;
    - the college live re-sim's segment blocks.
  - **If the scope test fails, or such a load changes the segment p,** the window is split at that load time.
    - The eight tests run on each part.
    - The verdict of record is the LATER part (the code that would be switched on), provided every primary cell has
      >= 30 games. If not, the later part reads `insufficient` and the earlier part is reported as descriptive.
- **(c) The college segment pricing switch** (`SYNDICATE_COLLEGE_LIVE_SEGMENT_PRICING`) is irrelevant to the expert,
  which opines either way. Record its fleet state for context only.

## Method — the registered grader, unchanged

Run the blob `dbcdcce69a22` through this wrapper, and nothing else. It mutates `PREREG` in place, so `grade()`'s
default argument sees the same dict:

```python
import sys
sys.path.insert(0, sys.argv[1])
import scripts.college_segment_grade as g
assert g.PREREG["seed"] == 763 and g.PREREG["n_tests"] == 8
g.PREREG["id"] = "college_segment_grade/2"
g.PREREG["registered"] = "2026-11-16, todo #763 re-grade, before any outcome was read"
g.PREREG["dates"] = tuple(f"2026-11-{d:02d}" for d in range(13, 31)) + tuple(f"2026-12-{d:02d}" for d in range(1, 7))
raise SystemExit(g.main(sys.argv[2:]))
```

- **Where:** on the fleet, read-only, at nice 19, under refresh-worker's environment, as the original ran.
  - Execute `python3 <wrapper> <checkout> --count-only` first, then `--grade --json <out>`, ONCE.
  - `<checkout>` = the fleet's `~/Syndicate` if its `scripts/college_segment_grade.py` is blob `dbcdcce69a22`.
    Otherwise use a checkout holding that blob.
  - The environment is read from refresh-worker's `/proc/<pid>/environ`, never printed.
- **Count-only first** (no score is read); record its tables. Then the grade.

## Gates

**The eight registered tests, unchanged:** the verdict of record.
- No test passes: `#763` stays off, now on this sample.
- A test passes: its smallest passing ceiling is a candidate quote-age ceiling for `#763`. A candidate, not a switch.

**Beside it, never a decision:**
- The registered by-age buckets and claimed-vs-realised edges.
- **A pool of nights 11-09 .. 12-06** (the original 162 games plus these): descriptive only, run by the same wrapper
  with `dates` 11-09 .. 12-06.

## Predictions, registered now

| # | prediction |
|---|---|
| P1 | No primary test passes. |
| P2 | Every <= 120 s cell's 95% half-width is below 0.008. |
| P3 | In every pair, d in the 300-900 s bucket is below d in the 0-30 s bucket, with the 300-900 s interval below 0. |
| P4 | At <= 120 s the realised edge on rows the engine and books differ by >= 5 pp is below half the claimed edge in every pair. |
| P5 | More than 70% of opined rows sit on quotes older than 120 s. |

**Falsification of the 11-13 verdict:** any primary test PASSES.

## What the result is allowed to change

- **Nothing is changed by the run itself.** It writes results here, plus the todo, the log and a deploys.md READING.
- **If a test passes,** turning college live segment pricing on at that ceiling (`SYNDICATE_COLLEGE_LIVE_SEGMENT_PRICING`
  plus a ceiling) is the user's call, with the numbers. That is a fleet env change: the #763 owner's recipe, never
  done by the run.
- **Out of scope:** WNCAAB (no segment quotes), full-game lines (#816 owns college totals), and pregame halves.

## Data

Read in place on the fleet (`~/syndicate-prod/data`: `live_evidence/ncaab/`, `ncaab_source/tracking/book_quotes/`
shards via the grader's own reader, `ncaab_source/data/scoreboard/`). Nothing is written to the fleet. The output
JSON goes to `/mnt/c/tmp/ncaab_seg_regrade/` (a new directory).
