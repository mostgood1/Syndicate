# PRE-REGISTRATION: NCAAB live totals, fresh quote, |edge| >= 20 pp (todo #780)

Registered 2026-11-13 by lane `ncaab-live-edge20-prereg`, session 8062940b. The registration time is when the commit
that adds this file reached `origin/main`. Nothing in the registered window existed at that time: the clock read
14:38Z, and `PREREG_780=count` found 0 priced NCAAB totals states on dates >= 11-13.

**Do not edit the rule below after that commit.** A changed rule is a new registration with a new name.

## Hypothesis

- **H1:** the rule below wins more than the -110 break-even, 0.5238, on games it has not been tuned on.
- **Origin:** `.syndicate/findings_2026-11-10_live_totals_grade.md`, result 1. The cell hit 0.590 +- 0.083 over 134
  games (ledger dates 11-02..11-09).
  - It was the best of about 12 cells read, so it is a hypothesis, not a result.
  - The same cell read 0.484 in NBA (31 games) and 0.520 in NCAAF (196). Those are not registered.

## The rule

Code: `scripts/live_totals_grade.py`, `PREREG_780`, with the constants `PREREG_*`.

- **Population:**
  - Source: the fleet's `ncaab_source/data/live_gameline_ledger/live_gameline_ledger_*.jsonl`.
  - Rows: `market` totals, `segment` full, `priceable` true, with model P(over), market fair P(over) and line present.
  - Ledger `date` >= **2026-11-13**.
- **State:** `(event_id, live_state_as_of or recorded_at, line)`. The first ledger row is kept.
- **Grading against finals:** each game is matched to its ESPN final with the script's own `finals()` / `match()`.
  - A game with no match is dropped and counted.
  - A push (final == line) is dropped.
  - A state whose score already exceeds the final is dropped.
- **Side and edge:** the side is over when model P(over) > market fair P(over), otherwise under. The edge is
  |model - fair| x 100, in pp.
- **Bet:** each game's FIRST state, in `live_state_as_of` order (UTC), with edge >= **20** pp and `quote_age_seconds`
  <= **30**.
- **Sample:** the first **200** such games, in time order.

## Decision

- **hit** = the share of the 200 bets that win.
- **PASS:** the one-sided 95% lower bound, hit - 1.645 x sqrt(hit(1-hit)/200), is above 0.5238. That needs hit >= 0.5813.
- **KILL:** hit <= 0.5238.
- **INCONCLUSIVE** otherwise. The test then extends ONCE to the first 400 games under the same tests, and
  INCONCLUSIVE at 400 counts as KILL.
- **Deadline 2026-12-15.** If fewer than 200 games qualify by then, grade on what exists, provided it is >= 100.
  Otherwise the registration expires with no verdict.
- **What a verdict licenses:**
  - PASS licenses only the next step: a paper track of this rule at real taken prices. It does not license stakes.
  - KILL closes the cell.
- **Reported alongside, not deciding:** realised edge against the market fair, the model's claim, ROI at -110, and the
  over / under split.
- **Power at n = 200** (normal approximation):

  | true hit | P(PASS) | P(KILL) |
  |---|---|---|
  | 0.524, no edge | 0.052 | 0.498 |
  | 0.55 | 0.187 | 0.228 |
  | 0.59, the discovery rate | 0.599 | 0.029 |

- **For scale:** the discovery sample itself reads INCONCLUSIVE under this test: 0.590, lower bound 0.520 at n = 134.
  This was the code check below.

## What was seen before registering

- **The discovery sample,** 11-02..11-09.
- **A peek at 11-10..11-12.** A default-mode run of `live_totals_grade.py`, before 14:38Z 11-13, printed this cell over
  ledger dates 11-02..11-12: 151 games, hit 0.596.
  - So about 17 games from 11-10..11-12 were seen in aggregate.
  - That is why the window starts at 11-13 rather than 11-10.
- **The guard against a repeat.** The script's default mode now holds out NCAAB rows on dates >= 11-13, and prints how
  many it held out. `PREREG_780_INCLUDE=1` reads them, but only after the registered grade has run.

## Code check (seen data only)

`PREREG_780=grade PREREG_DATE_FROM=2026-11-02 PREREG_DATE_TO=2026-11-09` reproduces the published cell exactly:

- 134 games, hit 0.590, market fair 0.525, model claimed 0.793.
- Realised edge +0.064 +- 0.080. Over 43 / under 91.

On the registered window:

- `PREREG_780=count` prints counts only.
- `PREREG_780=grade` refuses below 200, outside the deadline rule.

## Reads allowed before the grade

- **`PREREG_780=count`:** game counts per ledger date. No outcomes.
- **The `#780` Brier re-grade** (`scripts/live_gameline_age_grade.py`, owed from 11-17). It reads a superset at state
  level (every edge, by quote age), and it does not print this cell, so it is allowed. Do not add an |edge| >= 20
  split to it for these dates.

## Changes since the discovery window

The test is of the rule as the fleet serves it, not of a frozen model. Known changes:

- **`#768`, the NCAAB live total bias fix,** loaded 05:13Z 11-09. Most of the discovery sample predates it: the model
  ran ~2 points low, and the cell leaned under, 91 / 43. Expect the side mix to shift.
- **The 120 s quote ceiling,** 18:11Z 11-11. It does not touch rows with quotes <= 30 s.
- **Price-on-pull (`#786`),** 20:45Z 11-11. It produces more fresh-quote rows.
- **`#774` / `#792`, midnight carryover,** which adds post-midnight states for late games.
- **`#795`, college team names,** 22:03Z 11-12. It anchors more games.
- **Any NCAAB live-engine change that loads before the grade**, e.g. `#780` candidate fix 2, a spread-width fit. It
  changes which edges this rule selects. Record it here, with its load time, before grading.

## Amendments

Both were made 2026-11-13, before any game in the window existed. `PREREG_780=count` read 0 states after each.

1. **The registered grade reads the engine's own probability.**
   - It reads `model_home_win_prob_unscaled` whenever the join tempered P(over); ledger v7, todo `#780` candidate
     fix 2, lane `live-totals-prob-scale`. Otherwise it reads `model_home_win_prob`.
   - The cell was found on untempered probabilities, so a later scale must not change which games it selects.
   - NCAAB's scale is 1, so today this changes nothing.
   - One residual effect: if NCAAB is ever scaled, the precision gate judges the tempered edge. That would move a few
     rows between `priceable` true and false. If that happens before the grade, record it here.
2. **Finals are re-fetched until a date is over.**
   - The grade's `finals()` trusted an ESPN scoreboard cached at any time. A file cached before that date's games
     ended dropped every one of them as unmatched.
   - Measured: the 11-10 / 11-11 NCAAB files, cached 11-10 ~17:00 CST, unmatched 16,631 states of the width fit.
     The 11-13 file had been cached that morning, before its games, so the registered grade would have lost all of
     11-13.
   - Now a cached scoreboard is reused only once it was written after noon UTC on the following day
     (`final_cutoff`). This is a bug fix, not a rule change.

## Runs

```
wsl -d Ubuntu-24.04 -- env PREREG_780=count nice -n 19 python3 /mnt/c/<repo>/scripts/live_totals_grade.py /mnt/c/tmp/livegrade/espn </dev/null
wsl -d Ubuntu-24.04 -- env PREREG_780=grade nice -n 19 python3 /mnt/c/<repo>/scripts/live_totals_grade.py /mnt/c/tmp/livegrade/espn </dev/null   # ONCE
```
