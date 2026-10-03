# FINDINGS — what the WNBA prop book line knows that the model does not

**Lane** `wnba-book-information`, session `39b666bb`. **Date** 2026-10-03. **Measurement only.**
Model = the fix #2 + #3 stack (availability + rate shrink; as-of re-runs, evidence about the CODE). Book = OddsAPI
historical tip −60 min, de-vigged modal line. Regular season 2026 (points n 2,975; rebounds 2,542; assists 1,865;
PRA 2,086); playoffs reported but ~100 rows/market. `scripts/analyze_wnba_book_information.py`; full output
`C:/tmp/wnba_bt/book_info/book_information.json`.

## 0. Headline

1. **When the book and the model disagree, the book is right.** Regressing the outcome surprise (actual − model) on
   the disagreement (line − model): **points 0.94 [0.80, 1.07]**, PRA 0.90 [0.77, 1.02], rebounds 0.77 [0.63, 0.89],
   assists 0.62 [0.48, 0.77]. 1.0 would mean every point of the book's disagreement is information. The book's own
   over-rate is ~0.50 in every disagreement quintile -- it is calibrated at its line; the model is not.
2. **The book's information is split between MINUTES and per-minute RATE -- the "mostly minutes" hypothesis is only
   half right.** The 0.94 for points splits **0.41 minutes [0.34, 0.48] + 0.53 rate [0.42, 0.63]**; PRA 0.50 + 0.40;
   rebounds 0.32 + 0.44; assists 0.21 + 0.41. In the playoffs minutes dominates (points 0.82 minutes, rate n.s.; n 106).
   When the book sits ≥2.8 pts above the model, those players go on to play **+2.97 minutes** more than the sim gave them.
3. **Late absences are the largest single source, and the book under-prices them on points.** A teammate who played the
   team's previous game but does not play today (in the pregame inactive/injury report, so in no as-of history). With
   ≥15 such teammate-minutes (31% of points rows, 178 games):
   - model misses **+1.02 pts [+0.61, +1.44]** (vs −0.05 without), PRA +1.56 [+0.85, +2.23], rebounds +0.34, assists +0.34;
   - the book moves only **+0.35 pts** (vs +0.07) and itself still misses **+0.67 [+0.29, +1.08]** on points; on rebounds
     and assists it prices the absence fully (miss ≈ 0); PRA +0.47 [−0.24, +1.15].
   Remaining players gain **+1.36 minutes** in those games.

## 1. Disagreement buckets (regular season, points)

| book vs model | n | mean (line − model) | actual − model | actual − line | minutes surprise | over-rate |
|---|---|---|---|---|---|---|
| book far below | 595 | −2.12 | −1.55 | +0.57 | −1.45 | 0.506 |
| below | 595 | −0.75 | −0.56 | +0.20 | −0.36 | 0.462 |
| agree | 595 | −0.03 | +0.06 | +0.09 | +0.38 | 0.504 |
| above | 595 | +0.80 | +1.34 | +0.54 | +0.79 | 0.508 |
| book far above | 595 | +2.77 | +2.94 | +0.17 | +2.97 | 0.474 |

(Other markets in the JSON; same shape, slope < 1 for rebounds/assists.)

## 2. Information sources the model could acquire, ranked by measured size

1. **Pregame inactive / injury report (late absences).** ~31% of points rows; model misses +1.0 pts there, and the book
   under-reacts on points (+0.67) -- the one place in this whole series where the BOOK is measurably wrong in a
   predictable direction. Production now fetches injuries daily (`fetch-injuries`; the availability exclusion map
   already reads it), but the season's history of reports is not recoverable, so its effect is unmeasured. NEXT
   MEASUREMENT (cheap, no spend): an *oracle-availability* re-run -- exclude exactly the players who did not play --
   gives the ceiling of perfect injury information on minutes AND on teammates' usage; then capture injury reports
   forward with timestamps to see how much of that ceiling the real feed reaches by tip −60.
2. **Minutes expectations beyond availability** (rotation/role changes, rest): ~40–55% of the book's edge outside the
   late-out games. Candidate source: ESPN rotation history (now restored on the fleet, 09-17 onward) feeding expected
   minutes; it existed for none of this backtest's dates.
3. **Per-minute rate information** (~50% of the points edge): matchup and usage shifts -- partly the same late absences
   (usage rises when a teammate sits, beyond minutes). The rate-shrink fix pulls the sim toward the player's season
   rate, which by construction cannot see a usage shift.

## 3. Caveats

- "Late outs" are defined from the box score after the fact; some are coach's decisions not in any report, so the
  measured effect is an upper bound on what an injury feed alone recovers.
- The book snapshot is tip −60; most inactive lists are public by then, but not all.
- Line = modal line across books, treated as the book's central estimate (≈ median).
